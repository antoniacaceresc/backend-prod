# app/main.py
from __future__ import annotations

import os
import asyncio
import concurrent.futures
from concurrent.futures.process import BrokenProcessPool
from typing import List, Dict, Any, Optional

from fastapi import FastAPI, UploadFile, File, Path, HTTPException, Body, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse

# ==========================================
# IMPORTS REFACTORIZADOS
# ==========================================

from models.api import (PostProcessRequest, PostProcessResponse)
from optimization.orchestrator import procesar
from services.postprocess import (move_orders, add_truck, delete_truck, compute_stats, apply_truck_type_change)

# ----------------------------------------------------------------------------
# App & Middlewares
# ----------------------------------------------------------------------------
app = FastAPI(title="Truck Optimizer API", version=os.getenv("APP_VERSION", "1.0"))

origins = [os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
    max_age=600,
)
app.add_middleware(GZipMiddleware, minimum_size=int(os.getenv("GZIP_MIN_SIZE", "512")))

# ----------------------------------------------------------------------------
# Concurrencia
# ----------------------------------------------------------------------------
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "300"))
CPU_COUNT = os.cpu_count() or 4
MAX_WORKERS = max(CPU_COUNT - 1, 1)
MAX_CONCURRENT = max(1, MAX_WORKERS)

executor: concurrent.futures.ProcessPoolExecutor
semaphore = asyncio.Semaphore(MAX_CONCURRENT)


@app.on_event("startup")
def on_startup() -> None:
    """Inicializa el pool de procesos (mantener para OR-Tools).
    Los workers heredan importaciones pesadas al fork.
    """
    global executor
    executor = concurrent.futures.ProcessPoolExecutor(max_workers=MAX_WORKERS)


@app.on_event("shutdown")
def on_shutdown() -> None:
    """Cierra el pool de procesos al detener el servidor."""
    executor.shutdown(wait=True)


@app.get("/", response_class=HTMLResponse)
def root() -> str:
    return "<h2>Backend de FastAPI funcionando</h2>"



# ----------------------------------------------------------------------------
# Endpoints públicos (contratos mantenidos)
# ----------------------------------------------------------------------------
@app.post("/optimizar/{cliente}/{venta}")
async def optimizar(
    cliente: str = Path(...),
    venta: str = Path(...),
    file: UploadFile = File(...),
    vcuTarget: Optional[int] = Form(default=None),
    vcuTargetBH: Optional[int] = Form(default=None),
) -> Dict[str, Any]:
    """Orquesta el proceso de optimización, aplicando timeout y control de concurrencia.

    - Mantiene el contrato de entrada/salida y la llamada a `services.optimizer.procesar`.
    - Gestiona errores HTTP coherentes.
    """
    global executor

    if vcuTarget is not None:
        vcuTarget = max(1, min(100, int(vcuTarget)))
    if vcuTargetBH is not None:
        vcuTargetBH = max(1, min(100, int(vcuTargetBH)))

    content = await file.read()
    await file.close()

    loop = asyncio.get_running_loop()

    try:
        await asyncio.wait_for(semaphore.acquire(), timeout=3.0)
    except asyncio.TimeoutError as _:
        raise HTTPException(status_code=429, detail="Servicio ocupado: demasiadas optimizaciones en curso. Intenta nuevamente.")

    try:
        result = await asyncio.wait_for(
            loop.run_in_executor(
                executor,
                procesar,
                content,
                file.filename,
                cliente,
                venta,
                REQUEST_TIMEOUT,
                vcuTarget,
                vcuTargetBH,
            ),
            timeout=REQUEST_TIMEOUT,
        )
        if isinstance(result, dict) and "error" in result:
            detail = result["error"] if isinstance(result["error"], str) else result["error"].get("message", "Error en optimización")
            raise HTTPException(status_code=400, detail=detail)
        return result

    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Optimización excedió el límite de tiempo.")
    except BrokenProcessPool as e:
        # Reiniciar el executor para futuras requests
        try:
            executor.shutdown(wait=False)
        except Exception:
            pass
        executor = concurrent.futures.ProcessPoolExecutor(max_workers=MAX_WORKERS)
        raise HTTPException(status_code=500, detail="Error interno: proceso de optimización terminado inesperadamente. Reintenta.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {e}")
    finally:
        semaphore.release()


