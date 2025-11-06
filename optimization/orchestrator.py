"""
API pública del optimizador.
Orquesta el flujo completo de optimización en dos fases (VCU y BinPacking).
"""

from __future__ import annotations

import time
from typing import List, Dict, Any, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
import os

import pandas as pd

from services.file_processor import read_file, process_dataframe

from models.domain import Pedido, TruckCapacity, ConfiguracionGrupo, SKU
from models.enums import TipoCamion
from optimization.solvers.vcu import optimizar_grupo_vcu
from optimization.solvers.binpacking import optimizar_grupo_binpacking
from core.config import get_client_config
from core.constants import MAX_TIEMPO_POR_GRUPO
from utils.math_utils import format_dates
from optimization.groups import ( generar_grupos_optimizacion, calcular_tiempo_por_grupo, _generar_grupos_para_tipo, ajustar_tiempo_grupo )
from utils.config_helpers import extract_truck_capacities

# ============================================================================
# CONSTANTES
# ============================================================================

MAX_TIEMPO_POR_GRUPO = int(os.getenv("MAX_TIEMPO_POR_GRUPO", "30"))
THREAD_WORKERS_NORMAL = int(os.getenv("THREAD_WORKERS_NORMAL", str(min(8, (os.cpu_count() or 4)))))


# ============================================================================
# API PÚBLICA
# ============================================================================

def procesar(
    content: bytes,
    filename: str,
    client: str,
    venta: str,
    REQUEST_TIMEOUT: int,
    vcuTarget: Any,
    vcuTargetBH: Any
) -> Dict[str, Any]:
    """
    API principal de optimización (mantiene firma original para compatibilidad).
    
    Args:
        content: Contenido del archivo Excel
        filename: Nombre del archivo
        client: Nombre del cliente
        venta: Tipo de venta ("Secos", "Purina", etc.)
        REQUEST_TIMEOUT: Timeout total en segundos
        vcuTarget: Override de VCU mínimo normal (1-100)
        vcuTargetBH: Override de VCU mínimo BH (1-100)
    
    Returns:
        Dict con resultados de optimización o error
    """
    try:
        config = get_client_config(client)
        
        # Leer y procesar Excel
        df_full = read_file(content, filename, config, venta)
        
        # Aplicar overrides de VCU si vienen del frontend
        config = _aplicar_overrides_vcu(config, vcuTarget, vcuTargetBH)
        
        # Ejecutar optimización en dos fases
        return optimizar_con_dos_fases(
            df_full, config, client, venta,
            REQUEST_TIMEOUT, MAX_TIEMPO_POR_GRUPO
        )
    
    except Exception as e:
        import traceback as _tb
        return {
            "error": {
                "message": str(e),
                "traceback": _tb.format_exc()[:5000]
            }
        }


def optimizar_con_dos_fases(
    df_raw: pd.DataFrame,
    client_config,
    cliente: str,
    venta: str,
    request_timeout: int,
    max_tpg: int
) -> Dict[str, Any]:
    """
    Ejecuta optimización en dos fases: VCU y BinPacking.
    
    Args:
        df_raw: DataFrame crudo del Excel
        client_config: Configuración del cliente
        cliente: Nombre del cliente
        venta: Tipo de venta
        request_timeout: Timeout total
        max_tpg: Máximo tiempo por grupo
    
    Returns:
        Dict con resultados de ambas fases
    """
    # 1) Preprocesamiento
    pedidos_objetos, pedidos_dicts = _preprocesar_datos(df_raw, client_config, cliente, venta)
    
    # 2) Calcular tiempo por grupo
    tpg = calcular_tiempo_por_grupo(pedidos_objetos, client_config, request_timeout, max_tpg)
    
    # 3) Ejecutar optimización VCU
    resultado_vcu = _ejecutar_optimizacion_completa(
        pedidos_objetos, pedidos_dicts, client_config,
        cliente, "vcu", tpg, request_timeout
    )
    
    # 4) Ejecutar optimización BinPacking
    resultado_bp = _ejecutar_optimizacion_completa(
        pedidos_objetos, pedidos_dicts, client_config,
        cliente, "binpacking", tpg, request_timeout
    )
    
    # 5) Aplicar objetivo de ratio BH (si existe)
    resultado_vcu = _aplicar_objetivo_bh(resultado_vcu, cliente, client_config)
    resultado_bp = _aplicar_objetivo_bh(resultado_bp, cliente, client_config)
    
    # 6) Etiquetar camiones BH en BinPacking (regla especial)
    resultado_bp = _etiquetar_bh_binpacking(resultado_bp, client_config, cliente)
    
    return {
        "vcu": resultado_vcu,
        "binpacking": resultado_bp
    }


