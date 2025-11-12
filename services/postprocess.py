# services/postprocess.py
"""
Postprocesamiento de resultados de optimización.
Maneja operaciones de edición manual de camiones.

Estrategia:
1. Recibe dicts desde API
2. Convierte a objetos UNA VEZ al inicio
3. Ejecuta lógica de negocio con objetos
4. Convierte a dicts UNA VEZ al final
"""

from __future__ import annotations
from typing import List, Dict, Any, Optional, Tuple
import uuid
from collections import Counter

from models.domain import Pedido, Camion, TruckCapacity, TipoCamion, TipoRuta, SKU
from utils.config_helpers import extract_truck_capacities
from optimization.utils.helpers import calcular_posiciones_apilabilidad
from core.config import get_client_config
from optimization.validation.height_validator import HeightValidator


# ============================================================================
# CONFIGURACIÓN GLOBAL
# ============================================================================

# Flag para activar/desactivar prints de debug
DEBUG_VALIDATION = False  # Cambiar a True para ver prints detallados


# ============================================================================
# HELPERS DE CONVERSIÓN (llamados UNA VEZ por request)
# ============================================================================

def _rebuild_state(state: Dict[str, Any], cliente: str) -> Tuple[List[Camion], List[Pedido], Any, TruckCapacity]:
    """
    Reconstruye objetos desde dicts de forma eficiente.
    
    Returns:
        Tupla (camiones, pedidos_no_incluidos, config, capacidad_default)
    """
    config = get_client_config(cliente)
    capacidades = extract_truck_capacities(config)
    cap_default = capacidades[TipoCamion.NORMAL]
    
    # Conversión batch
    camiones = [_camion_from_dict(c, capacidades) for c in state.get("camiones", [])]
    pedidos_no_inc = [_pedido_from_dict(p) for p in state.get("pedidos_no_incluidos", [])]
    
    return camiones, pedidos_no_inc, config, cap_default


def _to_response(
    camiones: List[Camion], 
    pedidos_no_inc: List[Pedido], 
    cap_default: TruckCapacity
) -> Dict[str, Any]:
    """
    Convierte objetos a dicts y agrega estadísticas.
    ADEMÁS renumera camiones secuencialmente.
    
    Returns:
        Dict con formato API
    """
    # Renumerar camiones secuencialmente
    for idx, camion in enumerate(camiones, start=1):
        camion.numero = idx
        # También actualizar el número en cada pedido del camión
        for pedido in camion.pedidos:
            pedido.numero_camion = idx
    
    return {
        "camiones": [c.to_api_dict() for c in camiones],
        "pedidos_no_incluidos": [p.to_api_dict(cap_default) for p in pedidos_no_inc],
        "estadisticas": _compute_stats(camiones, pedidos_no_inc)
    }


def _camion_from_dict(cam_dict: Dict[str, Any], capacidades: Dict[TipoCamion, TruckCapacity]) -> Camion:
    """
    Reconstruye objeto Camion desde dict.
    
    Args:
        cam_dict: Diccionario con datos del camión
        capacidades: Dict con capacidades disponibles
    
    Returns:
        Objeto Camion reconstruido
    """
    # Convertir pedidos
    pedidos = [_pedido_from_dict(p) for p in cam_dict.get("pedidos", [])]
    
    # Determinar tipo de camión y capacidad
    try:
        tipo_camion = TipoCamion(cam_dict.get("tipo_camion", "normal"))
    except ValueError:
        tipo_camion = TipoCamion.NORMAL
    
    capacidad = capacidades.get(tipo_camion, capacidades[TipoCamion.NORMAL])
    
    # Determinar tipo de ruta
    try:
        tipo_ruta = TipoRuta(cam_dict.get("tipo_ruta", "normal"))
    except ValueError:
        tipo_ruta = TipoRuta.NORMAL
    
    return Camion(
        id=cam_dict["id"],
        numero=cam_dict.get("numero", 0),
        tipo_ruta=tipo_ruta,
        tipo_camion=tipo_camion,
        cd=cam_dict.get("cd", []),
        ce=cam_dict.get("ce", []),
        grupo=cam_dict.get("grupo", ""),
        capacidad=capacidad,
        pedidos=pedidos,
        metadata=cam_dict.get("metadata", {})
    )


