# optimization/pipelines/vcu_pipeline.py
"""
Pipeline de optimización VCU.

Ejecuta la cascada completa:
- Fase 0: Adherencia BH (si configurada)
- Fase 1: Camiones Nestlé (multi_ce_prioridad → normal → multi_ce → multi_cd)
- Fase 2: Camiones Backhaul (pedidos restantes)

Incluye validación, ajuste y recuperación entre fases.
"""

from __future__ import annotations

import time
from typing import List, Dict, Any, Tuple, Set
from concurrent.futures import ThreadPoolExecutor, as_completed

from models.domain import Pedido, Camion, TruckCapacity, ConfiguracionGrupo
from models.enums import TipoCamion, TipoRuta

from optimization.pipelines.base import (
    OptimizationPipeline, OptimizationPhase,
    PipelineResult, PhaseContext
)
from optimization.solvers.vcu import optimizar_grupo_vcu
from optimization.groups import _generar_grupos_para_tipo, ajustar_tiempo_grupo
from optimization.validation import ValidationCycle
from optimization.strategies import (
    TruckSelectorFactory,
    reclasificar_nestle_post_validacion,
    aplicar_adherencia_backhaul
)


# Flag para debug
DEBUG_VALIDATION = False

# Configuración de paralelismo
THREAD_WORKERS_NORMAL = 8