# ============================================================================
# HELPERS INTERNOS
# ============================================================================

def _preprocesar_datos(
    df_raw: pd.DataFrame,
    client_config,
    cliente: str,
    venta: str
) -> Tuple[List[Pedido], List[Dict[str, Any]]]:
    """
    Preprocesa datos del Excel a objetos Pedido.
    
    Returns:
        Tupla (lista_pedidos_objetos, lista_pedidos_dicts)
    """
    # Procesar DataFrame
    df_proc, pedidos_dicts_raw = process_dataframe(df_raw, client_config, cliente, venta)
    
    # Formatear fechas en dicts
    pedidos_dicts = [
        {
            **p,
            "Fecha preferente de entrega": format_dates(p.get("Fecha preferente de entrega"))
        }
        for p in pedidos_dicts_raw
    ]
    
    # Convertir a objetos Pedido
    pedidos_objetos = _dataframe_a_pedidos(df_proc, pedidos_dicts)
    
    return pedidos_objetos, pedidos_dicts


# En orchestrator.py, reemplazar la función _dataframe_a_pedidos

def _dataframe_a_pedidos(df: pd.DataFrame, pedidos_dicts: List[Dict]) -> List[Pedido]:
    """
    Convierte DataFrame procesado a lista de objetos Pedido.
    
    NUEVO: Incluye construcción de objetos SKU si existen en metadata.
    """
    pedidos_map = {p["PEDIDO"]: p for p in pedidos_dicts}
    pedidos = []
    
    for _, row in df.iterrows():
        pedido_id = row["PEDIDO"]
        metadata = pedidos_map.get(pedido_id, {})
        
        # Construir pedido base
        pedido = Pedido(
            pedido=str(pedido_id),
            cd=str(row["CD"]),
            ce=str(row["CE"]),
            po=str(row["PO"]),
            peso=float(row["PESO"]),
            volumen=float(row["VOL"]),
            pallets=float(row["PALLETS"]),
            valor=float(row["VALOR"]),
            valor_cafe=float(row.get("VALOR_CAFE", 0)),
            pallets_real=float(row["PALLETS_REAL"]) if "PALLETS_REAL" in row and pd.notna(row["PALLETS_REAL"]) else None,
            oc=str(row["OC"]) if "OC" in row and pd.notna(row["OC"]) else None,
            chocolates=str(row.get("CHOCOLATES", "NO")),
            valioso=bool(row.get("VALIOSO", 0)),
            pdq=bool(row.get("PDQ", 0)),
            baja_vu=bool(row.get("BAJA_VU", 0)),
            lote_dir=bool(row.get("LOTE_DIR", 0)),
            base=float(row.get("BASE", 0)),
            superior=float(row.get("SUPERIOR", 0)),
            flexible=float(row.get("FLEXIBLE", 0)),
            no_apilable=float(row.get("NO_APILABLE", 0)),
            si_mismo=float(row.get("SI_MISMO", 0)),
            skus=[],
            metadata=metadata
        )
        
        # NUEVO: Construir SKUs si existen en metadata
        skus_data = metadata.get("_skus", [])

        if skus_data:
            for sku_row in skus_data:
                try:
                    sku = SKU(
                        sku_id=str(sku_row["SKU"]),
                        pedido_id=pedido_id,
                        cantidad_pallets=float(sku_row["PALLETS"]),
                        altura_full_pallet_cm=float(sku_row["ALTURA_FULL_PALLET"]),
                        altura_picking_cm=float(sku_row.get("ALTURA_PICKING", 0)) if sku_row.get("ALTURA_PICKING", 0) > 0 else None,
                        peso_kg=float(sku_row.get("PESO", 0)),
                        volumen_m3=float(sku_row.get("VOL", 0)),
                        valor=float(sku_row.get("VALOR", 0)),
                        base=float(sku_row.get("BASE", 0)),
                        superior=float(sku_row.get("SUPERIOR", 0)),
                        flexible=float(sku_row.get("FLEXIBLE", 0)),
                        no_apilable=float(sku_row.get("NO_APILABLE", 0)),
                        si_mismo=float(sku_row.get("SI_MISMO", 0)),
                        descripcion=sku_row.get("descripcion")
                    )
                    
                    pedido.skus.append(sku)
                except Exception as e:
                    print(f"[ERROR] ❌ Error construyendo SKU para pedido {pedido_id}: {e}")
                    print(f"        Datos SKU: {sku_row}")
        pedidos.append(pedido)

    for p in pedidos:
        if p.tiene_skus:
            pallets_skus = sum(sku.cantidad_pallets for sku in p.skus)
            if abs(pallets_skus - p.pallets) > 0.1:
                print(f"[WARN] ⚠️ Pedido {p.pedido}: pallets agregado ({p.pallets:.2f}) != suma SKUs ({pallets_skus:.2f})")

    
    return pedidos