def _pedido_from_dict(p_dict: Dict[str, Any]) -> Pedido:
    """
    Reconstruye objeto Pedido desde dict.
    
    Args:
        p_dict: Diccionario con datos del pedido
    
    Returns:
        Objeto Pedido reconstruido con SKUs si existen
    """
    # Reconstruir SKUs si existen
    skus = []
    if "SKUS" in p_dict and p_dict["SKUS"]:
        for sku_dict in p_dict["SKUS"]:
            sku = SKU(
                sku_id=sku_dict["sku_id"],
                pedido_id=sku_dict["pedido_id"],
                cantidad_pallets=float(sku_dict["cantidad_pallets"]),
                altura_full_pallet_cm=float(sku_dict["altura_full_pallet_cm"]),
                altura_picking_cm=float(sku_dict["altura_picking_cm"]) if sku_dict.get("altura_picking_cm") else None,
                peso_kg=float(sku_dict.get("peso_kg", 0)),
                volumen_m3=float(sku_dict.get("volumen_m3", 0)),
                valor=float(sku_dict.get("valor", 0)),
                base=float(sku_dict.get("base", 0)),
                superior=float(sku_dict.get("superior", 0)),
                flexible=float(sku_dict.get("flexible", 0)),
                no_apilable=float(sku_dict.get("no_apilable", 0)),
                si_mismo=float(sku_dict.get("si_mismo", 0)),
                max_altura_apilable_cm=float(sku_dict["max_altura_apilable_cm"]) if sku_dict.get("max_altura_apilable_cm") else None,
                descripcion=sku_dict.get("descripcion")
            )
            skus.append(sku)
    
    return Pedido(
        pedido=str(p_dict["PEDIDO"]),
        cd=str(p_dict["CD"]),
        ce=str(p_dict["CE"]),
        po=str(p_dict["PO"]),
        peso=float(p_dict["PESO"]),
        volumen=float(p_dict["VOL"]),
        pallets=float(p_dict["PALLETS"]),
        valor=float(p_dict["VALOR"]),
        valor_cafe=float(p_dict.get("VALOR_CAFE", 0)),
        pallets_real=float(p_dict["PALLETS_REAL"]) if p_dict.get("PALLETS_REAL") else None,
        oc=p_dict.get("OC"),
        chocolates=str(p_dict.get("CHOCOLATES", "NO")),
        valioso=bool(p_dict.get("VALIOSO", 0)),
        pdq=bool(p_dict.get("PDQ", 0)),
        baja_vu=bool(p_dict.get("BAJA_VU", 0)),
        lote_dir=bool(p_dict.get("LOTE_DIR", 0)),
        base=float(p_dict.get("BASE", 0)),
        superior=float(p_dict.get("SUPERIOR", 0)),
        flexible=float(p_dict.get("FLEXIBLE", 0)),
        no_apilable=float(p_dict.get("NO_APILABLE", 0)),
        si_mismo=float(p_dict.get("SI_MISMO", 0)),
        skus=skus,
        metadata={}
    )


# ============================================================================
# API PÚBLICA (mantiene firmas originales para compatibilidad)
# ============================================================================

