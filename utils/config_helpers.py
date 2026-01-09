from typing import Dict, List
from models.domain import TruckCapacity
from models.enums import TipoCamion

def get_effective_config(client_config, venta: str = None) -> dict:
    """
    Retorna configuración efectiva, manejando clientes con/sin CHANNEL_CONFIG.
    """
    if hasattr(client_config, 'CHANNEL_CONFIG'):
        channel = {}
        
        if venta:
            # Búsqueda case-insensitive
            venta_upper = venta.upper()
            for key, value in client_config.CHANNEL_CONFIG.items():
                if key.upper() == venta_upper:
                    channel = value
                    break
        
        if not channel:
            channel = {}
        
        return {
            # Configuración algoritmo básica
            "USA_OC": channel.get("USA_OC", getattr(client_config, 'USA_OC', True)),
            "AGRUPAR_POR_PO": channel.get("AGRUPAR_POR_PO", getattr(client_config, 'AGRUPAR_POR_PO', False)),
            "MAX_ORDENES": channel.get("MAX_ORDENES", getattr(client_config, 'MAX_ORDENES', 10)),
            "MIX_GRUPOS": channel.get("MIX_GRUPOS", getattr(client_config, 'MIX_GRUPOS', [])),
            "MAX_PALLETS_REAL_CRR": channel.get("MAX_PALLETS_REAL_CRR", getattr(client_config, 'MAX_PALLETS_REAL_CRR', 90)),
            
            # Validación y consolidación
            "VALIDAR_ALTURA": channel.get("VALIDAR_ALTURA", getattr(client_config, 'VALIDAR_ALTURA', True)),
            "PERMITE_CONSOLIDACION": channel.get("PERMITE_CONSOLIDACION", getattr(client_config, 'PERMITE_CONSOLIDACION', False)),
            "MAX_SKUS_POR_PALLET": channel.get("MAX_SKUS_POR_PALLET", getattr(client_config, 'MAX_SKUS_POR_PALLET', 3)),
            
            # Auto-split para órdenes grandes
            "AUTO_SPLIT_ENABLED": channel.get("AUTO_SPLIT_ENABLED", getattr(client_config, 'AUTO_SPLIT_ENABLED', False)),
            "RESTRICT_PO_GROUP": channel.get("RESTRICT_PO_GROUP", getattr(client_config, 'RESTRICT_PO_GROUP', False)),
            "SPLIT_THRESHOLD_FACTOR": channel.get("SPLIT_THRESHOLD_FACTOR", getattr(client_config, 'SPLIT_THRESHOLD_FACTOR', 0.9)),
            
            # Adherencia backhaul
            "ADHERENCIA_BACKHAUL": channel.get("ADHERENCIA_BACKHAUL", getattr(client_config, 'ADHERENCIA_BACKHAUL', None)),
            "MODO_ADHERENCIA": channel.get("MODO_ADHERENCIA", getattr(client_config, 'MODO_ADHERENCIA', None)),
            
            # Restricciones específicas SMU
            "PROHIBIR_PICKING_DUPLICADO": channel.get("PROHIBIR_PICKING_DUPLICADO", getattr(client_config, 'PROHIBIR_PICKING_DUPLICADO', False)),
            "ALTURA_MAX_PICKING_APILADO_CM": channel.get("ALTURA_MAX_PICKING_APILADO_CM", getattr(client_config, 'ALTURA_MAX_PICKING_APILADO_CM', 180)),
            "CDS_SIN_APILAMIENTO": channel.get("CDS_SIN_APILAMIENTO", getattr(client_config, 'CDS_SIN_APILAMIENTO', [])),
            
            # Restricciones ALVI
            "ALVI_ALTURA_MAX_CM": channel.get("ALVI_ALTURA_MAX_CM", getattr(client_config, 'ALVI_ALTURA_MAX_CM', 230)),
            "ALVI_ELIMINAR_SKU_DUPLICADO": channel.get("ALVI_ELIMINAR_SKU_DUPLICADO", getattr(client_config, 'ALVI_ELIMINAR_SKU_DUPLICADO', False)),
            "ALVI_FLUJOS_SEPARADOS": channel.get("ALVI_FLUJOS_SEPARADOS", getattr(client_config, 'ALVI_FLUJOS_SEPARADOS', False)),
            "ALVI_FLUJO_CONTINUO_CAMIONES": channel.get("ALVI_FLUJO_CONTINUO_CAMIONES", getattr(client_config, 'ALVI_FLUJO_CONTINUO_CAMIONES', [])),
            "ALVI_FLUJO_CONTINUO_MAX_SKUS_PALLET": channel.get("ALVI_FLUJO_CONTINUO_MAX_SKUS_PALLET", getattr(client_config, 'ALVI_FLUJO_CONTINUO_MAX_SKUS_PALLET', 5)),
            
            # Configuración por subcliente (SMU)
            "SUBCLIENTE_CONFIG": channel.get("SUBCLIENTE_CONFIG", {}),

            # Camiones y rutas
            "TRUCK_TYPES": channel.get("TRUCK_TYPES", getattr(client_config, 'TRUCK_TYPES', {})),
            "RUTAS_POSIBLES": channel.get("RUTAS_POSIBLES", getattr(client_config, 'RUTAS_POSIBLES', {})),
        }
    
    # Para clientes sin CHANNEL_CONFIG (legacy)
    return {
        "USA_OC": getattr(client_config, 'USA_OC', True),
        "AGRUPAR_POR_PO": getattr(client_config, 'AGRUPAR_POR_PO', False),
        "MAX_ORDENES": getattr(client_config, 'MAX_ORDENES', 10),
        "MIX_GRUPOS": getattr(client_config, 'MIX_GRUPOS', []),
        "MAX_PALLETS_REAL_CRR": getattr(client_config, 'MAX_PALLETS_REAL_CRR', 90),
        "VALIDAR_ALTURA": getattr(client_config, 'VALIDAR_ALTURA', True),
        "PERMITE_CONSOLIDACION": getattr(client_config, 'PERMITE_CONSOLIDACION', False),
        "MAX_SKUS_POR_PALLET": getattr(client_config, 'MAX_SKUS_POR_PALLET', 3),
        "ADHERENCIA_BACKHAUL": getattr(client_config, 'ADHERENCIA_BACKHAUL', None),
        "MODO_ADHERENCIA": getattr(client_config, 'MODO_ADHERENCIA', None),
        "PROHIBIR_PICKING_DUPLICADO": getattr(client_config, 'PROHIBIR_PICKING_DUPLICADO', False),
        "ALTURA_MAX_PICKING_APILADO_CM": getattr(client_config, 'ALTURA_MAX_PICKING_APILADO_CM', 180),
        "CDS_SIN_APILAMIENTO": getattr(client_config, 'CDS_SIN_APILAMIENTO', []),
        "ALVI_ALTURA_MAX_CM": getattr(client_config, 'ALVI_ALTURA_MAX_CM', 230),
        "ALVI_ELIMINAR_SKU_DUPLICADO": getattr(client_config, 'ALVI_ELIMINAR_SKU_DUPLICADO', False),
        "ALVI_FLUJOS_SEPARADOS": getattr(client_config, 'ALVI_FLUJOS_SEPARADOS', False),
        "ALVI_FLUJO_CONTINUO_CAMIONES": getattr(client_config, 'ALVI_FLUJO_CONTINUO_CAMIONES', []),
        "ALVI_FLUJO_CONTINUO_MAX_SKUS_PALLET": getattr(client_config, 'ALVI_FLUJO_CONTINUO_MAX_SKUS_PALLET', 5),
        "SUBCLIENTE_CONFIG": {},
        "TRUCK_TYPES": getattr(client_config, 'TRUCK_TYPES', {}),
        "RUTAS_POSIBLES": getattr(client_config, 'RUTAS_POSIBLES', {}),
    }

