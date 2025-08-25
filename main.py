import os
import asyncio
import concurrent.futures
from concurrent.futures.process import BrokenProcessPool
from fastapi import FastAPI, UploadFile, File, Path, HTTPException, Body, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.middleware.gzip import GZipMiddleware
import optimizer as optimizer
import traceback  
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from services.postprocess import move_orders, add_truck, delete_truck, compute_stats


app = FastAPI()

origins = [
    os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")
]
# Permitir CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_methods=["GET","POST","PUT","PATCH","DELETE","OPTIONS"],
    allow_headers=["Content-Type","Authorization"],
    max_age=600,
)
app.add_middleware(GZipMiddleware, minimum_size=int(os.getenv("GZIP_MIN_SIZE", "512")))

# Configuración de concurrencia y tiempos
REQUEST_TIMEOUT = 150                   # segundos máximos por petición completa

CPU_COUNT = os.cpu_count() or 4
MAX_WORKERS = max(CPU_COUNT - 1, 1)         # Ej. 3
MAX_CONCURRENT = max(1, MAX_WORKERS // 1)   # o CPU_COUNT - 
executor: concurrent.futures.ProcessPoolExecutor
semaphore = asyncio.Semaphore(MAX_CONCURRENT)

@app.on_event("startup")
def on_startup():
    """
    Inicializa el pool de procesos al arrancar el servidor.
    Como ya importamos optimizer antes, los hijos
    al crearse heredarán las importaciones de OR-Tools.
    """
    global executor
    executor = concurrent.futures.ProcessPoolExecutor(max_workers=MAX_WORKERS)

@app.on_event("shutdown")
def on_shutdown():
    """Cierra el pool de procesos al detener el servidor"""
    executor.shutdown(wait=True)

@app.get("/", response_class=HTMLResponse)
def root():
    return "<h2> Backend de FastAPI funcionando</h2>"

@app.post("/optimizar/{cliente}/{venta}")
async def optimizar(
    cliente: str = Path(...),
    venta: str = Path(...),
    file: UploadFile = File(...),
    vcuTarget: Optional[int] = Form(default=None),
    vcuTargetBH: Optional[int] = Form(default=None)
):
    """
    1) Intentar adquirir el semáforo (hasta 3 segundos). Si no se libera un slot,
       devolvemos HTTP 429 (Too Many Requests).
    2) Una vez tenemos el semáforo, leemos el archivo y lanzamos la optimización
       en el ProcessPoolExecutor con un timeout total REQUEST_TIMEOUT.
    3) En caso de timeout (optimización > REQUEST_TIMEOUT), devolvemos 504.
    4) Si el worker muere (BrokenProcessPool), recreamos el executor y devolvemos 500.
    5) En cualquier otro error interno devolvemos 500.
    6) Siempre liberamos el semáforo en el bloque finally.
    """
    global executor  # Para poder recrear el executor en caso de BrokenProcessPool

    # VCU
    if vcuTarget is not None:
        vcuTarget = max(1, min(100, int(vcuTarget)))
    if vcuTargetBH is not None:
        vcuTargetBH = max(1, min(100, int(vcuTargetBH)))

    # Leer contenido del archivo y cerrarlo
    content = await file.read()
    await file.close()

    loop = asyncio.get_running_loop()

    # 1) Intentar adquirir semáforo en 3 segundos como máximo
    try:
        await asyncio.wait_for(semaphore.acquire(), timeout=3.0)
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=429,
            detail="Servicio ocupado: demasiadas optimizaciones en curso. Intenta nuevamente en unos segundos."
        )

    try:
        # 2) Ejecutar la optimización en el ProcessPoolExecutor con timeout REQUEST_TIMEOUT
        resultado = await asyncio.wait_for(
            loop.run_in_executor(
                executor,
                optimizer.procesar,
                content,
                file.filename,
                cliente,
                venta,
                REQUEST_TIMEOUT,  # Pasamos REQUEST_TIMEOUT para que optimizer lo use
                vcuTarget,
                vcuTargetBH
            ),
            timeout=REQUEST_TIMEOUT
        )
        if isinstance(resultado, dict) and 'error' in resultado:
            raise HTTPException(
                status_code=400,
                detail=resultado['error'] if isinstance(resultado['error'], str) else resultado['error'].get('message', 'Error en optimización')
            )

        return resultado

    except asyncio.TimeoutError:
        # 3) La optimización tardó más de REQUEST_TIMEOUT
        raise HTTPException(
            status_code=504,
            detail="Optimización excedió el límite de tiempo."
        )

    except BrokenProcessPool as e:
        # 4) Si algún worker murió abruptamente, lo recreamos y devolvemos 500
        print(f"[ERROR] BrokenProcessPool detectado: {e}", flush=True)
        try:
            executor.shutdown(wait=False)
        except Exception:
            pass
        executor = concurrent.futures.ProcessPoolExecutor(max_workers=MAX_WORKERS)
        raise HTTPException(
            status_code=500,
            detail="Error interno: proceso de optimización terminado inesperadamente. Por favor, reintenta."
        )

    except Exception as e:
        # 5) Cualquier otro error genérico
        traceback.print_exc()
        print(f"[ERROR]: {e}", flush=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error: {e}"
        )

    finally:
        # 6) Liberar siempre el semáforo, aunque haya excepción
        semaphore.release()

