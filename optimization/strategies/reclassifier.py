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


# Flag para activar/desactivar prints de debug
DEBUG_VALIDATION = False


class NestleReclassifier:
    """
    Reclasifica camiones Nestlé después de validación de altura.
    
    Lógica:
    - Se optimiza inicialmente con PAQUETERA (más posiciones, 270cm altura)
    - Después de validar altura, si el layout real cabe en RAMPLA_DIRECTA (220cm),
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
        """
        altura_maxima_usada = layout_info.get('altura_maxima_usada_cm', 0)
        posiciones_usadas = layout_info.get('posiciones_usadas', len(camion.pedidos))
        
        # Verificar dimensiones básicas
        peso_total = sum(p.peso for p in camion.pedidos)
        volumen_total = sum(p.volumen for p in camion.pedidos)
        pallets_total = camion.pallets_capacidad
        
        # Verificación completa: altura real + dimensiones + posiciones
        cabe_en_rampla = (
            altura_maxima_usada <= cap_rampla.altura_cm and  # Lo más importante
            posiciones_usadas <= cap_rampla.max_positions and
            peso_total <= cap_rampla.cap_weight and
            volumen_total <= cap_rampla.cap_volume and
            pallets_total <= cap_rampla.max_pallets
        )
        
        if cabe_en_rampla:
            # Verificar que cumple VCU target
            vcu_peso_rampla = peso_total / cap_rampla.cap_weight if cap_rampla.cap_weight > 0 else 0
            vcu_vol_rampla = volumen_total / cap_rampla.cap_volume if cap_rampla.cap_volume > 0 else 0
            vcu_max_rampla = max(vcu_peso_rampla, vcu_vol_rampla)
            
            if vcu_max_rampla >= cap_rampla.vcu_min:
                return TipoCamion.RAMPLA_DIRECTA
        
        return TipoCamion.PAQUETERA
    
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
        
        # Recalcular posiciones con nueva capacidad
        camion.pos_total = calcular_posiciones_apilabilidad(
            camion.pedidos,
            nueva_capacidad.max_positions
        )
        
        # Actualizar en todos los pedidos
        for pedido in camion.pedidos:
            pedido.tipo_camion = nuevo_tipo.value
        
        # Actualizar layout_info para reflejar nueva capacidad
        self._actualizar_layout_info(camion, nueva_capacidad)
    
    def _actualizar_layout_info(self, camion: Camion, nueva_capacidad: TruckCapacity):
        """Actualiza layout_info con la nueva capacidad."""
        if 'layout_info' not in camion.metadata:
            return
        
        layout_info = camion.metadata['layout_info']
        
        # Actualizar altura máxima del camión
        layout_info['altura_maxima_cm'] = nueva_capacidad.altura_cm
        
        # Recalcular aprovechamiento de altura con nueva referencia
        altura_usada = layout_info.get('altura_maxima_usada_cm', 0)
        if nueva_capacidad.altura_cm > 0:
            nuevo_aprovechamiento = (altura_usada / nueva_capacidad.altura_cm) * 100
            layout_info['aprovechamiento_altura'] = round(nuevo_aprovechamiento, 1)
        
        # Actualizar posiciones disponibles si cambiaron
        layout_info['posiciones_disponibles'] = nueva_capacidad.max_positions
        
        # Recalcular aprovechamiento de posiciones
        posiciones_usadas = layout_info.get('posiciones_usadas', 0)
        if nueva_capacidad.max_positions > 0:
            nuevo_aprov_pos = (posiciones_usadas / nueva_capacidad.max_positions) * 100
            layout_info['aprovechamiento_posiciones'] = round(nuevo_aprov_pos, 1)


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