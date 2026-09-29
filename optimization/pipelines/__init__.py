# optimization/pipelines/__init__.py
"""
Módulo de pipelines de optimización.

Contiene:
- VCUPipeline: Optimización VCU con cascada de fases
- BinPackingPipeline: Optimización minimizando camiones
- Clases base y estructuras de datos
"""

from optimization.pipelines.base import (
    OptimizationPipeline,
    OptimizationPhase,
    PipelineResult,
    PhaseContext
)
from optimization.pipelines.vcu_pipeline import VCUPipeline
from optimization.pipelines.binpacking_pipeline import BinPackingPipeline

__all__ = [
    # Clases base
    'OptimizationPipeline',
    'OptimizationPhase',
    'PipelineResult',
    'PhaseContext',
    
    # Pipelines concretos
    'VCUPipeline',
    'BinPackingPipeline',
]