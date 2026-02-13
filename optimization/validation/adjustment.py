# optimization/validation/adjustment.py
"""
Ajuste post-validación de camiones.
Maneja la remoción de pedidos de camiones inválidos y su recuperación.

"""

from __future__ import annotations

from itertools import combinations
from typing import List, Dict, Any, Optional, Tuple

from models.domain import Camion, Pedido, TruckCapacity, TipoCamion
from models.enums import TipoRuta
from optimization.validation.height_validator import HeightValidator
from optimization.utils.helpers import calcular_posiciones_apilabilidad


# Flag para activar/desactivar prints de debug
DEBUG_VALIDATION = False


class AdjustmentResult:
    """Resultado del proceso de ajuste."""
    
    def __init__(
        self,
        camiones_validos: List[Camion],
        pedidos_removidos: List[Pedido],
        camiones_desarmados: int = 0
    ):
        self.camiones_validos = camiones_validos
        self.pedidos_removidos = pedidos_removidos
        self.camiones_desarmados = camiones_desarmados


class PostValidationAdjuster:
    """
    Ajusta camiones inválidos después de la validación de altura.
    
    Estrategia:
    1. Identifica camiones con altura_validada == False
    2. Calcula cuántos fragmentos fallaron
    3. Busca combinación de pedidos cuya suma de fragmentos ≈ fallidos
    4. Remueve pedidos manteniendo VCU >= target
    5. Re-valida hasta válido o máx iteraciones
    """
    
    MAX_ITERACIONES = 3
    MAX_COMBO_SIZE = 4  # Máximo pedidos a considerar en combinación
    
    def __init__(self, client_config):
        """
        Args:
            client_config: Configuración del cliente
        """
        self.config = client_config
        # Se inicializarán con effective_config en ajustar_camiones
        self.permite_consolidacion = False
        self.max_skus_por_pallet = 1
    
    def ajustar_camiones(
        self,
        camiones: List[Camion],
        modo: str = "vcu",
        effective_config: dict = None
    ) -> AdjustmentResult:
        """
        Ajusta camiones inválidos removiendo pedidos problemáticos.
        
        Args:
            camiones: Lista de camiones (algunos pueden ser inválidos)
            modo: "vcu" o "binpacking" (afecta si se fuerza remoción)
        
        Returns:
            AdjustmentResult con camiones válidos y pedidos removidos
        """
        if effective_config:
            self.permite_consolidacion = effective_config.get('PERMITE_CONSOLIDACION', False)
            self.max_skus_por_pallet = effective_config.get('MAX_SKUS_POR_PALLET', 1)

        # Identificar camiones inválidos
        camiones_invalidos = [
            cam for cam in camiones
            if cam.metadata.get('layout_info', {}).get('altura_validada') == False
        ]
        
        if DEBUG_VALIDATION:
            print(f"\n{'='*80}")
            print(f"AJUSTE POST-VALIDACIÓN")
            print(f"{'='*80}")
            print(f"Camiones inválidos: {len(camiones_invalidos)}")
        
        pedidos_removidos_global: List[Pedido] = []
        
        # Procesar cada camión inválido
        for cam in camiones_invalidos:
            self._ajustar_camion(cam, pedidos_removidos_global, modo)
        
        # Separar camiones válidos de los que siguen inválidos
        camiones_validos = []
        camiones_desarmados = 0
        
        for cam in camiones:
            if cam.metadata.get('layout_info', {}).get('altura_validada') == True:
                camiones_validos.append(cam)
            else:
                # Desarmar: todos los pedidos van al pool
                if DEBUG_VALIDATION:
                    print(f"[AJUSTE] 🔴 Desarmando camión {cam.id} - {len(cam.pedidos)} pedidos al pool")
                pedidos_removidos_global.extend(cam.pedidos)
                camiones_desarmados += 1
        
        if DEBUG_VALIDATION:
            print(f"\n{'='*80}")
            print(f"RESUMEN AJUSTE POST-VALIDACIÓN")
            print(f"{'='*80}")
            print(f"Camiones válidos: {len(camiones_validos)}")
            print(f"Camiones desarmados: {camiones_desarmados}")
            print(f"Total pedidos removidos: {len(pedidos_removidos_global)}")
            print(f"{'='*80}\n")
        
        return AdjustmentResult(
            camiones_validos=camiones_validos,
            pedidos_removidos=pedidos_removidos_global,
            camiones_desarmados=camiones_desarmados
        )
    
    def _ajustar_camion(
        self,
        cam: Camion,
        pedidos_removidos_global: List[Pedido],
        modo: str
    ):
        """
        Ajusta un camión individual removiendo pedidos hasta que sea válido.
        
        Modifica el camión in-place y agrega pedidos removidos a la lista global.
        """
        layout_info = cam.metadata.get('layout_info', {})
        fragmentos_fallidos = layout_info.get('fragmentos_fallidos', [])
        n_fallidos = len(fragmentos_fallidos)
        
        if n_fallidos == 0:
            return
        
        for iteracion in range(self.MAX_ITERACIONES):
            # Obtener fragmentos fallidos actuales
            layout_info = cam.metadata.get('layout_info', {})
            fragmentos_fallidos = layout_info.get('fragmentos_fallidos', [])
            n_fallidos = len(fragmentos_fallidos)
            
            if n_fallidos == 0:
                break
            
            # Buscar pedidos a remover
            pedidos_a_remover = self._seleccionar_pedidos_a_remover(
                cam, n_fallidos, fragmentos_fallidos, forzar_remocion=False
            )
            
            if not pedidos_a_remover:
                if modo == "binpacking":
                    # En binpacking, forzar remoción aunque VCU baje
                    pedidos_a_remover = self._seleccionar_pedidos_a_remover(
                        cam, n_fallidos, fragmentos_fallidos, forzar_remocion=True
                    )
                    if not pedidos_a_remover:
                        break
                else:
                    break
            
            # Remover pedidos
            pedidos_ids_remover = {p.pedido for p in pedidos_a_remover}
            pedidos_removidos_global.extend(pedidos_a_remover)
            
            # Actualizar camión
            cam.pedidos = [p for p in cam.pedidos if p.pedido not in pedidos_ids_remover]
            cam._invalidar_cache()
            
            # Re-validar
            self._revalidar_camion(cam)
            
            # Verificar si ya es válido
            if cam.metadata.get('layout_info', {}).get('altura_validada'):
                break
    
    def _seleccionar_pedidos_a_remover(
        self,
        camion: Camion,
        n_fragmentos_fallidos: int,
        fragmentos_fallidos: List[Dict],
        forzar_remocion: bool = False
    ) -> List[Pedido]:
        """
        Selecciona los pedidos óptimos a remover para arreglar el camión.
        
        Estrategia:
        1. Buscar pedido único con fragmentos == n_fallidos
        2. Buscar combinación exacta (máx 4 pedidos)
        3. Buscar mejor aproximación
        
        Args:
            camion: Camión a ajustar
            n_fragmentos_fallidos: Cantidad de fragmentos que no cupieron
            fragmentos_fallidos: Lista de fragmentos fallidos (para análisis)
            forzar_remocion: Si True, ignora restricción de VCU mínimo
        
        Returns:
            Lista de pedidos a remover (puede estar vacía)
        """
        pedidos = camion.pedidos
        if not pedidos:
            return []
        
        # Función de impacto: preferir remover pedidos con menor impacto en VCU
        def impacto(p: Pedido) -> float:
            return p.volumen if camion.vcu_vol >= camion.vcu_peso else p.peso
        
        # PASO 1: Buscar pedido único exacto
        unicos = [p for p in pedidos if p.cantidad_fragmentos == n_fragmentos_fallidos]
        if unicos:
            elegido = min(unicos, key=impacto)
            if self._vcu_sigue_valido(camion, [elegido], forzar_remocion):
                return [elegido]
        
        # PASO 2: Buscar combinaciones EXACTAS (máx 4 pedidos)
        data = [(p, p.cantidad_fragmentos, impacto(p)) for p in pedidos]
        n = len(data)
        max_combo = min(self.MAX_COMBO_SIZE, n)
        
        exactas = []
        for r in range(2, max_combo + 1):  # Empezar en 2 (el 1 ya se probó)
            for combo in combinations(data, r):
                frag_sum = sum(x[1] for x in combo)
                if frag_sum == n_fragmentos_fallidos:
                    costo = sum(x[2] for x in combo)
                    exactas.append((combo, costo))
        
        if exactas:
            combo, _ = min(exactas, key=lambda x: x[1])
            seleccion = [x[0] for x in combo]
            if self._vcu_sigue_valido(camion, seleccion, forzar_remocion):
                return seleccion
        
        # PASO 3: Buscar mejor aproximación
        mejores = []
        target = n_fragmentos_fallidos
        
        for r in range(1, max_combo + 1):
            for combo in combinations(data, r):
                frag_sum = sum(x[1] for x in combo)
                diff = abs(frag_sum - target)
                impacto_total = sum(x[2] for x in combo)
                mejores.append((combo, diff, impacto_total, frag_sum))
        
        if not mejores:
            return []
        
        # Ordenar por: 1) menor diferencia, 2) menor impacto
        mejores.sort(key=lambda x: (x[1], x[2]))
        
        for combo, diff, imp, frag_sum in mejores:
            seleccion = [x[0] for x in combo]
            if self._vcu_sigue_valido(camion, seleccion, forzar_remocion):
                return seleccion
        
        # PASO 4: No existe combinación válida
        return []
    
    def _vcu_sigue_valido(
        self,
        camion: Camion,
        pedidos_a_remover: List[Pedido],
        forzar_remocion: bool = False
    ) -> bool:
        """
        Verifica si el camión mantiene VCU >= target sin ciertos pedidos.
        
        Args:
            camion: Camión a verificar
            pedidos_a_remover: Pedidos que se removerían
            forzar_remocion: Si True, solo verifica que no quede vacío
        
        Returns:
            True si el VCU resultante es válido
        """
        ids = {p.pedido for p in pedidos_a_remover}
        
        # Verificar que no quede vacío
        pedidos_restantes = len(camion.pedidos) - len(pedidos_a_remover)
        if pedidos_restantes <= 0:
            return False
        
        # En modo forzado, solo verificar que no quede vacío
        if forzar_remocion:
            return True
        
        # Calcular VCU resultante
        peso_rest = sum(p.peso for p in camion.pedidos if p.pedido not in ids)
        vol_rest = sum(p.volumen for p in camion.pedidos if p.pedido not in ids)
        
        cap = camion.capacidad
        vcu_peso = peso_rest / cap.cap_weight if cap.cap_weight > 0 else 0
        vcu_vol = vol_rest / cap.cap_volume if cap.cap_volume > 0 else 0
        
        return max(vcu_peso, vcu_vol) >= cap.vcu_min
    
    def _revalidar_camion(self, cam: Camion):
        """
        Re-valida un camión después de remover pedidos.
        Actualiza su metadata con el nuevo resultado.
        """
        
        from utils.config_helpers import get_consolidacion_config

        # Obtener altura real (ALVI=230, RENDIC=240, etc.)
        altura_maxima = cam.capacidad.altura_cm
        if hasattr(self.config, 'get_altura_maxima'):
            subcliente = ""
            if cam.pedidos:
                subcliente = cam.pedidos[0].metadata.get("SUBCLIENTE", "")
            altura_maxima = self.config.get_altura_maxima(subcliente, altura_maxima)

        # Obtener consolidación por subcliente
        subcliente = None
        oc = None
        if cam.pedidos:
            primer_pedido = cam.pedidos[0]
            subcliente = primer_pedido.metadata.get("SUBCLIENTE") if primer_pedido.metadata else None
            oc = getattr(primer_pedido, 'oc', None)

        consolidacion = get_consolidacion_config(self.config, subcliente=subcliente, oc=oc)

        validator = HeightValidator(
            altura_maxima_cm=altura_maxima,
            permite_consolidacion=consolidacion.get("PERMITE_CONSOLIDACION", self.permite_consolidacion),
            max_skus_por_pallet=consolidacion.get("MAX_SKUS_POR_PALLET", self.max_skus_por_pallet),
            max_altura_picking_apilado_cm=consolidacion.get("ALTURA_MAX_PICKING_APILADO_CM")
        )
        
        es_valido, errores, layout, debug_info = validator.validar_camion_rapido(cam)
        
        # Construir nuevo layout_info
        nuevo_layout_info = {
            'altura_validada': bool(es_valido),
            'errores_validacion': errores if errores else [],
            'fragmentos_fallidos': debug_info.get('fragmentos_fallidos', []) if debug_info else [],
            'fragmentos_totales': debug_info.get('fragmentos_totales', 0) if debug_info else 0,
        }
        
        if layout is not None:
            cam.pos_total = layout.posiciones_usadas
            nuevo_layout_info.update({
                'posiciones_usadas': layout.posiciones_usadas,
                'posiciones_disponibles': layout.posiciones_disponibles,
                'altura_maxima_cm': layout.altura_maxima_cm,
                'total_pallets_fisicos': layout.total_pallets,
                'altura_maxima_usada_cm': round(layout.altura_maxima_usada, 1),
                'altura_promedio_usada': round(layout.altura_promedio_usada, 1),
                'aprovechamiento_altura': round(layout.aprovechamiento_altura * 100, 1),
                'aprovechamiento_posiciones': round(layout.aprovechamiento_posiciones * 100, 1),
                'posiciones': self._serializar_posiciones(layout)
            })
        
        cam.metadata['layout_info'] = nuevo_layout_info
    
    def _serializar_posiciones(self, layout) -> List[Dict[str, Any]]:
        """Serializa las posiciones del layout a diccionarios."""
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
                                'descripcion': frag.descripcion 
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


