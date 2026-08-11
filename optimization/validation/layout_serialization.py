"""
Fuente única de verdad para serializar layouts a metadata['layout_info'].
Cualquier campo nuevo de fragmento/pallet se agrega SOLO aquí.
Convención: aprovechamientos en % con 1 decimal.
"""
from typing import Any, Dict, List, Optional


def serializar_posiciones(layout) -> List[Dict[str, Any]]:
    """Serializa las posiciones del layout a diccionarios (superset de campos)."""
    return [
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
                            'es_picking': frag.es_picking,
                            'es_valioso': frag.es_valioso,
                            'flujo': frag.flujo,
                            'cajas': round(frag.cajas, 1),
                            'descripcion': frag.descripcion,
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


def metricas_layout(layout) -> Dict[str, Any]:
    """Métricas estándar del layout + posiciones serializadas (sin estado de validación)."""
    return {
        'posiciones_usadas': layout.posiciones_usadas,
        'posiciones_disponibles': layout.posiciones_disponibles,
        'altura_maxima_cm': layout.altura_maxima_cm,
        'total_pallets_fisicos': layout.total_pallets,
        'altura_maxima_usada_cm': round(layout.altura_maxima_usada, 1),
        'altura_promedio_usada': round(layout.altura_promedio_usada, 1),
        'aprovechamiento_altura': round(layout.aprovechamiento_altura * 100, 1),
        'aprovechamiento_posiciones': round(layout.aprovechamiento_posiciones * 100, 1),
        'posiciones': serializar_posiciones(layout),
    }


def construir_layout_info(
    layout,
    *,
    altura_validada: bool = True,
    errores: Optional[List[str]] = None,
    extras: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """layout_info completo. `extras` se aplica al final y puede sobreescribir claves estándar."""
    info = {
        'altura_validada': altura_validada,
        'errores_validacion': errores or [],
    }
    info.update(metricas_layout(layout))
    if extras:
        info.update(extras)
    return info