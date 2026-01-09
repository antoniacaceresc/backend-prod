# optimization/validation/truck_validator.py
"""
Validación de altura de camiones en paralelo.
Extraído de orchestrator.py para mejor modularidad.
"""

from __future__ import annotations

import time
import threading
from typing import List, Tuple, Optional, Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed

from models.domain import Camion, TruckCapacity
from optimization.validation.height_validator import HeightValidator
from utils.config_helpers import get_consolidacion_config


# Flag para activar/desactivar prints de debug
DEBUG_VALIDATION = False


class TruckValidationResult:
    """Resultado de validación de un camión."""
    
    def __init__(
        self,
        camion_id: str,
        es_valido: bool,
        tiempo_ms: float,
        error_msg: Optional[str] = None
    ):
        self.camion_id = camion_id
        self.es_valido = es_valido
        self.tiempo_ms = tiempo_ms
        self.error_msg = error_msg


class TruckValidator:
    """
    Validador de altura de camiones con soporte para ejecución paralela.
    
    Responsabilidades:
    - Filtrar camiones que necesitan validación (tienen SKUs)
    - Ejecutar validación en paralelo con ThreadPoolExecutor
    - Actualizar metadata de camiones con resultados
    """
    
    def __init__(
        self,
        client_config,
        max_workers: int = 8
    ):
        """
        Args:
            client_config: Configuración del cliente
            max_workers: Máximo de threads paralelos
        """
        self.config = client_config
        self.max_workers = max_workers

        # Se inicializarán con effective_config en validar_camiones
        self.permite_consolidacion = False
        self.max_skus_por_pallet = 1
        self.venta = None
    
    def validar_camiones(
        self,
        camiones: List[Camion],
        operacion: str = "validacion",
        effective_config: dict = None,
        venta: str = None
    ) -> List[Camion]:
        """
        Valida altura de múltiples camiones EN PARALELO.
        
        Args:
            camiones: Lista de camiones a validar
            operacion: Nombre de la operación (para logging)
        
        Returns:
            Lista de camiones con metadata actualizada
        """
        if effective_config:
            self.permite_consolidacion = effective_config.get('PERMITE_CONSOLIDACION', False)
            self.max_skus_por_pallet = effective_config.get('MAX_SKUS_POR_PALLET', 1)
            self.venta = venta

        # Filtrar camiones que tienen pedidos con SKUs
        camiones_a_validar = [
            cam for cam in camiones
            if cam.pedidos and any(p.tiene_skus for p in cam.pedidos)
        ]
        
        if not camiones_a_validar:
            if DEBUG_VALIDATION:
                print(f"[{operacion.upper()}] No hay camiones con SKUs para validar")
            return camiones
        
        if DEBUG_VALIDATION:
            print(f"\n{'='*80}")
            print(f"VALIDACIÓN DE ALTURA PARALELA - {operacion.upper()}")
            print(f"{'='*80}")
            print(f"Total camiones a validar: {len(camiones_a_validar)}")
        
        # Determinar número de threads
        n_workers = min(self.max_workers, len(camiones_a_validar))
        if DEBUG_VALIDATION:
            print(f"Threads paralelos: {n_workers}")
            print(f"{'='*80}\n")
        
        # Lock para prints ordenados
        print_lock = threading.Lock()
        
        # Ejecutar validación en paralelo
        with ThreadPoolExecutor(max_workers=n_workers) as executor:
            futures = {
                executor.submit(
                    self._validar_camion_worker, 
                    cam, 
                    idx,
                    print_lock
                ): cam
                for idx, cam in enumerate(camiones_a_validar)
            }
            
            resultados = []
            for future in as_completed(futures):
                try:
                    resultado = future.result()
                    resultados.append(resultado)
                except Exception as e:
                    cam = futures[future]
                    if DEBUG_VALIDATION:
                        print(f"[VALIDACIÓN] ❌ Error en camión {cam.id}: {e}")
        
        if DEBUG_VALIDATION:
            validos = sum(1 for r in resultados if r.es_valido)
            print(f"\n[{operacion.upper()}] Resumen: {validos}/{len(resultados)} camiones válidos")
        
        return camiones
    
    def _validar_camion_worker(
        self,
        cam: Camion,
        cam_idx: int,
        print_lock: threading.Lock
    ) -> TruckValidationResult:
        """
        Worker que valida un camión individual.
        
        Args:
            cam: Camión a validar
            cam_idx: Índice del camión (para logging)
            print_lock: Lock para prints ordenados
        
        Returns:
            TruckValidationResult con el resultado
        """
        start = time.time()
        error_msg = None
        
        try:
            # Obtener altura máxima según configuración
            altura_maxima = self._get_altura_maxima(cam)

            # Obtener consolidación específica para este camión (SMU)
            consolidacion = self._get_consolidacion_camion(cam)
            
            # Crear validador
            validator = HeightValidator(
                altura_maxima_cm=altura_maxima,
                permite_consolidacion=consolidacion["PERMITE_CONSOLIDACION"],
                max_skus_por_pallet=consolidacion["MAX_SKUS_POR_PALLET"],
                max_altura_picking_apilado_cm=consolidacion.get("ALTURA_MAX_PICKING_APILADO_CM")
            )
            
            # Ejecutar validación
            es_valido, errores, layout, debug_info = validator.validar_camion_rapido(cam)
            
            # Normalizar errores
            errores_limpios = self._normalizar_errores(errores)
            error_msg = "; ".join(errores_limpios) if errores_limpios else None
            
            elapsed_ms = (time.time() - start) * 1000
            
            # Construir y guardar layout_info
            layout_info = self._construir_layout_info(
                es_valido, errores_limpios, layout, debug_info, cam
            )
            
            # Actualizar metadata del camión
            cam.metadata['layout_info'] = layout_info
            
            # Actualizar pos_total si hay layout válido
            if layout is not None:
                cam.pos_total = layout.posiciones_usadas
            
            return TruckValidationResult(
                camion_id=cam.id,
                es_valido=es_valido,
                tiempo_ms=elapsed_ms,
                error_msg=error_msg
            )
        
        except Exception as e:
            elapsed_ms = (time.time() - start) * 1000
            error_msg = str(e)
            
            import traceback
            if DEBUG_VALIDATION:
                with print_lock:
                    print(f"[VALIDACIÓN] ❌ Excepción en camión {cam.id}:")
                    traceback.print_exc()
            
            # Guardar error en metadata
            cam.metadata['layout_info'] = {
                'altura_validada': False,
                'errores_validacion': [f"Error en validación: {str(e)}"],
                'error_tipo': type(e).__name__,
                'error_detalle': str(e),
            }
            
            return TruckValidationResult(
                camion_id=cam.id,
                es_valido=False,
                tiempo_ms=elapsed_ms,
                error_msg=error_msg
            )
    
    def _get_altura_maxima(self, cam: Camion) -> float:
        """
        Obtiene la altura máxima para un camión según configuración.
        
        Soporta configuraciones especiales como SMU/Alvi.
        """
        altura_default = cam.capacidad.altura_cm
        
        # Soporte para configuración especial (ej: SMU con Alvi)
        if hasattr(self.config, 'get_altura_maxima'):
            subcliente = ""
            if cam.pedidos:
                subcliente = cam.pedidos[0].metadata.get("SUBCLIENTE", "")
            return self.config.get_altura_maxima(subcliente, altura_default)
        
        return altura_default

    def _get_consolidacion_camion(self, cam: Camion) -> dict:
        """
        Obtiene configuración de consolidación específica para un camión.
        Para SMU, depende del subcliente (Alvi/Rendic) y flujo (INV/CRR).
        
        Returns:
            Dict con PERMITE_CONSOLIDACION y MAX_SKUS_POR_PALLET
        """
        # Default: usar configuración de clase
        default = {
            "PERMITE_CONSOLIDACION": self.permite_consolidacion,
            "MAX_SKUS_POR_PALLET": self.max_skus_por_pallet
        }
        
        if not cam.pedidos:
            return default
        
        # Obtener subcliente y OC del primer pedido (asumimos homogéneo por camión)
        primer_pedido = cam.pedidos[0]
        subcliente = primer_pedido.metadata.get("SUBCLIENTE") if primer_pedido.metadata else None
        oc = primer_pedido.oc
        
        # Si no hay subcliente, usar default
        if not subcliente:
            return default
        
        # Obtener venta del camión
        venta = self.venta or (cam.metadata.get("venta") if cam.metadata else None)
        
        # Usar helper de config_helpers
        return get_consolidacion_config(
            self.config, 
            subcliente=subcliente, 
            oc=oc, 
            venta=venta
        )

    
    def _normalizar_errores(self, errores: Any) -> List[str]:
        """Normaliza lista de errores a strings limpios."""
        if errores is None:
            return []
        
        if not isinstance(errores, (list, tuple)):
            return [str(errores)]
        
        errores_limpios = []
        for e in errores:
            if e is not None and e is not Ellipsis and e != "":
                try:
                    errores_limpios.append(str(e))
                except Exception:
                    pass
        
        return errores_limpios
    
    def _construir_layout_info(
        self,
        es_valido: bool,
        errores: List[str],
        layout,
        debug_info: Optional[Dict],
        cam: Camion
    ) -> Dict[str, Any]:
        """
        Construye el diccionario layout_info para metadata del camión.
        """
        layout_info = {
            'altura_validada': bool(es_valido),
            'errores_validacion': errores,
            'fragmentos_fallidos': debug_info.get('fragmentos_fallidos', []) if debug_info else [],
            'fragmentos_totales': debug_info.get('fragmentos_totales', 0) if debug_info else 0,
        }
        
        if layout is not None:
            layout_info.update({
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
        else:
            # Si no hay layout válido pero pasó validación
            if es_valido:
                layout_info['posiciones_usadas'] = 0
            else:
                # Layout inválido - mantener estimación anterior
                layout_info['posiciones_usadas'] = cam.pos_total
        
        return layout_info
    
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

        

# Función de conveniencia para uso directo (mantiene compatibilidad)
def validar_altura_camiones_paralelo(
    camiones: List[Camion],
    client_config,
    operacion: str = "validacion",
    effective_config: dict = None,
    venta: str = None
) -> List[Camion]:
    """
    Función de conveniencia que mantiene la firma original.
    
    Args:
        camiones: Lista de camiones a validar
        client_config: Configuración del cliente
        operacion: Nombre de la operación
    
    Returns:
        Lista de camiones con metadata actualizada
    """
    validator = TruckValidator(client_config)
    return validator.validar_camiones(camiones, operacion, effective_config, venta)