class PedidoRecovery:
    """
    Recupera pedidos removidos intentando asignarlos a nuevos camiones.
    
    Estrategia:
    1. Intentar con camiones Nestlé primero
    2. Luego intentar con camiones Backhaul
    """
    
    def __init__(self, client_config, venta: str = None):
        """
        Args:
            client_config: Configuración del cliente
            venta: Canal de venta (Secos, Frios, etc.)
        """
        self.config = client_config
        self.venta = venta
    
    def recuperar_pedidos(
        self,
        pedidos: List[Pedido],
        capacidad_default: TruckCapacity
    ) -> List[Camion]:
        """
        Intenta recuperar pedidos removidos creando nuevos camiones.
        
        Args:
            pedidos: Pedidos a recuperar
            capacidad_default: Capacidad por defecto
        
        Returns:
            Lista de nuevos camiones con los pedidos recuperados
        """
        from utils.config_helpers import get_camiones_permitidos_para_ruta, get_capacity_for_type
        from optimization.solvers.vcu import optimizar_grupo_vcu
        from optimization.groups import generar_grupos_optimizacion
        
        if not pedidos:
            return []
        
        if DEBUG_VALIDATION:
            print(f"\n[RECUPERACIÓN] Intentando recuperar {len(pedidos)} pedidos")
        
        camiones_resultado = []
        pedidos_restantes = pedidos.copy()
        
        # === PASO 1: Intentar con Nestlé ===
        camiones_nestle, pedidos_restantes = self._recuperar_con_tipo(
            pedidos_restantes, "nestle"
        )
        camiones_resultado.extend(camiones_nestle)
        
        # === PASO 2: Intentar restantes con BH ===
        camiones_bh, pedidos_restantes = self._recuperar_con_tipo(
            pedidos_restantes, "backhaul"
        )
        camiones_resultado.extend(camiones_bh)
        
        if DEBUG_VALIDATION and pedidos_restantes:
            print(f"[RECUPERACIÓN] ⚠️ {len(pedidos_restantes)} pedidos sin recuperar")
        
        return camiones_resultado
    
    def _recuperar_con_tipo(
        self,
        pedidos: List[Pedido],
        tipo: str  # "nestle" o "backhaul"
    ) -> Tuple[List[Camion], List[Pedido]]:
        """
        Intenta recuperar pedidos con un tipo de camión específico.
        
        Returns:
            (camiones_creados, pedidos_no_recuperados)
        """
        from utils.config_helpers import get_camiones_permitidos_para_ruta, get_capacity_for_type
        from optimization.solvers.vcu import optimizar_grupo_vcu
        from optimization.groups import generar_grupos_optimizacion
        
        if not pedidos:
            return [], []
        
        # Filtrar pedidos que permiten este tipo
        pedidos_filtrados = []
        for p in pedidos:
            camiones_permitidos = get_camiones_permitidos_para_ruta(
                self.config, [p.cd], [p.ce], "normal", self.venta, p.oc
            )
            
            if tipo == "nestle":
                if any(c.es_nestle for c in camiones_permitidos):
                    pedidos_filtrados.append(p)
            else:  # backhaul
                if TipoCamion.BACKHAUL in camiones_permitidos:
                    pedidos_filtrados.append(p)
        
        if not pedidos_filtrados:
            return [], pedidos
        
        if DEBUG_VALIDATION:
            print(f"[RECUPERACIÓN] Intentando {len(pedidos_filtrados)} pedidos con {tipo}")
        
        # Generar grupos y optimizar
        from utils.config_helpers import get_effective_config
        effective = get_effective_config(self.config, self.venta)
        grupos = generar_grupos_optimizacion(pedidos_filtrados, effective, "vcu")

        camiones_resultado = []
        pedidos_asignados = set()
        
        for cfg, pedidos_grupo in grupos:
            if not pedidos_grupo:
                continue
            
            # Obtener capacidad según tipo
            if tipo == "nestle":
                camiones_permitidos = get_camiones_permitidos_para_ruta(
                    self.config, cfg.cd, cfg.ce, cfg.tipo.value, self.venta, cfg.oc
                )
                nestle_permitidos = [c for c in camiones_permitidos if c.es_nestle]
                if not nestle_permitidos:
                    continue
                tipo_camion = nestle_permitidos[0]
            else:
                tipo_camion = TipoCamion.BACKHAUL
            
            cap = get_capacity_for_type(self.config, tipo_camion, self.venta)
            
            # Ajustar capacidad si no permite apilamiento
            if not effective.get('PERMITE_APILAMIENTO', True):
                cap = cap.sin_apilamiento()
            
            resultado = optimizar_grupo_vcu(
                pedidos_grupo, cfg, effective, cap, 30
            )
            
            if resultado.get("status") in ("OPTIMAL", "FEASIBLE"):
                camiones = resultado.get("camiones", [])
                asignados = resultado.get("pedidos_asignados_ids", [])
                
                for cam in camiones:
                    cam.tipo_camion = tipo_camion
                    for p in cam.pedidos:
                        p.tipo_camion = tipo_camion.value
                
                camiones_resultado.extend(camiones)
                pedidos_asignados.update(asignados)
        
        # Pedidos no recuperados
        pedidos_no_recuperados = [p for p in pedidos if p.pedido not in pedidos_asignados]
        
        return camiones_resultado, pedidos_no_recuperados


# Funciones de conveniencia para mantener compatibilidad
def ajustar_camiones_invalidos(
    camiones: List[Camion],
    client_config,
    pedidos_removidos_global: List[Pedido],
    modo: str = "vcu",
    effective_config: dict = None
) -> List[Camion]:
    """
    Función de conveniencia que mantiene la firma original.
    
    NOTA: pedidos_removidos_global se modifica in-place por compatibilidad.
    """
    adjuster = PostValidationAdjuster(client_config)
    result = adjuster.ajustar_camiones(camiones, modo, effective_config)
    
    # Agregar pedidos removidos a la lista global (compatibilidad)
    pedidos_removidos_global.extend(result.pedidos_removidos)
    
    return result.camiones_validos


def recuperar_pedidos_sobrantes(
    pedidos: List[Pedido],
    client_config,
    capacidad_default: TruckCapacity,
    venta: str = None
) -> List[Camion]:
    """
    Función de conveniencia que mantiene la firma original.
    """
    recovery = PedidoRecovery(client_config, venta)
    return recovery.recuperar_pedidos(pedidos, capacidad_default)