def move_orders(
    state: Dict[str, Any], 
    pedidos: Optional[List[Dict[str, Any]]], 
    target_truck_id: Optional[str], 
    cliente: str
) -> Dict[str, Any]:
    """
    Mueve pedidos entre camiones o a pedidos no incluidos.
    
    Args:
        state: Estado actual (camiones y pedidos_no_incluidos)
        pedidos: Lista de pedidos a mover
        target_truck_id: ID del camión destino (None = mover a no incluidos)
        cliente: Nombre del cliente
    
    Returns:
        Estado actualizado con estadísticas
    
    Raises:
        ValueError: Si la operación no es válida
    """
    # 1) Reconstruir estado
    camiones, pedidos_no_inc, config, cap_default = _rebuild_state(state, cliente)
    pedidos_obj = [_pedido_from_dict(p) for p in (pedidos or [])]
    
    if not pedidos_obj:
        return _to_response(camiones, pedidos_no_inc, cap_default)
    
    # 2) Ejecutar lógica de negocio
    pedidos_ids = {p.pedido for p in pedidos_obj}
    
    # Remover pedidos de sus camiones actuales
    for cam in camiones:
        cam.pedidos = [p for p in cam.pedidos if p.pedido not in pedidos_ids]
    
    # Remover de pedidos no incluidos
    pedidos_no_inc = [p for p in pedidos_no_inc if p.pedido not in pedidos_ids]
    
    # Asignar al destino
    if target_truck_id:
        cam_dest = next((c for c in camiones if c.id == target_truck_id), None)
        if not cam_dest:
            raise ValueError("Camión destino no encontrado")
        
        # Agregar pedidos (valida automáticamente capacidad básica)
        try:
            cam_dest.agregar_pedidos(pedidos_obj)
        except ValueError as e:
            raise ValueError(f"No se pueden agregar pedidos: {e}")
        
        # Validaciones adicionales del cliente
        _validar_reglas_cliente(cam_dest, config, cliente)
        
        # Recalcular posiciones de apilabilidad
        cam_dest.pos_total = calcular_posiciones_apilabilidad(
            cam_dest.pedidos,
            cam_dest.capacidad.max_positions
        )

        # Actualizar metadata derivada
        _actualizar_opciones_tipo_camion(cam_dest, config)
    else:
        # Mover a no incluidos
        pedidos_no_inc.extend(pedidos_obj)
    
    # 3) Revalidar altura de todos los camiones afectados
    _revalidar_altura_camiones(camiones, config, cliente, operacion="move_orders")
    
    # 4) Devolver respuesta
    return _to_response(camiones, pedidos_no_inc, cap_default)


def add_truck(
    state: Dict[str, Any], 
    cd: List[str], 
    ce: List[str], 
    ruta: str, 
    cliente: str
) -> Dict[str, Any]:
    """
    Crea un camión vacío.
    
    Args:
        state: Estado actual
        cd: Lista de CDs del camión
        ce: Lista de CEs del camión
        ruta: Tipo de ruta ("normal", "bh", "multi_cd", etc.)
        cliente: Nombre del cliente
    
    Returns:
        Estado actualizado con el nuevo camión
    """
    # 1) Reconstruir estado
    camiones, pedidos_no_inc, config, cap_default = _rebuild_state(state, cliente)
    
    # 2) Determinar tipo de ruta
    try:
        tipo_ruta = TipoRuta(ruta.lower())
    except ValueError:
        tipo_ruta = TipoRuta.NORMAL
    
    # 3) Crear camión nuevo
    nuevo_camion = Camion(
        id=uuid.uuid4().hex,
        tipo_ruta=tipo_ruta,
        tipo_camion=TipoCamion.NORMAL,
        cd=cd if isinstance(cd, list) else [cd],
        ce=ce if isinstance(ce, list) else [ce],
        grupo=f"manual__{'-'.join(cd)}__{'-'.join(map(str, ce))}",
        capacidad=cap_default,
        pedidos=[]
    )
    
    # Calcular opciones de cambio de tipo
    _actualizar_opciones_tipo_camion(nuevo_camion, config)
    
    camiones.append(nuevo_camion)
    
    # 4) Revalidar altura (principalmente para mantener consistencia)
    _revalidar_altura_camiones(camiones, config, cliente, operacion="add_truck")
    
    # 5) Devolver respuesta
    return _to_response(camiones, pedidos_no_inc, cap_default)