@app.get("/ping")
async def ping() -> Dict[str, str]:
    return {"message": "pong"}


@app.post("/postprocess/move_orders", response_model=PostProcessResponse)
async def api_move_orders(req: PostProcessRequest = Body(...)) -> Dict[str, Any]:
    state = {"camiones": req.camiones, "pedidos_no_incluidos": req.pedidos_no_incluidos}
    try:
        await asyncio.wait_for(semaphore.acquire(), timeout=3.0)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=429, detail="Servicio ocupado: demasiadas operaciones en curso.")

    try:
        return await asyncio.to_thread(move_orders, state, req.pedidos, req.target_truck_id, req.cliente)
    except Exception as e:  # por validaciones de negocio
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        semaphore.release()

@app.post("/postprocess/update_truck_type", response_model=PostProcessResponse)
async def api_update_truck_type(
    camiones = Body(...),
    pedidos_no_incluidos = Body(...),
    cliente: str = Body(...),
    truck_id: str = Body(...),
    tipo_camion: str = Body(...),
) -> Dict[str, Any]:
    """
    Cambia el tipo de un camión delegando toda la validación y el recálculo
    a `services.postprocess.apply_truck_type_change(...)`.
    Devuelve: {camiones, pedidos_no_incluidos, estadisticas}.
    """
    try:
        await asyncio.wait_for(semaphore.acquire(), timeout=3.0)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=429, detail="Servicio ocupado: demasiadas operaciones en curso.")

    try:
        state = {
            "camiones": list(camiones or []),
            "pedidos_no_incluidos": list(pedidos_no_incluidos or []),
        }
        updated = await asyncio.to_thread(
            apply_truck_type_change,
            state,
            truck_id,
            (tipo_camion or "").lower(),
            cliente,
        )
        return updated

    except ValueError as e:
        # Errores de negocio (no cabe / no permitido / regla del cliente, etc.)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        print(f"\n❌ ERROR EN UPDATE_TRUCK_TYPE:")
        print(error_detail)
        raise HTTPException(status_code=500, detail=f"Error interno: {e}")
    finally:
        semaphore.release()


@app.post("/postprocess/add_truck", response_model=PostProcessResponse)
async def api_add_truck(req: PostProcessRequest = Body(...)) -> Dict[str, Any]:
    state = {"camiones": req.camiones, "pedidos_no_incluidos": req.pedidos_no_incluidos}
    try:
        await asyncio.wait_for(semaphore.acquire(), timeout=3.0)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=429, detail="Servicio ocupado: demasiadas operaciones en curso.")
    try:
        return await asyncio.to_thread(add_truck, state, req.cd, req.ce, req.ruta, req.cliente)
    finally:
        semaphore.release()


@app.post("/postprocess/delete_truck", response_model=PostProcessResponse)
async def api_delete_truck(req: PostProcessRequest = Body(...)) -> Dict[str, Any]:
    state = {"camiones": req.camiones, "pedidos_no_incluidos": req.pedidos_no_incluidos}
    try:
        await asyncio.wait_for(semaphore.acquire(), timeout=3.0)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=429, detail="Servicio ocupado: demasiadas operaciones en curso.")
    try:
        return await asyncio.to_thread(delete_truck, state, req.target_truck_id, req.cliente)
    finally:
        semaphore.release()


@app.post("/postprocess/compute_stats", response_model=Dict[str, Any])
async def api_compute_stats(req: PostProcessRequest = Body(...)) -> Dict[str, Any]:
    try:
        await asyncio.wait_for(semaphore.acquire(), timeout=3.0)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=429, detail="Servicio ocupado: demasiadas operaciones en curso.")
    try:
        return await asyncio.to_thread(compute_stats, req.camiones, req.pedidos_no_incluidos, req.cliente)
    finally:
        semaphore.release()