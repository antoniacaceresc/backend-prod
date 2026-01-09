# services/postprocess.py
"""
Postprocesamiento de resultados de optimización.
Maneja operaciones de edición manual de camiones.

Estrategia:
1. Recibe dicts desde API
2. Convierte a objetos UNA VEZ al inicio
3. Ejecuta lógica de negocio con objetos
4. Convierte a dicts UNA VEZ al final

REFACTORIZADO: Usa optimization.validation en lugar de orchestrator
"""

from __future__ import annotations
from typing import List, Dict, Any, Optional, Tuple
import uuid

from models.domain import Pedido, Camion, TruckCapacity, TipoCamion, TipoRuta, SKU
from utils.config_helpers import extract_truck_capacities
from optimization.utils.helpers import calcular_posiciones_apilabilidad
from core.config import get_client_config
from optimization.validation.height_validator import HeightValidator

# ✅ NUEVO: Importar desde módulo de validación refactorizado
from optimization.validation import TruckValidator


# ============================================================================
# CONFIGURACIÓN GLOBAL
# ============================================================================

# Flag para activar/desactivar prints de debug
DEBUG_VALIDATION = False  # Cambiar a True para ver prints detallados


def _rebuild_state(state: Dict[str, Any], cliente: str, venta: str) -> Tuple[List[Camion], List[Pedido], Any, TruckCapacity]:
    """
    Reconstruye objetos desde dicts de forma eficiente.
    
    Returns:
        Tupla (camiones, pedidos_no_incluidos, config, capacidad_default)
    """
    config = get_client_config(cliente)
    
    capacidades = extract_truck_capacities(config, venta)
    cap_default = capacidades.get(TipoCamion.PAQUETERA, next(iter(capacidades.values())))
    
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
        tipo_camion = TipoCamion.PAQUETERA
    
    capacidad = capacidades.get(tipo_camion, capacidades.get(TipoCamion.PAQUETERA, next(iter(capacidades.values()))))
    
    # Determinar tipo de ruta
    try:
        tipo_ruta = TipoRuta(cam_dict.get("tipo_ruta", "normal"))
    except ValueError:
        tipo_ruta = TipoRuta.NORMAL
    
    # ✅ Reconstruir metadata incluyendo layout_info del nivel raíz
    metadata = cam_dict.get("metadata", {}).copy()
    
    # Si layout_info está en la raíz del dict (formato API), moverlo a metadata
    if "layout_info" in cam_dict:
        metadata["layout_info"] = cam_dict["layout_info"]
    
    # También preservar otros campos de validación si existen
    if "altura_validada" in cam_dict:
        metadata["altura_validada"] = cam_dict["altura_validada"]
    
    if "errores_validacion" in cam_dict:
        metadata["errores_validacion"] = cam_dict["errores_validacion"]
    
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
        metadata=metadata
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
    
    # Campos conocidos que no van en metadata
    campos_conocidos = {
        "PEDIDO", "CD", "CE", "PO", "PESO", "VOL", "PALLETS", "VALOR",
        "VALOR_CAFE", "PALLETS_REAL", "OC", "CHOCOLATES", "VALIOSO", "PDQ",
        "BAJA_VU", "LOTE_DIR", "BASE", "SUPERIOR", "FLEXIBLE", "NO_APILABLE",
        "SI_MISMO", "SKUS", "VCU_VOL", "VCU_PESO", "CAMION", "GRUPO",
        "TIPO_RUTA", "TIPO_CAMION"
    }
    
    # Extraer metadata (campos extra)
    metadata = {k: v for k, v in p_dict.items() if k not in campos_conocidos}

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
        metadata=metadata
    )


# ============================================================================
# API PÚBLICA (mantiene firmas originales para compatibilidad)
# ============================================================================

