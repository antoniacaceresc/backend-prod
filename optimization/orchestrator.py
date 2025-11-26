"""
API pública del optimizador.
Orquesta el flujo completo de optimización en dos fases (VCU y BinPacking).
"""

from __future__ import annotations

import time
from typing import List, Dict, Any, Tuple, Optional
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
from utils.config_helpers import extract_truck_capacities, get_camiones_permitidos_para_ruta, get_capacity_for_type
from models.domain import Camion

# ============================================================================
# CONSTANTES
# ============================================================================

MAX_TIEMPO_POR_GRUPO = int(os.getenv("MAX_TIEMPO_POR_GRUPO", "30"))
THREAD_WORKERS_NORMAL = int(os.getenv("THREAD_WORKERS_NORMAL", str(min(8, (os.cpu_count() or 4)))))

# Flag para activar/desactivar prints de debug
DEBUG_VALIDATION = True  # ✅ CAMBIAR A True TEMPORALMENTE

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
    fase: str,
    tpg: int,
    request_timeout: int
) -> Dict[str, Any]:
    """
    Ejecuta optimización completa (VCU o BinPacking).
    
    Args:
        pedidos_objetos: Lista de objetos Pedido
        pedidos_dicts: Lista de dicts de pedidos
        client_config: Configuración del cliente
        cliente: Nombre del cliente
        fase: "vcu" o "binpacking"
        tpg: Tiempo por grupo
        request_timeout: Timeout total
    
    Returns:
        Dict con resultados consolidados
    """
    start_total = time.time()
    
    # Extraer capacidades
    capacidades = extract_truck_capacities(client_config)
    capacidad_default = capacidades.get(TipoCamion.PAQUETERA, next(iter(capacidades.values())))
    
    print(f"\n{'='*80}")
    print(f"INICIANDO OPTIMIZACIÓN {fase.upper()}")
    print(f"{'='*80}")
    print(f"Total pedidos: {len(pedidos_objetos)}")
    print(f"Tiempo por grupo: {tpg}s")
    print(f"Timeout total: {request_timeout}s")
    
    if fase == "vcu":
        # Usar nueva función de cascada con tipos de camión
        resultados = _optimizar_grupos_vcu_cascada_con_camiones(
            pedidos_objetos, client_config, capacidades,
            tpg, request_timeout, start_total
        )
    else:  # binpacking
        grupos = generar_grupos_optimizacion(pedidos_objetos, client_config, "binpacking")
        resultados = _optimizar_grupos_binpacking(
            grupos, client_config, capacidades,
            tpg, request_timeout, start_total
        )
    
    # Consolidar resultados
    return _consolidar_resultados(
        resultados, pedidos_objetos, pedidos_dicts,
        capacidad_default, client_config
    )


def _optimizar_grupos_paralelo_nestle(
    grupos_con_capacidad: List[Tuple],
    client_config,
    tpg: int,
    request_timeout: int,
    start_total: float
) -> List[Tuple[Dict[str, Any], TipoCamion]]:
    """
    Optimiza grupos normales en paralelo con camiones Nestlé.
    
    Returns:
        Lista de tuplas (resultado, tipo_camion_usado)
    """
    resultados = []
    
    def optimizar_grupo_wrapper(args):
        cfg, pedidos_grupo, cap, tipo_camion = args
        n_pedidos = len(pedidos_grupo)
        tiempo_grupo = ajustar_tiempo_grupo(tpg, n_pedidos, "normal")
        
        print(f"[VCU]   Optimizando {cfg.id}: {n_pedidos} pedidos, {tiempo_grupo}s, camión: {tipo_camion.value}")
        
        res = optimizar_grupo_vcu(
            pedidos_grupo, cfg, client_config, cap, tiempo_grupo
        )
        
        return (res, tipo_camion, cfg.id, n_pedidos)
    
    # Ejecutar en paralelo
    with ThreadPoolExecutor(max_workers=THREAD_WORKERS_NORMAL) as executor:
        futures = {
            executor.submit(optimizar_grupo_wrapper, args): args 
            for args in grupos_con_capacidad
        }
        
        for future in as_completed(futures):
            if time.time() - start_total > (request_timeout - 2):
                print("[VCU] Timeout cercano, cancelando tareas pendientes")
                break
            
            try:
                res, tipo_camion, grupo_id, n_pedidos = future.result()
                
                if res.get("status") in ("OPTIMAL", "FEASIBLE"):
                    nuevos = res.get("pedidos_asignados_ids", [])
                    n_camiones = len(res.get("camiones", []))
                    
                    if nuevos and n_camiones > 0:
                        resultados.append((res, tipo_camion))
                        print(f"[VCU] ✓ Normal {grupo_id}: {len(nuevos)}/{n_pedidos} pedidos en {n_camiones} camiones")
                    else:
                        print(f"[VCU] ⚠️ Normal {grupo_id}: {res.get('status')} pero 0 pedidos/camiones")
                else:
                    print(f"[VCU] ✗ Normal {grupo_id}: {res.get('status', 'NO_SOLUTION')}")
            
            except Exception as e:
                print(f"[VCU] Error en grupo: {e}")
    
    return resultados