def _ejecutar_optimizacion_completa(
    pedidos_objetos: List[Pedido],
    pedidos_dicts: List[Dict[str, Any]],
    client_config,
    cliente: str,
    modo: str,
    tpg: int,
    request_timeout: int
) -> Dict[str, Any]:
    """
    Ejecuta optimización completa para un modo (VCU o BinPacking).
    """
    start_total = time.time()
    
    # Extraer capacidades
    capacidades = extract_truck_capacities(client_config)
    
    if modo == "vcu":
        # ✅ Para VCU: Solo generar grupos NORMALES inicialmente
        grupos_iniciales = generar_grupos_optimizacion(
            pedidos_objetos, client_config, "normal"  # ✅ Solo normales
        )
        
        print(f"[VCU] Grupos normales generados: {len(grupos_iniciales)}")
        
        # ✅ VCU maneja cascada internamente
        resultados = _optimizar_grupos_vcu(
            grupos_iniciales, 
            client_config, 
            capacidades,
            tpg, 
            request_timeout, 
            start_total,
            pedidos_objetos  # ✅ Pasar todos los pedidos
        )
    else:
        # BinPacking: generar todos los grupos
        grupos = generar_grupos_optimizacion(pedidos_objetos, client_config, modo)
        
        resultados = _optimizar_grupos_binpacking(
            grupos, client_config, capacidades,
            tpg, request_timeout, start_total
        )
    
    # Consolidar
    return _consolidar_resultados(
        resultados, pedidos_objetos, pedidos_dicts, 
        capacidades[TipoCamion.NORMAL], client_config
    )


