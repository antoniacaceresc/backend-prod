"""
API pública del optimizador.
Orquesta el flujo completo de optimización en dos fases (VCU y BinPacking).
"""

from __future__ import annotations
from itertools import combinations

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
DEBUG_VALIDATION = False 

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
        # Retorna camiones ya validados y set de pedidos asignados
        camiones_vcu, pedidos_asignados_vcu = _optimizar_grupos_vcu_cascada_con_camiones(
            pedidos_objetos, client_config, capacidades,
            tpg, request_timeout, start_total, capacidad_default
        )
        
        # Consolidar resultados (camiones ya validados)
        return _consolidar_resultados(
            camiones_vcu, pedidos_objetos, pedidos_dicts,
            capacidad_default, client_config, fase
        )
    else:  # binpacking
        grupos = generar_grupos_optimizacion(pedidos_objetos, client_config, "binpacking")
        resultados = _optimizar_grupos_binpacking(
            grupos, client_config, capacidades,
            tpg, request_timeout, start_total
        )
        
        # Consolidar resultados (necesita validación)
        return _consolidar_resultados(
            resultados, pedidos_objetos, pedidos_dicts,
            capacidad_default, client_config, fase
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
    start_total: float,
    capacidad_default: TruckCapacity
) -> Tuple[List[Camion], set]:
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
    all_camiones = []
    pedidos_asignados_global = set()
    pedidos_disponibles = pedidos_originales.copy()

    
    # ========================================================================
    # FASE 0: OPTIMIZACIÓN BH PRIMERO (solo si hay adherencia configurada)
    # ========================================================================
    adherencia_bh = getattr(client_config, 'ADHERENCIA_BACKHAUL', None)
    n_bh_creados = 0
    n_bh_target = 0
    
    if adherencia_bh:
        # Estimar camiones totales necesarios
        cap_ref = capacidades.get(TipoCamion.PAQUETERA) or list(capacidades.values())[0]
        total_peso = sum(p.peso for p in pedidos_disponibles)
        total_vol = sum(p.volumen for p in pedidos_disponibles)
        
        cam_por_peso = total_peso / cap_ref.cap_weight
        cam_por_vol = total_vol / cap_ref.cap_volume
        n_camiones_estimado = max(cam_por_peso, cam_por_vol)
        n_camiones_estimado = max(1, int(n_camiones_estimado) + 2)  # Margen
        
        n_bh_target = int(n_camiones_estimado * adherencia_bh)
        n_bh_target = max(1, n_bh_target)
        
        print(f"\n[ADHERENCIA] Estimación: {n_camiones_estimado} camiones, BH target: {n_bh_target}")
        print("="*80)
        print("FASE 0: OPTIMIZACIÓN BH PRIMERO (ADHERENCIA)")
        print("="*80)
        
        cap_backhaul = get_capacity_for_type(client_config, TipoCamion.BACKHAUL)
        
        # Filtrar pedidos que permiten BH
        from utils.config_helpers import es_ruta_solo_backhaul
        
        pedidos_permiten_bh = []
        for p in pedidos_disponibles:
            camiones_permitidos = get_camiones_permitidos_para_ruta(
                client_config, [p.cd], [p.ce], "normal"
            )
            if TipoCamion.BACKHAUL in camiones_permitidos:
                pedidos_permiten_bh.append(p)
        
        if pedidos_permiten_bh:
            print(f"[ADHERENCIA] {len(pedidos_permiten_bh)} pedidos permiten BH")
            
            # Generar grupos para BH
            grupos_bh = _generar_grupos_para_tipo(pedidos_permiten_bh, client_config, "normal")
            
            for cfg, pedidos_grupo in grupos_bh:
                if n_bh_creados >= n_bh_target:
                    print(f"[ADHERENCIA] ✓ Alcanzado target de {n_bh_target} camiones BH")
                    break
                
                if time.time() - start_total > (request_timeout - 2):
                    break
                
                pedidos_no_asignados = [p for p in pedidos_grupo if p.pedido not in pedidos_asignados_global]
                if not pedidos_no_asignados:
                    continue
                
                n_pedidos = len(pedidos_no_asignados)
                tiempo_grupo = ajustar_tiempo_grupo(tpg, n_pedidos, "normal")
                
                print(f"[BH ADHER] Optimizando {cfg.id}: {n_pedidos} pedidos, {tiempo_grupo}s")
                
                res = optimizar_grupo_vcu(
                    pedidos_no_asignados, cfg, client_config, cap_backhaul, tiempo_grupo
                )
                
                if res.get("status") in ("OPTIMAL", "FEASIBLE"):
                    nuevos = res.get("pedidos_asignados_ids", [])
                    camiones = res.get("camiones", [])
                    
                    if nuevos and camiones:
                        # Marcar como backhaul
                        for cam in camiones:
                            cam.tipo_camion = TipoCamion.BACKHAUL
                            for pedido in cam.pedidos:
                                pedido.tipo_camion = "backhaul"
                        
                        pedidos_asignados_global.update(nuevos)
                        resultados.append(res)
                        n_bh_creados += len(camiones)
                        print(f"[BH ADHER] ✓ {len(nuevos)}/{n_pedidos} pedidos en {len(camiones)} camiones BH (total BH: {n_bh_creados}/{n_bh_target})")
            
            # Extraer camiones de resultados de FASE 0
            camiones_fase0 = []
            for res in resultados:
                camiones_fase0.extend(res.get("camiones", []))
            
            # Validar, ajustar y recuperar FASE 0
            if camiones_fase0:
                camiones_fase0 = _validar_ajustar_recuperar(
                    camiones_fase0, client_config, capacidad_default,
                    pedidos_asignados_global, "FASE 0 BH"
                )
                all_camiones.extend(camiones_fase0)
                resultados = []  # Limpiar resultados ya procesados
            
            # Actualizar pedidos disponibles
            pedidos_disponibles = [p for p in pedidos_disponibles if p.pedido not in pedidos_asignados_global]
            print(f"[ADHERENCIA] Pedidos restantes: {len(pedidos_disponibles)}")
    
    
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
                    
                    pedidos_asignados_global.update(nuevos)
                    resultados.append(res)
                    
                    print(f"[VCU] ✓ MULTI_CE_PRIORIDAD Nestlé: {len(nuevos)}/{n_pedidos} pedidos en {len(camiones)} camiones")
                else:
                    print(f"[VCU] ⚠️ MULTI_CE_PRIORIDAD Nestlé: {res.get('status')} pero 0 pedidos/camiones")
            else:
                print(f"[VCU] ✗ MULTI_CE_PRIORIDAD Nestlé: {res.get('status', 'NO_SOLUTION')}")
        
        # Actualizar pedidos disponibles
        pedidos_disponibles = [p for p in pedidos_disponibles if p.pedido not in pedidos_asignados_global]
    
    # 0.5 Separar pedidos de rutas solo-backhaul (se procesan en Fase 2)
    from utils.config_helpers import es_ruta_solo_backhaul
    
    pedidos_solo_bh = []
    pedidos_para_nestle = []
    
    for p in pedidos_disponibles:
        if es_ruta_solo_backhaul(client_config, p.cd, p.ce, "normal"):
            pedidos_solo_bh.append(p)
        else:
            pedidos_para_nestle.append(p)
    
    if pedidos_solo_bh:
        print(f"[VCU] Separados {len(pedidos_solo_bh)} pedidos de rutas solo-backhaul (irán a Fase 2)")
    
    pedidos_disponibles = pedidos_para_nestle

    # 1. Rutas NORMALES en PARALELO
    grupos_normal = _generar_grupos_para_tipo(pedidos_disponibles, client_config, "normal")
    
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
                    pedidos_asignados_global.update(nuevos)
                    resultados.append(res)
                    print(f"[VCU] ✓ {tipo_ruta.upper()} Nestlé: {len(nuevos)}/{n_pedidos} pedidos en {len(camiones)} camiones")
                else:
                    print(f"[VCU] ⚠️ {tipo_ruta.upper()} Nestlé: {res.get('status')} pero 0 pedidos/camiones")
            else:
                print(f"[VCU] ✗ {tipo_ruta.upper()} Nestlé: {res.get('status', 'NO_SOLUTION')}")
        
        # Actualizar pedidos disponibles
        pedidos_disponibles = [p for p in pedidos_disponibles if p.pedido not in pedidos_asignados_global]
    
    # Validar, ajustar y recuperar FASE 1
    camiones_fase1 = []
    for res in resultados:
        camiones_fase1.extend(res.get("camiones", []))
    
    if camiones_fase1:
        camiones_fase1 = _validar_ajustar_recuperar(
            camiones_fase1, client_config, capacidad_default,
            pedidos_asignados_global, "FASE 1 NESTLÉ"
        )
        all_camiones.extend(camiones_fase1)
        resultados = []  # Limpiar resultados ya procesados
    
    # Actualizar pedidos disponibles para FASE 2
    pedidos_disponibles = [p for p in pedidos_originales if p.pedido not in pedidos_asignados_global]
    
    # ========================================================================
    # FASE 2: OPTIMIZACIÓN CON CAMIONES BACKHAUL
    # ========================================================================
    print("\n" + "="*80)
    print("FASE 2: OPTIMIZACIÓN CON CAMIONES BACKHAUL")
    print("="*80)

    # Agregar pedidos de rutas solo-BH que separamos al inicio
    if pedidos_solo_bh:
        pedidos_disponibles = pedidos_disponibles + pedidos_solo_bh
        print(f"[VCU] Agregando {len(pedidos_solo_bh)} pedidos de rutas solo-backhaul")
    
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
    
    # Validar, ajustar y recuperar FASE 2
    camiones_fase2 = []
    for res in resultados:
        camiones_fase2.extend(res.get("camiones", []))
    
    if camiones_fase2:
        camiones_fase2 = _validar_ajustar_recuperar(
            camiones_fase2, client_config, capacidad_default,
            pedidos_asignados_global, "FASE 2 BH"
        )
        all_camiones.extend(camiones_fase2)
    
    print(f"\n[VCU] Optimización completa: {len(all_camiones)} camiones, {len(pedidos_asignados_global)} pedidos asignados")
    
    return all_camiones, pedidos_asignados_global



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
                if not tipo_camion.es_nestle:
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
    client_config,
    modo: str = "vcu"
) -> Dict[str, Any]:
    """
    Consolida resultados de todos los grupos en una respuesta única.
    """
    from services.postprocess import _actualizar_opciones_tipo_camion 
    
    if modo == "vcu":
        # VCU: ya vienen como List[Camion] validados
        all_camiones = resultados
    else:
        # BinPacking: vienen como List[Dict], necesitan validación
        all_camiones = []
        for res in resultados:
            all_camiones.extend(res.get("camiones", []))
        
        # 1. Validación masiva de altura
        all_camiones = _validar_altura_camiones_paralelo(all_camiones, client_config)

        # 2. Ajustar camiones inválidos removiendo pedidos
        pedidos_removidos = []
        all_camiones = _ajustar_camiones_invalidos(all_camiones, client_config, pedidos_removidos, modo)

        # 3. Recuperar pedidos removidos (loop hasta 3 intentos)
        max_intentos = 3
        intento = 0
        
        while pedidos_removidos and intento < max_intentos:
            intento += 1
            print(f"[RECUPERACIÓN] Intento {intento}: {len(pedidos_removidos)} pedidos")
            
            camiones_recuperados = _recuperar_pedidos_sobrantes(
                pedidos_removidos, client_config, capacidad_default
            )
            
            if not camiones_recuperados:
                break
            
            camiones_recuperados = _validar_altura_camiones_paralelo(camiones_recuperados, client_config)
            
            pedidos_removidos = []
            camiones_recuperados = _ajustar_camiones_invalidos(
                camiones_recuperados, client_config, pedidos_removidos, modo
            )
            
            all_camiones.extend(camiones_recuperados)
        
        if pedidos_removidos:
            print(f"[RECUPERACIÓN] ⚠️ {len(pedidos_removidos)} pedidos sin recuperar")

    # 4. Aplicar adherencia backhaul si está configurada
    adherencia_bh = getattr(client_config, 'ADHERENCIA_BACKHAUL', None)
    if adherencia_bh is not None and adherencia_bh > 0:
        all_camiones = _aplicar_adherencia_backhaul(all_camiones, client_config, adherencia_bh)

    # 5. Reclasificación Nestlé basada en validación REAL
    _reclasificar_nestle_post_validacion(all_camiones, client_config)

    # 6. Actualizar opciones de tipo de camión
    for camion in all_camiones:
        _actualizar_opciones_tipo_camion(camion, client_config)
    
    # Identificar pedidos asignados
    pedidos_asignados_ids = set()
    for cam in all_camiones:
        pedidos_asignados_ids.update(p.pedido for p in cam.pedidos)
    
    # Pedidos no incluidos
    pedidos_map = {p["PEDIDO"]: p for p in pedidos_dicts}


    # DEBUG: Analizar pedidos que quedaron fuera
    pedidos_no_asignados = [p for p in pedidos_originales if p.pedido not in pedidos_asignados_ids]
    
    if pedidos_no_asignados:
        print(f"\n{'='*80}")
        print(f"DEBUG: ANÁLISIS DE {len(pedidos_no_asignados)} PEDIDOS NO ASIGNADOS")
        print(f"{'='*80}")
        
        from utils.config_helpers import get_camiones_permitidos_para_ruta, get_capacity_for_type
        
        # Agrupar por CD/CE
        grupos_debug = {}
        for p in pedidos_no_asignados:
            key = f"{p.cd}__{p.ce}"
            if key not in grupos_debug:
                grupos_debug[key] = []
            grupos_debug[key].append(p)
        
        for key, pedidos_grupo in grupos_debug.items():
            print(f"\n[DEBUG] Grupo {key}: {len(pedidos_grupo)} pedidos")
            
            # Calcular totales
            total_peso = sum(p.peso for p in pedidos_grupo)
            total_vol = sum(p.volumen for p in pedidos_grupo)
            total_pallets = sum(p.pallets_capacidad for p in pedidos_grupo)
            
            # Verificar qué camiones permite esta ruta
            p0 = pedidos_grupo[0]
            camiones_permitidos = get_camiones_permitidos_para_ruta(
                client_config, [p0.cd], [p0.ce], "normal"
            )
            
            print(f"   Camiones permitidos: {[c.value for c in camiones_permitidos]}")
            print(f"   Total peso: {total_peso:.0f}, vol: {total_vol:.0f}, pallets: {total_pallets:.1f}")
            
            # Calcular VCU potencial con cada tipo de camión
            for tipo in camiones_permitidos:
                cap = get_capacity_for_type(client_config, tipo)
                vcu_peso = total_peso / cap.cap_weight
                vcu_vol = total_vol / cap.cap_volume
                vcu_max = max(vcu_peso, vcu_vol)
                
                puede_cumplir = "✓" if vcu_max >= cap.vcu_min else "✗"
                print(f"   {tipo.value}: VCU={vcu_max:.1%} vs min={cap.vcu_min:.0%} {puede_cumplir}")
            
            # Listar pedidos
            for p in pedidos_grupo:
                print(f"      - {p.pedido}: peso={p.peso:.0f}, vol={p.volumen:.0f}, pallets={p.pallets_capacidad:.1f}")




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
            return camiones
        
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
        
        
        permite_consolidacion = getattr(config, 'PERMITE_CONSOLIDACION', False)
        max_skus_por_pallet = getattr(config, 'MAX_SKUS_POR_PALLET', 3)
        
        
        # Función worker con logging ordenado
        def validar_camion_worker(cam: Camion, cam_idx: int) -> Tuple[str, bool, float, Optional[str]]:
            """
            Worker que valida un camión.
            Returns: (camion_id, es_valido, tiempo_ms, error_msg)
            """
            start = time.time()
            elapsed_ms = 0 
            error_msg = None
            
            try:
                
                validator = HeightValidator(
                    altura_maxima_cm=cam.capacidad.altura_cm,
                    permite_consolidacion=permite_consolidacion,
                    max_skus_por_pallet=max_skus_por_pallet
        )
                es_valido, errores, layout, debug_info = validator.validar_camion_rapido(cam)
                
                
                # Normalizar errores con validación exhaustiva
                errores_limpios = []
                
                if errores is None:
                    errores_limpios = []
                elif not isinstance(errores, (list, tuple)):
                    errores_limpios = [str(errores)]
                else:                    
                    # Filtrar elementos válidos
                    for e in errores:
                        if e is not None and e is not Ellipsis and e != "":
                            try:
                                errores_limpios.append(str(e))
                            except Exception as conv_err:
                                with print_lock:
                                    print(f"[DEBUG] Error convirtiendo elemento: {conv_err}")

                error_msg = "; ".join(errores_limpios) if errores_limpios else None

                elapsed_ms = (time.time() - start) * 1000


                # ✅ CONSTRUIR Y GUARDAR LAYOUT_INFO COMPLETO
                layout_info = {
                    'altura_validada': bool(es_valido),
                    'errores_validacion': errores_limpios,
                    'fragmentos_fallidos': debug_info.get('fragmentos_fallidos', []) if debug_info else [],
                    'fragmentos_totales': debug_info.get('fragmentos_totales', 0) if debug_info else 0,
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
                    else:
                        # Layout inválido - mantener estimación anterior o resetear
                        layout_info['posiciones_usadas'] = cam.pos_total
                
                # ✅ GUARDAR EN METADATA
                cam.metadata['layout_info'] = layout_info
                
                return (cam.id, es_valido, elapsed_ms, error_msg)


            except Exception as e:
                elapsed_ms = (time.time() - start) * 1000
                error_msg = str(e)
                
                import traceback
                error_detail = traceback.format_exc()
                
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
        
            if errores_capturados:
                print(f"\n🔴 CAMIONES CON ERRORES:")
                for cam_id, error_msg in errores_capturados:
                    print(f"   • {cam_id}: {error_msg}")
            
            print(f"{'='*80}\n")

        return camiones


def _ajustar_camiones_invalidos(
    camiones: List[Camion],
    client_config,
    pedidos_removidos_global: List[Pedido],
    modo: str = "vcu"
) -> List[Camion]:
    """
    Ajusta camiones inválidos removiendo pedidos hasta que validen.
    
    Estrategia:
    1. Identifica camiones inválidos (altura_validada == False)
    2. Para cada uno, calcula N = cantidad de fragmentos fallidos
    3. Busca pedido(s) cuya suma de fragmentos ≈ N (ordenados de menor a mayor)
    4. Verifica que VCU sin esos pedidos >= target
    5. Remueve pedidos y re-valida
    6. Repite hasta válido o máx 3 iteraciones
    """
    from optimization.validation.height_validator import HeightValidator
    
    MAX_ITERACIONES = 3
    
    # Identificar camiones inválidos
    camiones_invalidos = [
        cam for cam in camiones
        if cam.metadata.get('layout_info', {}).get('altura_validada') == False
    ]
    
    if not camiones_invalidos:
        print(f"\n[AJUSTE] ✅ Todos los camiones son válidos, no se requiere ajuste")
        return camiones
    
    print(f"\n{'='*80}")
    print(f"AJUSTE POST-VALIDACIÓN")
    print(f"{'='*80}")
    print(f"Camiones inválidos: {len(camiones_invalidos)}")
    
    permite_consolidacion = getattr(client_config, 'PERMITE_CONSOLIDACION', False)
    max_skus_por_pallet = getattr(client_config, 'MAX_SKUS_POR_PALLET', 3)
    
    for cam in camiones_invalidos:
        layout_info = cam.metadata.get('layout_info', {})
        fragmentos_fallidos = layout_info.get('fragmentos_fallidos', [])
        n_fallidos = len(fragmentos_fallidos)
        
        if n_fallidos == 0:
            continue
        
        for iteracion in range(MAX_ITERACIONES):
            
            # Obtener fragmentos fallidos actuales
            layout_info = cam.metadata.get('layout_info', {})
            fragmentos_fallidos = layout_info.get('fragmentos_fallidos', [])
            n_fallidos = len(fragmentos_fallidos)
            
            if n_fallidos == 0:
                break
            
            # Buscar pedidos a remover
            pedidos_a_remover = _seleccionar_pedidos_a_remover(
                cam, n_fallidos, fragmentos_fallidos, client_config
            )
            
            if not pedidos_a_remover:
                if modo == "binpacking":
                    # En binpacking, forzar remoción aunque VCU baje
                    pedidos_a_remover = _seleccionar_pedidos_a_remover(
                        cam, n_fallidos, fragmentos_fallidos, client_config, forzar_remocion=True
                    )
                    if not pedidos_a_remover:
                        break
                else:
                    break
            
            # Remover pedidos
            pedidos_ids_remover = {p.pedido for p in pedidos_a_remover}
            fragmentos_removidos = sum(p.cantidad_fragmentos for p in pedidos_a_remover)
            
            
            # Guardar pedidos removidos
            pedidos_removidos_global.extend(pedidos_a_remover)
            
            # Actualizar camión
            cam.pedidos = [p for p in cam.pedidos if p.pedido not in pedidos_ids_remover]
            cam._invalidar_cache()
            
            # Re-validar
            validator = HeightValidator(
                altura_maxima_cm=cam.capacidad.altura_cm,
                permite_consolidacion=permite_consolidacion,
                max_skus_por_pallet=max_skus_por_pallet
            )
            
            es_valido, errores, layout, debug_info = validator.validar_camion_rapido(cam)
            
            # Actualizar layout_info
            nuevo_layout_info = {
                'altura_validada': bool(es_valido),
                'errores_validacion': errores if errores else [],
                'fragmentos_fallidos': debug_info.get('fragmentos_fallidos', []) if debug_info else [],
                'fragmentos_totales': debug_info.get('fragmentos_totales', 0) if debug_info else 0,
            }
            
            if layout is not None:
                cam.pos_total = layout.posiciones_usadas
                nuevo_layout_info.update({
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
            
            cam.metadata['layout_info'] = nuevo_layout_info
            
            nuevos_fallidos = len(nuevo_layout_info.get('fragmentos_fallidos', []))
            
            if es_valido:
                break
        
        # Resumen del camión
        es_valido_final = cam.metadata.get('layout_info', {}).get('altura_validada', False)
    
    # Resumen final
    camiones_aun_invalidos = [
        cam for cam in camiones
        if cam.metadata.get('layout_info', {}).get('altura_validada') == False
    ]
    
    print(f"\n{'='*80}")
    print(f"RESUMEN AJUSTE POST-VALIDACIÓN")
    print(f"{'='*80}")
    print(f"Camiones ajustados: {len(camiones_invalidos) - len(camiones_aun_invalidos)}")
    print(f"Camiones aún inválidos: {len(camiones_aun_invalidos)}")
    print(f"Total pedidos removidos: {len(pedidos_removidos_global)}")
    print(f"{'='*80}\n")
    
    # Filtrar: solo retornar camiones válidos, desarmar los inválidos
    camiones_validos = []
    for cam in camiones:
        if cam.metadata.get('layout_info', {}).get('altura_validada') == True:
            camiones_validos.append(cam)
        else:
            # Desarmar: todos los pedidos van al pool
            print(f"[AJUSTE] 🔴 Desarmando camión {cam.id} - {len(cam.pedidos)} pedidos van al pool")
            pedidos_removidos_global.extend(cam.pedidos)

    # En binpacking, crear camiones nuevos con pedidos removidos
    if modo == "binpacking" and pedidos_removidos_global:
        camiones_adicionales = _crear_camiones_para_pedidos_removidos(
            list(pedidos_removidos_global), client_config
        )
        camiones_validos.extend(camiones_adicionales)
        pedidos_removidos_global.clear()
    
    return camiones_validos


def _seleccionar_pedidos_a_remover(
    camion: Camion,
    n_fragmentos_fallidos: int,
    fragmentos_fallidos: List[Dict],
    client_config,
    forzar_remocion: bool = False
) -> List[Pedido]:
    from itertools import combinations
    
    pedidos = camion.pedidos
    if not pedidos:
        return []

    # --- UTILIDAD ---
    def impacto(p):
        return p.volumen if camion.vcu_vol >= camion.vcu_peso else p.peso

    # =====================================================
    # PASO 1: Buscar pedido único exacto
    # =====================================================
    unicos = [p for p in pedidos if p.cantidad_fragmentos == n_fragmentos_fallidos]
    if unicos:
        elegido = min(unicos, key=impacto)
        if _vcu_sigue_valido(camion, [elegido], forzar_remocion):
            return [elegido]

    # =====================================================
    # PASO 2: Buscar combinaciones EXACTAS (máx 4 pedidos)
    # =====================================================
    data = [(p, p.cantidad_fragmentos, impacto(p)) for p in pedidos]
    n = len(data)
    MAX_COMBO_SIZE = min(4, n)  # Limitar para performance
    
    exactas = []
    for r in range(2, MAX_COMBO_SIZE + 1):  # Empezar en 2 (el 1 ya se probó arriba)
        for combo in combinations(data, r):
            frag_sum = sum(x[1] for x in combo)
            if frag_sum == n_fragmentos_fallidos:
                costo = sum(x[2] for x in combo)
                exactas.append((combo, costo))

    if exactas:
        combo, _ = min(exactas, key=lambda x: x[1])
        seleccion = [x[0] for x in combo]
        if _vcu_sigue_valido(camion, seleccion, forzar_remocion):
            return seleccion

    # =====================================================
    # PASO 3: Buscar alternativa más cercana (máx 4 pedidos)
    # =====================================================
    mejores = []
    target = n_fragmentos_fallidos

    for r in range(1, MAX_COMBO_SIZE + 1):
        for combo in combinations(data, r):
            frag_sum = sum(x[1] for x in combo)
            diff = abs(frag_sum - target)
            impacto_total = sum(x[2] for x in combo)
            mejores.append((combo, diff, impacto_total, frag_sum))

    if not mejores:
        return []

    # Ordenar por: 1) menor diferencia, 2) menor impacto
    mejores.sort(key=lambda x: (x[1], x[2]))

    for combo, diff, imp, frag_sum in mejores:
        seleccion = [x[0] for x in combo]
        if _vcu_sigue_valido(camion, seleccion, forzar_remocion):
            return seleccion

    # =====================================================
    # PASO 4: No existe combinación válida
    # =====================================================
    return []


def _vcu_sigue_valido(camion: Camion, pedidos_a_remover: List[Pedido], forzar_remocion: bool = False) -> bool:
    """Verifica si el camión mantiene VCU >= target sin ciertos pedidos."""
    ids = {p.pedido for p in pedidos_a_remover}
    
    # Verificar que no quede vacío
    pedidos_restantes = len(camion.pedidos) - len(pedidos_a_remover)
    if pedidos_restantes <= 0:
        return False
    
    # En modo forzado, solo verificar que no quede vacío
    if forzar_remocion:
        return True
    
    peso_rest = sum(p.peso for p in camion.pedidos if p.pedido not in ids)
    vol_rest = sum(p.volumen for p in camion.pedidos if p.pedido not in ids)
    
    cap = camion.capacidad
    vcu_peso = peso_rest / cap.cap_weight if cap.cap_weight > 0 else 0
    vcu_vol = vol_rest / cap.cap_volume if cap.cap_volume > 0 else 0
    
    return max(vcu_peso, vcu_vol) >= cap.vcu_min


def _recuperar_pedidos_sobrantes(
    pedidos: List[Pedido],
    client_config,
    capacidad_default: TruckCapacity
) -> List[Camion]:
    """
    Intenta recuperar pedidos removidos, probando primero Nestlé y luego BH.
    """
    from utils.config_helpers import get_camiones_permitidos_para_ruta, get_capacity_for_type
    from models.enums import TipoCamion
    from optimization.solvers.vcu import optimizar_grupo_vcu
    from optimization.groups import generar_grupos_optimizacion
    
    if not pedidos:
        return []
    
    print(f"\n[RECUPERACIÓN] Intentando recuperar {len(pedidos)} pedidos")
    
    camiones_resultado = []
    pedidos_restantes = pedidos.copy()
    
    # === PASO 1: Intentar con Nestlé ===
    pedidos_para_nestle = []
    for p in pedidos_restantes:
        camiones_permitidos = get_camiones_permitidos_para_ruta(
            client_config, [p.cd], [p.ce], "normal"
        )
        nestle_permitidos = [c for c in camiones_permitidos if c.es_nestle]
        
        # DEBUG para ruta específica
        if "N641" in p.cd and p.ce == "0103":
            print(f"   [DEBUG N641-0103] Pedido {p.pedido}: camiones_permitidos={[c.value for c in camiones_permitidos]}, nestle={[c.value for c in nestle_permitidos]}")
        
        if nestle_permitidos:
            pedidos_para_nestle.append(p)
    
    if pedidos_para_nestle:
        print(f"[RECUPERACIÓN] Intentando {len(pedidos_para_nestle)} pedidos con Nestlé")
        
        grupos = generar_grupos_optimizacion(pedidos_para_nestle, client_config, "vcu")
        
        # DEBUG: Mostrar grupos generados
        for cfg, pedidos_grupo in grupos:
            print(f"   [DEBUG] Grupo {cfg.id}: {len(pedidos_grupo)} pedidos")
            
            # DEBUG específico para N641-0103
            if "N641" in cfg.id and "0103" in cfg.id:
                print(f"   [DEBUG N641-0103] Procesando grupo con {len(pedidos_grupo)} pedidos")
                for p in pedidos_grupo:
                    print(f"      - {p.pedido}: peso={p.peso:.0f}, vol={p.volumen:.0f}, pallets={p.pallets_capacidad:.1f}")
        
        for cfg, pedidos_grupo in grupos:
            if not pedidos_grupo:
                continue
            
            camiones_permitidos = get_camiones_permitidos_para_ruta(
                client_config, cfg.cd, cfg.ce, cfg.tipo.value
            )
            nestle_permitidos = [c for c in camiones_permitidos if c.es_nestle]
            
            if not nestle_permitidos:
                print(f"   [DEBUG] Grupo {cfg.id}: No hay Nestlé permitido, saltando")
                continue
            
            tipo_camion = nestle_permitidos[0]
            cap = get_capacity_for_type(client_config, tipo_camion)
            
            # DEBUG específico para N641-0103
            if "N641" in cfg.id and "0103" in cfg.id:
                print(f"   [DEBUG N641-0103] Optimizando con {tipo_camion.value}")
                print(f"   [DEBUG N641-0103] Capacidad: peso={cap.cap_weight}, vol={cap.cap_volume}, vcu_min={cap.vcu_min}")
                
                # Calcular VCU potencial del grupo
                total_peso = sum(p.peso for p in pedidos_grupo)
                total_vol = sum(p.volumen for p in pedidos_grupo)
                vcu_peso = total_peso / cap.cap_weight
                vcu_vol = total_vol / cap.cap_volume
                print(f"   [DEBUG N641-0103] VCU potencial: peso={vcu_peso:.2%}, vol={vcu_vol:.2%}, max={max(vcu_peso, vcu_vol):.2%}")
            
            resultado = optimizar_grupo_vcu(
                pedidos_grupo, cfg, client_config, cap, 30
            )
            
            # DEBUG específico para N641-0103
            if "N641" in cfg.id and "0103" in cfg.id:
                print(f"   [DEBUG N641-0103] Resultado: status={resultado.get('status')}, asignados={len(resultado.get('pedidos_asignados_ids', []))}, camiones={len(resultado.get('camiones', []))}")
            
            if resultado.get("status") in ("OPTIMAL", "FEASIBLE"):
                camiones = resultado.get("camiones", [])
                asignados = resultado.get("pedidos_asignados_ids", [])
                
                for cam in camiones:
                    cam.tipo_camion = tipo_camion
                    for p in cam.pedidos:
                        p.tipo_camion = tipo_camion.value
                
                camiones_resultado.extend(camiones)
                pedidos_restantes = [p for p in pedidos_restantes if p.pedido not in asignados]
                
                if camiones:
                    print(f"[RECUPERACIÓN] ✓ Nestlé: {len(asignados)} pedidos en {len(camiones)} camiones")
    
    # === PASO 2: Intentar restantes con BH ===
    pedidos_para_bh = []
    for p in pedidos_restantes:
        camiones_permitidos = get_camiones_permitidos_para_ruta(
            client_config, [p.cd], [p.ce], "normal"
        )
        if TipoCamion.BACKHAUL in camiones_permitidos:
            pedidos_para_bh.append(p)
    
    if pedidos_para_bh:
        print(f"[RECUPERACIÓN] Intentando {len(pedidos_para_bh)} pedidos restantes con BH")
        
        # DEBUG para N641-0103
        for p in pedidos_para_bh:
            if "N641" in p.cd and p.ce == "0103":
                print(f"   [DEBUG N641-0103] Pedido {p.pedido} va a intento BH")
        
        cap_backhaul = get_capacity_for_type(client_config, TipoCamion.BACKHAUL)
        grupos = generar_grupos_optimizacion(pedidos_para_bh, client_config, "vcu")
        
        for cfg, pedidos_grupo in grupos:
            if not pedidos_grupo:
                continue
            
            resultado = optimizar_grupo_vcu(
                pedidos_grupo, cfg, client_config, cap_backhaul, 30
            )
            
            if resultado.get("status") in ("OPTIMAL", "FEASIBLE"):
                camiones = resultado.get("camiones", [])
                asignados = resultado.get("pedidos_asignados_ids", [])
                
                for cam in camiones:
                    cam.tipo_camion = TipoCamion.BACKHAUL
                    for p in cam.pedidos:
                        p.tipo_camion = "backhaul"
                
                camiones_resultado.extend(camiones)
                pedidos_restantes = [p for p in pedidos_restantes if p.pedido not in asignados]
                
                if camiones:
                    print(f"[RECUPERACIÓN] ✓ BH: {len(asignados)} pedidos en {len(camiones)} camiones")
    
    # DEBUG: Pedidos que quedaron sin recuperar
    if pedidos_restantes:
        print(f"[RECUPERACIÓN] ⚠️ {len(pedidos_restantes)} pedidos sin recuperar:")
        for p in pedidos_restantes:
            print(f"   - {p.pedido}: CD={p.cd}, CE={p.ce}")
    
    print(f"[RECUPERACIÓN] Total: {len(camiones_resultado)} camiones")
    
    return camiones_resultado


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


def _reclasificar_nestle_post_validacion(
    camiones: List[Camion],
    client_config
) -> None:
    """
    Reclasifica camiones Nestlé DESPUÉS de validación de altura.
    Usa los datos reales del layout para decidir si downgrade a rampla.
    
    Modifica camiones in-place.
    """
    from utils.config_helpers import get_capacity_for_type
    
    total_reclasificados = 0
    
    for cam in camiones:
        # Solo reclasificar camiones paquetera
        if cam.tipo_camion != TipoCamion.PAQUETERA:
            continue

        # ⚠️ Solo reclasificar si el camión está validado
        layout_info = cam.metadata.get('layout_info', {})
        if not layout_info.get('altura_validada', False):
            continue
        
        tipo_optimo = _reclasificar_camion_nestle(cam, client_config)
        tipo_optimo_enum = TipoCamion(tipo_optimo)
        
        # Si cambió a rampla_directa
        if tipo_optimo_enum == TipoCamion.RAMPLA_DIRECTA:
            nueva_capacidad = get_capacity_for_type(client_config, tipo_optimo_enum)
            cam.cambiar_tipo(tipo_optimo_enum, nueva_capacidad)

            from optimization.utils.helpers import calcular_posiciones_apilabilidad

            # Recalcular posiciones con nueva capacidad
            cam.pos_total = calcular_posiciones_apilabilidad(
                cam.pedidos,
                nueva_capacidad.max_positions
            )
            
            # Actualizar en todos los pedidos
            for pedido in cam.pedidos:
                pedido.tipo_camion = tipo_optimo

            # ✅ ACTUALIZAR altura_maxima_cm en layout_info para reflejar nueva capacidad
            if 'layout_info' in cam.metadata:
                layout_info = cam.metadata['layout_info']
                
                # Actualizar altura máxima del camión
                altura_anterior = layout_info.get('altura_maxima_cm', 0)
                layout_info['altura_maxima_cm'] = nueva_capacidad.altura_cm
                
                # Recalcular aprovechamiento de altura con nueva referencia
                altura_usada = layout_info.get('altura_maxima_usada_cm', 0)
                if nueva_capacidad.altura_cm > 0:
                    nuevo_aprovechamiento = (altura_usada / nueva_capacidad.altura_cm) * 100
                    layout_info['aprovechamiento_altura'] = round(nuevo_aprovechamiento, 1)
                
                # Actualizar posiciones disponibles si cambiaron
                layout_info['posiciones_disponibles'] = nueva_capacidad.max_positions
                
                # Recalcular aprovechamiento de posiciones
                posiciones_usadas = layout_info.get('posiciones_usadas', 0)
                if nueva_capacidad.max_positions > 0:
                    nuevo_aprov_pos = (posiciones_usadas / nueva_capacidad.max_positions) * 100
                    layout_info['aprovechamiento_posiciones'] = round(nuevo_aprov_pos, 1)
            
            
            total_reclasificados += 1
            
            # El layout se calculó con paquetera pero cabe en rampla, así que es válido
    
    if total_reclasificados > 0:
        print(f"\n[RECLASIFICACIÓN] ✅ {total_reclasificados} camiones: paquetera → rampla_directa")


def _reclasificar_camion_nestle(
    camion: Camion,
    client_config
) -> str:
    """
    Determina el tipo de camión Nestlé óptimo basándose en la validación de altura REAL.
    
    Lógica:
    - Se optimiza inicialmente con PAQUETERA (más posiciones, 270cm altura)
    - Después de validar altura, si el layout real cabe en RAMPLA_DIRECTA (220cm), se reclasifica
    
    Args:
        camion: Objeto Camion con metadata de validación ya ejecutada
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
        cap_paquetera.cap_volume == cap_rampla.cap_volume and
        cap_paquetera.altura_cm == cap_rampla.altura_cm):
        return "paquetera"  # Por defecto
    
    # ✅ NUEVA LÓGICA: Usar datos REALES de validación de altura
    layout_info = camion.metadata.get('layout_info', {})
    
    # Si no hay layout_info o no está validado, usar lógica conservadora
    if not layout_info or not layout_info.get('altura_validada'):
        # Fallback a lógica anterior (sin altura)
        peso_total = sum(p.peso for p in camion.pedidos)
        volumen_total = sum(p.volumen for p in camion.pedidos)
        pallets_total = camion.pallets_capacidad
        
        cabe_en_rampla = (
            len(camion.pedidos) <= cap_rampla.max_positions and
            peso_total <= cap_rampla.cap_weight and
            volumen_total <= cap_rampla.cap_volume and
            pallets_total <= cap_rampla.max_pallets
        )
        
        if cabe_en_rampla:
            vcu_peso_rampla = peso_total / cap_rampla.cap_weight if cap_rampla.cap_weight > 0 else 0
            vcu_vol_rampla = volumen_total / cap_rampla.cap_volume if cap_rampla.cap_volume > 0 else 0
            vcu_max_rampla = max(vcu_peso_rampla, vcu_vol_rampla)
            
            if vcu_max_rampla >= cap_rampla.vcu_min:
                return "rampla_directa"
        
        return "paquetera"
    
    # ✅ USAR DATOS REALES DEL LAYOUT
    altura_maxima_usada = layout_info.get('altura_maxima_usada_cm', 0)
    posiciones_usadas = layout_info.get('posiciones_usadas', len(camion.pedidos))
    
    # Verificar dimensiones básicas (peso, volumen, pallets)
    peso_total = sum(p.peso for p in camion.pedidos)
    volumen_total = sum(p.volumen for p in camion.pedidos)
    pallets_total = camion.pallets_capacidad
    
    # ✅ VERIFICACIÓN COMPLETA: altura real + dimensiones + posiciones
    cabe_en_rampla = (
        altura_maxima_usada <= cap_rampla.altura_cm and  # ⭐ Lo más importante
        posiciones_usadas <= cap_rampla.max_positions and
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
    
    # Si no cabe o no cumple VCU target, mantener paquetera
    return "paquetera"


def _aplicar_adherencia_backhaul(
    camiones: List[Camion],
    client_config,
    adherencia_target: float
) -> List[Camion]:
    """
    Convierte camiones Nestlé a Backhaul para cumplir adherencia mínima.
    
    Estrategia:
    1. Calcular déficit de BH
    2. Ordenar camiones Nestlé por VCU (menor primero)
    3. Convertir los de menor VCU a BH si su ruta lo permite
    4. Re-validar los convertidos
    """
    from utils.config_helpers import get_camiones_permitidos_para_ruta, get_capacity_for_type
    from models.enums import TipoCamion
    from optimization.validation.height_validator import HeightValidator
    
    n_total = len(camiones)
    if n_total == 0:
        return camiones
    
    # Contar camiones actuales por tipo
    camiones_bh = [c for c in camiones if c.tipo_camion == TipoCamion.BACKHAUL]
    camiones_nestle = [c for c in camiones if c.tipo_camion != TipoCamion.BACKHAUL]
    
    n_bh_actual = len(camiones_bh)
    n_bh_requerido = int(n_total * adherencia_target)
    deficit = n_bh_requerido - n_bh_actual
    
    print(f"\n[ADHERENCIA BH] Total: {n_total}, BH actual: {n_bh_actual}, Requerido: {n_bh_requerido}, Déficit: {deficit}")
    
    if deficit <= 0:
        return camiones
    
    # Ordenar Nestlé por VCU (menor primero = candidatos a convertir)
    camiones_nestle_ordenados = sorted(camiones_nestle, key=lambda c: c.vcu_max)
    
    # Obtener capacidad BH
    cap_backhaul = get_capacity_for_type(client_config, TipoCamion.BACKHAUL)
    permite_consolidacion = getattr(client_config, 'PERMITE_CONSOLIDACION', False)
    max_skus_por_pallet = getattr(client_config, 'MAX_SKUS_POR_PALLET', 3)
    
    convertidos = 0
    
    for cam in camiones_nestle_ordenados:
        if convertidos >= deficit:
            break
        
        # Verificar si la ruta permite BH
        cam_cd = [cam.cd] if isinstance(cam.cd, str) else cam.cd
        cam_ce = [cam.ce] if isinstance(cam.ce, str) else cam.ce
        tipo_ruta_str = cam.tipo_ruta.value if hasattr(cam.tipo_ruta, 'value') else str(cam.tipo_ruta)
        
        camiones_permitidos = get_camiones_permitidos_para_ruta(
            client_config, cam_cd, cam_ce, tipo_ruta_str
        )
        
        if TipoCamion.BACKHAUL not in camiones_permitidos:
            continue
        
        # Calcular peso y volumen del camión
        peso_camion = sum(p.peso for p in cam.pedidos)
        volumen_camion = sum(p.volumen for p in cam.pedidos)
        
        # Verificar si cabe en capacidad BH
        if peso_camion > cap_backhaul.cap_weight or volumen_camion > cap_backhaul.cap_volume:
            continue
        
        # Guardar tipo original por si hay que revertir
        tipo_original = cam.tipo_camion
        capacidad_original = cam.capacidad
        
        # Convertir a BH
        cam.tipo_camion = TipoCamion.BACKHAUL
        cam.capacidad = cap_backhaul
        cam._invalidar_cache()
        for p in cam.pedidos:
            p.tipo_camion = "backhaul"
        
        # Re-validar altura (BH tiene altura menor)
        validator = HeightValidator(
            altura_maxima_cm=cap_backhaul.altura_cm,
            permite_consolidacion=permite_consolidacion,
            max_skus_por_pallet=max_skus_por_pallet
        )
        
        es_valido, errores, layout, debug_info = validator.validar_camion_rapido(cam)
        
        if es_valido:
            convertidos += 1
            
            # Actualizar layout_info
            if layout is not None:
                cam.metadata['layout_info'] = {
                    'altura_validada': True,
                    'errores_validacion': [],
                    'fragmentos_fallidos': [],
                    'posiciones_usadas': layout.posiciones_usadas,
                    'altura_maxima_cm': layout.altura_maxima_cm,
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
                }
        else:
            # Revertir conversión
            cam.tipo_camion = tipo_original
            cam.capacidad = capacidad_original
            cam._invalidar_cache()
            for p in cam.pedidos:
                p.tipo_camion = tipo_original.value
    
    # Resumen
    n_bh_final = len([c for c in camiones if c.tipo_camion == TipoCamion.BACKHAUL])
    print(f"[ADHERENCIA BH] Resultado: {n_bh_final}/{n_total} = {n_bh_final/n_total*100:.1f}% (target: {adherencia_target*100:.0f}%)")
    
    return camiones


def _crear_camiones_para_pedidos_removidos(
    pedidos: List[Pedido],
    client_config
) -> List[Camion]:
    """
    Crea camiones para pedidos removidos en modo binpacking.
    Usa backhaul si la ruta lo permite, sino Nestlé.
    """
    from utils.config_helpers import get_camiones_permitidos_para_ruta, get_capacity_for_type
    from models.enums import TipoCamion
    from optimization.solvers.binpacking import optimizar_grupo_binpacking
    from optimization.groups import generar_grupos_optimizacion
    
    if not pedidos:
        return []
    
    # Generar grupos
    grupos = generar_grupos_optimizacion(pedidos, client_config, "binpacking")
    
    camiones_resultado = []
    
    for cfg, pedidos_grupo in grupos:
        if not pedidos_grupo:
            continue
        
        # Determinar tipo de camión (preferir backhaul por VCU bajo)
        camiones_permitidos = get_camiones_permitidos_para_ruta(
            client_config, cfg.cd, cfg.ce, cfg.tipo.value
        )
        
        if TipoCamion.BACKHAUL in camiones_permitidos:
            tipo_camion = TipoCamion.BACKHAUL
        elif camiones_permitidos:
            tipo_camion = camiones_permitidos[0]
        else:
            tipo_camion = TipoCamion.PAQUETERA
        
        cap = get_capacity_for_type(client_config, tipo_camion)
        
        resultado = optimizar_grupo_binpacking(
            pedidos_grupo, cfg, client_config, cap, 30
        )
        
        if resultado.get("status") in ("OPTIMAL", "FEASIBLE"):
            camiones = resultado.get("camiones", [])
            
            for cam in camiones:
                cam.tipo_camion = tipo_camion
                for p in cam.pedidos:
                    p.tipo_camion = tipo_camion.value
            
            camiones_resultado.extend(camiones)
    
    # Validar los camiones creados
    if camiones_resultado:
        camiones_resultado = _validar_altura_camiones_paralelo(camiones_resultado, client_config)
    
    print(f"[AJUSTE BP] Creados {len(camiones_resultado)} camiones adicionales")
    
    return camiones_resultado


def _validar_ajustar_recuperar(
    camiones: List[Camion],
    client_config,
    capacidad_default: TruckCapacity,
    pedidos_asignados_global: set,
    fase: str
) -> List[Camion]:
    """
    Ejecuta el ciclo completo de validación, ajuste y recuperación para una fase.
    Retorna los camiones válidos y actualiza pedidos_asignados_global.
    """
    if not camiones:
        return []
    
    print(f"\n[{fase}] Validando {len(camiones)} camiones...")
    
    # 1. Validar altura
    camiones = _validar_altura_camiones_paralelo(camiones, client_config)
    
    # 2. Ajustar inválidos
    pedidos_removidos = []
    camiones = _ajustar_camiones_invalidos(camiones, client_config, pedidos_removidos, "vcu")
    
    # 3. Recuperar pedidos removidos (loop hasta 3 intentos)
    max_intentos = 3
    intento = 0
    
    while pedidos_removidos and intento < max_intentos:
        intento += 1
        print(f"[{fase}] Recuperación intento {intento}: {len(pedidos_removidos)} pedidos")
        
        camiones_recuperados = _recuperar_pedidos_sobrantes(
            pedidos_removidos, client_config, capacidad_default
        )
        
        if not camiones_recuperados:
            break
        
        # Validar recuperados
        camiones_recuperados = _validar_altura_camiones_paralelo(camiones_recuperados, client_config)
        
        # Ajustar recuperados
        pedidos_removidos = []
        camiones_recuperados = _ajustar_camiones_invalidos(
            camiones_recuperados, client_config, pedidos_removidos, "vcu"
        )
        
        camiones.extend(camiones_recuperados)
    
    if pedidos_removidos:
        print(f"[{fase}] ⚠️ {len(pedidos_removidos)} pedidos no recuperados")
    
    # Actualizar pedidos asignados
    for cam in camiones:
        pedidos_asignados_global.update(p.pedido for p in cam.pedidos)
    
    print(f"[{fase}] ✓ {len(camiones)} camiones válidos")
    
    return camiones