class VCUPipeline(OptimizationPipeline):
    """
    Pipeline completo de optimización VCU.
    
    Flujo:
    1. (Opcional) Fase 0: Crear camiones BH para cumplir adherencia
    2. Fase 1: Optimizar con camiones Nestlé
    3. Fase 2: Optimizar restantes con camiones Backhaul
    4. Consolidar y reclasificar
    """
    
    def __init__(self, client_config, venta: str = None):
        self.venta = venta
        super().__init__(client_config, venta)
        
        # Componentes del pipeline
        self.truck_selector = TruckSelectorFactory.create(client_config)
        self.validation_cycle = ValidationCycle(client_config, self.capacidad_default)
        
        # Configuración de adherencia
        self.adherencia_bh = None 
    
    def ejecutar(
        self,
        pedidos: List[Pedido],
        timeout: int,
        tpg: int
    ) -> PipelineResult:
        """
        Ejecuta el pipeline VCU completo.
        """
        from utils.config_helpers import get_effective_config
        self.effective_config = get_effective_config(self.config, self.venta)
        self.adherencia_bh = self.effective_config.get('ADHERENCIA_BACKHAUL')

        if not pedidos:
            return PipelineResult()
        
        context = self._crear_contexto(timeout, tpg)
        all_camiones: List[Camion] = []
        
        start_time = time.time()
        
        # ================================================================
        # FASE 0: Adherencia BH (opcional)
        # ================================================================
        if self.adherencia_bh and self.adherencia_bh > 0:
            fase0_result = self._ejecutar_fase_adherencia(pedidos, context)
            all_camiones.extend(fase0_result.camiones)
            context.pedidos_asignados.update(fase0_result.pedidos_asignados)
        
        
        # Pedidos disponibles para Fase 1
        pedidos_disponibles = self._filtrar_disponibles(pedidos, context.pedidos_asignados)
        

        # ================================================================
        # FASE 1: Camiones Nestlé
        # ================================================================
        if not context.timeout_cercano() and pedidos_disponibles:
            fase1_result = self._ejecutar_fase_nestle(pedidos_disponibles, context)
            all_camiones.extend(fase1_result.camiones)
            context.pedidos_asignados.update(fase1_result.pedidos_asignados)
        
        # Pedidos disponibles para Fase 2
        pedidos_disponibles = self._filtrar_disponibles(pedidos, context.pedidos_asignados)

        # ================================================================
        # FASE 2: Camiones Backhaul
        # ================================================================
        if not context.timeout_cercano() and pedidos_disponibles:
            fase2_result = self._ejecutar_fase_backhaul(pedidos_disponibles, context)
            all_camiones.extend(fase2_result.camiones)
            context.pedidos_asignados.update(fase2_result.pedidos_asignados)
        
        # ================================================================
        # POST-PROCESAMIENTO
        # ================================================================
        
        # Reclasificar Nestlé (paquetera → rampla si cabe)
        reclasificar_nestle_post_validacion(all_camiones, self.config, self.venta)
        
        # Aplicar adherencia final si está configurada
        if self.adherencia_bh and self.adherencia_bh > 0:
            all_camiones = aplicar_adherencia_backhaul(
                all_camiones, self.config, self.adherencia_bh
            )

        # CRÍTICO: Recalcular pedidos_asignados basándose en los camiones reales
        context.pedidos_asignados = set()
        for cam in all_camiones:
            context.pedidos_asignados.update(p.pedido for p in cam.pedidos)
        
        # Pedidos no incluidos
        pedidos_no_incluidos = self._filtrar_disponibles(pedidos, context.pedidos_asignados)
        
        elapsed_ms = (time.time() - start_time) * 1000
        
        return PipelineResult(
            camiones=all_camiones,
            pedidos_asignados=context.pedidos_asignados,
            pedidos_no_incluidos=pedidos_no_incluidos,
            tiempo_total_ms=elapsed_ms,
            fases_ejecutadas=['adherencia', 'nestle', 'backhaul']
        )
    
    def _ejecutar_fase_adherencia(
        self,
        pedidos: List[Pedido],
        context: PhaseContext
    ) -> PipelineResult:
        """
        Fase 0: Crear camiones BH para cumplir adherencia.
        """
        from utils.config_helpers import get_camiones_permitidos_para_ruta, get_capacity_for_type
        
        # Estimar camiones necesarios
        n_bh_target = self._estimar_target_bh(pedidos)
        
        # Filtrar pedidos que permiten BH
        pedidos_permiten_bh = self._filtrar_pedidos_permiten_bh(pedidos)
        
        if not pedidos_permiten_bh:
            return PipelineResult()
        
        cap_backhaul = get_capacity_for_type(self.config, TipoCamion.BACKHAUL, self.venta)
        
        # Optimizar grupos BH
        camiones_bh, pedidos_asignados = self._optimizar_grupos_secuencial(
            pedidos_permiten_bh,
            context,
            TipoCamion.BACKHAUL,
            cap_backhaul,
            max_camiones=n_bh_target
        )
        
        # Validar y ajustar
        if camiones_bh:
            validation_result = self.validation_cycle.ejecutar(
                camiones_bh,
                pedidos_asignados,
                "FASE_0_BH",
                "vcu",
                self.effective_config,
                self.venta
            )
            return PipelineResult(
                camiones=validation_result.camiones_validos,
                pedidos_asignados=validation_result.pedidos_asignados
            )
        
        return PipelineResult()
    
    def _ejecutar_fase_nestle(
        self,
        pedidos: List[Pedido],
        context: PhaseContext
    ) -> PipelineResult:
        """
        Fase 1: Optimizar con camiones Nestlé.
        
        Orden:
        1. multi_ce_prioridad (secuencial)
        2. normal (paralelo)
        3. multi_ce (secuencial)
        4. multi_cd (secuencial)
        """
        from utils.config_helpers import es_ruta_solo_backhaul
        
        all_camiones: List[Camion] = []
        pedidos_asignados: Set[str] = set()
        pedidos_disponibles = pedidos.copy()
        
        # Separar pedidos de rutas solo-BH
        pedidos_solo_bh = []
        pedidos_para_nestle = []
        
        for p in pedidos_disponibles:
            if es_ruta_solo_backhaul(self.config, p.cd, p.ce, "normal", self.venta, p.oc):
                pedidos_solo_bh.append(p)
            else:
                pedidos_para_nestle.append(p)
        
        pedidos_disponibles = pedidos_para_nestle
        
        # 1. multi_ce_prioridad (secuencial)
        if not context.timeout_cercano():
            result = self._procesar_tipo_ruta_nestle(
                pedidos_disponibles, context, "multi_ce_prioridad", paralelo=False
            )
            all_camiones.extend(result.camiones)
            pedidos_asignados.update(result.pedidos_asignados)
            pedidos_disponibles = self._filtrar_disponibles(pedidos_disponibles, pedidos_asignados)
        
        # 2. normal (paralelo)
        if not context.timeout_cercano() and pedidos_disponibles:
            result = self._procesar_tipo_ruta_nestle(
                pedidos_disponibles, context, "normal", paralelo=True
            )
            all_camiones.extend(result.camiones)
            pedidos_asignados.update(result.pedidos_asignados)
            pedidos_disponibles = self._filtrar_disponibles(pedidos_disponibles, pedidos_asignados)
        
        # 3. multi_ce (secuencial)
        if not context.timeout_cercano() and pedidos_disponibles:
            result = self._procesar_tipo_ruta_nestle(
                pedidos_disponibles, context, "multi_ce", paralelo=False
            )
            all_camiones.extend(result.camiones)
            pedidos_asignados.update(result.pedidos_asignados)
            pedidos_disponibles = self._filtrar_disponibles(pedidos_disponibles, pedidos_asignados)
        
        # 4. multi_cd (secuencial)
        if not context.timeout_cercano() and pedidos_disponibles:
            result = self._procesar_tipo_ruta_nestle(
                pedidos_disponibles, context, "multi_cd", paralelo=False
            )
            all_camiones.extend(result.camiones)
            pedidos_asignados.update(result.pedidos_asignados)
        
        # Validar y ajustar fase completa
        if all_camiones:
            # Actualizar contexto con asignados
            context.pedidos_asignados.update(pedidos_asignados)
            
            validation_result = self.validation_cycle.ejecutar(
                all_camiones,
                context.pedidos_asignados,
                "FASE_1_NESTLE",
                "vcu",
                self.effective_config,
                self.venta
            )
            
            return PipelineResult(
                camiones=validation_result.camiones_validos,
                pedidos_asignados=validation_result.pedidos_asignados
            )
        
        return PipelineResult(pedidos_asignados=pedidos_asignados)
    
    def _ejecutar_fase_backhaul(
        self,
        pedidos: List[Pedido],
        context: PhaseContext
    ) -> PipelineResult:
        """
        Fase 2: Optimizar restantes con camiones Backhaul.
        """
        from utils.config_helpers import get_capacity_for_type
        
        cap_backhaul = get_capacity_for_type(self.config, TipoCamion.BACKHAUL, self.venta)
        
        all_camiones: List[Camion] = []
        pedidos_asignados: Set[str] = set()
        pedidos_disponibles = pedidos.copy()
        
        # Procesar todos los tipos de ruta con BH
        for tipo_ruta in ["multi_ce_prioridad", "normal", "multi_ce", "multi_cd"]:
            if context.timeout_cercano():
                break
            
            result = self._procesar_tipo_ruta_backhaul(
                pedidos_disponibles, context, tipo_ruta, cap_backhaul
            )
            
            all_camiones.extend(result.camiones)
            pedidos_asignados.update(result.pedidos_asignados)
            pedidos_disponibles = self._filtrar_disponibles(pedidos_disponibles, pedidos_asignados)
        
        # Validar y ajustar
        if all_camiones:
            context.pedidos_asignados.update(pedidos_asignados)
            
            validation_result = self.validation_cycle.ejecutar(
                all_camiones,
                context.pedidos_asignados,
                "FASE_2_BH",
                "vcu",
                self.effective_config,
                self.venta
            )
            
            return PipelineResult(
                camiones=validation_result.camiones_validos,
                pedidos_asignados=validation_result.pedidos_asignados
            )
        
        return PipelineResult(pedidos_asignados=pedidos_asignados)
    
    def _procesar_tipo_ruta_nestle(
        self,
        pedidos: List[Pedido],
        context: PhaseContext,
        tipo_ruta: str,
        paralelo: bool = False
    ) -> PipelineResult:
        """
        Procesa un tipo de ruta con camiones Nestlé.
        """
        from utils.config_helpers import get_camiones_permitidos_para_ruta, get_capacity_for_type
        
        grupos = _generar_grupos_para_tipo(pedidos, self.effective_config, tipo_ruta)
        
        if not grupos:
            return PipelineResult()
        
        # Preparar grupos con capacidades
        grupos_preparados = []
        
        for cfg, pedidos_grupo in grupos:
            pedidos_no_asignados = self._filtrar_disponibles(
                pedidos_grupo, context.pedidos_asignados
            )
            
            if not pedidos_no_asignados:
                continue
            
            # Obtener tipo de camión Nestlé
            camiones_permitidos = get_camiones_permitidos_para_ruta(
                self.config, cfg.cd, cfg.ce, tipo_ruta, self.venta, cfg.oc
            )

            camiones_nestle = [c for c in camiones_permitidos if c.es_nestle]
                
            tipo_camion = self.truck_selector.seleccionar_tipo_camion(
                cfg, camiones_nestle, {'fase': 'nestle'}
            )


            camiones_nestle = [c for c in camiones_permitidos if c.es_nestle]
            
            if not camiones_nestle:
                continue
            
            tipo_camion = self.truck_selector.seleccionar_tipo_camion(
                cfg, camiones_nestle, {'fase': 'nestle'}
            )
            
            cap = get_capacity_for_type(self.config, tipo_camion, self.venta)
            
            # Ajustar si no permite apilamiento
            from utils.config_helpers import permite_apilamiento_cd
            cd_grupo = cfg.cd[0] if cfg.cd else ""
            if not permite_apilamiento_cd(self.config, cd_grupo, self.venta):
                cap = cap.sin_apilamiento()
            
            grupos_preparados.append((cfg, pedidos_no_asignados, cap, tipo_camion))
        
        if not grupos_preparados:
            return PipelineResult()
        
        # Ejecutar optimización
        if paralelo:
            return self._optimizar_paralelo(grupos_preparados, context)
        else:
            return self._optimizar_secuencial_grupos(grupos_preparados, context)
    
    def _procesar_tipo_ruta_backhaul(
        self,
        pedidos: List[Pedido],
        context: PhaseContext,
        tipo_ruta: str,
        cap_backhaul: TruckCapacity
    ) -> PipelineResult:
        """
        Procesa un tipo de ruta con camiones Backhaul.
        """
        from utils.config_helpers import get_camiones_permitidos_para_ruta
        
        grupos = _generar_grupos_para_tipo(pedidos, self.effective_config, tipo_ruta)
        
        if not grupos:
            return PipelineResult()
        
        all_camiones: List[Camion] = []
        pedidos_asignados: Set[str] = set()
        
        for cfg, pedidos_grupo in grupos:
            if context.timeout_cercano():
                break
            
            pedidos_no_asignados = self._filtrar_disponibles(
                pedidos_grupo, context.pedidos_asignados | pedidos_asignados
            )
            
            if not pedidos_no_asignados:
                continue
            
            # Verificar si permite BH
            camiones_permitidos = get_camiones_permitidos_para_ruta(
                self.config, cfg.cd, cfg.ce, tipo_ruta, self.venta, cfg.oc
            )
            
            if TipoCamion.BACKHAUL not in camiones_permitidos:
                continue
            
            n_pedidos = len(pedidos_no_asignados)
            tiempo_grupo = ajustar_tiempo_grupo(context.tpg, n_pedidos, tipo_ruta)
            
            res = optimizar_grupo_vcu(
                pedidos_no_asignados, cfg, self.effective_config, cap_backhaul, tiempo_grupo, TipoCamion.BACKHAUL
            )
            
            if res.get("status") in ("OPTIMAL", "FEASIBLE"):
                camiones = res.get("camiones", [])
                nuevos = res.get("pedidos_asignados_ids", [])
                
                if camiones and nuevos:
                    # Marcar como backhaul
                    for cam in camiones:
                        cam.tipo_camion = TipoCamion.BACKHAUL
                        for p in cam.pedidos:
                            p.tipo_camion = "backhaul"
                    
                    all_camiones.extend(camiones)
                    pedidos_asignados.update(nuevos)
        
        return PipelineResult(
            camiones=all_camiones,
            pedidos_asignados=pedidos_asignados
        )
    
    def _optimizar_paralelo(
        self,
        grupos_preparados: List[Tuple],
        context: PhaseContext
    ) -> PipelineResult:
        """
        Optimiza grupos en paralelo.
        """
        all_camiones: List[Camion] = []
        pedidos_asignados: Set[str] = set()
        
        # Ordenar por complejidad (más pedidos primero)
        grupos_sorted = sorted(
            grupos_preparados,
            key=lambda x: len(x[1]),
            reverse=True
        )
        
        def optimizar_wrapper(args):
            cfg, pedidos_grupo, cap, tipo_camion = args
            n_pedidos = len(pedidos_grupo)
            tiempo_grupo = ajustar_tiempo_grupo(context.tpg, n_pedidos, "normal")
            
            res = optimizar_grupo_vcu(
                pedidos_grupo, cfg, self.effective_config, cap, tiempo_grupo, tipo_camion
            )
            
            return (res, tipo_camion, cfg.id, n_pedidos)
        
        with ThreadPoolExecutor(max_workers=THREAD_WORKERS_NORMAL) as executor:
            futures = {
                executor.submit(optimizar_wrapper, args): args
                for args in grupos_sorted
            }
            
            for future in as_completed(futures):
                if context.timeout_cercano():
                    break
                
                try:
                    res, tipo_camion, grupo_id, n_pedidos = future.result()
                    
                    if res.get("status") in ("OPTIMAL", "FEASIBLE"):
                        camiones = res.get("camiones", [])
                        nuevos = res.get("pedidos_asignados_ids", [])
                        
                        if camiones and nuevos:
                            all_camiones.extend(camiones)
                            pedidos_asignados.update(nuevos)
                
                except Exception as e:
                    if DEBUG_VALIDATION:
                        print(f"[VCU] Error en grupo: {e}")
        
        return PipelineResult(
            camiones=all_camiones,
            pedidos_asignados=pedidos_asignados
        )
    
    def _optimizar_secuencial_grupos(
        self,
        grupos_preparados: List[Tuple],
        context: PhaseContext
    ) -> PipelineResult:
        """
        Optimiza grupos secuencialmente.
        """
        all_camiones: List[Camion] = []
        pedidos_asignados: Set[str] = set()
        
        for cfg, pedidos_grupo, cap, tipo_camion in grupos_preparados:
            if context.timeout_cercano():
                break
            
            n_pedidos = len(pedidos_grupo)
            tiempo_grupo = ajustar_tiempo_grupo(context.tpg, n_pedidos, cfg.tipo.value)
            
            res = optimizar_grupo_vcu(
                pedidos_grupo, cfg, self.effective_config, cap, tiempo_grupo, tipo_camion
            )
            
            if res.get("status") in ("OPTIMAL", "FEASIBLE"):
                camiones = res.get("camiones", [])
                nuevos = res.get("pedidos_asignados_ids", [])
                
                if camiones and nuevos:
                    all_camiones.extend(camiones)
                    pedidos_asignados.update(nuevos)
        
        return PipelineResult(
            camiones=all_camiones,
            pedidos_asignados=pedidos_asignados
        )
    
    def _optimizar_grupos_secuencial(
        self,
        pedidos: List[Pedido],
        context: PhaseContext,
        tipo_camion: TipoCamion,
        capacidad: TruckCapacity,
        max_camiones: int = None
    ) -> Tuple[List[Camion], Set[str]]:
        """
        Optimiza pedidos creando camiones hasta un máximo.
        """
        grupos = _generar_grupos_para_tipo(pedidos, self.effective_config, "normal")
        
        all_camiones: List[Camion] = []
        pedidos_asignados: Set[str] = set()
        n_camiones_creados = 0
        
        for cfg, pedidos_grupo in grupos:
            if max_camiones and n_camiones_creados >= max_camiones:
                break
            
            if context.timeout_cercano():
                break
            
            pedidos_no_asignados = self._filtrar_disponibles(
                pedidos_grupo, context.pedidos_asignados | pedidos_asignados
            )
            
            if not pedidos_no_asignados:
                continue
            
            n_pedidos = len(pedidos_no_asignados)
            tiempo_grupo = ajustar_tiempo_grupo(context.tpg, n_pedidos, "normal")
            
            res = optimizar_grupo_vcu(
                pedidos_no_asignados, cfg, self.effective_config, capacidad, tiempo_grupo, tipo_camion
            )
            
            if res.get("status") in ("OPTIMAL", "FEASIBLE"):
                camiones = res.get("camiones", [])
                nuevos = res.get("pedidos_asignados_ids", [])
                
                if camiones and nuevos:
                    for cam in camiones:
                        cam.tipo_camion = tipo_camion
                        for p in cam.pedidos:
                            p.tipo_camion = tipo_camion.value
                    
                    all_camiones.extend(camiones)
                    pedidos_asignados.update(nuevos)
                    n_camiones_creados += len(camiones)
        
        return all_camiones, pedidos_asignados
    
    def _estimar_target_bh(self, pedidos: List[Pedido]) -> int:
        """Estima número de camiones BH necesarios para adherencia."""
        cap_ref = self.capacidades.get(TipoCamion.PAQUETERA) or self.capacidad_default
        
        total_peso = sum(p.peso for p in pedidos)
        total_vol = sum(p.volumen for p in pedidos)
        
        cam_por_peso = total_peso / cap_ref.cap_weight if cap_ref.cap_weight > 0 else 0
        cam_por_vol = total_vol / cap_ref.cap_volume if cap_ref.cap_volume > 0 else 0
        
        n_camiones_estimado = max(cam_por_peso, cam_por_vol)
        n_camiones_estimado = max(1, int(n_camiones_estimado) + 2)
        
        n_bh_target = int(n_camiones_estimado * self.adherencia_bh)
        return max(1, n_bh_target)
    
    def _filtrar_pedidos_permiten_bh(self, pedidos: List[Pedido]) -> List[Pedido]:
        """Filtra pedidos cuya ruta permite backhaul."""
        from utils.config_helpers import get_camiones_permitidos_para_ruta
        
        resultado = []
        for p in pedidos:
            camiones_permitidos = get_camiones_permitidos_para_ruta(
                self.config, [p.cd], [p.ce], "normal", self.venta, p.oc
            )
            if TipoCamion.BACKHAUL in camiones_permitidos:
                resultado.append(p)
        
        return resultado
    
    def _filtrar_disponibles(
        self,
        pedidos: List[Pedido],
        asignados: Set[str]
    ) -> List[Pedido]:
        """Filtra pedidos no asignados."""
        return [p for p in pedidos if p.pedido not in asignados]