def _optimizar_grupos_vcu(
    grupos_iniciales: List[Tuple],  # Solo grupos normales
    client_config,
    capacidades: Dict[TipoCamion, TruckCapacity],
    tpg: int,
    request_timeout: int,
    start_total: float,
    todos_los_pedidos: List[Pedido]
) -> List[Dict[str, Any]]:
    """
    Optimiza grupos en modo VCU con cascada serial:
    1. Optimiza grupos NORMALES en paralelo
    2. Regenera grupos ESPECIALES con pedidos no asignados y optimiza en serie
    """


    resultados = []
    pedidos_asignados_global = set()
    
    # ========================================
    # FASE 1: Optimizar NORMALES en PARALELO
    # ========================================
    grupos_normal = [(cfg, peds) for cfg, peds in grupos_iniciales if cfg.tipo.value == "normal"]
    
    print(f"[VCU] Fase 1: Optimizando {len(grupos_normal)} grupos NORMALES en paralelo")
    
    if grupos_normal:
        with ThreadPoolExecutor(max_workers=min(THREAD_WORKERS_NORMAL, len(grupos_normal))) as pool:
            futures = []
            
            for cfg, pedidos_grupo in grupos_normal:
                if not pedidos_grupo:
                    continue
                
                n_pedidos = len(pedidos_grupo)
                tiempo_grupo = ajustar_tiempo_grupo(tpg, n_pedidos, "normal")
                
                if time.time() - start_total + tiempo_grupo > (request_timeout - 2):
                    continue
                
                cap = capacidades[TipoCamion.NORMAL]
                
                fut = pool.submit(
                    optimizar_grupo_vcu,
                    pedidos_grupo, cfg, client_config, cap, tiempo_grupo
                )
                futures.append((fut, cfg.id, len(pedidos_grupo)))
            
            # Recoger resultados
            for fut, grupo_id, n_pedidos in futures:
                try:
                    res = fut.result(timeout=max(1, request_timeout - int(time.time() - start_total)))
                    
                    if res.get("status") in ("OPTIMAL", "FEASIBLE") and res.get("camiones"):
                        nuevos = res.get("pedidos_asignados_ids", [])
                        pedidos_asignados_global.update(nuevos)
                        resultados.append(res)
                        print(f"[VCU] ✓ Normal {grupo_id}: {len(nuevos)}/{n_pedidos} pedidos asignados")
                    else:
                        print(f"[VCU] ✗ Normal {grupo_id}: NO_SOLUTION")
                except Exception as e:
                    print(f"[VCU] ✗ Normal {grupo_id}: ERROR - {e}")
    
    print(f"[VCU] Fase 1 completa: {len(pedidos_asignados_global)} pedidos asignados totales")
    
    # ========================================
    # FASE 2: CASCADA DINÁMICA DE RUTAS ESPECIALES
    # ========================================
    tipos_especiales = ["multi_ce_prioridad", "multi_ce", "multi_cd", "bh"]
    
    for tipo in tipos_especiales:
        # ✅ CALCULAR pedidos NO asignados hasta ahora
        pedidos_disponibles = [
            p for p in todos_los_pedidos 
            if p.pedido not in pedidos_asignados_global
        ]
        
        if not pedidos_disponibles:
            print(f"[VCU] Fase 2 ({tipo}): No quedan pedidos disponibles, deteniendo cascada")
            break
        
        print(f"\n[VCU] Fase 2 ({tipo}): {len(pedidos_disponibles)} pedidos disponibles")
        
        # ✅ GENERAR grupos de este tipo CON pedidos disponibles
        grupos_tipo = _generar_grupos_para_tipo(
            pedidos_disponibles, 
            client_config, 
            tipo
        )
        
        if not grupos_tipo:
            print(f"[VCU] Fase 2 ({tipo}): No se generaron grupos, skip")
            continue
        
        print(f"[VCU] Fase 2 ({tipo}): {len(grupos_tipo)} grupos generados")
        
        # ✅ OPTIMIZAR cada grupo de este tipo EN SERIE
        for cfg, pedidos_grupo in grupos_tipo:
            if not pedidos_grupo:
                continue
            
            n_ped = len(pedidos_grupo)
            tiempo_grupo = ajustar_tiempo_grupo(tpg, n_ped, tipo)
            
            if time.time() - start_total + tiempo_grupo > (request_timeout - 2):
                print(f"[VCU] Timeout cercano, deteniendo cascada")
                break
            
            # Determinar capacidad
            if tipo == "bh":
                cap = capacidades.get(TipoCamion.BH, capacidades[TipoCamion.NORMAL])
            else:
                cap = capacidades[TipoCamion.NORMAL]
            
            print(f"[VCU]   Optimizando {cfg.id}: {n_ped} pedidos, {tiempo_grupo}s")
            
            res = optimizar_grupo_vcu(
                pedidos_grupo, cfg, client_config, cap, tiempo_grupo
            )
            
            if res.get("status") in ("OPTIMAL", "FEASIBLE"):
                nuevos = res.get("pedidos_asignados_ids", [])
                n_camiones = len(res.get("camiones", []))
                
                if nuevos and n_camiones > 0:
                    pedidos_asignados_global.update(nuevos)
                    resultados.append(res)
                    print(f"[VCU] ✓ Normal {grupo_id}: {len(nuevos)}/{n_pedidos} pedidos asignados en {n_camiones} camiones")
                else:
                    print(f"[VCU] ⚠️ Normal {grupo_id}: {res.get('status')} pero 0 pedidos/camiones asignados")
            else:
                print(f"[VCU] ✗ Normal {grupo_id}: {res.get('status', 'NO_SOLUTION')}")
            
            if time.time() - start_total > (request_timeout - 2):
                break
        
        # Si timeout, detener cascada
        if time.time() - start_total > (request_timeout - 2):
            break
    
    print(f"\n[VCU] Optimización completa: {len(resultados)} grupos, {len(pedidos_asignados_global)} pedidos asignados")
    
    return resultados