def _optimizar_grupos_vcu_cascada_con_camiones(
    pedidos_originales: List[Pedido],
    client_config,
    capacidades: Dict[TipoCamion, TruckCapacity],
    tpg: int,
    request_timeout: int,
    start_total: float
) -> List[Dict[str, Any]]:
    """
    Optimización VCU en cascada considerando tipos de camión.
    
    Flujo:
    0. Procesa rutas multi_ce_prioridad SECUENCIAL con camiones Nestlé (si existen)
    1. Procesa rutas normales EN PARALELO con camiones Nestlé (paquetera, rampla_directa)
    2. Procesa multi_ce SECUENCIAL con camiones Nestlé
    3. Procesa multi_cd SECUENCIAL con camiones Nestlé
    4. Repite el ciclo anterior con camiones backhaul en rutas que lo permitan
    
    Los pedidos no asignados fluyen de una etapa a otra.
    """
    from utils.config_helpers import get_camiones_permitidos_para_ruta, get_capacity_for_type
    
    resultados = []
    pedidos_asignados_global = set()
    pedidos_disponibles = pedidos_originales.copy()
    
    # ========================================================================
    # FASE 1: OPTIMIZACIÓN CON CAMIONES NESTLÉ
    # ========================================================================
    print("\n" + "="*80)
    print("FASE 1: OPTIMIZACIÓN CON CAMIONES NESTLÉ")
    print("="*80)
    
    # 0. Rutas MULTI_CE_PRIORIDAD en SECUENCIAL (PRIMERO)
    grupos_prioridad = _generar_grupos_para_tipo(pedidos_disponibles, client_config, "multi_ce_prioridad")
    
    if grupos_prioridad:
        print(f"\n[VCU] Procesando MULTI_CE_PRIORIDAD con camiones Nestlé SECUENCIAL: {len(grupos_prioridad)} grupos")
        
        for cfg, pedidos_grupo in grupos_prioridad:
            if time.time() - start_total > (request_timeout - 2):
                break
            
            # Filtrar pedidos ya asignados
            pedidos_no_asignados = [p for p in pedidos_grupo if p.pedido not in pedidos_asignados_global]
            if not pedidos_no_asignados:
                continue
            
            n_pedidos = len(pedidos_no_asignados)
            tiempo_grupo = ajustar_tiempo_grupo(tpg, n_pedidos, "multi_ce_prioridad")
            
            # Obtener camiones permitidos para esta ruta
            camiones_permitidos = get_camiones_permitidos_para_ruta(
                client_config, cfg.cd, cfg.ce, "multi_ce_prioridad"
            )
            camiones_nestle = [c for c in camiones_permitidos if c.es_nestle]
            
            if not camiones_nestle:
                continue
            
            # Elegir tipo de camión
            if TipoCamion.PAQUETERA in camiones_nestle:
                tipo_camion = TipoCamion.PAQUETERA
            elif TipoCamion.RAMPLA_DIRECTA in camiones_nestle:
                tipo_camion = TipoCamion.RAMPLA_DIRECTA
            else:
                tipo_camion = camiones_nestle[0]
            
            cap = get_capacity_for_type(client_config, tipo_camion)
            
            print(f"[VCU]   Optimizando {cfg.id}: {n_pedidos} pedidos, {tiempo_grupo}s, camión: {tipo_camion.value}")
            
            res = optimizar_grupo_vcu(
                pedidos_no_asignados, cfg, client_config, cap, tiempo_grupo
            )
            
            if res.get("status") in ("OPTIMAL", "FEASIBLE"):
                nuevos = res.get("pedidos_asignados_ids", [])
                camiones = res.get("camiones", [])
                
                if nuevos and camiones:
                    # Reclasificar y etiquetar camiones
                    for cam in camiones:
                        tipo_optimo = _reclasificar_camion_nestle(cam, client_config)
                        
                        # Asignar el tipo - siempre es un objeto Camion aquí
                        cam.tipo_camion = TipoCamion(tipo_optimo)
                        
                        # También actualizar en todos los pedidos del camión
                        for pedido in cam.pedidos:
                            pedido.tipo_camion = tipo_optimo
                    
                    pedidos_asignados_global.update(nuevos)
                    resultados.append(res)
                    print(f"[VCU] ✓ MULTI_CE_PRIORIDAD Nestlé: {len(nuevos)}/{n_pedidos} pedidos en {len(camiones)} camiones")
                else:
                    print(f"[VCU] ⚠️ MULTI_CE_PRIORIDAD Nestlé: {res.get('status')} pero 0 pedidos/camiones")
            else:
                print(f"[VCU] ✗ MULTI_CE_PRIORIDAD Nestlé: {res.get('status', 'NO_SOLUTION')}")
        
        # Actualizar pedidos disponibles
        pedidos_disponibles = [p for p in pedidos_disponibles if p.pedido not in pedidos_asignados_global]
    
    # 1. Rutas NORMALES en PARALELO
    print("armando grupos normales")
    grupos_normal = _generar_grupos_para_tipo(pedidos_disponibles, client_config, "normal")
    print("previo a grupos normales")
    
    if grupos_normal:
        # ORDENAR grupos por complejidad (más pedidos primero)
        grupos_normal_sorted = sorted(
            grupos_normal,
            key=lambda x: len(x[1]),  # x[1] son los pedidos del grupo
            reverse=True  # Descendente: más complejos primero
        )

        tamaños = [len(g[1]) for g in grupos_normal_sorted[:5]]
        print(f"\n[VCU] Procesando NORMAL con camiones Nestlé EN PARALELO: {len(grupos_normal)} grupos")

        # Preparar grupos con sus capacidades
        grupos_con_capacidad = []
        for cfg, pedidos_grupo in grupos_normal_sorted:
            # Filtrar pedidos ya asignados
            pedidos_no_asignados = [p for p in pedidos_grupo if p.pedido not in pedidos_asignados_global]
            if not pedidos_no_asignados:
                continue
            
            # Obtener tipo de camión Nestlé para esta ruta
            camiones_permitidos = get_camiones_permitidos_para_ruta(
                client_config, cfg.cd, cfg.ce, "normal"
            )
            camiones_nestle = [c for c in camiones_permitidos if c.es_nestle]
            
            if not camiones_nestle:
                continue
            
            # Elegir tipo de camión (paquetera por defecto)
            if TipoCamion.PAQUETERA in camiones_nestle:
                tipo_camion = TipoCamion.PAQUETERA
            elif TipoCamion.RAMPLA_DIRECTA in camiones_nestle:
                tipo_camion = TipoCamion.RAMPLA_DIRECTA
            else:
                tipo_camion = camiones_nestle[0]
            
            cap = get_capacity_for_type(client_config, tipo_camion)
            
            grupos_con_capacidad.append((cfg, pedidos_no_asignados, cap, tipo_camion))
        
        # Optimizar rutas normales EN PARALELO
        if grupos_con_capacidad:
            resultados_normal = _optimizar_grupos_paralelo_nestle(
                grupos_con_capacidad, client_config, tpg, request_timeout, start_total
            )
            
            # Consolidar resultados con reclasificación
            for res, tipo_camion_usado in resultados_normal:
                if res.get("status") in ("OPTIMAL", "FEASIBLE"):
                    nuevos = res.get("pedidos_asignados_ids", [])
                    camiones = res.get("camiones", [])
                    
                    if nuevos and camiones:
                        # Reclasificar cada camión individualmente
                        for cam in camiones:
                            tipo_optimo = _reclasificar_camion_nestle(cam, client_config)
                            
                            # Asignar el tipo - siempre es un objeto Camion aquí
                            cam.tipo_camion = TipoCamion(tipo_optimo)
                            
                            # También actualizar en todos los pedidos del camión
                            for pedido in cam.pedidos:
                                pedido.tipo_camion = tipo_optimo
                        
                        pedidos_asignados_global.update(nuevos)
                        resultados.append(res)
        
        # Actualizar pedidos disponibles
        pedidos_disponibles = [p for p in pedidos_disponibles if p.pedido not in pedidos_asignados_global]
    
    # 2. Rutas MULTI_CE y MULTI_CD en SECUENCIAL (cascada)
    for tipo_ruta in ["multi_ce", "multi_cd"]:
        if time.time() - start_total > (request_timeout - 2):
            print(f"[VCU] Timeout cercano, deteniendo en tipo {tipo_ruta}")
            break
        
        # Generar grupos para este tipo de ruta
        grupos_tipo = _generar_grupos_para_tipo(pedidos_disponibles, client_config, tipo_ruta)
        
        if not grupos_tipo:
            print(f"[VCU] {tipo_ruta.upper()}: No hay grupos")
            continue
        
        print(f"\n[VCU] Procesando {tipo_ruta.upper()} con camiones Nestlé SECUENCIAL: {len(grupos_tipo)} grupos")
        
        # Procesar cada grupo secuencialmente
        for cfg, pedidos_grupo in grupos_tipo:
            if time.time() - start_total > (request_timeout - 2):
                break
            
            # Filtrar pedidos ya asignados
            pedidos_no_asignados = [p for p in pedidos_grupo if p.pedido not in pedidos_asignados_global]
            if not pedidos_no_asignados:
                continue
            
            n_pedidos = len(pedidos_no_asignados)
            tiempo_grupo = ajustar_tiempo_grupo(tpg, n_pedidos, tipo_ruta)
            
            # Obtener camiones permitidos para esta ruta
            camiones_permitidos = get_camiones_permitidos_para_ruta(
                client_config, cfg.cd, cfg.ce, tipo_ruta
            )
            camiones_nestle = [c for c in camiones_permitidos if c.es_nestle]
            
            if not camiones_nestle:
                continue
            
            # Elegir tipo de camión
            if TipoCamion.PAQUETERA in camiones_nestle:
                tipo_camion = TipoCamion.PAQUETERA
            elif TipoCamion.RAMPLA_DIRECTA in camiones_nestle:
                tipo_camion = TipoCamion.RAMPLA_DIRECTA
            else:
                tipo_camion = camiones_nestle[0]
            
            cap = get_capacity_for_type(client_config, tipo_camion)
            
            print(f"[VCU]   Optimizando {cfg.id}: {n_pedidos} pedidos, {tiempo_grupo}s, camión: {tipo_camion.value}")
            
            res = optimizar_grupo_vcu(
                pedidos_no_asignados, cfg, client_config, cap, tiempo_grupo
            )
            
            if res.get("status") in ("OPTIMAL", "FEASIBLE"):
                nuevos = res.get("pedidos_asignados_ids", [])
                camiones = res.get("camiones", [])
                
                if nuevos and camiones:
                    # Reclasificar y etiquetar camiones
                    for cam in camiones:
                        tipo_optimo = _reclasificar_camion_nestle(cam, client_config)
                        
                        # Asignar el tipo - siempre es un objeto Camion aquí
                        cam.tipo_camion = TipoCamion(tipo_optimo)
                        
                        # También actualizar en todos los pedidos del camión
                        for pedido in cam.pedidos:
                            pedido.tipo_camion = tipo_optimo
                    
                    pedidos_asignados_global.update(nuevos)
                    resultados.append(res)
                    print(f"[VCU] ✓ {tipo_ruta.upper()} Nestlé: {len(nuevos)}/{n_pedidos} pedidos en {len(camiones)} camiones")
                else:
                    print(f"[VCU] ⚠️ {tipo_ruta.upper()} Nestlé: {res.get('status')} pero 0 pedidos/camiones")
            else:
                print(f"[VCU] ✗ {tipo_ruta.upper()} Nestlé: {res.get('status', 'NO_SOLUTION')}")
        
        # Actualizar pedidos disponibles
        pedidos_disponibles = [p for p in pedidos_disponibles if p.pedido not in pedidos_asignados_global]
    
    # ========================================================================
    # FASE 2: OPTIMIZACIÓN CON CAMIONES BACKHAUL
    # ========================================================================
    print("\n" + "="*80)
    print("FASE 2: OPTIMIZACIÓN CON CAMIONES BACKHAUL")
    print("="*80)
    
    # Definir el orden: multi_ce_prioridad, normal, multi_ce, multi_cd
    orden_tipos_ruta_bh = ["multi_ce_prioridad", "normal", "multi_ce", "multi_cd"]
    
    for tipo_ruta in orden_tipos_ruta_bh:
        if time.time() - start_total > (request_timeout - 2):
            print(f"[VCU] Timeout cercano, deteniendo en tipo {tipo_ruta} BH")
            break
        
        # Generar grupos para este tipo de ruta
        grupos_tipo = _generar_grupos_para_tipo(pedidos_disponibles, client_config, tipo_ruta)
        
        if not grupos_tipo:
            continue
        
        print(f"\n[VCU] Procesando {tipo_ruta.upper()} con camiones Backhaul: {len(grupos_tipo)} grupos")
        
        # Procesar cada grupo
        for cfg, pedidos_grupo in grupos_tipo:
            if time.time() - start_total > (request_timeout - 2):
                break
            
            # Filtrar pedidos ya asignados
            pedidos_no_asignados = [p for p in pedidos_grupo if p.pedido not in pedidos_asignados_global]
            if not pedidos_no_asignados:
                continue
            
            n_pedidos = len(pedidos_no_asignados)
            tiempo_grupo = ajustar_tiempo_grupo(tpg, n_pedidos, tipo_ruta)
            
            # Verificar si esta ruta permite backhaul
            camiones_permitidos = get_camiones_permitidos_para_ruta(
                client_config, cfg.cd, cfg.ce, tipo_ruta
            )
            
            if TipoCamion.BACKHAUL not in camiones_permitidos:
                continue
            
            # Usar capacidad backhaul
            cap = get_capacity_for_type(client_config, TipoCamion.BACKHAUL)
            
            print(f"[VCU]   Optimizando {cfg.id}: {n_pedidos} pedidos, {tiempo_grupo}s, camión: backhaul")
            
            res = optimizar_grupo_vcu(
                pedidos_no_asignados, cfg, client_config, cap, tiempo_grupo
            )
            
            if res.get("status") in ("OPTIMAL", "FEASIBLE"):
                nuevos = res.get("pedidos_asignados_ids", [])
                camiones = res.get("camiones", [])
                
                if nuevos and camiones:
                    # Etiquetar camiones como backhaul
                    for cam in camiones:
                        cam.tipo_camion = TipoCamion.BACKHAUL
                        
                        # También actualizar en todos los pedidos del camión
                        for pedido in cam.pedidos:
                            pedido.tipo_camion = "backhaul"
                    
                    pedidos_asignados_global.update(nuevos)
                    resultados.append(res)
                    print(f"[VCU] ✓ {tipo_ruta.upper()} BH: {len(nuevos)}/{n_pedidos} pedidos en {len(camiones)} camiones")
                else:
                    print(f"[VCU] ⚠️ {tipo_ruta.upper()} BH: {res.get('status')} pero 0 pedidos/camiones")
            else:
                print(f"[VCU] ✗ {tipo_ruta.upper()} BH: {res.get('status', 'NO_SOLUTION')}")
        
        # Actualizar pedidos disponibles para siguiente tipo de ruta
        pedidos_disponibles = [p for p in pedidos_disponibles if p.pedido not in pedidos_asignados_global]
    
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
    from utils.config_helpers import get_camiones_permitidos_para_ruta, get_capacity_for_type
    
    resultados = []
    
    for cfg, pedidos_grupo in grupos:
        if not pedidos_grupo:
            continue
        
        n_pedidos = len(pedidos_grupo)
        tiempo_grupo = ajustar_tiempo_grupo(tpg, n_pedidos, cfg.tipo.value)
        
        if time.time() - start_total + tiempo_grupo > (request_timeout - 2):
            break
        
        # Obtener camiones permitidos para esta ruta
        camiones_permitidos = get_camiones_permitidos_para_ruta(
            client_config, cfg.cd, cfg.ce, cfg.tipo.value
        )
        
        # Usar el primer tipo permitido (prioridad a Nestlé)
        tipo_camion = camiones_permitidos[0] if camiones_permitidos else TipoCamion.PAQUETERA
        cap = get_capacity_for_type(client_config, tipo_camion)
        
        res = optimizar_grupo_binpacking(pedidos_grupo, cfg, client_config, cap, tiempo_grupo)
        
        if res.get("status") in ("OPTIMAL", "FEASIBLE") and res.get("camiones"):
            camiones = res.get("camiones", [])
            
            # Etiquetar camiones - son objetos Camion
            for cam in camiones:
                # Si es Nestlé, reclasificar
                if tipo_camion.es_nestle:
                    tipo_optimo = _reclasificar_camion_nestle(cam, client_config)
                    cam.tipo_camion = TipoCamion(tipo_optimo)
                    
                    # Actualizar en todos los pedidos
                    for pedido in cam.pedidos:
                        pedido.tipo_camion = tipo_optimo
                else:
                    # Si es backhaul, asignar directamente
                    cam.tipo_camion = tipo_camion
                    
                    # Actualizar en todos los pedidos
                    for pedido in cam.pedidos:
                        pedido.tipo_camion = tipo_camion.value
            
            resultados.append(res)
        
        if time.time() - start_total > (request_timeout - 2):
            break
    
    return resultados


