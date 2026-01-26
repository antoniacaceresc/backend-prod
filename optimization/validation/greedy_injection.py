# optimization/validation/greedy_injection.py
"""
Inyección greedy de pedidos sobrantes a camiones existentes.
VERSIÓN 2: Con diagnóstico detallado de fallos.
"""

from __future__ import annotations

from typing import List, Dict, Set, Tuple, Optional
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

from models.domain import Camion, Pedido, TruckCapacity
from optimization.validation.height_validator import HeightValidator
from optimization.utils.helpers import calcular_posiciones_apilabilidad


# Flag para debug
DEBUG_INJECTION = False  # Activado para diagnóstico

# Workers para procesamiento paralelo
INJECTION_WORKERS = 4


class GreedyInjectionResult:
    """Resultado del proceso de inyección greedy."""
    
    def __init__(
        self,
        camiones_actualizados: List[Camion],
        pedidos_inyectados: List[Pedido],
        pedidos_no_inyectados: List[Pedido],
        estadisticas: Dict
    ):
        self.camiones_actualizados = camiones_actualizados
        self.pedidos_inyectados = pedidos_inyectados
        self.pedidos_no_inyectados = pedidos_no_inyectados
        self.estadisticas = estadisticas
    
    @property
    def total_inyectados(self) -> int:
        return len(self.pedidos_inyectados)
    
    @property
    def total_no_inyectados(self) -> int:
        return len(self.pedidos_no_inyectados)