def _optimizar_grupos_binpacking(
    grupos: List[Tuple],
    client_config,
    capacidades: Dict[TipoCamion, TruckCapacity],
    tpg: int,
    request_timeout: int,
    start_total: float
) -> List[Dict[str, Any]]:
    """
    Optimiza grupos en modo BinPacking (secuencial).
    """
    resultados = []
    
    for cfg, pedidos_grupo in grupos:
        if not pedidos_grupo:
            continue
        
        n_pedidos = len(pedidos_grupo)
        tiempo_grupo = ajustar_tiempo_grupo(tpg, n_pedidos, cfg.tipo.value)
        
        if time.time() - start_total + tiempo_grupo > (request_timeout - 2):
            break
        
        cap = capacidades.get(
            TipoCamion.BH if cfg.tipo.value == 'bh' else TipoCamion.NORMAL,
            capacidades[TipoCamion.NORMAL]
        )
        
        res = optimizar_grupo_binpacking(pedidos_grupo, cfg, client_config, cap, tiempo_grupo)
        
        if res.get("status") in ("OPTIMAL", "FEASIBLE") and res.get("camiones"):
            resultados.append(res)
        
        if time.time() - start_total > (request_timeout - 2):
            break
    
    return resultados


def _consolidar_resultados(
    resultados: List[Dict[str, Any]],
    pedidos_originales: List[Pedido],
    pedidos_dicts: List[Dict[str, Any]],
    capacidad_default: TruckCapacity,
    client_config  # ✅ NUEVO: necesitamos el config
) -> Dict[str, Any]:
    """
    Consolida resultados de todos los grupos en una respuesta única.
    """
    from services.postprocess import _actualizar_opciones_tipo_camion 
    
    # Consolidar camiones
    all_camiones = []
    for res in resultados:
        all_camiones.extend(res.get("camiones", []))
    
    for camion in all_camiones:
        _actualizar_opciones_tipo_camion(camion, client_config)
    
    # Identificar pedidos asignados
    pedidos_asignados_ids = set()
    for cam in all_camiones:
        pedidos_asignados_ids.update(p.pedido for p in cam.pedidos)
    
    # Pedidos no incluidos
    pedidos_map = {p["PEDIDO"]: p for p in pedidos_dicts}
    pedidos_no_incluidos = []
    
    for pedido_obj in pedidos_originales:
        if pedido_obj.pedido not in pedidos_asignados_ids:
            vcu_peso, vcu_vol, _ = pedido_obj.calcular_vcu(capacidad_default)
            
            pedido_dict = {
                "PEDIDO": pedido_obj.pedido,
                "CE": pedido_obj.ce,
                "CD": pedido_obj.cd,
                "OC": pedido_obj.oc,
                "PO": pedido_obj.po,
                "CHOCOLATES": pedido_obj.chocolates,
                "PESO": pedido_obj.peso,
                "VOL": pedido_obj.volumen,
                "PALLETS": pedido_obj.pallets,
                "VALOR": pedido_obj.valor,
                "VCU_VOL": vcu_vol,
                "VCU_PESO": vcu_peso,
                "Fecha preferente de entrega": pedidos_map.get(pedido_obj.pedido, {}).get("Fecha preferente de entrega"),
            }
            
            pedido_dict.update(pedidos_map.get(pedido_obj.pedido, {}))
            pedidos_no_incluidos.append(pedido_dict)
    
    # Convertir camiones a dicts para API
    camiones_dicts = [cam.to_api_dict() for cam in all_camiones]
    
    return {
        "camiones": camiones_dicts,
        "pedidos_no_incluidos": pedidos_no_incluidos
    }


