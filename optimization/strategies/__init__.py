# optimization/strategies/__init__.py
"""
Módulo de estrategias de optimización.

Contiene:
- TruckSelector: Selección de tipo de camión (patrón Strategy)
- NestleReclassifier: Reclasificación post-validación
- BackhaulAdherenceManager: Gestión de adherencia BH
"""

from optimization.strategies.truck_selector import (
    TruckSelector,
    DefaultTruckSelector,
    NestleTruckSelector,
    SmuTruckSelector,
    WalmartTruckSelector,
    TruckSelectorFactory,
    seleccionar_tipo_camion
)

from optimization.strategies.reclassifier import (
    NestleReclassifier,
    reclasificar_nestle_post_validacion
)

from optimization.strategies.backhaul_adherence import (
    BackhaulAdherenceManager,
    BackhaulAdherenceResult,
    aplicar_adherencia_backhaul
)

__all__ = [
    # Selectores de tipo de camión
    'TruckSelector',
    'DefaultTruckSelector',
    'NestleTruckSelector',
    'SmuTruckSelector',
    'WalmartTruckSelector',
    'TruckSelectorFactory',
    'seleccionar_tipo_camion',
    
    # Reclasificación
    'NestleReclassifier',
    'reclasificar_nestle_post_validacion',
    
    # Adherencia backhaul
    'BackhaulAdherenceManager',
    'BackhaulAdherenceResult',
    'aplicar_adherencia_backhaul',
]