def _consolidar_resultados(
    resultados: List[Dict[str, Any]],
    pedidos_originales: List[Pedido],
    pedidos_dicts: List[Dict[str, Any]],
    capacidad_default: TruckCapacity,
    client_config 
) -> Dict[str, Any]:
    """
    Consolida resultados de todos los grupos en una respuesta única.
    """
    from services.postprocess import _actualizar_opciones_tipo_camion 
    
    # Consolidar camiones
    all_camiones = []
    for res in resultados:
        all_camiones.extend(res.get("camiones", []))

    # Validación masiva de altura
    all_camiones = _validar_altura_camiones_paralelo(all_camiones, client_config)
    
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
            # Usar to_api_dict para mantener consistencia y preservar SKUs
            pedido_dict = pedido_obj.to_api_dict(capacidad_default)
            
            # Agregar metadata adicional del Excel original si existe
            pedidos_map = {p["PEDIDO"]: p for p in pedidos_dicts}
            extra_data = pedidos_map.get(pedido_obj.pedido, {})
            
            # Solo agregar campos que no están en to_api_dict
            if "Fecha preferente de entrega" in extra_data:
                pedido_dict["Fecha preferente de entrega"] = extra_data["Fecha preferente de entrega"]
            
            pedidos_no_incluidos.append(pedido_dict)
    
    # Convertir camiones a dicts para API
    camiones_dicts = [cam.to_api_dict() for cam in all_camiones]

    return {
        "camiones": camiones_dicts,
        "pedidos_no_incluidos": pedidos_no_incluidos,
        "estadisticas": _compute_stats_from_objects(all_camiones, pedidos_originales, pedidos_asignados_ids)
    }


