# services/optimizer.py
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
from services.math_utils import format_dates
from services.models import Pedido, Camion, TruckCapacity, TipoCamion
from services.config_helpers import extract_truck_capacities
from services.optimizer_groups import generar_grupos_optimizacion, calcular_tiempo_por_grupo
from services.optimizer_vcu import optimizar_grupo_vcu
from services.optimizer_binpacking import optimizar_grupo_binpacking
from config import get_client_config


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


def _dataframe_a_pedidos(df: pd.DataFrame, pedidos_dicts: List[Dict]) -> List[Pedido]:
    """
    Convierte DataFrame procesado a lista de objetos Pedido.
    """
    pedidos_map = {p["PEDIDO"]: p for p in pedidos_dicts}
    pedidos = []
    
    for _, row in df.iterrows():
        pedido_id = row["PEDIDO"]
        metadata = pedidos_map.get(pedido_id, {})
        
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
            metadata=metadata
        )
        
        pedidos.append(pedido)
    
    return pedidos


def _ejecutar_optimizacion_completa(
    pedidos: List[Pedido],
    pedidos_dicts: List[Dict[str, Any]],
    client_config,
    cliente: str,
    modo: str,
    tpg: int,
    request_timeout: int
) -> Dict[str, Any]:
    """
    Ejecuta optimización completa para un modo (VCU o BinPacking).
    
    Args:
        pedidos: Lista de pedidos objetos
        pedidos_dicts: Lista de pedidos dicts (para metadata)
        client_config: Configuración del cliente
        cliente: Nombre del cliente
        modo: "vcu" o "binpacking"
        tpg: Tiempo por grupo
        request_timeout: Timeout total
    
    Returns:
        Dict con camiones y pedidos_no_incluidos
    """
    start_total = time.time()
    
    # Generar grupos
    grupos = generar_grupos_optimizacion(pedidos, client_config, modo)
    
    # Extraer capacidades
    capacidades = extract_truck_capacities(client_config)
    
    # Optimizar grupos
    if modo == "vcu":
        resultados = _optimizar_grupos_vcu(
            grupos, client_config, capacidades,
            tpg, request_timeout, start_total
        )
    else:  # binpacking
        resultados = _optimizar_grupos_binpacking(
            grupos, client_config, capacidades,
            tpg, request_timeout, start_total
        )
    
    # Consolidar resultados
    return _consolidar_resultados(resultados, pedidos, pedidos_dicts, capacidades[TipoCamion.NORMAL])


