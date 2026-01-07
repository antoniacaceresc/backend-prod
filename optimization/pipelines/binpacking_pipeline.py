# optimization/pipelines/binpacking_pipeline.py
"""
Pipeline de optimización BinPacking.

Minimiza el número de camiones asegurando que todos los pedidos
sean asignados.

Flujo más simple que VCU:
1. Generar grupos
2. Optimizar cada grupo con solver binpacking
3. Validar y ajustar
"""

from __future__ import annotations

import time
from typing import List, Dict, Any, Set

from models.domain import Pedido, Camion, TruckCapacity, ConfiguracionGrupo
from models.enums import TipoCamion, TipoRuta

from optimization.pipelines.base import (
    OptimizationPipeline,
    PipelineResult, PhaseContext
)
from optimization.solvers.binpacking import optimizar_grupo_binpacking
from optimization.groups import generar_grupos_optimizacion, ajustar_tiempo_grupo
from optimization.validation import ValidationCycle
from optimization.strategies import TruckSelectorFactory


# Flag para debug
DEBUG_VALIDATION = False


class BinPackingPipeline(OptimizationPipeline):
    """
    Pipeline de optimización BinPacking.
    
    A diferencia de VCU:
    - Todos los pedidos DEBEN ser asignados
    - Minimiza número de camiones
    - No tiene cascada de fases (proceso más simple)
    """
    
    def __init__(self, client_config, venta: str = None):
        self.venta = venta
        super().__init__(client_config, venta)
        
        # Componentes
        self.truck_selector = TruckSelectorFactory.create(client_config)
        self.validation_cycle = ValidationCycle(client_config, self.capacidad_default)
    
    def ejecutar(
        self,
        pedidos: List[Pedido],
        timeout: int,
        tpg: int
    ) -> PipelineResult:
        """
        Ejecuta el pipeline BinPacking.
        """
        from utils.config_helpers import get_effective_config
        self.effective_config = get_effective_config(self.config, self.venta)

        if not pedidos:
            return PipelineResult()
        
        context = self._crear_contexto(timeout, tpg)
        start_time = time.time()
        
        # Generar grupos
        grupos = generar_grupos_optimizacion(pedidos, self.effective_config, "binpacking")
      
        
        if not grupos:
            return PipelineResult(pedidos_no_incluidos=pedidos)
        
        # Optimizar cada grupo
        all_camiones: List[Camion] = []
        pedidos_asignados: Set[str] = set()
        
        for cfg, pedidos_grupo in grupos:
            if context.timeout_cercano():
                if DEBUG_VALIDATION:
                    print(f"[BP] Timeout cercano, deteniendo")
                break
            
            if not pedidos_grupo:
                continue
            
            result = self._optimizar_grupo(cfg, pedidos_grupo, context)
            
            all_camiones.extend(result.camiones)
            pedidos_asignados.update(result.pedidos_asignados)
        
        # Validar y ajustar
        if all_camiones:
            validation_result = self.validation_cycle.ejecutar(
                all_camiones,
                pedidos_asignados,
                "BINPACKING",
                "binpacking",
                self.effective_config,
                self.venta
            )
            
            all_camiones = validation_result.camiones_validos
            pedidos_asignados = validation_result.pedidos_asignados
        
        # Pedidos no incluidos
        pedidos_no_incluidos = [
            p for p in pedidos if p.pedido not in pedidos_asignados
        ]
        
        elapsed_ms = (time.time() - start_time) * 1000
        
        if DEBUG_VALIDATION:
            print(f"\n[BP] Resultado:")
            print(f"  - Camiones: {len(all_camiones)}")
            print(f"  - Pedidos asignados: {len(pedidos_asignados)}")
            print(f"  - Pedidos no incluidos: {len(pedidos_no_incluidos)}")
            print(f"  - Tiempo: {elapsed_ms:.0f}ms")
        
        return PipelineResult(
            camiones=all_camiones,
            pedidos_asignados=pedidos_asignados,
            pedidos_no_incluidos=pedidos_no_incluidos,
            tiempo_total_ms=elapsed_ms,
            fases_ejecutadas=['binpacking']
        )
    
    def _optimizar_grupo(
        self,
        cfg: ConfiguracionGrupo,
        pedidos: List[Pedido],
        context: PhaseContext
    ) -> PipelineResult:
        """
        Optimiza un grupo con solver binpacking.
        """
        from utils.config_helpers import get_camiones_permitidos_para_ruta, get_capacity_for_type
        
        n_pedidos = len(pedidos)
        tiempo_grupo = ajustar_tiempo_grupo(context.tpg, n_pedidos, cfg.tipo.value)
        
        # Obtener tipo de camión
        camiones_permitidos = get_camiones_permitidos_para_ruta(
            self.config, cfg.cd, cfg.ce, cfg.tipo.value, self.venta, cfg.oc
        )
        
        tipo_camion = self.truck_selector.seleccionar_tipo_camion(
            cfg, camiones_permitidos, {'fase': 'binpacking'}
        )
        
        cap = get_capacity_for_type(self.config, tipo_camion, self.venta)
        
        # Ajustar si no permite apilamiento
        from utils.config_helpers import permite_apilamiento_cd
        cd_grupo = cfg.cd[0] if cfg.cd else ""
        if not permite_apilamiento_cd(self.config, cd_grupo, self.venta):
            cap = cap.sin_apilamiento()
        
        if DEBUG_VALIDATION:
            print(f"[BP] Optimizando {cfg.id}: {n_pedidos} pedidos, {tiempo_grupo}s")

        # Ejecutar solver
        res = optimizar_grupo_binpacking(
            pedidos, cfg, self.effective_config, cap, tiempo_grupo, tipo_camion
        )

        if res.get("status") in ("OPTIMAL", "FEASIBLE"):
            camiones = res.get("camiones", [])
            nuevos = res.get("pedidos_asignados_ids", [])
            
            if camiones and nuevos:
                # Etiquetar camiones
                for cam in camiones:
                    if not tipo_camion.es_nestle:
                        cam.tipo_camion = tipo_camion
                        for p in cam.pedidos:
                            p.tipo_camion = tipo_camion.value
                
                if DEBUG_VALIDATION:
                    print(f"[BP] ✓ {cfg.id}: {len(nuevos)}/{n_pedidos} en {len(camiones)} camiones")
                
                return PipelineResult(
                    camiones=camiones,
                    pedidos_asignados=set(nuevos)
                )
        
        if DEBUG_VALIDATION:
            print(f"[BP] ✗ {cfg.id}: {res.get('status', 'NO_SOLUTION')}")

        return PipelineResult()