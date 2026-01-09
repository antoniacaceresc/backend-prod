# optimization/validation/validation_cycle.py
"""
Ciclo completo de validación de camiones.

Combina:
1. Validación paralela de altura
2. Ajuste de camiones inválidos (remoción de pedidos)
3. Recuperación de pedidos removidos en nuevos camiones
4. Loop iterativo hasta estabilizar

Extraído de orchestrator.py para mejor modularidad.
"""

from __future__ import annotations

from typing import List, Set, Tuple

from models.domain import Camion, Pedido, TruckCapacity
from optimization.validation.truck_validator import TruckValidator
from optimization.validation.adjustment import PostValidationAdjuster, PedidoRecovery


# Flag para activar/desactivar prints de debug
DEBUG_VALIDATION = False


class ValidationCycleResult:
    """Resultado del ciclo completo de validación."""
    
    def __init__(
        self,
        camiones_validos: List[Camion],
        pedidos_asignados: Set[str],
        pedidos_no_recuperados: List[Pedido],
        iteraciones: int
    ):
        self.camiones_validos = camiones_validos
        self.pedidos_asignados = pedidos_asignados
        self.pedidos_no_recuperados = pedidos_no_recuperados
        self.iteraciones = iteraciones
    
    @property
    def total_camiones(self) -> int:
        return len(self.camiones_validos)
    
    @property
    def total_pedidos_asignados(self) -> int:
        return len(self.pedidos_asignados)