def _optimizar_grupos_vcu(
    grupos: List[Tuple],
    client_config,
    capacidades: Dict[TipoCamion, TruckCapacity],
    tpg: int,
    request_timeout: int,
    start_total: float
) -> List[Dict[str, Any]]:
    """
    Optimiza grupos en modo VCU con paralelización para rutas normales.
    """
    resultados = []
    pedidos_restantes_ids = set()
    
    # Separar grupos normales del resto
    grupos_normal = [(cfg, peds) for cfg, peds in grupos if cfg.tipo.value == "normal"]
    grupos_otros = [(cfg, peds) for cfg, peds in grupos if cfg.tipo.value != "normal"]
    
    # Paralelizar grupos normales
    if grupos_normal:
        with ThreadPoolExecutor(max_workers=min(THREAD_WORKERS_NORMAL, len(grupos_normal))) as pool:
            futures = []
            
            for cfg, pedidos_grupo in grupos_normal:
                if not pedidos_grupo:
                    continue
                
                # Calcular tiempo proporcional
                tiempo_grupo = max(1, int(tpg * len(pedidos_grupo) / 10))
                
                if time.time() - start_total + tiempo_grupo > (request_timeout - 2):
                    continue
                
                # Determinar capacidad
                cap = capacidades.get(
                    TipoCamion.BH if cfg.tipo.value == 'bh' else TipoCamion.NORMAL,
                    capacidades[TipoCamion.NORMAL]
                )
                
                fut = pool.submit(
                    optimizar_grupo_vcu,
                    pedidos_grupo, cfg, client_config, cap, tiempo_grupo
                )
                futures.append(fut)
            
            # Recoger resultados
            for fut in as_completed(futures, timeout=max(1, request_timeout - int(time.time() - start_total))):
                try:
                    res = fut.result()
                    if res.get("status") in ("OPTIMAL", "FEASIBLE") and res.get("camiones"):
                        # Evitar duplicados
                        nuevos = [
                            pid for pid in res.get("pedidos_asignados_ids", [])
                            if pid not in pedidos_restantes_ids
                        ]
                        if nuevos:
                            pedidos_restantes_ids.update(nuevos)
                            resultados.append(res)
                except Exception:
                    continue
    
    # Procesar otros grupos secuencialmente
    for cfg, pedidos_grupo in grupos_otros:
        if not pedidos_grupo:
            continue
        
        tiempo_grupo = max(1, int(tpg * len(pedidos_grupo) / 10))
        
        if time.time() - start_total + tiempo_grupo > (request_timeout - 2):
            break
        
        cap = capacidades.get(
            TipoCamion.BH if cfg.tipo.value == 'bh' else TipoCamion.NORMAL,
            capacidades[TipoCamion.NORMAL]
        )
        
        res = optimizar_grupo_vcu(pedidos_grupo, cfg, client_config, cap, tiempo_grupo)
        
        if res.get("status") in ("OPTIMAL", "FEASIBLE") and res.get("camiones"):
            resultados.append(res)
        
        if time.time() - start_total > (request_timeout - 2):
            break
    
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
        
        tiempo_grupo = max(1, int(tpg * len(pedidos_grupo) / 10))
        
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


# optimizer.py - Función _consolidar_resultados corregida

def _consolidar_resultados(
    resultados: List[Dict[str, Any]],
    pedidos_originales: List[Pedido],
    pedidos_dicts: List[Dict[str, Any]],
    capacidad_default: TruckCapacity
) -> Dict[str, Any]:
    """
    Consolida resultados de todos los grupos en una respuesta única.
    """
    # Consolidar camiones
    all_camiones = []
    for res in resultados:
        all_camiones.extend(res.get("camiones", []))
    
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
            
            # ✅ AGREGAR TODAS LAS COLUMNAS NECESARIAS
            pedido_dict = {
                "PEDIDO": pedido_obj.pedido,
                "CE": pedido_obj.ce,
                "CD": pedido_obj.cd,
                "OC": pedido_obj.oc,
                "PO": pedido_obj.po,
                "CHOCOLATES": pedido_obj.chocolates,
                # ✅ AGREGAR DIMENSIONES FÍSICAS (esto faltaba)
                "PESO": pedido_obj.peso,
                "VOL": pedido_obj.volumen,
                "PALLETS": pedido_obj.pallets,
                "VALOR": pedido_obj.valor,
                # VCU calculados
                "VCU_VOL": vcu_vol,
                "VCU_PESO": vcu_peso,
                # Metadata
                "Fecha preferente de entrega": pedidos_map.get(pedido_obj.pedido, {}).get("Fecha preferente de entrega"),
            }
            
            # Agregar metadata adicional
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
    
    if type(client_config).__name__ == "CencosudConfig" or str(cliente).strip().lower() == "cencosud":
        return resultado
    
    cd_con_bh = getattr(client_config, "CD_CON_BH", [])
    bh_vcu_max = getattr(client_config, "BH_VCU_MAX", 1)
    
    for cam in resultado.get("camiones", []):
        cds = cam.get("cd", [])
        if not cds:
            continue
        
        if (cds[0] in cd_con_bh
            and cam.get("flujo_oc") != "MIX"
            and cam.get("vcu_max", 0) <= bh_vcu_max
            and cam.get("tipo_ruta") == "normal"):
            cam["tipo_camion"] = "bh"
    
    return resultado