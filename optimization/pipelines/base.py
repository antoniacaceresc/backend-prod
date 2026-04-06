# optimization/pipelines/base.py
"""
Clases base para pipelines de optimización.

Define interfaces y estructuras comunes para todos los pipelines.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Dict, Any, Set, Optional

from models.domain import Pedido, Camion, TruckCapacity, ConfiguracionGrupo
from models.enums import TipoCamion


@dataclass
class PipelineResult:
    """
    Resultado de ejecutar un pipeline de optimización.
    """
    camiones: List[Camion] = field(default_factory=list)
    pedidos_asignados: Set[str] = field(default_factory=set)
    pedidos_no_incluidos: List[Pedido] = field(default_factory=list)
    estadisticas: Dict[str, Any] = field(default_factory=dict)
    
    # Metadata del proceso
    fases_ejecutadas: List[str] = field(default_factory=list)
    tiempo_total_ms: float = 0.0
    errores: List[str] = field(default_factory=list)
    
    @property
    def total_camiones(self) -> int:
        return len(self.camiones)
    
    @property
    def total_pedidos_asignados(self) -> int:
        return len(self.pedidos_asignados)
    
    @property
    def total_pedidos_no_incluidos(self) -> int:
        return len(self.pedidos_no_incluidos)
    
    @property
    def tasa_asignacion(self) -> float:
        """Porcentaje de pedidos asignados."""
        total = self.total_pedidos_asignados + self.total_pedidos_no_incluidos
        if total == 0:
            return 0.0
        return (self.total_pedidos_asignados / total) * 100
    
    def merge(self, other: 'PipelineResult') -> 'PipelineResult':
        """
        Combina dos resultados de pipeline.
        Útil para combinar resultados de fases.
        """
        return PipelineResult(
            camiones=self.camiones + other.camiones,
            pedidos_asignados=self.pedidos_asignados | other.pedidos_asignados,
            pedidos_no_incluidos=other.pedidos_no_incluidos,  # Usar los del último
            estadisticas={**self.estadisticas, **other.estadisticas},
            fases_ejecutadas=self.fases_ejecutadas + other.fases_ejecutadas,
            tiempo_total_ms=self.tiempo_total_ms + other.tiempo_total_ms,
            errores=self.errores + other.errores,
        )


@dataclass
class PhaseContext:
    """
    Contexto compartido entre fases de un pipeline.
    """
    client_config: Any
    capacidades: Dict[TipoCamion, TruckCapacity]
    capacidad_default: TruckCapacity
    timeout: int
    tpg: int  # Tiempo por grupo
    start_time: float
    venta: str = ""
    
    # Estado mutable
    pedidos_asignados: Set[str] = field(default_factory=set)
    
    def tiempo_restante(self) -> float:
        """Calcula tiempo restante antes del timeout."""
        import time
        return self.timeout - (time.time() - self.start_time)
    
    def timeout_cercano(self, margen: float = 2.0) -> bool:
        """Indica si el timeout está cerca."""
        return self.tiempo_restante() < margen


class OptimizationPipeline(ABC):
    """
    Clase base abstracta para pipelines de optimización.
    
    Cada pipeline implementa un flujo completo de optimización
    (VCU, BinPacking, etc.) con sus propias fases y estrategias.
    """
    
    def __init__(self, client_config, venta: str = None):
        """
        Args:
            client_config: Configuración del cliente
        """
        self.config = client_config
        self.venta = venta
        self._setup_components()
    
    def _setup_components(self):
        """
        Configura componentes internos del pipeline.
        Sobrescribir en subclases para agregar componentes específicos.
        """
        from utils.config_helpers import extract_truck_capacities
        
        self.capacidades = extract_truck_capacities(self.config, self.venta)
        self.capacidad_default = self.capacidades.get(
            TipoCamion.PAQUETERA,
            next(iter(self.capacidades.values()))
        )
    
    @abstractmethod
    def ejecutar(
        self,
        pedidos: List[Pedido],
        timeout: int,
        tpg: int
    ) -> PipelineResult:
        """
        Ejecuta el pipeline completo.
        
        Args:
            pedidos: Lista de pedidos a optimizar
            timeout: Timeout total en segundos
            tpg: Tiempo máximo por grupo
        
        Returns:
            PipelineResult con camiones y estadísticas
        """
        pass
    
    def _crear_contexto(
        self,
        timeout: int,
        tpg: int,
        venta: str = ""
    ) -> PhaseContext:
        """Crea el contexto inicial para el pipeline."""
        import time
        
        return PhaseContext(
            client_config=self.config,
            capacidades=self.capacidades,
            capacidad_default=self.capacidad_default,
            timeout=timeout,
            tpg=tpg,
            start_time=time.time(),
            venta=venta,
            pedidos_asignados=set()
        )


class OptimizationPhase(ABC):
    """
    Clase base para fases individuales de un pipeline.
    
    Cada fase procesa un subconjunto de pedidos con una estrategia específica.
    """
    
    def __init__(self, name: str, client_config):
        """
        Args:
            name: Nombre de la fase (para logging)
            client_config: Configuración del cliente
        """
        self.name = name
        self.config = client_config
    
    @abstractmethod
    def ejecutar(
        self,
        pedidos: List[Pedido],
        context: PhaseContext
    ) -> PipelineResult:
        """
        Ejecuta la fase.
        
        Args:
            pedidos: Pedidos disponibles para esta fase
            context: Contexto compartido del pipeline
        
        Returns:
            PipelineResult con resultados de la fase
        """
        pass
    
    def filtrar_pedidos_disponibles(
        self,
        pedidos: List[Pedido],
        asignados: Set[str]
    ) -> List[Pedido]:
        """Filtra pedidos que aún no han sido asignados."""
        return [p for p in pedidos if p.pedido not in asignados]