def _validar_altura_camiones_paralelo(
        camiones: List[Camion],
        config,
        operacion: str = "operacion"
    ) -> None:
        """
        Valida altura de múltiples camiones EN PARALELO con logging ordenado.
        """
        import time
        import threading
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from optimization.validation.height_validator import HeightValidator
        
        # ✅ LOCK para prints ordenados
        print_lock = threading.Lock()
        
        # Filtrar camiones que tienen pedidos con SKUs
        camiones_a_validar = [
            cam for cam in camiones
            if cam.pedidos and any(p.tiene_skus for p in cam.pedidos)
        ]
        
        if not camiones_a_validar:
            if DEBUG_VALIDATION:
                print(f"[{operacion.upper()}] No hay camiones con SKUs para validar")
            return
        
        with print_lock:
            print(f"\n{'='*80}")
            print(f"VALIDACIÓN DE ALTURA PARALELA - {operacion.upper()}")
            print(f"{'='*80}")
            print(f"Total camiones a validar: {len(camiones_a_validar)}")
        
        # Determinar número de threads
        max_workers = min(8, len(camiones_a_validar))
        with print_lock:
            print(f"Threads paralelos: {max_workers}")
            print(f"{'='*80}\n")
        
        # Crear validador
        altura_maxima = 270
        if hasattr(config, 'TRUCK_TYPES') and 'paquetera' in config.TRUCK_TYPES:
            altura_maxima = config.TRUCK_TYPES['paquetera'].get('altura_cm', 270)
        
        permite_consolidacion = getattr(config, 'PERMITE_CONSOLIDACION', False)
        max_skus_por_pallet = getattr(config, 'MAX_SKUS_POR_PALLET', 3)
        
        validator = HeightValidator(
            altura_maxima_cm=altura_maxima,
            permite_consolidacion=permite_consolidacion,
            max_skus_por_pallet=max_skus_por_pallet
        )
        
        # Función worker con logging ordenado
        def validar_camion_worker(cam: Camion, cam_idx: int) -> Tuple[str, bool, float, Optional[str]]:
            """
            Worker que valida un camión.
            Returns: (camion_id, es_valido, tiempo_ms, error_msg)
            """
            start = time.time()
            elapsed_ms = 0 
            error_msg = None
            
            with print_lock:
                print(f"\n{'─'*80}")
                print(f"🔍 VALIDANDO CAMIÓN [{cam_idx}/{len(camiones_a_validar)}]: {cam.id}")
                print(f"   Pedidos: {len(cam.pedidos)} | Pallets: {cam.pallets_conf:.1f}")
                print(f"{'─'*80}")
            
            try:
                es_valido, errores, layout = validator.validar_camion_rapido(cam)
                
                # 🔍 DEBUG: Imprimir qué retornó la validación
                with print_lock:
                    print(f"[DEBUG] Retorno validación:")
                    print(f"  es_valido: {es_valido} (type: {type(es_valido)})")
                    print(f"  errores: {errores} (type: {type(errores)})")
                    print(f"  layout: {layout} (type: {type(layout)})")
                
                # Normalizar errores con validación exhaustiva
                errores_limpios = []
                
                if errores is None:
                    with print_lock:
                        print(f"[DEBUG] errores es None, usando lista vacía")
                    errores_limpios = []
                elif not isinstance(errores, (list, tuple)):
                    with print_lock:
                        print(f"[DEBUG] errores NO es lista/tupla, convirtiendo a string")
                    errores_limpios = [str(errores)]
                else:
                    with print_lock:
                        print(f"[DEBUG] errores es lista con {len(errores)} elementos")
                        for i, e in enumerate(errores):
                            print(f"    [{i}]: {repr(e)} (type: {type(e)})")
                    
                    # Filtrar elementos válidos
                    for e in errores:
                        if e is not None and e is not Ellipsis and e != "":
                            try:
                                errores_limpios.append(str(e))
                            except Exception as conv_err:
                                with print_lock:
                                    print(f"[DEBUG] Error convirtiendo elemento: {conv_err}")

                error_msg = "; ".join(errores_limpios) if errores_limpios else None

                with print_lock:
                    print(f"[DEBUG] errores_limpios final: {errores_limpios}")

                elapsed_ms = (time.time() - start) * 1000


                # ✅ CONSTRUIR Y GUARDAR LAYOUT_INFO COMPLETO
                layout_info = {
                    'altura_validada': bool(es_valido),
                    'errores_validacion': errores_limpios,
                }
                
                if layout is not None:
                    cam.pos_total = layout.posiciones_usadas
                    
                    layout_info.update({
                        'posiciones_usadas': layout.posiciones_usadas,
                        'posiciones_disponibles': layout.posiciones_disponibles,
                        'altura_maxima_cm': layout.altura_maxima_cm,
                        'total_pallets_fisicos': layout.total_pallets,
                        'altura_maxima_usada_cm': round(layout.altura_maxima_usada, 1),
                        'altura_promedio_usada': round(layout.altura_promedio_usada, 1),
                        'aprovechamiento_altura': round(layout.aprovechamiento_altura * 100, 1),
                        'aprovechamiento_posiciones': round(layout.aprovechamiento_posiciones * 100, 1),
                        'posiciones': [
                            {
                                'id': pos.id,
                                'altura_usada_cm': pos.altura_usada_cm,
                                'altura_disponible_cm': pos.espacio_disponible_cm,
                                'num_pallets': pos.num_pallets,
                                'pallets': [
                                    {
                                        'id': pallet.id,
                                        'nivel': pallet.nivel,
                                        'altura_cm': pallet.altura_total_cm,
                                        'skus': [
                                            {
                                                'sku_id': frag.sku_id,
                                                'pedido_id': frag.pedido_id,
                                                'altura_cm': frag.altura_cm,
                                                'categoria': frag.categoria.value,
                                                'es_picking': frag.es_picking
                                            }
                                            for frag in pallet.fragmentos
                                        ]
                                    }
                                    for pallet in pos.pallets_apilados
                                ]
                            }
                            for pos in layout.posiciones
                            if not pos.esta_vacia
                        ]
                    })
                else:
                    # Si no hay layout válido pero pasó validación
                    if es_valido:
                        layout_info['posiciones_usadas'] = 0
                
                # ✅ GUARDAR EN METADATA
                cam.metadata['layout_info'] = layout_info
                
                # Print de resultado
                with print_lock:
                    if es_valido:
                        print(f"✅ Camión {cam.id}: VÁLIDO ({elapsed_ms:.0f}ms)")
                    else:
                        print(f"{'='*80}")
                        print(f"❌ Camión {cam.id}: INVÁLIDO ({elapsed_ms:.0f}ms)")
                        if errores_limpios:
                            for err in errores_limpios:
                                print(f"   • {err}")
                        print(f"{'='*80}")
                
                return (cam.id, es_valido, elapsed_ms, error_msg)


            except Exception as e:
                elapsed_ms = (time.time() - start) * 1000
                error_msg = str(e)
                
                import traceback
                error_detail = traceback.format_exc()
                
                with print_lock:
                    print(f"❌❌❌ EXCEPCIÓN en camión {cam.id} ❌❌❌")
                    print(f"Tipo: {type(e).__name__}")
                    print(f"Mensaje: {str(e)}")
                    print(f"Traceback:")
                    print(error_detail)
                    print(f"{'─'*80}")
                
                cam.metadata['layout_info'] = {
                    'altura_validada': False,
                    'errores_validacion': [f"Error en validación: {str(e)}"],
                    'error_tipo': type(e).__name__,
                    'error_detalle': str(e),
                    'error_traceback': error_detail
                }
                
                return (cam.id, False, elapsed_ms, str(e))
        
        # Ejecutar validaciones en paralelo
        validos = 0
        invalidos = 0
        errores_capturados = []
        tiempos = []
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Enviar todos los trabajos con índice
            futures = {
                executor.submit(validar_camion_worker, cam, idx+1): cam
                for idx, cam in enumerate(camiones_a_validar)
            }
            
            # Recolectar resultados
            for future in as_completed(futures):
                cam = futures[future]
                try:
                    camion_id, es_valido, tiempo_ms, error_msg = future.result()
                    tiempos.append(tiempo_ms)
                    
                    if es_valido:
                        validos += 1
                    else:
                        invalidos += 1
                        if error_msg:
                            errores_capturados.append((camion_id, error_msg))
                        
                except Exception as e:
                    invalidos += 1
                    with print_lock:
                        print(f"❌ Error obteniendo resultado de {cam.id}: {e}")
                        import traceback
                        traceback.print_exc()
        
        # Reporte final
        tiempo_promedio = sum(tiempos) / len(tiempos) if tiempos else 0
        
        with print_lock:
            print(f"\n{'='*80}")
            print(f"RESUMEN DE VALIDACIÓN - {operacion.upper()}")
            print(f"{'='*80}")
            print(f"✅ Válidos: {validos}")
            print(f"❌ Inválidos: {invalidos}")
            print(f"⏱️  Tiempo promedio: {tiempo_promedio:.0f}ms")
            
            if errores_capturados:
                print(f"\n🔴 CAMIONES CON ERRORES:")
                for cam_id, error_msg in errores_capturados:
                    print(f"   • {cam_id}: {error_msg}")
            
            print(f"{'='*80}\n")

        return camiones




