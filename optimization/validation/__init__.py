# optimization/validation/__init__.py
"""
Módulo de validación de camiones.

Contiene:
- HeightValidator: Validación física de altura de pallets
- TruckValidator: Validación paralela de múltiples camiones
- PostValidationAdjuster: Ajuste de camiones inválidos
- PedidoRecovery: Recuperación de pedidos removidos
- ValidationCycle: Ciclo completo validación → ajuste → recuperación
"""

from optimization.validation.height_validator import HeightValidator
from optimization.validation.truck_validator import (
    TruckValidator,
    TruckValidationResult,
    validar_altura_camiones_paralelo
)
from optimization.validation.adjustment import (
    PostValidationAdjuster,
    PedidoRecovery,
    AdjustmentResult,
    ajustar_camiones_invalidos,
    recuperar_pedidos_sobrantes
)
from optimization.validation.validation_cycle import (
    ValidationCycle,
    ValidationCycleResult,
    validar_ajustar_recuperar
)

__all__ = [
    # Clases principales
    'HeightValidator',
    'TruckValidator',
    'TruckValidationResult',
    'PostValidationAdjuster',
    'PedidoRecovery',
    'AdjustmentResult',
    'ValidationCycle',
    'ValidationCycleResult',
    
    # Funciones de conveniencia (compatibilidad)
    'validar_altura_camiones_paralelo',
    'ajustar_camiones_invalidos',
    'recuperar_pedidos_sobrantes',
    'validar_ajustar_recuperar',
]