@app.get("/ping")
async def ping():
    return {"message": "pong"}


class PostProcessRequest(BaseModel):
    camiones: List[Dict[str, Any]]              = Field(default_factory=list)
    pedidos_no_incluidos: List[Dict[str, Any]]  = Field(default_factory=list)
    pedidos: Optional[List[Dict[str, Any]]]     = Field(default_factory=list)
    target_truck_id: Optional[str]              = None
    cd: Optional[List[str]]                     = Field(default_factory=list)
    ce: Optional[List[str]]                     = Field(default_factory=list)
    ruta: Optional[str]                         = None
    cliente: str


class PostProcessResponse(BaseModel):
    camiones: List[Dict[str, Any]]
    pedidos_no_incluidos: List[Dict[str, Any]]
    estadisticas: Dict[str, Any]

@app.post("/postprocess/move_orders", response_model=PostProcessResponse)
async def api_move_orders(req: PostProcessRequest = Body(...)):
    state = {"camiones": req.camiones, "pedidos_no_incluidos": req.pedidos_no_incluidos}
    try:
        await asyncio.wait_for(semaphore.acquire(), timeout=3.0)
    except asyncio.TimeoutError:
        from fastapi import HTTPException
        raise HTTPException(status_code=429, detail="Servicio ocupado: demasiadas operaciones en curso.")

    try:
        result = await asyncio.to_thread(
            move_orders, state, req.pedidos, req.target_truck_id, req.cliente
        )
        return result
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        semaphore.release()


@app.post("/postprocess/add_truck", response_model=PostProcessResponse)
async def api_add_truck(req: PostProcessRequest = Body(...)):
    state = {"camiones": req.camiones, "pedidos_no_incluidos": req.pedidos_no_incluidos}
    try:
        await asyncio.wait_for(semaphore.acquire(), timeout=3.0)
    except asyncio.TimeoutError:
        from fastapi import HTTPException
        raise HTTPException(status_code=429, detail="Servicio ocupado: demasiadas operaciones en curso.")
    try:
        return await asyncio.to_thread(add_truck, state, req.cd, req.ce, req.ruta, req.cliente)
    finally:
        semaphore.release()


@app.post("/postprocess/delete_truck", response_model=PostProcessResponse)
async def api_delete_truck(req: PostProcessRequest = Body(...)):
    state = {"camiones": req.camiones, "pedidos_no_incluidos": req.pedidos_no_incluidos}
    try:
        await asyncio.wait_for(semaphore.acquire(), timeout=3.0)
    except asyncio.TimeoutError:
        from fastapi import HTTPException
        raise HTTPException(status_code=429, detail="Servicio ocupado: demasiadas operaciones en curso.")
    try:
        return await asyncio.to_thread(delete_truck, state, req.target_truck_id, req.cliente)
    finally:
        semaphore.release()


@app.post("/postprocess/compute_stats", response_model=Dict[str, Any])
async def api_compute_stats(req: PostProcessRequest = Body(...)):
    nulls = [k for k, v in req.dict().items() if v is None]
    if nulls:
        print(f"[WARN] Campos nulos en compute_stats: {nulls}")
    try:
        await asyncio.wait_for(semaphore.acquire(), timeout=3.0)
    except asyncio.TimeoutError:
        from fastapi import HTTPException
        raise HTTPException(status_code=429, detail="Servicio ocupado: demasiadas operaciones en curso.")
    try:
        return await asyncio.to_thread(compute_stats, req.camiones, req.pedidos_no_incluidos, req.cliente)
    finally:
        semaphore.release()