def extract_truck_capacities(client_config, venta: str = None) -> Dict[TipoCamion, TruckCapacity]:
    """
    Extrae capacidades de camiones desde configuración de cliente.
    
    Returns:
        Dict con capacidades por tipo de camión (PAQUETERA, RAMPLA_DIRECTA, BACKHAUL)
    """
    # Obtener TRUCK_TYPES desde config efectiva
    effective = get_effective_config(client_config, venta)
    truck_types = effective["TRUCK_TYPES"]
    
    capacidades = {}
    
    # Capacidad paquetera
    if 'paquetera' in truck_types:
        capacidades[TipoCamion.PAQUETERA] = TruckCapacity.from_config(truck_types['paquetera'])
    
    # Capacidad rampla directa
    if 'rampla_directa' in truck_types:
        capacidades[TipoCamion.RAMPLA_DIRECTA] = TruckCapacity.from_config(truck_types['rampla_directa'])
    
    # Capacidad backhaul
    if 'backhaul' in truck_types:
        capacidades[TipoCamion.BACKHAUL] = TruckCapacity.from_config(truck_types['backhaul'])
    
    # Capacidad mediano
    if 'mediano' in truck_types:
        capacidades[TipoCamion.MEDIANO] = TruckCapacity.from_config(truck_types['mediano'])
    
    # Capacidad pequeño
    if 'pequeño' in truck_types:
        capacidades[TipoCamion.PEQUEÑO] = TruckCapacity.from_config(truck_types['pequeño'])
    
    # Fallback: si no hay ningún tipo definido, usar el primero disponible para todos
    if not capacidades and truck_types:
        first_type = next(iter(truck_types.values()))
        default_capacity = TruckCapacity.from_config(first_type)
        capacidades[TipoCamion.PAQUETERA] = default_capacity
        capacidades[TipoCamion.RAMPLA_DIRECTA] = default_capacity
        capacidades[TipoCamion.BACKHAUL] = default_capacity
    
    return capacidades


