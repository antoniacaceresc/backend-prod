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

from services.models import Pedido, Camion, TruckCapacity, TipoCamion, TipoRuta
from services.config_helpers import extract_truck_capacities
from services.solver_helpers import calcular_posiciones_apilabilidad
from config import get_client_config


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


# services/postprocess.py (actualizar función _to_response)

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
    
    # Crear camión
    camion = Camion(
        id=cam_dict["id"],
        tipo_ruta=tipo_ruta,
        tipo_camion=tipo_camion,
        cd=cam_dict.get("cd", []),
        ce=cam_dict.get("ce", []),
        grupo=cam_dict.get("grupo", ""),
        capacidad=capacidad,
        pedidos=pedidos,
        opciones_tipo_camion=cam_dict.get("opciones_tipo_camion", ["normal"]),
        numero=cam_dict.get("numero", 0)
    )
    
    # Restaurar pos_total si existe
    if "pos_total" in cam_dict:
        camion.pos_total = cam_dict["pos_total"]
    
    return camion


def _pedido_from_dict(p_dict: Dict[str, Any]) -> Pedido:
    """
    Reconstruye objeto Pedido desde dict.
    
    Args:
        p_dict: Diccionario con datos del pedido
    
    Returns:
        Objeto Pedido reconstruido
    """
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
        metadata={}  # Se puede reconstruir si es necesario
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
    
    # Actualizar metadata de todos los camiones
    for cam in camiones:
        if cam.pedidos:  # Solo actualizar si tiene pedidos
            _actualizar_opciones_tipo_camion(cam, config)
    
    # 3) Devolver respuesta
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
    
    # 4) Devolver respuesta
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
    
    # 3) Devolver respuesta
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
    
    # 8) Devolver respuesta
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
    
    # Convertir de vuelta a dicts
    return (
        [c.to_api_dict() for c in camiones_obj],
        [p.to_api_dict(cap_default) for p in pedidos_obj]
    )


# ============================================================================
# HELPERS DE VALIDACIÓN Y METADATA
# ============================================================================

def _validar_reglas_cliente(camion: Camion, config, cliente: str):
    """
    Valida reglas específicas del cliente después de modificar un camión.
    
    Raises:
        ValueError: Si alguna regla no se cumple
    """
    # Walmart: límites de órdenes
    if config.__name__ == 'WalmartConfig':
        if camion.tipo_ruta == TipoRuta.MULTI_CD:
            # Máximo 10 por CD, 20 total
            cds_count = Counter(p.cd for p in camion.pedidos)
            for cd, count in cds_count.items():
                if count > 10:
                    raise ValueError(
                        f"Walmart (multi_cd): máximo 10 órdenes por CD. "
                        f"CD '{cd}' tiene {count} órdenes"
                    )
            if len(camion.pedidos) > 20:
                raise ValueError(
                    "Walmart (multi_cd): máximo 20 órdenes totales por camión"
                )
        else:
            max_ordenes = getattr(config, 'MAX_ORDENES', 10)
            if len(camion.pedidos) > max_ordenes:
                raise ValueError(
                    f"Walmart: máximo {max_ordenes} órdenes por camión"
                )
    
    # Cencosud: pallets reales
    if cliente.lower() == "cencosud":
        pallets_totales = sum(p.pallets_capacidad for p in camion.pedidos)
        max_pallets = camion.capacidad.max_pallets
        if pallets_totales > max_pallets:
            raise ValueError(
                f"Cencosud: pallets totales ({pallets_totales:.1f}) "
                f"exceden máximo ({max_pallets})"
            )


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
    if hasattr(client_config, 'CD_CON_BH'):
        cd_ok = all(cd in client_config.CD_CON_BH for cd in (camion.cd or []))
        if not cd_ok:
            camion.opciones_tipo_camion = opciones
            return
    
    # 3) Flujo MIX
    permite_mix = getattr(client_config, 'BH_PERMITE_MIX', False)
    if not permite_mix and camion.flujo_oc == 'MIX':
        camion.opciones_tipo_camion = opciones
        return
    
    # 4) VCU máximo
    if hasattr(client_config, 'BH_VCU_MAX'):
        if camion.vcu_max > float(client_config.BH_VCU_MAX) + 1e-6:
            camion.opciones_tipo_camion = opciones
            return
    
    # Todo OK, puede ser BH
    opciones.append('bh')
    
    # Poner tipo actual primero
    actual = camion.tipo_camion.value
    if actual in opciones:
        opciones.remove(actual)
        opciones.insert(0, actual)
    
    camion.opciones_tipo_camion = opciones