class ValidationCycle:
    """
    Ejecuta el ciclo completo de validación, ajuste y recuperación.
    
    Flujo:
    1. Validar altura de todos los camiones
    2. Ajustar inválidos (remover pedidos problemáticos)
    3. Recuperar pedidos removidos en nuevos camiones
    4. Repetir hasta máx N intentos o sin pedidos removidos
    
    Uso típico:
        cycle = ValidationCycle(client_config, capacidad_default)
        result = cycle.ejecutar(camiones, pedidos_asignados)
    """
    
    MAX_INTENTOS_RECUPERACION = 3
    
    def __init__(
        self,
        client_config,
        capacidad_default: TruckCapacity
    ):
        """
        Args:
            client_config: Configuración del cliente
            capacidad_default: Capacidad por defecto para recuperación
        """
        self.venta = None

        self.config = client_config
        self.capacidad_default = capacidad_default
        self.effective_config = None  # Se establece en ejecutar()
        
        # Componentes internos
        self.validator = TruckValidator(client_config)
        self.adjuster = PostValidationAdjuster(client_config)
    
    def ejecutar(
        self,
        camiones: List[Camion],
        pedidos_asignados_inicial: Set[str] = None,
        fase: str = "validacion",
        modo: str = "vcu",
        effective_config: dict = None,
        venta: str = None
    ) -> ValidationCycleResult:
        """
        Ejecuta el ciclo completo de validación.
        
        Args:
            camiones: Lista de camiones a validar
            pedidos_asignados_inicial: Set de pedidos ya asignados (opcional)
            fase: Nombre de la fase (para logging)
            modo: "vcu" o "binpacking"
        
        Returns:
            ValidationCycleResult con camiones válidos y estadísticas
        """
        self.effective_config = effective_config
        self.venta = venta
        self.recovery = PedidoRecovery(self.config, venta)

        if not camiones:
            return ValidationCycleResult(
                camiones_validos=[],
                pedidos_asignados=pedidos_asignados_inicial or set(),
                pedidos_no_recuperados=[],
                iteraciones=0
            )
        
        pedidos_asignados = set(pedidos_asignados_inicial or [])
        all_camiones = []
        
        if DEBUG_VALIDATION:
            print(f"\n{'='*80}")
            print(f"CICLO DE VALIDACIÓN - {fase.upper()}")
            print(f"{'='*80}")
            print(f"Camiones a procesar: {len(camiones)}")
        
        # 1. Validar altura SOLO si está habilitado
        validar_altura = self.effective_config.get('VALIDAR_ALTURA', True) if self.effective_config else True

        if validar_altura:
            camiones = self.validator.validar_camiones(camiones, f"{fase}_validacion", self.effective_config, self.venta)
            # 2. Ajustar inválidos
            adjustment_result = self.adjuster.ajustar_camiones(camiones, modo)
            camiones_validos = adjustment_result.camiones_validos
            pedidos_removidos = adjustment_result.pedidos_removidos
        else:
            # Sin validación de altura, todos los camiones son válidos
            camiones_validos = camiones
            pedidos_removidos = []

            # Marcar como validados (skip)
            for cam in camiones_validos:
                cam.metadata['layout_info'] = {
                    'altura_validada': True,
                    'validacion_skipped': True,
                    'errores_validacion': []
                }
        
        all_camiones.extend(camiones_validos)
        
        
        # 3. Loop de recuperación
        intento = 0
        while pedidos_removidos and intento < self.MAX_INTENTOS_RECUPERACION:
            intento += 1
            
            if DEBUG_VALIDATION:
                print(f"\n[RECUPERACIÓN] Intento {intento}: {len(pedidos_removidos)} pedidos")
            
            # Recuperar pedidos
            camiones_recuperados = self.recovery.recuperar_pedidos(
                pedidos_removidos, self.capacidad_default
            )

            # Dentro del while loop, DESPUÉS de self.recovery.recuperar_pedidos():
            camiones_recuperados = self.recovery.recuperar_pedidos(
                pedidos_removidos, self.capacidad_default
            )

            if not camiones_recuperados:
                break
            
            # Validar recuperados
            if validar_altura:
                camiones_recuperados = self.validator.validar_camiones(camiones_recuperados, f"{fase}_recuperacion_{intento}", self.effective_config, self.venta)
                adj_result = self.adjuster.ajustar_camiones(camiones_recuperados, modo)
            else:
                adj_result = AdjustmentResult(camiones_recuperados, [])
            
            all_camiones.extend(adj_result.camiones_validos)
            pedidos_removidos = adj_result.pedidos_removidos

        # Actualizar pedidos asignados
        pedidos_asignados = set()
        for cam in all_camiones:
            pedidos_asignados.update(p.pedido for p in cam.pedidos)
        
        if DEBUG_VALIDATION:
            print(f"\n[CICLO COMPLETO] Resultado {fase}:")
            print(f"  - Camiones válidos: {len(all_camiones)}")
            print(f"  - Pedidos asignados: {len(pedidos_asignados)}")
            print(f"  - Pedidos sin recuperar: {len(pedidos_removidos)}")
            print(f"  - Iteraciones: {intento}")

        return ValidationCycleResult(
            camiones_validos=all_camiones,
            pedidos_asignados=pedidos_asignados,
            pedidos_no_recuperados=pedidos_removidos,
            iteraciones=intento
        )


# Función de conveniencia para uso simple
def validar_ajustar_recuperar(
    camiones: List[Camion],
    client_config,
    capacidad_default: TruckCapacity,
    pedidos_asignados_global: Set[str],
    fase: str = "validacion",
    modo: str = "vcu",
    effective_config: dict = None,
    venta: str = None
) -> List[Camion]:
    """
    Función de conveniencia que ejecuta el ciclo completo.
    
    NOTA: pedidos_asignados_global se modifica in-place por compatibilidad.
    
    Args:
        camiones: Camiones a validar
        client_config: Configuración del cliente
        capacidad_default: Capacidad por defecto
        pedidos_asignados_global: Set de pedidos asignados (se actualiza)
        fase: Nombre de la fase
        modo: "vcu" o "binpacking"
    
    Returns:
        Lista de camiones válidos
    """
    cycle = ValidationCycle(client_config, capacidad_default)
    result = cycle.ejecutar(
        camiones,
        pedidos_asignados_global,
        fase,
        modo,
        effective_config,
        venta
    )
    
    # Actualizar el set global (compatibilidad)
    pedidos_asignados_global.clear()
    pedidos_asignados_global.update(result.pedidos_asignados)
    
    return result.camiones_validos