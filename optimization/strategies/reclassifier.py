# optimization/strategies/reclassifier.py
"""
Reclasificación de camiones post-validación.

Determina si un camión paquetera puede ser reclasificado a rampla_directa
basándose en la validación de altura REAL.

Extraído de orchestrator.py para mejor modularidad.
"""

from __future__ import annotations

from typing import List, Optional, Dict, Any

from models.domain import Camion, TruckCapacity
from models.enums import TipoCamion
from optimization.utils.helpers import calcular_posiciones_apilabilidad
from optimization.validation.height_validator import HeightValidator


# Flag para activar/desactivar prints de debug
DEBUG_VALIDATION = False


class NestleReclassifier:
    """
    Reclasifica camiones Nestlé después de validación de altura.
    
    Lógica:
    - Se optimiza inicialmente con PAQUETERA (más posiciones, 280cm altura)
    - Después de validar altura, si el layout real cabe en RAMPLA_DIRECTA (270cm),
      se reclasifica para usar camión más económico
    """
    
    def __init__(self, client_config, venta: str = None):
        """
        Args:
            client_config: Configuración del cliente
        """
        self.config = client_config
        self.venta = venta
    
    def reclasificar_camiones(self, camiones: List[Camion]) -> int:
        """
        Reclasifica camiones paquetera a rampla_directa si es posible.
        
        Modifica los camiones in-place.
        
        Args:
            camiones: Lista de camiones a evaluar
        
        Returns:
            Número de camiones reclasificados
        """
        from utils.config_helpers import get_capacity_for_type
        
        total_reclasificados = 0
        
        for cam in camiones:
            # Solo reclasificar camiones paquetera
            if cam.tipo_camion != TipoCamion.PAQUETERA:
                continue
            
            # Solo reclasificar si el camión está validado
            layout_info = cam.metadata.get('layout_info', {})
            if not layout_info.get('altura_validada', False):
                continue
            
            # Determinar tipo óptimo
            tipo_optimo = self._determinar_tipo_optimo(cam)
            
            # Si cambió a rampla_directa
            if tipo_optimo == TipoCamion.RAMPLA_DIRECTA:
                nueva_capacidad = get_capacity_for_type(self.config, tipo_optimo, self.venta)
                self._aplicar_reclasificacion(cam, tipo_optimo, nueva_capacidad)
                total_reclasificados += 1
        
        if DEBUG_VALIDATION and total_reclasificados > 0:
            print(f"\n[RECLASIFICACIÓN] ✅ {total_reclasificados} camiones: paquetera → rampla_directa")
        
        return total_reclasificados
    
    def _determinar_tipo_optimo(self, camion: Camion) -> TipoCamion:
        """
        Determina el tipo de camión Nestlé óptimo basándose en validación real.
        
        Args:
            camion: Camión a evaluar (ya validado)
        
        Returns:
            TipoCamion óptimo
        """
        from utils.config_helpers import get_capacity_for_type
        
        # Obtener capacidades de ambos tipos
        cap_paquetera = get_capacity_for_type(self.config, TipoCamion.PAQUETERA, self.venta)
        cap_rampla = get_capacity_for_type(self.config, TipoCamion.RAMPLA_DIRECTA, self.venta)
        
        # Si tienen las mismas capacidades, no hay diferencia
        if self._capacidades_iguales(cap_paquetera, cap_rampla):
            return TipoCamion.PAQUETERA
        
        # Usar datos REALES de validación de altura
        layout_info = camion.metadata.get('layout_info', {})
        
        # Si no hay layout_info o no está validado, usar lógica conservadora
        if not layout_info or not layout_info.get('altura_validada'):
            return self._determinar_sin_layout(camion, cap_rampla)
        
        # Usar datos reales del layout
        return self._determinar_con_layout(camion, layout_info, cap_rampla)
    
    def _capacidades_iguales(self, cap1: TruckCapacity, cap2: TruckCapacity) -> bool:
        """Verifica si dos capacidades son iguales."""
        return (
            cap1.max_positions == cap2.max_positions and
            cap1.cap_weight == cap2.cap_weight and
            cap1.cap_volume == cap2.cap_volume and
            cap1.altura_cm == cap2.altura_cm
        )
    
    def _determinar_sin_layout(
        self, 
        camion: Camion, 
        cap_rampla: TruckCapacity
    ) -> TipoCamion:
        """
        Determina tipo óptimo sin datos de layout (fallback conservador).
        """
        peso_total = sum(p.peso for p in camion.pedidos)
        volumen_total = sum(p.volumen for p in camion.pedidos)
        pallets_total = camion.pallets_capacidad
        
        cabe_en_rampla = (
            len(camion.pedidos) <= cap_rampla.max_positions and
            peso_total <= cap_rampla.cap_weight and
            volumen_total <= cap_rampla.cap_volume and
            pallets_total <= cap_rampla.max_pallets
        )
        
        if cabe_en_rampla:
            vcu_peso_rampla = peso_total / cap_rampla.cap_weight if cap_rampla.cap_weight > 0 else 0
            vcu_vol_rampla = volumen_total / cap_rampla.cap_volume if cap_rampla.cap_volume > 0 else 0
            vcu_max_rampla = max(vcu_peso_rampla, vcu_vol_rampla)
            
            if vcu_max_rampla >= cap_rampla.vcu_min:
                return TipoCamion.RAMPLA_DIRECTA
        
        return TipoCamion.PAQUETERA
    
    def _determinar_con_layout(
        self,
        camion: Camion,
        layout_info: Dict[str, Any],
        cap_rampla: TruckCapacity
    ) -> TipoCamion:
            """
            Determina tipo óptimo usando datos reales del layout.
            Re-valida el layout con altura de rampla antes de confirmar.
            """
            altura_maxima_usada = layout_info.get('altura_maxima_usada_cm', 0)
            posiciones_usadas = layout_info.get('posiciones_usadas', len(camion.pedidos))
            
            # Verificar dimensiones básicas
            peso_total = sum(p.peso for p in camion.pedidos)
            volumen_total = sum(p.volumen for p in camion.pedidos)
            pallets_total = camion.pallets_capacidad
            
            # Verificación rápida: si claramente no cabe, no hacer validación costosa
            if (posiciones_usadas > cap_rampla.max_positions or
                peso_total > cap_rampla.cap_weight or
                volumen_total > cap_rampla.cap_volume or
                pallets_total > cap_rampla.max_pallets):
                return TipoCamion.PAQUETERA
            
            # Si la altura ya excede, no cabe
            if altura_maxima_usada > cap_rampla.altura_cm:
                return TipoCamion.PAQUETERA
            
            # ═══════════════════════════════════════════════════════════════════
            # CRÍTICO: Re-validar el layout con la altura de rampla_directa
            # ═══════════════════════════════════════════════════════════════════
            if not self._validar_layout_para_rampla(camion, cap_rampla):
                if DEBUG_VALIDATION:
                    print(f"[RECLASIFICACIÓN] ❌ Camión {camion.id}: layout inválido para rampla_directa")
                return TipoCamion.PAQUETERA
            
            # Verificar que cumple VCU target
            vcu_peso_rampla = peso_total / cap_rampla.cap_weight if cap_rampla.cap_weight > 0 else 0
            vcu_vol_rampla = volumen_total / cap_rampla.cap_volume if cap_rampla.cap_volume > 0 else 0
            vcu_max_rampla = max(vcu_peso_rampla, vcu_vol_rampla)
            
            if vcu_max_rampla >= cap_rampla.vcu_min:
                return TipoCamion.RAMPLA_DIRECTA
            
            return TipoCamion.PAQUETERA
        
    def _validar_layout_para_rampla(
        self,
        camion: Camion,
        cap_rampla: TruckCapacity
    ) -> bool:
        """
        Valida que el layout del camión sea válido con las restricciones de rampla_directa.
        Verifica TANTO altura como número de posiciones.
        
        Returns:
            True si el layout es válido para rampla_directa
        """
        from utils.config_helpers import get_consolidacion_config
        
        # Obtener configuración de consolidación
        subcliente = None
        oc = None
        if camion.pedidos:
            primer_pedido = camion.pedidos[0]
            subcliente = primer_pedido.metadata.get("SUBCLIENTE") if primer_pedido.metadata else None
            oc = getattr(primer_pedido, 'oc', None)
        
        consolidacion = get_consolidacion_config(
            self.config,
            subcliente=subcliente,
            oc=oc,
            venta=self.venta
        )
        
        # Crear validador con altura de RAMPLA_DIRECTA
        altura_maxima = cap_rampla.altura_cm
        if hasattr(self.config, 'get_altura_maxima'):
            sub = subcliente or ""
            altura_maxima = self.config.get_altura_maxima(sub, altura_maxima)

        altura_maxima_mismo_sku_cm = None
        if hasattr(self.config, 'get_altura_maxima_mismo_sku'):
            altura_maxima_mismo_sku_cm = self.config.get_altura_maxima_mismo_sku(subcliente or "")


        validator = HeightValidator(
            altura_maxima_cm=altura_maxima,
            permite_consolidacion=consolidacion.get("PERMITE_CONSOLIDACION", True),
            max_skus_por_pallet=consolidacion.get("MAX_SKUS_POR_PALLET", 3),
            max_altura_picking_apilado_cm=consolidacion.get("ALTURA_MAX_PICKING_APILADO_CM"),
            altura_maxima_mismo_sku_cm=altura_maxima_mismo_sku_cm,
        )
        
        # Ejecutar validación de altura
        es_valido, errores, layout, debug_info = validator.validar_camion_rapido(camion)
        
        if not es_valido:
            if DEBUG_VALIDATION:
                print(f"[RECLASIFICACIÓN] Camión {camion.id} falló validación altura rampla: {errores}")
            return False
        
        # ═══════════════════════════════════════════════════════════════════
        # CRÍTICO: Verificar que el layout NO excede las posiciones de rampla
        # HeightValidator solo valida altura, NO valida límite de posiciones
        # ═══════════════════════════════════════════════════════════════════
        if layout is not None and layout.posiciones_usadas > cap_rampla.max_positions:
            if DEBUG_VALIDATION:
                print(f"[RECLASIFICACIÓN] ❌ Camión {camion.id}: layout usa {layout.posiciones_usadas} posiciones, "
                    f"rampla_directa permite máx {cap_rampla.max_positions}")
            return False
        
        # ═══════════════════════════════════════════════════════════════════
        # Si es válido, guardar el nuevo layout_info para rampla
        # ═══════════════════════════════════════════════════════════════════
        if layout is not None:
            camion.metadata['layout_info'] = {
                'altura_validada': True,
                'errores_validacion': [],
                'altura_maxima_cm': altura_maxima,
                'altura_maxima_usada_cm': round(layout.altura_maxima_usada, 1),
                'altura_promedio_usada': round(layout.altura_promedio_usada, 1),
                'posiciones_usadas': layout.posiciones_usadas,
                'posiciones_disponibles': cap_rampla.max_positions,
                'total_pallets_fisicos': layout.total_pallets,
                'aprovechamiento_altura': round(layout.aprovechamiento_altura * 100, 1),
                'aprovechamiento_posiciones': round((layout.posiciones_usadas / cap_rampla.max_positions) * 100, 1),
                'validado_para_tipo': 'rampla_directa',
                'posiciones': self._serializar_posiciones(layout)
            }
            camion.pos_total = layout.posiciones_usadas
        
        return True

    def _aplicar_reclasificacion(
        self,
        camion: Camion,
        nuevo_tipo: TipoCamion,
        nueva_capacidad: TruckCapacity
    ):
        """
        Aplica la reclasificación a un camión.
        
        Modifica el camión in-place.
        """
        # Cambiar tipo y capacidad
        camion.cambiar_tipo(nuevo_tipo, nueva_capacidad)
        
        # Actualizar en todos los pedidos
        for pedido in camion.pedidos:
            pedido.tipo_camion = nuevo_tipo.value


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
                                'es_picking': frag.es_picking
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

# Función de conveniencia
def reclasificar_nestle_post_validacion(
    camiones: List[Camion],
    client_config,
    venta: str = None
) -> None:
    """
    Función de conveniencia que mantiene la firma original.
    
    Modifica camiones in-place.
    
    Args:
        camiones: Lista de camiones a reclasificar
        client_config: Configuración del cliente
    """
    reclassifier = NestleReclassifier(client_config, venta)
    reclassifier.reclasificar_camiones(camiones)