class GreedyInjector:
    """
    Inyecta pedidos sobrantes en camiones existentes con espacio.
    """
    
    def __init__(
        self,
        client_config,
        effective_config: Dict = None,
        venta: str = None
    ):
        self.config = client_config
        self.effective_config = effective_config or {}
        self.venta = venta
        
        # Configuración de validación
        self.altura_maxima = self.effective_config.get('ALTURA_MAXIMA_CM', 270)
        self.permite_consolidacion = self.effective_config.get('PERMITE_CONSOLIDACION', False)
        self.max_skus_por_pallet = self.effective_config.get('MAX_SKUS_POR_PALLET', 1)
        self.max_altura_picking = self.effective_config.get('MAX_ALTURA_PICKING_APILADO_CM')
        
        # Crear validador de altura
        self.height_validator = HeightValidator(
            altura_maxima_cm=self.altura_maxima,
            permite_consolidacion=self.permite_consolidacion,
            max_skus_por_pallet=self.max_skus_por_pallet,
            max_altura_picking_apilado_cm=self.max_altura_picking
        )
    
    def inyectar(
        self,
        camiones: List[Camion],
        pedidos_sobrantes: List[Pedido]
    ) -> GreedyInjectionResult:
        """
        Ejecuta la inyección greedy.
        """
        if not camiones or not pedidos_sobrantes:
            return GreedyInjectionResult(
                camiones_actualizados=camiones,
                pedidos_inyectados=[],
                pedidos_no_inyectados=pedidos_sobrantes,
                estadisticas={'motivo': 'sin_datos_entrada'}
            )
        
        # Estadísticas detalladas
        stats = {
            'total_pedidos': len(pedidos_sobrantes),
            'total_camiones': len(camiones),
            'fallos': {
                'sin_camion_compatible': 0,
                'excede_peso': 0,
                'excede_volumen': 0,
                'excede_posiciones': 0,
                'fallo_reglas': 0,
                'fallo_altura': 0,
            },
            'detalle_fallos': []  # Para debugging
        }
        
        if DEBUG_INJECTION:
            print(f"\n{'='*60}")
            print(f"DIAGNÓSTICO INYECCIÓN GREEDY")
            print(f"{'='*60}")
            print(f"Pedidos a inyectar: {len(pedidos_sobrantes)}")
            print(f"Camiones disponibles: {len(camiones)}")
            
            # Mostrar capacidad disponible por camión
            print(f"\nCAPACIDAD DISPONIBLE POR CAMIÓN:")
            for cam in camiones:
                peso_usado = sum(p.peso for p in cam.pedidos)
                vol_usado = sum(p.volumen for p in cam.pedidos)
                holgura_peso = cam.capacidad.cap_weight - peso_usado
                holgura_vol = cam.capacidad.cap_volume - vol_usado
                holgura_pos = cam.capacidad.max_positions - cam.pos_total
                print(f"  {cam.id[:8]}... CD={cam.cd} CE={cam.ce}")
                print(f"    Peso: {holgura_peso:.0f}kg | Vol: {holgura_vol:.0f}m³ | Pos: {holgura_pos:.1f}")
        
        # Ordenar pedidos de mayor a menor
        pedidos_ordenados = sorted(
            pedidos_sobrantes,
            key=lambda p: (p.pallets, p.peso, p.volumen),
            reverse=True
        )
        
        pedidos_inyectados = []
        pedidos_no_inyectados = []
        
        for pedido in pedidos_ordenados:
            resultado = self._intentar_inyectar_pedido(pedido, camiones, stats)
            
            if resultado['exito']:
                pedidos_inyectados.append(pedido)
            else:
                pedidos_no_inyectados.append(pedido)
                if DEBUG_INJECTION:
                    print(f"\n  ✗ Pedido {pedido.pedido} (CD={pedido.cd}, CE={pedido.ce}, {pedido.pallets:.1f}p, {pedido.peso:.0f}kg)")
                    print(f"    Razón: {resultado['razon']}")
        
        if DEBUG_INJECTION:
            print(f"\n{'='*60}")
            print(f"RESUMEN FALLOS:")
            for motivo, cantidad in stats['fallos'].items():
                if cantidad > 0:
                    print(f"  {motivo}: {cantidad}")
            print(f"{'='*60}\n")
        
        return GreedyInjectionResult(
            camiones_actualizados=camiones,
            pedidos_inyectados=pedidos_inyectados,
            pedidos_no_inyectados=pedidos_no_inyectados,
            estadisticas=stats
        )
    
    def _intentar_inyectar_pedido(
        self,
        pedido: Pedido,
        camiones: List[Camion],
        stats: Dict
    ) -> Dict:
        """
        Intenta inyectar un pedido en algún camión.
        Retorna dict con 'exito' y 'razon'.
        """
        # 1. Buscar camiones compatibles por CD/CE
        camiones_compatibles = self._buscar_camiones_compatibles(pedido, camiones)
        
        if not camiones_compatibles:
            stats['fallos']['sin_camion_compatible'] += 1
            return {
                'exito': False,
                'razon': f"Sin camión compatible CD={pedido.cd}/CE={pedido.ce}. Camiones disponibles: {[(c.cd, c.ce) for c in camiones[:3]]}"
            }
        
        # 2. Ordenar por VCU (preferir más llenos)
        camiones_ordenados = sorted(
            camiones_compatibles,
            key=lambda c: c.vcu_max,
            reverse=True
        )
        
        # 3. Intentar en cada camión
        razones_fallo = []
        
        for cam in camiones_ordenados:
            # Verificar capacidad
            puede, motivo = self._verificar_capacidad_teorica(cam, pedido)
            
            if not puede:
                razones_fallo.append(f"{cam.id[:8]}: {motivo}")
                if motivo == 'peso':
                    stats['fallos']['excede_peso'] += 1
                elif motivo == 'volumen':
                    stats['fallos']['excede_volumen'] += 1
                elif motivo == 'posiciones':
                    stats['fallos']['excede_posiciones'] += 1
                continue
            
            # Verificar reglas del cliente
            if not self._verificar_reglas_cliente(cam, pedido):
                razones_fallo.append(f"{cam.id[:8]}: reglas_cliente")
                stats['fallos']['fallo_reglas'] += 1
                continue
            
            # Simular y validar altura
            if self._simular_y_validar_inyeccion(cam, pedido):
                # ¡Éxito! Confirmar inyección
                self._confirmar_inyeccion(cam, pedido)
                if DEBUG_INJECTION:
                    print(f"\n  ✓ Pedido {pedido.pedido} → Camión {cam.id[:8]}...")
                return {'exito': True, 'razon': None}
            else:
                razones_fallo.append(f"{cam.id[:8]}: fallo_altura")
                stats['fallos']['fallo_altura'] += 1
        
        # No se pudo inyectar en ningún camión
        return {
            'exito': False,
            'razon': f"Probó {len(camiones_compatibles)} camiones: {'; '.join(razones_fallo[:3])}"
        }
    
    def _buscar_camiones_compatibles(
        self,
        pedido: Pedido,
        camiones: List[Camion]
    ) -> List[Camion]:
        """
        Busca camiones donde el pedido podría ir según CD/CE.
        
        LÓGICA RELAJADA:
        - El CD del pedido debe estar en los CDs del camión
        - El CE del pedido debe estar en los CEs del camión
        """
        compatibles = []
        
        for cam in camiones:
            # Normalizar a listas
            cam_cds = cam.cd if isinstance(cam.cd, list) else [cam.cd]
            cam_ces = cam.ce if isinstance(cam.ce, list) else [cam.ce]
            
            # El pedido es compatible si su CD/CE están en los del camión
            cd_compatible = pedido.cd in cam_cds
            ce_compatible = pedido.ce in cam_ces
            
            if cd_compatible and ce_compatible:
                compatibles.append(cam)
        
        return compatibles
    
    def _verificar_capacidad_teorica(
        self,
        camion: Camion,
        pedido: Pedido
    ) -> Tuple[bool, Optional[str]]:
        """
        Verifica si el pedido cabe teóricamente en el camión.
        """
        cap = camion.capacidad
        
        # Calcular uso actual
        peso_actual = sum(p.peso for p in camion.pedidos)
        vol_actual = sum(p.volumen for p in camion.pedidos)
        
        # Holguras
        holgura_peso = cap.cap_weight - peso_actual
        holgura_vol = cap.cap_volume - vol_actual
        holgura_pos = cap.max_positions - camion.pos_total
        
        # Check peso
        if pedido.peso > holgura_peso:
            return False, 'peso'
        
        # Check volumen
        if pedido.volumen > holgura_vol:
            return False, 'volumen'
        
        # Check posiciones (estimación)
        posiciones_pedido = self._estimar_posiciones_pedido(pedido)
        if posiciones_pedido > holgura_pos + 0.5:  # Pequeña tolerancia
            return False, 'posiciones'
        
        return True, None
    
    def _estimar_posiciones_pedido(self, pedido: Pedido) -> float:
        """Estima posiciones que ocupará el pedido."""
        if hasattr(pedido, 'pos_total') and pedido.pos_total and pedido.pos_total > 0:
            return pedido.pos_total
        
        # Estimación basada en categorías de apilabilidad
        base = getattr(pedido, 'base', 0) or 0
        no_apilable = getattr(pedido, 'no_apilable', 0) or 0
        superior = getattr(pedido, 'superior', 0) or 0
        flexible = getattr(pedido, 'flexible', 0) or 0
        si_mismo = getattr(pedido, 'si_mismo', 0) or 0
        
        # BASE y NO_APILABLE ocupan 1 posición cada uno
        pos_fijas = base + no_apilable
        
        # Apilables pueden compartir posición
        apilables = superior + flexible + si_mismo
        pos_apilables = apilables / 2 if apilables > 0 else 0
        
        if pos_fijas == 0 and pos_apilables == 0:
            return pedido.pallets / 2
        
        return pos_fijas + pos_apilables
    
    def _verificar_reglas_cliente(
        self,
        camion: Camion,
        pedido: Pedido
    ) -> bool:
        """Verifica reglas de negocio del cliente."""
        effective = self.effective_config
        
        # Regla: No mezclar chocolates
        if effective.get('SEPARAR_CHOCOLATES', False):
            camion_tiene_choco = any(p.chocolates == 'SI' for p in camion.pedidos)
            pedido_es_choco = pedido.chocolates == 'SI'
            if camion.pedidos and (camion_tiene_choco != pedido_es_choco):
                return False
        
        # Regla: Restricción de PO
        if effective.get('RESTRICT_PO_GROUP', False):
            po_pedido = pedido.metadata.get('po_group', pedido.po)
            for p in camion.pedidos:
                po_existente = p.metadata.get('po_group', p.po)
                if po_pedido == po_existente and pedido.pedido != p.pedido:
                    if pedido.metadata.get('is_from_split') and p.metadata.get('is_from_split'):
                        return False
        
        # Regla: Picking duplicado (SMU)
        if effective.get('PROHIBIR_PICKING_DUPLICADO', False):
            if pedido.tiene_skus:
                skus_picking_pedido = set()
                for sku in pedido.skus:
                    if sku.cantidad_pallets % 1 > 0.001:
                        skus_picking_pedido.add(sku.sku_id)
                
                for p in camion.pedidos:
                    if p.tiene_skus:
                        for sku in p.skus:
                            if sku.cantidad_pallets % 1 > 0.001:
                                if sku.sku_id in skus_picking_pedido:
                                    return False
        
        return True
    
    def _simular_y_validar_inyeccion(
        self,
        camion: Camion,
        pedido: Pedido
    ) -> bool:
        """
        Simula la inyección y valida altura.
        """
        # Crear camión temporal
        camion_temp = Camion(
            id=f"{camion.id}_sim",
            tipo_ruta=camion.tipo_ruta,
            tipo_camion=camion.tipo_camion,
            cd=camion.cd,
            ce=camion.ce,
            grupo=camion.grupo,
            capacidad=camion.capacidad
        )
        
        # Agregar todos los pedidos
        try:
            for p in camion.pedidos:
                camion_temp.pedidos.append(p)
            camion_temp.pedidos.append(pedido)
            camion_temp._invalidar_cache()
        except Exception:
            return False
        
        # Validar altura
        es_valido, errores, layout, debug_info = self.height_validator.validar_camion_rapido(
            camion_temp
        )
        
        return es_valido
    
    def _confirmar_inyeccion(
        self,
        camion: Camion,
        pedido: Pedido
    ) -> None:
        """
        Confirma la inyección del pedido en el camión.
        """
        camion.pedidos.append(pedido)
        camion._invalidar_cache()
        
        # Recalcular posiciones
        camion.pos_total = calcular_posiciones_apilabilidad(
            camion.pedidos,
            camion.capacidad.max_positions
        )
        
        # Actualizar metadata del pedido
        pedido.tipo_camion = camion.tipo_camion.value if hasattr(camion.tipo_camion, 'value') else str(camion.tipo_camion)
        
        # Re-validar y actualizar layout_info
        es_valido, errores, layout, debug_info = self.height_validator.validar_camion_rapido(camion)
        
        camion.metadata['layout_info'] = {
            'altura_validada': es_valido,
            'errores_validacion': errores,
            'fragmentos_colocados': debug_info.get('fragmentos_colocados', 0),
            'fragmentos_totales': debug_info.get('fragmentos_totales', 0),
            'inyeccion_greedy': True
        }


def inyectar_pedidos_greedy(
    camiones: List[Camion],
    pedidos_sobrantes: List[Pedido],
    client_config,
    effective_config: Dict = None,
    venta: str = None
) -> GreedyInjectionResult:
    """
    Función de conveniencia para ejecutar inyección greedy.
    """
    injector = GreedyInjector(client_config, effective_config, venta)
    return injector.inyectar(camiones, pedidos_sobrantes)