# optimization/orchestrator.py
"""
Orquestador simplificado de optimización.

Coordina los pipelines de VCU y BinPacking sin contener lógica de negocio.
La lógica está delegada a:
- optimization/pipelines/ - Flujos de optimización
- optimization/validation/ - Validación y ajuste
- optimization/strategies/ - Selección de camiones y reclasificación

NOTA: Este archivo reemplaza al orchestrator.py original (~2125 líneas → ~200 líneas)
"""

from __future__ import annotations

import os
from typing import List, Dict, Any, Tuple

import pandas as pd

from services.file_processor import read_file, process_dataframe
from models.domain import Pedido, SKU
from models.enums import TipoCamion
from core.config import get_client_config
from optimization.groups import calcular_tiempo_por_grupo
from utils.math_utils import format_dates
from utils.config_helpers import extract_truck_capacities, get_camiones_permitidos_para_ruta, get_capacity_for_type, get_effective_config
from optimization.pipelines import VCUPipeline, BinPackingPipeline


# ============================================================================
# CONSTANTES
# ============================================================================

MAX_TIEMPO_POR_GRUPO = int(os.getenv("MAX_TIEMPO_POR_GRUPO", "30"))


# ============================================================================
# API PÚBLICA
# ============================================================================

def procesar(
    content: bytes,
    filename: str,
    client: str,
    venta: str,
    REQUEST_TIMEOUT: int,
    vcuTarget: Any = None,
    vcuTargetBH: Any = None
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
        
        # Leer Excel
        df_full = read_file(content, filename, config, venta)
        
        # Aplicar overrides de VCU
        config = _aplicar_overrides_vcu(config, vcuTarget, vcuTargetBH, venta)
        
        # Ejecutar optimización
        return optimizar_con_dos_fases(
            df_full, config, client, venta,
            REQUEST_TIMEOUT, MAX_TIEMPO_POR_GRUPO
        )
    
    except Exception as e:
        import traceback as _tb
        return {
            "error": {
                "message": _tb.format_exc()[:2000],
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
    pedidos_objetos, pedidos_dicts = _preprocesar_datos(
        df_raw, client_config, cliente, venta
    )
    
    # 2) Calcular tiempo por grupo
    effective_config = get_effective_config(client_config, venta)
    tpg = calcular_tiempo_por_grupo(pedidos_objetos, effective_config, request_timeout, max_tpg)
    
    # 3) Ejecutar pipeline VCU
    resultado_vcu = _ejecutar_pipeline_vcu(
        pedidos_objetos, pedidos_dicts, client_config, tpg, request_timeout, venta
    )
    
    # 4) Ejecutar pipeline BinPacking
    resultado_bp = _ejecutar_pipeline_binpacking(
        pedidos_objetos, pedidos_dicts, client_config, tpg, request_timeout, venta
    )
    
    return {
        "vcu": resultado_vcu,
        "binpacking": resultado_bp
    }


# ============================================================================
# EJECUCIÓN DE PIPELINES
# ============================================================================

def _ejecutar_pipeline_vcu(
    pedidos: List[Pedido],
    pedidos_dicts: List[Dict],
    client_config,
    tpg: int,
    timeout: int,
    venta
) -> Dict[str, Any]:
    """
    Ejecuta el pipeline VCU y formatea resultado.
    """
    capacidades = extract_truck_capacities(client_config, venta)
    capacidad_default = capacidades.get(
        TipoCamion.PAQUETERA,
        next(iter(capacidades.values()))
    )

    # Ejecutar pipeline
    pipeline = VCUPipeline(client_config, venta)
    result = pipeline.ejecutar(pedidos, timeout, tpg)
    
    # Formatear salida
    return _formatear_resultado(
        result.camiones,
        result.pedidos_no_incluidos,
        capacidad_default,
        client_config,
        venta
    )


def _ejecutar_pipeline_binpacking(
    pedidos: List[Pedido],
    pedidos_dicts: List[Dict],
    client_config,
    tpg: int,
    timeout: int,
    venta
) -> Dict[str, Any]:
    """
    Ejecuta el pipeline BinPacking y formatea resultado.
    """
    capacidades = extract_truck_capacities(client_config, venta)
    capacidad_default = capacidades.get(
        TipoCamion.PAQUETERA,
        next(iter(capacidades.values()))
    )

    # Ejecutar pipeline
    pipeline = BinPackingPipeline(client_config, venta)
    result = pipeline.ejecutar(pedidos, timeout, tpg)

    # Formatear salida
    return _formatear_resultado(
        result.camiones,
        result.pedidos_no_incluidos,
        capacidad_default,
        client_config,
        venta
    )


# ============================================================================
# PREPROCESAMIENTO
# ============================================================================

def _preprocesar_datos(
    df_raw: pd.DataFrame,
    client_config,
    cliente: str,
    venta: str
) -> Tuple[List[Pedido], List[Dict[str, Any]]]:
    """
    Preprocesa datos del Excel a objetos Pedido.
    """
    # Procesar DataFrame
    df_proc, pedidos_dicts_raw = process_dataframe(
        df_raw, client_config, cliente, venta
    )

    # Convertir a objetos Pedido
    pedidos_objetos = []
    pedidos_dicts = []
    
    for p_dict in pedidos_dicts_raw:
        pedido = _crear_pedido_desde_dict(p_dict, client_config)
        pedidos_objetos.append(pedido)
        pedidos_dicts.append(p_dict)
    
    return pedidos_objetos, pedidos_dicts


def _crear_pedido_desde_dict(p_dict: Dict[str, Any], client_config) -> Pedido:
    """
    Crea objeto Pedido desde diccionario del Excel.
    """
    # Campos conocidos
    campos_conocidos = {
        "PEDIDO", "CD", "CE", "PO", "PESO", "VOL", "PALLETS", "VALOR",
        "VALOR_CAFE", "OC", "CHOCOLATES", "VALIOSO", "PDQ", "BAJA_VU",
        "LOTE_DIR", "BASE", "SUPERIOR", "FLEXIBLE", "NO_APILABLE",
        "SI_MISMO", "_skus", "SUBCLIENTE"
    }
    
    # Extraer metadata (campos extra)
    metadata = {k: v for k, v in p_dict.items() if k not in campos_conocidos}
    
    # Agregar SUBCLIENTE a metadata si existe
    if "SUBCLIENTE" in p_dict:
        metadata["SUBCLIENTE"] = p_dict["SUBCLIENTE"]
    
    # Crear SKUs si existen
    skus = []
    if "_skus" in p_dict and p_dict["_skus"]:
        for sku_data in p_dict["_skus"]:
            sku = SKU(
                sku_id=str(sku_data.get("SKU", "")),
                pedido_id=str(p_dict["PEDIDO"]),
                cantidad_pallets=float(sku_data.get("PALLETS", 0)),
                altura_full_pallet_cm=float(sku_data.get("ALTURA_FULL_PALLET", 0)),
                altura_picking_cm=float(sku_data.get("ALTURA_PICKING", 0)) if sku_data.get("ALTURA_PICKING") else None,
                peso_kg=float(sku_data.get("PESO", 0)),
                volumen_m3=float(sku_data.get("VOL", 0)),
                valor=float(sku_data.get("VALOR", 0)),
                base=float(sku_data.get("BASE", 0)),
                superior=float(sku_data.get("SUPERIOR", 0)),
                flexible=float(sku_data.get("FLEXIBLE", 0)),
                no_apilable=float(sku_data.get("NO_APILABLE", 0)),
                si_mismo=float(sku_data.get("SI_MISMO", 0)),
            )
            skus.append(sku)
    
    return Pedido(
        pedido=str(p_dict["PEDIDO"]),
        cd=str(p_dict["CD"]),
        ce=str(p_dict["CE"]),
        po=str(p_dict.get("PO", "")),
        peso=float(p_dict.get("PESO", 0)),
        volumen=float(p_dict.get("VOL", 0)),
        pallets=float(p_dict.get("PALLETS", 0)),
        valor=float(p_dict.get("VALOR", 0)),
        valor_cafe=float(p_dict.get("VALOR_CAFE", 0)),
        oc=p_dict.get("OC"),
        chocolates=str(p_dict.get("CHOCOLATES", "NO")),
        valioso=bool(p_dict.get("VALIOSO", 0)),
        pdq=bool(p_dict.get("PDQ", 0)),
        baja_vu=bool(p_dict.get("BAJA_VU", 0)),
        lote_dir=bool(p_dict.get("LOTE_DIR", 0)),
        base=float(p_dict.get("BASE", 0)),
        superior=float(p_dict.get("SUPERIOR", 0)),
        flexible=float(p_dict.get("FLEXIBLE", 0)),
        no_apilable=float(p_dict.get("NO_APILABLE", 0)),
        si_mismo=float(p_dict.get("SI_MISMO", 0)),
        skus=skus,
        metadata=metadata
    )


# ============================================================================
# FORMATEO DE SALIDA
# ============================================================================

def _formatear_resultado(
    camiones: List,
    pedidos_no_incluidos: List,
    capacidad_default,
    client_config,
    venta: str = None
) -> Dict[str, Any]:
    """
    Formatea resultado para la API.
    """
    from utils.config_helpers import get_camiones_permitidos_para_ruta, extract_truck_capacities
    from services.postprocess import _actualizar_opciones_tipo_camion

    # Renumerar camiones
    for idx, cam in enumerate(camiones, start=1):
        cam.numero = idx
        if venta:
            cam.metadata["venta"] = venta
        # Calcular opciones_tipo_camion
        _actualizar_opciones_tipo_camion(cam, client_config, venta)
    
    # Calcular estadísticas
    estadisticas = _calcular_estadisticas(camiones, pedidos_no_incluidos)

    # Convertir a dicts
    return {
        "camiones": [c.to_api_dict() for c in camiones],
        "pedidos_no_incluidos": [
            p.to_api_dict(capacidad_default) for p in pedidos_no_incluidos
        ],
        "estadisticas": estadisticas
    }


def _calcular_estadisticas(camiones: List, pedidos_no_incluidos: List) -> Dict[str, Any]:
    """
    Calcula estadísticas agregadas.
    """
    from collections import Counter
    
    total_pedidos = len(pedidos_no_incluidos) + sum(len(c.pedidos) for c in camiones)
    pedidos_asignados = total_pedidos - len(pedidos_no_incluidos)
    
    # Por tipo de camión
    tipos = Counter(c.tipo_camion.value for c in camiones)
    n_paquetera = tipos.get('paquetera', 0)
    n_rampla = tipos.get('rampla_directa', 0)
    n_backhaul = tipos.get('backhaul', 0)
    n_nestle = n_paquetera + n_rampla
    
    # VCU promedios
    vcu_total = sum(c.vcu_max for c in camiones) / len(camiones) if camiones else 0
    
    camiones_nestle = [c for c in camiones if c.tipo_camion.es_nestle]
    vcu_nestle = sum(c.vcu_max for c in camiones_nestle) / len(camiones_nestle) if camiones_nestle else 0
    
    camiones_bh = [c for c in camiones if c.tipo_camion == TipoCamion.BACKHAUL]
    vcu_bh = sum(c.vcu_max for c in camiones_bh) / len(camiones_bh) if camiones_bh else 0
    
    # Valorizado
    valorizado = sum(sum(p.valor for p in c.pedidos) for c in camiones)
    
    return {
        "promedio_vcu": round(vcu_total, 3),
        "promedio_vcu_nestle": round(vcu_nestle, 3),
        "promedio_vcu_backhaul": round(vcu_bh, 3),
        "cantidad_camiones": len(camiones),
        "cantidad_camiones_nestle": n_nestle,
        "cantidad_camiones_paquetera": n_paquetera,
        "cantidad_camiones_rampla_directa": n_rampla,
        "cantidad_camiones_backhaul": n_backhaul,
        "cantidad_pedidos_asignados": pedidos_asignados,
        "total_pedidos": total_pedidos,
        "valorizado": valorizado
    }


# ============================================================================
# HELPERS
# ============================================================================

def _aplicar_overrides_vcu(config, vcuTarget, vcuTargetBH, venta: str = None):
    """
    Aplica overrides de VCU desde el frontend.
    """
    if vcuTarget is None and vcuTargetBH is None:
        return config
    
    # Obtener TRUCK_TYPES efectivo
    from utils.config_helpers import get_effective_config
    effective = get_effective_config(config, venta)
    truck_types = effective["TRUCK_TYPES"]
    
    # VCU target para Nestlé
    if vcuTarget is not None:
        vcu_decimal = vcuTarget / 100.0
        for tipo in ['paquetera', 'rampla_directa', 'mediano', 'pequeño']:
            if tipo in truck_types:
                truck_types[tipo]['vcu_min'] = vcu_decimal
    
    # VCU target para BH
    if vcuTargetBH is not None:
        vcu_decimal = vcuTargetBH / 100.0
        if 'backhaul' in truck_types:
            truck_types['backhaul']['vcu_min'] = vcu_decimal
    
    return config