def delete_truck(
    state: Dict[str, Any], 
    truck_id: Optional[str], 
    cliente: str
) -> Dict[str, Any]:
    """
    Elimina un camión y mueve sus pedidos a no incluidos.
    
    Args:
        state: Estado actual
        truck_id: ID del camión a eliminar
        cliente: Nombre del cliente
    
    Returns:
        Estado actualizado sin el camión eliminado
    
    Raises:
        ValueError: Si el camión no existe
    """
    # 1) Reconstruir estado
    camiones, pedidos_no_inc, config, cap_default = _rebuild_state(state, cliente)
    
    if not truck_id:
        raise ValueError("ID de camión requerido")
    
    # 2) Buscar y eliminar camión
    cam_a_eliminar = next((c for c in camiones if c.id == truck_id), None)
    
    if not cam_a_eliminar:
        raise ValueError("Camión no encontrado")
    
    # Mover pedidos a no incluidos
    pedidos_no_inc.extend(cam_a_eliminar.pedidos)
    
    # Remover camión
    camiones = [c for c in camiones if c.id != truck_id]
    
    # 3) Revalidar altura de camiones restantes
    _revalidar_altura_camiones(camiones, config, cliente, operacion="delete_truck")
    
    # 4) Devolver respuesta
    return _to_response(camiones, pedidos_no_inc, cap_default)


def apply_truck_type_change(
    state: Dict[str, Any], 
    truck_id: str, 
    tipo_camion: str, 
    cliente: str
) -> Dict[str, Any]:
    """
    Cambia el tipo de camión (normal ↔ bh).
    
    Args:
        state: Estado actual
        truck_id: ID del camión a modificar
        tipo_camion: Nuevo tipo ("normal" o "bh")
        cliente: Nombre del cliente
    
    Returns:
        Estado actualizado con el tipo cambiado
    
    Raises:
        ValueError: Si el cambio no es válido
    """
    # 1) Reconstruir estado
    camiones, pedidos_no_inc, config, cap_default = _rebuild_state(state, cliente)
    capacidades = extract_truck_capacities(config)
    
    # 2) Buscar camión
    camion = next((c for c in camiones if c.id == truck_id), None)
    if not camion:
        raise ValueError("Camión no encontrado")
    
    # 3) Validar que el cambio sea permitido
    tipo_nuevo = tipo_camion.lower()
    if tipo_nuevo not in camion.opciones_tipo_camion:
        raise ValueError(
            f"Cambio a '{tipo_nuevo}' no permitido para este camión. "
            f"Opciones disponibles: {camion.opciones_tipo_camion}"
        )
    
    # 4) Determinar nueva capacidad
    try:
        nuevo_tipo_enum = TipoCamion(tipo_nuevo)
    except ValueError:
        raise ValueError(f"Tipo de camión inválido: '{tipo_nuevo}'")
    
    nueva_capacidad = capacidades.get(nuevo_tipo_enum, cap_default)
    
    # 5) Validar que cabe con la nueva capacidad
    if not camion.valida_capacidad(nueva_capacidad):
        # Calcular VCU actual con nueva capacidad para mensaje de error
        vol_total = sum(p.volumen for p in camion.pedidos)
        peso_total = sum(p.peso for p in camion.pedidos)
        vcu_vol = (vol_total / nueva_capacidad.cap_volume) * 100
        vcu_peso = (peso_total / nueva_capacidad.cap_weight) * 100
        
        raise ValueError(
            f"El camión excede las capacidades del tipo '{tipo_nuevo}'. "
            f"VCU Volumen: {vcu_vol:.1f}%, VCU Peso: {vcu_peso:.1f}%, "
            f"Pallets: {camion.pallets_conf:.1f}/{nueva_capacidad.max_pallets}. "
            f"Ninguna dimensión puede superar 100%."
        )
    
    # 6) Validar reglas específicas del cliente
    _validar_cambio_tipo_cliente(camion, nuevo_tipo_enum, config, cliente)
    
    # 7) Aplicar cambio
    camion.tipo_camion = nuevo_tipo_enum
    camion.capacidad = nueva_capacidad
    
    # Invalidar cache de métricas calculadas
    camion._invalidar_cache()
    
    # Recalcular posiciones con la nueva capacidad
    camion.pos_total = calcular_posiciones_apilabilidad(
        camion.pedidos,
        nueva_capacidad.max_positions
    )
    
    # Actualizar opciones disponibles (pueden cambiar después del cambio)
    _actualizar_opciones_tipo_camion(camion, config)
    
    # 8) Revalidar altura (CRÍTICO: nueva altura máxima)
    _revalidar_altura_camiones(camiones, config, cliente, operacion="change_truck_type")
    
    # 9) Devolver respuesta
    return _to_response(camiones, pedidos_no_inc, cap_default)