def _validar_cambio_tipo_cliente(
    camion: Camion, 
    nuevo_tipo: TipoCamion, 
    client_config, 
    cliente: str
):
    """
    Valida reglas específicas del cliente para cambio de tipo de camión.
    
    Raises:
        ValueError: Si el cambio no cumple las reglas
    """
    if nuevo_tipo == TipoCamion.BH:
        # Validar ruta BH
        rutas_bh = getattr(client_config, 'RUTAS_POSIBLES', {}).get('bh', [])
        
        def norm_cd(x): 
            return ('' if x is None else str(x).strip())
        
        def norm_ce(x): 
            s = ('' if x is None else str(x).strip())
            return s.lstrip('0') or '0'
        
        set_cd = {norm_cd(c) for c in (camion.cd or [])}
        set_ce = {norm_ce(e) for e in (camion.ce or [])}
        
        ruta_ok = False
        for cds, ces in rutas_bh:
            cds_norm = {norm_cd(c) for c in (cds or [])}
            ces_norm = {norm_ce(e) for e in (ces or [])}
            if set_cd.issubset(cds_norm) and set_ce.issubset(ces_norm):
                ruta_ok = True
                break
        
        if not ruta_ok:
            raise ValueError(
                "La ruta del camión no está habilitada para BH según la configuración del cliente"
            )
        
        # CD habilitados
        if hasattr(client_config, 'CD_CON_BH'):
            for cd in (camion.cd or []):
                if cd not in client_config.CD_CON_BH:
                    raise ValueError(
                        f"El CD '{cd}' no admite BH para este cliente"
                    )
        
        # Flujo MIX
        permite_mix = getattr(client_config, 'BH_PERMITE_MIX', False)
        if not permite_mix and camion.flujo_oc == 'MIX':
            raise ValueError(
                "BH no permite mezcla de flujos OC para este cliente"
            )


def _compute_stats(
    camiones: List[Camion], 
    pedidos_no_inc: List[Pedido]
) -> Dict[str, Any]:
    """
    Calcula estadísticas globales usando propiedades de los objetos.
    
    Returns:
        Dict con estadísticas
    """
    cantidad_camiones = len(camiones)
    cantidad_normal = sum(1 for c in camiones if c.tipo_camion == TipoCamion.NORMAL)
    cantidad_bh = cantidad_camiones - cantidad_normal
    
    cantidad_asig = sum(len(c.pedidos) for c in camiones)
    total_pedidos = cantidad_asig + len(pedidos_no_inc)
    
    # VCU promedio
    vcu_vals = [c.vcu_max for c in camiones] if camiones else []
    promedio_vcu = (sum(vcu_vals) / cantidad_camiones) if cantidad_camiones else 0
    
    norm_vals = [c.vcu_max for c in camiones if c.tipo_camion == TipoCamion.NORMAL]
    promedio_norm = (sum(norm_vals) / cantidad_normal) if cantidad_normal else 0
    
    bh_vals = [c.vcu_max for c in camiones if c.tipo_camion == TipoCamion.BH]
    promedio_bh = (sum(bh_vals) / cantidad_bh) if cantidad_bh else 0
    
    valorizado = sum(c.valor_total for c in camiones)
    
    return {
        "cantidad_camiones": cantidad_camiones,
        "cantidad_camiones_normal": cantidad_normal,
        "cantidad_camiones_bh": cantidad_bh,
        "cantidad_pedidos_asignados": cantidad_asig,
        "total_pedidos": total_pedidos,
        "promedio_vcu": promedio_vcu,
        "promedio_vcu_normal": promedio_norm,
        "promedio_vcu_bh": promedio_bh,
        "valorizado": valorizado,
    }