def get_capacity_for_type(
    client_config, 
    tipo_camion: TipoCamion,
    venta: str = None
) -> TruckCapacity:
    """
    Obtiene capacidad específica para un tipo de camión.
    
    Args:
        client_config: Configuración del cliente
        tipo_camion: TipoCamion enum
    
    Returns:
        TruckCapacity para el tipo solicitado
    """
    capacidades = extract_truck_capacities(client_config, venta)
    
    # Si el tipo específico existe, usarlo
    if tipo_camion in capacidades:
        return capacidades[tipo_camion]
    
    # Fallback: paquetera, o el primero disponible
    return capacidades.get(TipoCamion.PAQUETERA) or next(iter(capacidades.values()))


def _normalize_cd_list(lst):
    if not lst:
        return []
    return [str(x).strip() for x in lst]


def _normalize_ce_list(lst):
    if not lst:
        return []
    norm = []
    for x in lst:
        s = str(x).strip()
        # Si es numérico y tiene menos de 4 dígitos, le agregamos ceros a la izquierda
        if s.isdigit() and len(s) < 4:
            s = s.zfill(4)
        norm.append(s)
    return norm


def get_camiones_permitidos_para_ruta(
    client_config, cds: List[str], ces: List[str], tipo_ruta: str, venta: str = None, oc: str = None
) -> List[TipoCamion]:
    """
    Obtiene los tipos de camiones permitidos para una ruta específica.
    """
    
    effective = get_effective_config(client_config, venta)
    rutas_posibles = effective["RUTAS_POSIBLES"]
    
    rutas_tipo = rutas_posibles.get(tipo_ruta, [])

    # Normalizar lo que viene del camión
    cds_busqueda = _normalize_cd_list(cds or [])
    ces_busqueda = _normalize_ce_list(ces or [])
    
    for idx, ruta in enumerate(rutas_tipo):
        # Formato nuevo (dict con cds, ces, camiones_permitidos)
        if isinstance(ruta, dict):
            ruta_cds = _normalize_cd_list(ruta.get('cds', []))
            ruta_ces = _normalize_ce_list(ruta.get('ces', []))
            ruta_ocs = ruta.get('ocs', [])
            
            if ruta_cds == cds_busqueda and ruta_ces == ces_busqueda:
                # Si la ruta tiene OCs definidos, verificar match
                if ruta_ocs:
                    if not oc or oc.upper() not in [o.upper() for o in ruta_ocs]:
                        continue  # No matchea por OC

                tipos_str = ruta.get('camiones_permitidos', [])
                return [TipoCamion(t) for t in tipos_str]
    
    # Si no se encuentra, retornar todos los tipos Nestlé por defecto
    print(f"[DEBUG RUTA] ⚠️ No se encontró match exacto para cds={cds_busqueda}, ces={ces_busqueda}, oc={oc}")
    print(f"[DEBUG RUTA]   Usando default: PAQUETERA + RAMPLA_DIRECTA")
    return [TipoCamion.PAQUETERA, TipoCamion.RAMPLA_DIRECTA]