def move_orders(
    state: Dict[str, Any], 
    pedidos: Optional[List[Dict[str, Any]]], 
    target_truck_id: Optional[str], 
    cliente: str, 
    venta=None
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
    camiones, pedidos_no_inc, config, cap_default = _rebuild_state(state, cliente, venta)
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
        
        # Validar reglas del cliente ANTES de agregar
        _validar_reglas_cliente_pre_agregar(cam_dest, pedidos_obj, config, cliente, venta)
        
        # Agregar pedidos (valida automáticamente capacidad básica)
        try:
            cam_dest.agregar_pedidos(pedidos_obj)
        except ValueError as e:
            raise ValueError(f"No se pueden agregar pedidos: {e}")

        # Recalcular posiciones de apilabilidad
        cam_dest.pos_total = calcular_posiciones_apilabilidad(
            cam_dest.pedidos,
            cam_dest.capacidad.max_positions
        )

        # Actualizar metadata derivada
        _actualizar_opciones_tipo_camion(cam_dest, config, venta)
    else:
        # Mover a no incluidos
        pedidos_no_inc.extend(pedidos_obj)
    
    # 3) Revalidar altura de todos los camiones afectados
    _revalidar_altura_camiones(camiones, config, cliente, venta, operacion="move_orders")

    # RECALCULAR opciones para TODOS los camiones
    for cam in camiones:
        _actualizar_opciones_tipo_camion(cam, config, venta)
    
    # 4) Devolver respuesta
    return _to_response(camiones, pedidos_no_inc, cap_default)


def add_truck(
    state: Dict[str, Any], 
    cd: List[str], 
    ce: List[str], 
    ruta: str, 
    cliente: str, 
    venta=None
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
    camiones, pedidos_no_inc, config, cap_default = _rebuild_state(state, cliente, venta)
    
    # 2) Determinar tipo de ruta
    try:
        tipo_ruta = TipoRuta(ruta.lower())
    except ValueError:
        tipo_ruta = TipoRuta.NORMAL
    
    # 3) Crear camión nuevo
    nuevo_camion = Camion(
        id=uuid.uuid4().hex,
        tipo_ruta=tipo_ruta,
        tipo_camion=TipoCamion.PAQUETERA,
        cd=cd if isinstance(cd, list) else [cd],
        ce=ce if isinstance(ce, list) else [ce],
        grupo=f"manual__{'-'.join(cd)}__{'-'.join(map(str, ce))}",
        capacidad=cap_default,
        pedidos=[]
    )
    
    # Calcular opciones de cambio de tipo
    _actualizar_opciones_tipo_camion(nuevo_camion, config, venta)
    
    camiones.append(nuevo_camion)
    
    # 4) Revalidar altura (principalmente para mantener consistencia)
    _revalidar_altura_camiones(camiones, config, cliente, venta, operacion="add_truck")

    # RECALCULAR opciones para TODOS los camiones
    for cam in camiones:
        _actualizar_opciones_tipo_camion(cam, config, venta)
    
    # 5) Devolver respuesta
    return _to_response(camiones, pedidos_no_inc, cap_default)


def delete_truck(
    state: Dict[str, Any], 
    truck_id: Optional[str], 
    cliente: str, 
    venta=None
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
    camiones, pedidos_no_inc, config, cap_default = _rebuild_state(state, cliente, venta)
    
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
    _revalidar_altura_camiones(camiones, config, cliente, venta, operacion="delete_truck")

    # RECALCULAR opciones para TODOS los camiones
    for cam in camiones:
        _actualizar_opciones_tipo_camion(cam, config, venta)
    
    # 4) Devolver respuesta
    return _to_response(camiones, pedidos_no_inc, cap_default)


def apply_truck_type_change(
    state: Dict[str, Any], 
    truck_id: str, 
    tipo_camion: str, 
    cliente: str, 
    venta=None
) -> Dict[str, Any]:
    """
    Cambia el tipo de camión entre los tipos permitidos.
    
    Args:
        state: Estado actual
        truck_id: ID del camión a modificar
        tipo_camion: Nuevo tipo ("paquetera", "rampla_directa", "backhaul")
        cliente: Nombre del cliente
    
    Returns:
        Estado actualizado con el tipo cambiado
    
    Raises:
        ValueError: Si el cambio no es válido
    """
    # 1) Reconstruir estado
    camiones, pedidos_no_inc, config, cap_default = _rebuild_state(state, cliente, venta)
    
    # ✅ CORREGIDO: Inferir venta correctamente
    capacidades = extract_truck_capacities(config, venta)
    
    # 2) Buscar camión
    camion = next((c for c in camiones if c.id == truck_id), None)
    if not camion:
        raise ValueError("Camión no encontrado")
    
    # 3) RECALCULAR opciones ANTES de validar
    _actualizar_opciones_tipo_camion(camion, config, venta)

    # Normalizar tipo (aceptar variantes)
    tipo_nuevo = tipo_camion.lower().strip()
    
    # Mapeo de nombres alternativos
    tipo_mapping = {
        'paquetera': 'paquetera',
        'rampla': 'rampla_directa',
        'rampla_directa': 'rampla_directa',
        'backhaul': 'backhaul',
        'bh': 'backhaul',
    }
    
    tipo_nuevo = tipo_mapping.get(tipo_nuevo, tipo_nuevo)
    
    # Validar que el cambio sea permitido
    if tipo_nuevo not in camion.opciones_tipo_camion:
        raise ValueError(
            f"Cambio a '{tipo_nuevo}' no permitido para este camión. "
            f"Tipo actual: '{camion.tipo_camion.value}'. "
            f"Opciones disponibles: {', '.join(camion.opciones_tipo_camion)}"
        )
    
    # 4) Determinar nueva capacidad
    try:
        nuevo_tipo_enum = TipoCamion(tipo_nuevo)
    except ValueError:
        raise ValueError(f"Tipo de camión '{tipo_nuevo}' no válido")
    
    nueva_capacidad = capacidades.get(nuevo_tipo_enum)
    if not nueva_capacidad:
        raise ValueError(f"Sin capacidad definida para tipo '{tipo_nuevo}'")
    
    # Validar que el camión cabe en la nueva capacidad
    if not camion.valida_capacidad(nueva_capacidad):
        raise ValueError(f"El camión no cabe en capacidad de tipo '{tipo_nuevo}'")
    
    # Validar reglas del cliente
    _validar_cambio_tipo_cliente(camion, nuevo_tipo_enum, config, cliente, venta)
    
    # 5) Aplicar cambio
    camion.cambiar_tipo(nuevo_tipo_enum, nueva_capacidad)
    
    # Recalcular posiciones
    camion.pos_total = calcular_posiciones_apilabilidad(
        camion.pedidos,
        nueva_capacidad.max_positions
    )
    
    # Actualizar tipo en pedidos
    for p in camion.pedidos:
        p.tipo_camion = nuevo_tipo_enum.value
    
    # 6) Revalidar altura (crítico: cambió la capacidad)
    _revalidar_altura_camiones(camiones, config, cliente, venta, operacion="change_type")
    
    # RECALCULAR opciones para TODOS los camiones
    for cam in camiones:
        _actualizar_opciones_tipo_camion(cam, config, venta)
    
    # 7) Devolver respuesta
    return _to_response(camiones, pedidos_no_inc, cap_default)


def compute_stats(
    camiones: Optional[List[Dict[str, Any]]], 
    pedidos_no_incluidos: Optional[List[Dict[str, Any]]], 
    cliente: str, 
    venta=None
) -> Dict[str, Any]:
    """
    Recalcula estadísticas sin modificar estado.
    
    Args:
        camiones: Lista de camiones (dicts)
        pedidos_no_incluidos: Lista de pedidos no asignados (dicts)
        cliente: Nombre del cliente
    
    Returns:
        Dict con estadísticas
    """
    state = {
        "camiones": camiones or [],
        "pedidos_no_incluidos": pedidos_no_incluidos or []
    }
    
    # Reconstruir objetos para calcular estadísticas
    camiones_obj, pedidos_obj, config, cap_default = _rebuild_state(state, cliente, venta)
    
    return _compute_stats(camiones_obj, pedidos_obj)


# ============================================================================
# VALIDACIÓN DE ALTURA (REFACTORIZADO)
# ============================================================================

def _revalidar_altura_camiones(
    camiones: List[Camion], 
    config, 
    cliente: str,
    venta: str = None,
    operacion: str = "operacion"
) -> None:
    """
    Revalidación paralela (para operaciones de postproceso).
    
    ✅ REFACTORIZADO: Usa TruckValidator del módulo optimization.validation
    en lugar de _validar_altura_camiones_paralelo del orchestrator.
    """
    
    from utils.config_helpers import get_effective_config
    
    effective = get_effective_config(config, venta)

    validator = TruckValidator(config)
    validator.validar_camiones(camiones, operacion=operacion, effective_config=effective, venta=venta)



# ============================================================================
# HELPERS INTERNOS
# ============================================================================

def _obtener_todos_tipos_para_ruta(client_config, cds, ces, tipo_ruta: str, venta: str = None) -> List[TipoCamion]:
    """
    Obtiene TODOS los tipos de camión permitidos para una ruta,
    combinando todos los flujos (OCs) posibles.
    """
    from utils.config_helpers import get_effective_config, _normalize_cd_list, _normalize_ce_list
    
    effective = get_effective_config(client_config, venta)
    rutas_posibles = effective.get("RUTAS_POSIBLES", {})
    rutas_tipo = rutas_posibles.get(tipo_ruta, [])
    
    cds_busqueda = _normalize_cd_list(cds or [])
    ces_busqueda = _normalize_ce_list(ces or [])
    
    todos_tipos = set()
    
    for ruta in rutas_tipo:
        if isinstance(ruta, dict):
            ruta_cds = _normalize_cd_list(ruta.get('cds', []))
            ruta_ces = _normalize_ce_list(ruta.get('ces', []))
            
            # Match por CD y CE (ignorando OC)
            if ruta_cds == cds_busqueda and ruta_ces == ces_busqueda:
                tipos_str = ruta.get('camiones_permitidos', [])
                for t in tipos_str:
                    try:
                        todos_tipos.add(TipoCamion(t))
                    except ValueError:
                        pass
    
    # Si no encontró nada, usar default
    if not todos_tipos:
        todos_tipos = {TipoCamion.PAQUETERA, TipoCamion.RAMPLA_DIRECTA}
    
    return list(todos_tipos)


def _actualizar_opciones_tipo_camion(camion: Camion, client_config, venta: str = None):
    """
    Calcula y actualiza las opciones de tipo de camión disponibles.
    Modifica camion.opciones_tipo_camion in-place.
    
    Lógica:
    - Siempre incluye el tipo actual del camión
    - Verifica si puede cambiar a otros tipos según rutas y capacidad
    """
    from utils.config_helpers import get_camiones_permitidos_para_ruta
    
    opciones = set()
    
    # Siempre incluir el tipo actual (CRÍTICO)
    opciones.add(camion.tipo_camion.value)
    
    # Obtener tipo_ruta del camión
    tipo_ruta = camion.tipo_ruta.value if hasattr(camion, 'tipo_ruta') and camion.tipo_ruta else "normal"
    
    # Obtener OC del camión (desde el primer pedido si existe)
    oc_camion = None
    if camion.pedidos:
        oc_camion = getattr(camion.pedidos[0], 'oc', None)

    # Si NO hay pedidos, obtener tipos de TODOS los flujos para esta ruta
    if not camion.pedidos:
        camiones_permitidos = _obtener_todos_tipos_para_ruta(
            client_config, camion.cd, camion.ce, tipo_ruta, venta
        )
    else:
        # Obtener camiones permitidos para esta ruta
        try:
            camiones_permitidos = get_camiones_permitidos_para_ruta(client_config, camion.cd, camion.ce, tipo_ruta,venta, oc_camion)
        except Exception as e:
            # Fallback: usar solo el tipo actual
            camiones_permitidos = [camion.tipo_camion]
    
    capacidades = extract_truck_capacities(client_config, venta)
    
    for tipo in camiones_permitidos:
        try:
            cap = capacidades.get(tipo)
            if not cap:
                continue
            
            # Verificar si el camión actual cabe en esta capacidad
            if camion.valida_capacidad(cap):
                opciones.add(tipo.value)
        except Exception as e:
            if DEBUG_VALIDATION:
                print(f"[DEBUG] ⚠️ Error validando tipo '{tipo.value}': {e}")
    
    # Convertir a lista ordenada
    orden = ['pequeño','mediano','paquetera', 'rampla_directa', 'backhaul']
    opciones_ordenadas = [t for t in orden if t in opciones]
    
    # Agregar cualquier otro tipo no estándar que pueda estar
    for tipo in opciones:
        if tipo not in opciones_ordenadas:
            opciones_ordenadas.append(tipo)
    
    # Si opciones_ordenadas está vacía, al menos incluir el tipo actual
    if not opciones_ordenadas:
        opciones_ordenadas = [camion.tipo_camion.value]
    
    camion.opciones_tipo_camion = opciones_ordenadas


def _validar_cambio_tipo_cliente(
    camion: Camion, 
    nuevo_tipo: TipoCamion, 
    config, 
    cliente: str,
    venta: str = None
):
    """
    Validaciones específicas del cliente para cambio de tipo.
    Lanza ValueError si no cumple.
    """
    from utils.config_helpers import get_camiones_permitidos_para_ruta
    
    # Verificar que el nuevo tipo esté permitido para esta ruta
    tipo_ruta = camion.tipo_ruta.value if hasattr(camion, 'tipo_ruta') and camion.tipo_ruta else "normal"
    
    # Obtener OC del camión (desde el primer pedido si existe)
    oc_camion = None
    if camion.pedidos:
        oc_camion = getattr(camion.pedidos[0], 'oc', None)

    # Si el camión NO tiene pedidos, obtener todos los tipos de todos los flujos
    if not camion.pedidos:
        camiones_permitidos = _obtener_todos_tipos_para_ruta(
            config, camion.cd, camion.ce, tipo_ruta, venta
        )
    else:
        camiones_permitidos = get_camiones_permitidos_para_ruta(
            config,
            camion.cd,
            camion.ce,
            tipo_ruta,
            venta,
            oc_camion
        )
    
    if nuevo_tipo not in camiones_permitidos:
        raise ValueError(
            f"Tipo '{nuevo_tipo.value}' no permitido para ruta "
            f"CD={camion.cd}, CE={camion.ce}, tipo_ruta={tipo_ruta}. "
            f"Tipos permitidos: {[t.value for t in camiones_permitidos]}"
        )
    
    # Validaciones específicas por cliente
    if cliente.lower() == "cencosud":
        pass
    elif cliente.lower() == "walmart":
        pass
    elif cliente.lower() == "disvet":
        pass


def _validar_reglas_cliente_pre_agregar(
    camion: Camion, 
    pedidos_a_agregar: List[Pedido],
    config, 
    cliente: str,
    venta: str = None
):
    """
    Valida reglas del cliente ANTES de agregar pedidos.
    Lanza ValueError si agregar los pedidos violaría alguna regla.
    
    Args:
        camion: Camión destino
        pedidos_a_agregar: Pedidos que se quieren agregar
        config: Configuración del cliente
        cliente: Nombre del cliente
    
    Raises:
        ValueError: Si agregar los pedidos violaría alguna regla
    """
    if cliente.lower() == "walmart":
        # Obtener effective_config para MAX_ORDENES
        effective = _get_effective_config_para_postprocess(config, [camion], venta)
        max_ordenes = effective.get('MAX_ORDENES', 10)

        n_actual = len(camion.pedidos)
        n_a_agregar = len(pedidos_a_agregar)
        n_total = n_actual + n_a_agregar
        
        if n_total > max_ordenes:
            raise ValueError(
                f"Walmart permite máximo {max_ordenes} pedidos por camión. "
                f"El camión tiene {n_actual} y se intentan agregar {n_a_agregar} "
                f"(total: {n_total})."
            )
    
    # Validación SMU: no mezclar flujos OC
    elif cliente.lower() == "smu":
        from utils.config_helpers import get_camiones_permitidos_para_ruta

        # Obtener flujos actuales del camión
        flujos_actuales = set()
        for pedido in camion.pedidos:
            flujo = getattr(pedido, 'oc', None) or getattr(pedido, 'flujo_oc', None)
            if flujo:
                flujos_actuales.add(flujo.upper())
        
        # Obtener flujos de pedidos a agregar
        flujos_nuevos = set()
        for pedido in pedidos_a_agregar:
            flujo = getattr(pedido, 'oc', None) or getattr(pedido, 'flujo_oc', None)
            if flujo:
                flujos_nuevos.add(flujo.upper())
        
        # Verificar mezcla de flujos
        if flujos_actuales and flujos_nuevos:
            todos_flujos = flujos_actuales | flujos_nuevos
            if len(todos_flujos) > 1:
                raise ValueError(
                    f"SMU no permite mezclar flujos en un camión. "
                )
        
        # Validación SMU: no permitir picking duplicado del mismo SKU
        effective = _get_effective_config_para_postprocess(config, [camion], venta)
        if effective.get('PROHIBIR_PICKING_DUPLICADO', False):
            # Obtener SKUs de picking actuales en el camión
            skus_picking_actuales = set()
            for pedido in camion.pedidos:
                if hasattr(pedido, 'skus') and pedido.skus:
                    for sku in pedido.skus:
                        if sku.cantidad_pallets < 1.0:  # Es picking
                            skus_picking_actuales.add(sku.sku_id)
            
            # Verificar SKUs de picking en pedidos a agregar
            for pedido in pedidos_a_agregar:
                if hasattr(pedido, 'skus') and pedido.skus:
                    for sku in pedido.skus:
                        if sku.cantidad_pallets % 1 > 0.001:  # Es picking
                            if sku.sku_id in skus_picking_actuales:
                                raise ValueError(
                                    f"SMU no permite picking duplicado del mismo SKU en un camión. "
                                    f"El SKU {sku.sku_id} ya tiene picking en este camión."
                                )

        # Validar que el tipo de camión sea válido para el flujo del pedido
        tipo_ruta = camion.tipo_ruta.value if camion.tipo_ruta else "normal"
        for pedido in pedidos_a_agregar:
            oc_pedido = getattr(pedido, 'oc', None)
            if oc_pedido:
                camiones_permitidos = get_camiones_permitidos_para_ruta(
                    config, camion.cd, camion.ce, tipo_ruta, venta, oc_pedido
                )
                if camion.tipo_camion not in camiones_permitidos:
                    raise ValueError(
                        f"El tipo de camión '{camion.tipo_camion.value}' no está permitido "
                        f"para el flujo '{oc_pedido}'. "
                        f"Tipos permitidos: {[c.value for c in camiones_permitidos]}"
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
    
    # Contadores por tipo de camión
    tipos_camion = Counter(c.tipo_camion.value for c in camiones)
    cantidad_paquetera = tipos_camion.get('paquetera', 0)
    cantidad_rampla = tipos_camion.get('rampla_directa', 0)
    cantidad_backhaul = tipos_camion.get('backhaul', 0)
    
    # Camiones Nestlé = paquetera + rampla_directa
    cantidad_nestle = cantidad_paquetera + cantidad_rampla
    
    # VCU promedios
    vcu_total = sum(c.vcu_max for c in camiones) / len(camiones) if camiones else 0
    
    # VCU promedio de camiones Nestlé (paquetera + rampla_directa)
    camiones_nestle = [c for c in camiones if c.tipo_camion.es_nestle]
    vcu_nestle = sum(c.vcu_max for c in camiones_nestle) / len(camiones_nestle) if camiones_nestle else 0
    
    # VCU promedio de camiones Backhaul
    camiones_bh = [c for c in camiones if c.tipo_camion == TipoCamion.BACKHAUL]
    vcu_bh = sum(c.vcu_max for c in camiones_bh) / len(camiones_bh) if camiones_bh else 0
    
    # Valorizado
    valorizado = sum(
        sum(p.valor for p in c.pedidos)
        for c in camiones
    )
    
    return {
        "promedio_vcu": round(vcu_total, 3),
        "promedio_vcu_nestle": round(vcu_nestle, 3),
        "promedio_vcu_backhaul": round(vcu_bh, 3),
        "cantidad_camiones": len(camiones),
        "cantidad_camiones_nestle": cantidad_nestle,
        "cantidad_camiones_paquetera": cantidad_paquetera,
        "cantidad_camiones_rampla_directa": cantidad_rampla,
        "cantidad_camiones_backhaul": cantidad_backhaul,
        "cantidad_pedidos_asignados": pedidos_asignados,
        "total_pedidos": total_pedidos,
        "valorizado": valorizado
    }


def _get_effective_config_para_postprocess(config, camiones: List[Camion], venta: str = None):
    """
    Obtiene effective_config inferiendo venta desde metadata de camiones.
    
    Args:
        config: Configuración del cliente
        camiones: Lista de camiones (para inferir venta)
    
    Returns:
        effective_config dict
    """
    from utils.config_helpers import get_effective_config
    
    return get_effective_config(config, venta)