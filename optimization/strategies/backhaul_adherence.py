# optimization/strategies/backhaul_adherence.py
"""
Gestión de adherencia a camiones backhaul.

Convierte camiones Nestlé a Backhaul para cumplir con un porcentaje
mínimo de adherencia configurado.

Extraído de orchestrator.py para mejor modularidad.
"""

from __future__ import annotations

from typing import List, Optional, Dict, Any

from models.domain import Camion, TruckCapacity
from models.enums import TipoCamion
from optimization.validation.height_validator import HeightValidator


# Flag para activar/desactivar prints de debug
DEBUG_VALIDATION = False


class BackhaulAdherenceResult:
    """Resultado de aplicar adherencia backhaul."""
    
    def __init__(
        self,
        camiones: List[Camion],
        convertidos: int,
        target: int,
        deficit_inicial: int
    ):
        self.camiones = camiones
        self.convertidos = convertidos
        self.target = target
        self.deficit_inicial = deficit_inicial
    
    @property
    def cumple_adherencia(self) -> bool:
        """Indica si se alcanzó el target de adherencia."""
        return self.convertidos >= self.deficit_inicial


class BackhaulAdherenceManager:
    """
    Gestiona la conversión de camiones Nestlé a Backhaul para cumplir adherencia.
    
    Estrategia:
    1. Calcular déficit de BH según target de adherencia
    2. Ordenar camiones Nestlé por VCU (menor primero = candidatos a convertir)
    3. Convertir los de menor VCU a BH si su ruta lo permite
    4. Re-validar los convertidos (BH tiene altura menor)
    """
    
    def __init__(self, client_config, venta: str = None):
        """
        Args:
            client_config: Configuración del cliente
        """
        self.config = client_config
        self.venta = venta
        # Se inicializarán en aplicar_adherencia con effective_config
        self.permite_consolidacion = False
        self.max_skus_por_pallet = 1
    
    def aplicar_adherencia(
        self,
        camiones: List[Camion],
        adherencia_target: float,
        effective_config: dict = None
    ) -> BackhaulAdherenceResult:
        """
        Aplica adherencia backhaul convirtiendo camiones Nestlé.
        
        Args:
            camiones: Lista de camiones
            adherencia_target: Porcentaje de adherencia (0.0 a 1.0)
        
        Returns:
            BackhaulAdherenceResult con camiones modificados y estadísticas
        """
        # Actualizar configuración si se proporciona
        if effective_config:
            self.permite_consolidacion = effective_config.get('PERMITE_CONSOLIDACION', False)
            self.max_skus_por_pallet = effective_config.get('MAX_SKUS_POR_PALLET', 1)

        from utils.config_helpers import get_capacity_for_type
        
        n_total = len(camiones)
        if n_total == 0:
            return BackhaulAdherenceResult(camiones, 0, 0, 0)
        
        # Contar camiones actuales por tipo
        camiones_bh = [c for c in camiones if c.tipo_camion == TipoCamion.BACKHAUL]
        camiones_nestle = [c for c in camiones if c.tipo_camion != TipoCamion.BACKHAUL]
        
        n_bh_actual = len(camiones_bh)
        n_bh_requerido = int(n_total * adherencia_target)
        deficit = n_bh_requerido - n_bh_actual
        
        if DEBUG_VALIDATION:
            print(f"\n[ADHERENCIA BH] Total: {n_total}, BH actual: {n_bh_actual}, "
                  f"Requerido: {n_bh_requerido}, Déficit: {deficit}")
        
        if deficit <= 0:
            return BackhaulAdherenceResult(camiones, 0, n_bh_requerido, 0)
        
        # Ordenar Nestlé por VCU (menor primero = candidatos a convertir)
        camiones_nestle_ordenados = sorted(camiones_nestle, key=lambda c: c.vcu_max)
        
        # Obtener capacidad BH
        cap_backhaul = get_capacity_for_type(self.config, TipoCamion.BACKHAUL, self.venta)
        
        convertidos = 0
        
        for cam in camiones_nestle_ordenados:
            if convertidos >= deficit:
                break
            
            # Verificar si la ruta permite BH
            if not self._ruta_permite_backhaul(cam):
                continue
            
            # Verificar si cabe en capacidad BH
            if not self._cabe_en_backhaul(cam, cap_backhaul):
                continue
            
            # Intentar conversión
            if self._convertir_a_backhaul(cam, cap_backhaul):
                convertidos += 1
        
        # Resumen
        if DEBUG_VALIDATION:
            n_bh_final = len([c for c in camiones if c.tipo_camion == TipoCamion.BACKHAUL])
            print(f"[ADHERENCIA BH] Convertidos: {convertidos}, BH final: {n_bh_final}")
        
        return BackhaulAdherenceResult(
            camiones=camiones,
            convertidos=convertidos,
            target=n_bh_requerido,
            deficit_inicial=deficit
        )
    
    def _ruta_permite_backhaul(self, cam: Camion) -> bool:
        """Verifica si la ruta del camión permite backhaul."""
        from utils.config_helpers import get_camiones_permitidos_para_ruta
        
        cam_cd = [cam.cd] if isinstance(cam.cd, str) else cam.cd
        cam_ce = [cam.ce] if isinstance(cam.ce, str) else cam.ce
        tipo_ruta_str = cam.tipo_ruta.value if hasattr(cam.tipo_ruta, 'value') else str(cam.tipo_ruta)
        
        camiones_permitidos = get_camiones_permitidos_para_ruta(
            self.config, cam_cd, cam_ce, tipo_ruta_str, self.venta
        )
        
        return TipoCamion.BACKHAUL in camiones_permitidos
    
    def _cabe_en_backhaul(self, cam: Camion, cap_backhaul: TruckCapacity) -> bool:
        """Verifica si el camión cabe en capacidad backhaul."""
        peso_camion = sum(p.peso for p in cam.pedidos)
        volumen_camion = sum(p.volumen for p in cam.pedidos)
        
        return (
            peso_camion <= cap_backhaul.cap_weight and
            volumen_camion <= cap_backhaul.cap_volume
        )
    
    def _convertir_a_backhaul(self, cam: Camion, cap_backhaul: TruckCapacity) -> bool:
        """
        Intenta convertir un camión a backhaul.
        
        Incluye re-validación de altura.
        
        Args:
            cam: Camión a convertir
            cap_backhaul: Capacidad de backhaul
        
        Returns:
            True si la conversión fue exitosa
        """
        # Guardar tipo original por si hay que revertir
        tipo_original = cam.tipo_camion
        capacidad_original = cam.capacidad
        
        # Convertir a BH
        cam.tipo_camion = TipoCamion.BACKHAUL
        cam.capacidad = cap_backhaul
        cam._invalidar_cache()
        
        for p in cam.pedidos:
            p.tipo_camion = "backhaul"
        
        # Re-validar altura (BH tiene altura menor)
        validator = HeightValidator(
            altura_maxima_cm=cap_backhaul.altura_cm,
            permite_consolidacion=self.permite_consolidacion,
            max_skus_por_pallet=self.max_skus_por_pallet
        )
        
        es_valido, errores, layout, debug_info = validator.validar_camion_rapido(cam)
        
        if es_valido:
            # Actualizar layout_info
            self._actualizar_layout_info(cam, layout, debug_info)
            return True
        else:
            # Revertir conversión
            cam.tipo_camion = tipo_original
            cam.capacidad = capacidad_original
            cam._invalidar_cache()
            
            for p in cam.pedidos:
                p.tipo_camion = tipo_original.value
            
            return False
    
    def _actualizar_layout_info(
        self,
        cam: Camion,
        layout,
        debug_info: Optional[Dict]
    ):
        """Actualiza layout_info después de conversión exitosa."""
        if layout is None:
            return
        
        cam.metadata['layout_info'] = {
            'altura_validada': True,
            'errores_validacion': [],
            'fragmentos_fallidos': [],
            'posiciones_usadas': layout.posiciones_usadas,
            'altura_maxima_cm': layout.altura_maxima_cm,
            'posiciones': self._serializar_posiciones(layout)
        }
    
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
def aplicar_adherencia_backhaul(
    camiones: List[Camion],
    client_config,
    adherencia_target: float,
    effective_config: dict = None,
    venta: str = None
) -> List[Camion]:
    """
    Función de conveniencia que mantiene la firma original.
    
    Args:
        camiones: Lista de camiones
        client_config: Configuración del cliente
        adherencia_target: Porcentaje de adherencia (0.0 a 1.0)
    
    Returns:
        Lista de camiones (modificados in-place)
    """
    manager = BackhaulAdherenceManager(client_config, venta)
    result = manager.aplicar_adherencia(camiones, adherencia_target, effective_config)
    return result.camiones