def es_ruta_solo_backhaul(client_config, cd: str, ce: str, tipo_ruta: str = "normal", venta: str = None, oc:str = None) -> bool:
    """
    Verifica si una ruta SOLO permite backhaul (no permite Nestlé).
    """
    from models.enums import TipoCamion
    
    # Convertir a listas para compatibilidad con get_camiones_permitidos_para_ruta
    camiones_permitidos = get_camiones_permitidos_para_ruta(client_config, [cd], [ce], tipo_ruta, venta, oc)
    
    # Solo backhaul si BH está permitido y NO hay camiones Nestlé
    tiene_backhaul = TipoCamion.BACKHAUL in camiones_permitidos
    tiene_nestle = any(c.es_nestle for c in camiones_permitidos)
    
    return tiene_backhaul and not tiene_nestle


def permite_apilamiento_cd(client_config, cd: str, venta: str = None) -> bool:
    """
    Verifica si un CD permite apilamiento.
    Primero intenta usar el método del config, sino usa effective_config.
    """
    # Si el config tiene método propio, usarlo
    if hasattr(client_config, 'permite_apilamiento'):
        return client_config.permite_apilamiento(cd, venta) if venta else client_config.permite_apilamiento(cd)
    
    # Sino, usar effective_config
    effective = get_effective_config(client_config, venta)
    cds_sin_apilamiento = effective.get("CDS_SIN_APILAMIENTO", [])
    return cd not in cds_sin_apilamiento

def get_consolidacion_config(client_config, subcliente: str = None, oc: str = None, venta: str = None) -> dict:
    """
    Retorna configuración de consolidación específica para SMU según subcliente y flujo.
    
    Args:
        client_config: Configuración del cliente
        subcliente: "Alvi" o "Rendic" (None = usar default)
        oc: "INV" o "CRR" (solo aplica a Alvi)
        venta: Canal de venta
    
    Returns:
        Dict con PERMITE_CONSOLIDACION y MAX_SKUS_POR_PALLET
    """
    print(f"[DEBUG CONSOLIDACION] subcliente={subcliente}, oc={oc}, venta={venta}")
    effective = get_effective_config(client_config, venta)
    
    # Valores por defecto del canal
    config = {
        "PERMITE_CONSOLIDACION": effective.get("PERMITE_CONSOLIDACION", False),
        "MAX_SKUS_POR_PALLET": effective.get("MAX_SKUS_POR_PALLET", 1),
        "ALTURA_MAX_PICKING_APILADO_CM": effective.get("ALTURA_MAX_PICKING_APILADO_CM"),
    }
    
    # Si no hay subcliente, retornar default
    if not subcliente:
        return config
    
    # Buscar SUBCLIENTE_CONFIG en el channel
    if hasattr(client_config, 'CHANNEL_CONFIG'):
        channel = client_config.CHANNEL_CONFIG.get(venta, {}) if venta else {}
        subcliente_configs = channel.get("SUBCLIENTE_CONFIG", {})
        
        if subcliente in subcliente_configs:
            sub_config = subcliente_configs[subcliente]
            
            # Si es Alvi y tiene flujo específico (INV o CRR)
            if subcliente == "Alvi" and oc and oc.upper() in sub_config:
                flujo_config = sub_config[oc.upper()]
                config["PERMITE_CONSOLIDACION"] = flujo_config.get("PERMITE_CONSOLIDACION", False)
                config["MAX_SKUS_POR_PALLET"] = flujo_config.get("MAX_SKUS_POR_PALLET", 1)
            else:
                # Config general del subcliente (Rendic o Alvi sin flujo)
                config["PERMITE_CONSOLIDACION"] = sub_config.get("PERMITE_CONSOLIDACION", False)
                config["MAX_SKUS_POR_PALLET"] = sub_config.get("MAX_SKUS_POR_PALLET", 1)
    return config