def compute_stats(
    camiones: Optional[List[Dict[str, Any]]], 
    pedidos_no_incluidos: Optional[List[Dict[str, Any]]], 
    cliente: str
) -> Dict[str, Any]:
    """
    Calcula estadísticas globales del estado actual.
    
    Args:
        camiones: Lista de camiones
        pedidos_no_incluidos: Lista de pedidos no asignados
        cliente: Nombre del cliente
    
    Returns:
        Dict con estadísticas
    """
    state = {
        "camiones": camiones or [],
        "pedidos_no_incluidos": pedidos_no_incluidos or []
    }
    
    # Reconstruir objetos para calcular estadísticas
    camiones_obj, pedidos_obj, config, cap_default = _rebuild_state(state, cliente)
    
    return _compute_stats(camiones_obj, pedidos_obj)


def enforce_bh_target(
    camiones: List[Dict[str, Any]],
    pedidos_no_incluidos: List[Dict[str, Any]],
    cliente: str,
    target_ratio: float,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Intenta alcanzar ratio objetivo de camiones BH convirtiendo camiones normales.
    
    Args:
        camiones: Lista de camiones (dicts)
        pedidos_no_incluidos: Pedidos no asignados (dicts)
        cliente: Nombre del cliente
        target_ratio: Ratio objetivo (ej: 0.6 = 60% BH)
    
    Returns:
        Tupla (camiones_actualizados, pedidos_no_incluidos_actualizados)
    """
    try:
        config = get_client_config(cliente)
    except Exception:
        return camiones, pedidos_no_incluidos
    
    if not camiones or not getattr(config, "PERMITE_BH", False):
        return camiones, pedidos_no_incluidos
    
    if not (isinstance(target_ratio, (int, float)) and target_ratio > 0):
        return camiones, pedidos_no_incluidos
    
    # Reconstruir objetos
    capacidades = extract_truck_capacities(config)
    cap_default = capacidades[TipoCamion.NORMAL]
    
    camiones_obj = [_camion_from_dict(c, capacidades) for c in camiones]
    pedidos_obj = [_pedido_from_dict(p) for p in pedidos_no_incluidos]
    
    # Calcular cuántos BH se necesitan
    total = len(camiones_obj)
    deseado = int(round(target_ratio * total))
    actuales_bh = sum(1 for c in camiones_obj if c.tipo_camion == TipoCamion.BH)
    faltan = max(0, deseado - actuales_bh)
    
    if faltan == 0:
        return camiones, pedidos_no_incluidos
    
    # Candidatos: camiones normales que PUEDEN cambiar a BH
    candidatos = []
    for c in camiones_obj:
        if c.tipo_camion == TipoCamion.BH:
            continue
        
        # Actualizar opciones para verificar si puede ser BH
        _actualizar_opciones_tipo_camion(c, config)
        
        if "bh" in c.opciones_tipo_camion:
            candidatos.append(c)
    
    if not candidatos:
        return camiones, pedidos_no_incluidos
    
    # Ordenar por VCU (menor primero = más seguro cambiar)
    candidatos.sort(key=lambda x: x.vcu_max)
    
    # Cambiar camiones
    capacidad_bh = capacidades.get(TipoCamion.BH, cap_default)
    
    for c in candidatos[:faltan]:
        try:
            if not c.valida_capacidad(capacidad_bh):
                continue
            
            c.tipo_camion = TipoCamion.BH
            c.capacidad = capacidad_bh
            c._invalidar_cache()
            c.pos_total = calcular_posiciones_apilabilidad(
                c.pedidos,
                capacidad_bh.max_positions
            )
            _actualizar_opciones_tipo_camion(c, config)
        except Exception:
            # Si falla, continuar con el siguiente
            continue
    
    # Revalidar altura de todos los camiones
    _revalidar_altura_camiones(camiones_obj, config, cliente, operacion="enforce_bh")
    
    # Convertir de vuelta a dicts
    return (
        [c.to_api_dict() for c in camiones_obj],
        [p.to_api_dict(cap_default) for p in pedidos_obj]
    )


# ============================================================================
# HELPERS DE VALIDACIÓN Y METADATA (con código centralizado)
# ============================================================================

def _revalidar_altura_camiones(
    camiones: List[Camion], 
    config, 
    cliente: str,
    operacion: str = "operacion"
) -> None:
    """
    Función centralizada para revalidar altura de múltiples camiones.
    
    Args:
        camiones: Lista de camiones a validar
        config: Configuración del cliente
        cliente: Nombre del cliente
        operacion: Nombre de la operación (para logging)
    """
    if DEBUG_VALIDATION:
        print(f"\n[{operacion.upper()}] Revalidando {len(camiones)} camiones...")
    
    for cam in camiones:
        if cam.pedidos:  # Solo validar si tiene pedidos
            if DEBUG_VALIDATION:
                print(f"[{operacion.upper()}] Validando camión {cam.id}: {len(cam.pedidos)} pedidos")
            _validar_altura_no_bloqueante(cam, config, cliente)
        else:
            if DEBUG_VALIDATION:
                print(f"[{operacion.upper()}] Saltando camión vacío: {cam.id}")


def _validar_reglas_cliente(camion: Camion, config, cliente: str):
    """
    Valida reglas específicas del cliente sobre el camión.
    Lanza ValueError si no cumple.
    
    Args:
        camion: Camión a validar
        config: Configuración del cliente
        cliente: Nombre del cliente
    
    Raises:
        ValueError: Si viola alguna regla
    """
    # Ejemplo: Walmart no permite mezclar chocolates con ciertos productos
    if cliente.lower() == "walmart":
        tiene_chocolates = any(p.chocolates == "SI" for p in camion.pedidos)
        tiene_valiosos = any(p.valioso for p in camion.pedidos)
        
        if tiene_chocolates and tiene_valiosos:
            raise ValueError("No se pueden mezclar chocolates con productos valiosos")
    
    # Agregar más validaciones específicas según cliente


def _validar_altura_no_bloqueante(camion: Camion, config, cliente: str) -> None:
    """
    Valida altura del camión y actualiza metadata, pero NO bloquea la operación.
    
    Esta función:
    1. Verifica si la validación de altura está habilitada para el cliente
    2. Ejecuta la validación si hay SKUs disponibles
    3. Almacena el resultado en camion.metadata para que el frontend lo muestre
    4. NUNCA lanza excepciones - es informativa, no bloqueante
    
    Args:
        camion: Camión a validar
        config: Configuración del cliente
        cliente: Nombre del cliente
    """
    if DEBUG_VALIDATION:
        print(f"\n[VALIDATION] Validando camión {camion.id}")
    
    # Verificar si está habilitada la validación para este cliente
    validar_altura = getattr(config, 'VALIDAR_ALTURA', False)
    
    if not validar_altura:
        if DEBUG_VALIDATION:
            print(f"[VALIDATION] Validación deshabilitada para {cliente}")
        # Limpiar metadata si existe
        if 'altura_validada' in camion.metadata:
            del camion.metadata['altura_validada']
        if 'layout_info' in camion.metadata:
            del camion.metadata['layout_info']
        if 'errores_validacion' in camion.metadata:
            del camion.metadata['errores_validacion']
        return
    
    # Verificar si hay SKUs para validar
    pedidos_con_skus = [p for p in camion.pedidos if p.tiene_skus]
    
    if not pedidos_con_skus:
        if DEBUG_VALIDATION:
            print(f"[VALIDATION] Sin SKUs detallados (datos legacy)")
        camion.metadata['altura_validada'] = None
        return
    
    try:
        # Configurar validador según cliente
        altura_maxima = camion.capacidad.altura_cm
        permite_consolidacion = getattr(config, 'PERMITE_CONSOLIDACION', False)
        max_skus_por_pallet = getattr(config, 'MAX_SKUS_POR_PALLET', 3)
        
        validator = HeightValidator(
            altura_maxima_cm=altura_maxima,
            permite_consolidacion=permite_consolidacion,
            max_skus_por_pallet=max_skus_por_pallet
        )
        
        # Ejecutar validación
        es_valido, errores, layout = validator.validar_camion_rapido(camion)
        
        if DEBUG_VALIDATION:
            print(f"[VALIDATION] Resultado: {'✅ VÁLIDO' if es_valido else '❌ INVÁLIDO'}")
        
        # Almacenar resultado en metadata
        camion.metadata['altura_validada'] = es_valido
        
        if es_valido and layout:
            # Guardar layout_info completo
            camion.metadata['layout_info'] = {
                'altura_validada': es_valido,
                'posiciones_usadas': layout.posiciones_usadas,
                'posiciones_disponibles': layout.posiciones_disponibles,
                'altura_maxima_cm': layout.altura_maxima_cm,
                'total_pallets_fisicos': layout.total_pallets,
                'altura_maxima_usada_cm': round(layout.altura_maxima_usada, 1),
                'altura_promedio_usada': round(layout.altura_promedio_usada, 1),
                'aprovechamiento_altura': round(layout.aprovechamiento_altura * 100, 1),
                'aprovechamiento_posiciones': round(layout.aprovechamiento_posiciones * 100, 1),
                'posiciones': [
                    {
                        'id': pos.id,
                        'altura_usada_cm': round(pos.altura_usada_cm, 1),
                        'altura_disponible_cm': round(pos.espacio_disponible_cm, 1),
                        'num_pallets': pos.num_pallets,
                        'pallets': [
                            {
                                'id': pallet.id,
                                'nivel': pallet.nivel,
                                'altura_cm': round(pallet.altura_total_cm, 1),
                                'skus': [
                                    {
                                        'sku_id': frag.sku_id,
                                        'pedido_id': frag.pedido_id,
                                        'fraccion': round(frag.fraccion, 2),
                                        'altura_cm': round(frag.altura_cm, 1),
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
            }
            
            # Limpiar errores previos si existen
            if 'errores_validacion' in camion.metadata:
                del camion.metadata['errores_validacion']
                
        else:
            # Filtrar y limpiar errores
            errores_limpios = [str(e) for e in errores if e is not ... and e is not Ellipsis]
            camion.metadata['errores_validacion'] = errores_limpios
            
            if DEBUG_VALIDATION and errores_limpios:
                print(f"[VALIDATION] Errores: {len(errores_limpios)}")
                for i, error in enumerate(errores_limpios[:3], 1):
                    print(f"[VALIDATION]   {i}. {error}")
            
            # Limpiar layout_info si existe
            if 'layout_info' in camion.metadata:
                del camion.metadata['layout_info']
        
    except Exception as e:
        if DEBUG_VALIDATION:
            print(f"[VALIDATION] ❌ Excepción: {type(e).__name__}: {str(e)}")
        
        # Si hay error en validación, registrarlo pero no bloquear
        camion.metadata['altura_validada'] = False
        camion.metadata['errores_validacion'] = [f'Error en validación: {str(e)}']
        
        # Limpiar layout_info si existe
        if 'layout_info' in camion.metadata:
            del camion.metadata['layout_info']


def _actualizar_opciones_tipo_camion(camion: Camion, client_config):
    """
    Calcula y actualiza las opciones de tipo de camión disponibles.
    Modifica camion.opciones_tipo_camion in-place.
    """
    opciones = ['normal']
    
    if not getattr(client_config, 'PERMITE_BH', False):
        camion.opciones_tipo_camion = opciones
        return
    
    # Verificar si puede ser BH
    rutas_bh = getattr(client_config, 'RUTAS_POSIBLES', {}).get('bh', [])
    
    # Normalizar para comparación
    def norm_cd(x): 
        return ('' if x is None else str(x).strip())
    
    def norm_ce(x): 
        s = ('' if x is None else str(x).strip())
        return s.lstrip('0') or '0'
    
    set_cd = {norm_cd(c) for c in (camion.cd or [])}
    set_ce = {norm_ce(e) for e in (camion.ce or [])}
    
    # 1) Verificar ruta
    ruta_ok = False
    for cds, ces in rutas_bh:
        cds_norm = {norm_cd(c) for c in (cds or [])}
        ces_norm = {norm_ce(e) for e in (ces or [])}
        if set_cd.issubset(cds_norm) and set_ce.issubset(ces_norm):
            ruta_ok = True
            break
    
    if not ruta_ok:
        camion.opciones_tipo_camion = opciones
        return
    
    # 2) CD habilitados
    cds_habilitados = set(getattr(client_config, 'CDS_BH', []))
    if cds_habilitados:
        if not set_cd.issubset(cds_habilitados):
            camion.opciones_tipo_camion = opciones
            return
    
    # 3) Verificar capacidad
    capacidades = extract_truck_capacities(client_config)
    capacidad_bh = capacidades.get(TipoCamion.BH)
    
    if capacidad_bh and camion.valida_capacidad(capacidad_bh):
        opciones.append('bh')
    
    camion.opciones_tipo_camion = opciones


def _validar_cambio_tipo_cliente(
    camion: Camion, 
    nuevo_tipo: TipoCamion, 
    config, 
    cliente: str
):
    """
    Validaciones específicas del cliente para cambio de tipo.
    Lanza ValueError si no cumple.
    """
    if cliente.lower() == "cencosud" and nuevo_tipo == TipoCamion.BH:
        # Normalizar para comparación
        def norm_cd(x): 
            return ('' if x is None else str(x).strip())
        
        def norm_ce(x): 
            s = ('' if x is None else str(x).strip())
            return s.lstrip('0') or '0'
        
        set_cd = {norm_cd(c) for c in (camion.cd or [])}
        set_ce = {norm_ce(e) for e in (camion.ce or [])}
        
        # Verificar que esté en rutas BH
        rutas_bh = getattr(config, 'RUTAS_POSIBLES', {}).get('bh', [])
        ruta_valida = False
        
        for cds, ces in rutas_bh:
            cds_norm = {norm_cd(c) for c in (cds or [])}
            ces_norm = {norm_ce(e) for e in (ces or [])}
            
            if set_cd.issubset(cds_norm) and set_ce.issubset(ces_norm):
                ruta_valida = True
                break
        
        if not ruta_valida:
            raise ValueError(
                f"Ruta [{','.join(camion.cd)}] → [{','.join(camion.ce)}] "
                f"no está habilitada para camiones BH en {cliente}"
            )


def _compute_stats(
    camiones: List[Camion], 
    pedidos_no_inc: List[Pedido]
) -> Dict[str, Any]:
    """
    Calcula estadísticas del estado actual.
    
    ✅ SIEMPRE se ejecuta, independientemente de qué camiones fueron validados.
    
    Returns:
        Dict con estadísticas agregadas en formato compatible con frontend
    """
    from collections import Counter
    
    total_pedidos = len(pedidos_no_inc) + sum(len(c.pedidos) for c in camiones)
    pedidos_asignados = total_pedidos - len(pedidos_no_inc)
    
    # Contadores por tipo
    tipos_camion = Counter(c.tipo_camion.value for c in camiones)
    cantidad_normal = tipos_camion.get('normal', 0)
    cantidad_bh = tipos_camion.get('bh', 0)
    
    # VCU promedios
    vcu_total = sum(c.vcu_max for c in camiones) / len(camiones) if camiones else 0
    
    camiones_normal = [c for c in camiones if c.tipo_camion.value == 'normal']
    vcu_normal = sum(c.vcu_max for c in camiones_normal) / len(camiones_normal) if camiones_normal else 0
    
    camiones_bh = [c for c in camiones if c.tipo_camion.value == 'bh']
    vcu_bh = sum(c.vcu_max for c in camiones_bh) / len(camiones_bh) if camiones_bh else 0
    
    # Valorizado
    valorizado = sum(
        sum(p.valor for p in c.pedidos)
        for c in camiones
    )
    
    return {
        "promedio_vcu": round(vcu_total, 3),
        "promedio_vcu_normal": round(vcu_normal, 3),
        "promedio_vcu_bh": round(vcu_bh, 3),
        "cantidad_camiones": len(camiones),
        "cantidad_camiones_normal": cantidad_normal,
        "cantidad_camiones_bh": cantidad_bh,
        "cantidad_pedidos_asignados": pedidos_asignados,
        "total_pedidos": total_pedidos,
        "valorizado": valorizado
    }