def _aplicar_overrides_vcu(config, vcuTarget: Any, vcuTargetBH: Any):
    """
    Aplica overrides de VCU mínimo desde el frontend.
    """
    if vcuTarget is not None:
        try:
            vcu = max(1, min(100, int(vcuTarget)))
            config.VCU_MIN = float(vcu) / 100.0
        except Exception:
            pass
    
    if vcuTargetBH is not None:
        try:
            vcu_bh = max(1, min(100, int(vcuTargetBH)))
            config.BH_VCU_MIN = float(vcu_bh) / 100.0
        except Exception:
            pass
    
    return config


def _aplicar_objetivo_bh(
    resultado: Dict[str, Any],
    cliente: str,
    client_config
) -> Dict[str, Any]:
    """
    Intenta alcanzar ratio objetivo de camiones BH.
    """
    try:
        from services.postprocess import enforce_bh_target
        
        target_ratio = getattr(client_config, "BH_TRUCK_TARGET_RATIO", None)
        
        if isinstance(target_ratio, (int, float)) and target_ratio > 0:
            cam_dicts, pni_dicts = enforce_bh_target(
                resultado.get("camiones", []),
                resultado.get("pedidos_no_incluidos", []),
                cliente,
                float(target_ratio)
            )
            
            resultado["camiones"] = cam_dicts
            resultado["pedidos_no_incluidos"] = pni_dicts
    
    except Exception:
        # Si falla, continuar sin aplicar el objetivo
        pass
    
    return resultado


def _etiquetar_bh_binpacking(
    resultado: Dict[str, Any],
    client_config,
    cliente: str
) -> Dict[str, Any]:
    """
    Etiqueta camiones como BH en BinPacking según reglas especiales.
    """
    if not getattr(client_config, "PERMITE_BH", False):
        return resultado
    
    cd_con_bh = getattr(client_config, "CD_CON_BH", [])
    bh_vcu_max = getattr(client_config, "BH_VCU_MAX", 1)
    
    # Obtener vcu_min desde TRUCK_TYPES['bh']
    truck_types = getattr(client_config, "TRUCK_TYPES", {})
    normal_truck = truck_types.get('normal', {})
    normal_target = float(normal_truck.get('vcu_min', 1))
    
    conversiones = 0

    for cam in resultado.get("camiones", []):
        cds = cam.get("cd", [])
        if not cds:
            continue
        
        vcu = cam.get("vcu_max", 0)
        
        if (cds[0] in cd_con_bh
            and cam.get("flujo_oc") != "MIX"
            and vcu <= bh_vcu_max
            and vcu < normal_target
            and cam.get("tipo_ruta") == "normal"):
            
            cam["tipo_camion"] = "bh"
            conversiones += 1

    if conversiones > 0:
        print(f"[BINPACKING] Auto-etiquetados {conversiones} camiones como BH")

    
    return resultado