def _compute_stats_from_objects(
    camiones: List[Camion],
    pedidos_originales: List[Pedido],
    pedidos_asignados_ids: set
) -> Dict[str, Any]:
    """
    Calcula estadísticas desde objetos Camion y Pedido.
    """
    from collections import Counter
    
    total_pedidos = len(pedidos_originales)
    pedidos_asignados = len(pedidos_asignados_ids)
    
    # Contadores por tipo de camión
    tipos_camion = Counter(c.tipo_camion.value for c in camiones)
    cantidad_paquetera = tipos_camion.get('paquetera', 0)
    cantidad_rampla = tipos_camion.get('rampla_directa', 0)
    cantidad_backhaul = tipos_camion.get('backhaul', 0)
    
    # Camiones Nestlé = paquetera + rampla_directa
    cantidad_nestle = cantidad_paquetera + cantidad_rampla
    
    # VCU promedios
    vcu_total = sum(c.vcu_max for c in camiones) / len(camiones) if camiones else 0
    
    # VCU promedio de camiones Nestlé (paquetera + rampla_directa)
    camiones_nestle = [c for c in camiones if c.tipo_camion.es_nestle]
    vcu_nestle = sum(c.vcu_max for c in camiones_nestle) / len(camiones_nestle) if camiones_nestle else 0
    
    # VCU promedio de camiones Backhaul
    camiones_bh = [c for c in camiones if c.tipo_camion == TipoCamion.BACKHAUL]
    vcu_bh = sum(c.vcu_max for c in camiones_bh) / len(camiones_bh) if camiones_bh else 0
    
    # Valorizado
    valorizado = sum(
        sum(p.valor for p in c.pedidos)
        for c in camiones
    )
    
    return {
        "promedio_vcu": round(vcu_total, 3),
        "promedio_vcu_nestle": round(vcu_nestle, 3),
        "promedio_vcu_backhaul": round(vcu_bh, 3),
        "cantidad_camiones": len(camiones),
        "cantidad_camiones_nestle": cantidad_nestle,
        "cantidad_camiones_paquetera": cantidad_paquetera,
        "cantidad_camiones_rampla_directa": cantidad_rampla,
        "cantidad_camiones_backhaul": cantidad_backhaul,
        "cantidad_pedidos_asignados": pedidos_asignados,
        "total_pedidos": total_pedidos,
        "valorizado": valorizado,
        # Mantener compatibilidad con frontend antiguo (deprecated)
        "promedio_vcu_normal": round(vcu_nestle, 3),
        "promedio_vcu_bh": round(vcu_bh, 3),
        "cantidad_camiones_normal": cantidad_nestle,
        "cantidad_camiones_bh": cantidad_backhaul,
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


def _reclasificar_camion_nestle(camion, client_config) -> str:
    """
    Determina el tipo de camión Nestlé óptimo para un camión ya optimizado.
    
    Lógica:
    - Se optimiza inicialmente con PAQUETERA (más posiciones)
    - Si el resultado cabe en RAMPLA_DIRECTA, se reclasifica
    
    Args:
        camion: Objeto Camion o dict con datos del camión
        client_config: Configuración del cliente
    
    Returns:
        Tipo de camión óptimo: "paquetera" o "rampla_directa"
    """
    from utils.config_helpers import get_capacity_for_type
    
    # Obtener capacidades de ambos tipos
    cap_paquetera = get_capacity_for_type(client_config, TipoCamion.PAQUETERA)
    cap_rampla = get_capacity_for_type(client_config, TipoCamion.RAMPLA_DIRECTA)
    
    # Si tienen las mismas capacidades, no hay diferencia
    if (cap_paquetera.max_positions == cap_rampla.max_positions and
        cap_paquetera.cap_weight == cap_rampla.cap_weight and
        cap_paquetera.cap_volume == cap_rampla.cap_volume):
        return "paquetera"  # Por defecto
    
    # Extraer métricas del camión (soporta objeto o dict)
    if hasattr(camion, 'pedidos'):
        # Es un objeto Camion
        num_pedidos = len(camion.pedidos)
        peso_total = sum(p.peso for p in camion.pedidos)
        volumen_total = sum(p.volumen for p in camion.pedidos)
        pallets_total = camion.pallets_capacidad
    else:
        # Es un dict
        num_pedidos = len(camion.get("pedidos", []))
        peso_total = camion.get("peso_total", 0)
        volumen_total = camion.get("volumen_total", 0)
        pallets_total = camion.get("pallets_total", 0)
    
    # Verificar si cabe en rampla directa
    cabe_en_rampla = (
        num_pedidos <= cap_rampla.max_positions and
        peso_total <= cap_rampla.cap_weight and
        volumen_total <= cap_rampla.cap_volume and
        pallets_total <= cap_rampla.max_pallets
    )
    
    if cabe_en_rampla:
        # Calcular VCU con rampla para verificar que cumple el target
        vcu_peso_rampla = peso_total / cap_rampla.cap_weight if cap_rampla.cap_weight > 0 else 0
        vcu_vol_rampla = volumen_total / cap_rampla.cap_volume if cap_rampla.cap_volume > 0 else 0
        vcu_max_rampla = max(vcu_peso_rampla, vcu_vol_rampla)
        
        # Verificar si cumple el target de VCU
        if vcu_max_rampla >= cap_rampla.vcu_min:
            return "rampla_directa"
    
    # Si no cabe o no cumple VCU target, usar paquetera
    return "paquetera"


def _aplicar_reclasificacion_nestle(
    resultados: List[Tuple[Dict[str, Any], TipoCamion]], 
    client_config
) -> List[Tuple[Dict[str, Any], TipoCamion]]:
    """
    Aplica reclasificación de camiones Nestlé a resultados de optimización.
    
    Args:
        resultados: Lista de tuplas (resultado_optimizacion, tipo_camion)
        client_config: Configuración del cliente
    
    Returns:
        Lista de tuplas con tipos de camión reclasificados
    """
    resultados_reclasificados = []
    
    total_reclasificados = 0
    
    for res, tipo_camion_original in resultados:
        # Solo reclasificar si es camión Nestlé
        if tipo_camion_original not in (TipoCamion.PAQUETERA, TipoCamion.RAMPLA_DIRECTA):
            resultados_reclasificados.append((res, tipo_camion_original))
            continue
        
        camiones = res.get("camiones", [])
        
        for camion in camiones:
            # Reclasificar cada camión
            tipo_optimo = _reclasificar_camion_nestle(camion, client_config)
            
            if tipo_optimo != tipo_camion_original.value:
                total_reclasificados += 1
            
            # Actualizar tipo en el camión (se hará después en el flujo principal)
        
        resultados_reclasificados.append((res, tipo_camion_original))
    
    if total_reclasificados > 0:
        print(f"[VCU] Reclasificados {total_reclasificados} camiones de paquetera a rampla_directa")
    
    return resultados_reclasificados