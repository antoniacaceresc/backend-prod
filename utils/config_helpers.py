# services/config_helpers.py
"""Helpers para extraer información de configuraciones de cliente"""

from typing import Dict, List
from models.domain import TruckCapacity
from models.enums import TipoCamion


def extract_truck_capacities(client_config) -> Dict[TipoCamion, TruckCapacity]:
    """
    Extrae capacidades de camiones desde configuración de cliente.
    
    Returns:
        Dict con capacidades por tipo de camión (PAQUETERA, RAMPLA_DIRECTA, BACKHAUL)
    """
    # Normalizar config a dict
    if isinstance(client_config.TRUCK_TYPES, dict):
        truck_types = client_config.TRUCK_TYPES
    else:
        truck_types = {t.get('type'): t for t in client_config.TRUCK_TYPES}
    
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
    
    # Fallback: si no hay ningún tipo definido, usar el primero disponible para todos
    if not capacidades:
        first_type = next(iter(truck_types.values()))
        default_capacity = TruckCapacity.from_config(first_type)
        capacidades[TipoCamion.PAQUETERA] = default_capacity
        capacidades[TipoCamion.RAMPLA_DIRECTA] = default_capacity
        capacidades[TipoCamion.BACKHAUL] = default_capacity
    
    return capacidades


def get_capacity_for_type(
    client_config, 
    tipo_camion: TipoCamion
) -> TruckCapacity:
    """
    Obtiene capacidad específica para un tipo de camión.
    
    Args:
        client_config: Configuración del cliente
        tipo_camion: TipoCamion enum
    
    Returns:
        TruckCapacity para el tipo solicitado
    """
    capacidades = extract_truck_capacities(client_config)
    
    # Si el tipo específico no existe, usar paquetera como fallback
    return capacidades.get(tipo_camion, capacidades.get(TipoCamion.PAQUETERA))


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
    client_config,
    cds: List[str],
    ces: List[str],
    tipo_ruta: str
) -> List[TipoCamion]:
    """
    Obtiene los tipos de camiones permitidos para una ruta específica.
    """
    rutas_posibles = getattr(client_config, 'RUTAS_POSIBLES', {})
    
    rutas_tipo = rutas_posibles.get(tipo_ruta, [])

    # Normalizar lo que viene del camión
    cds_busqueda = _normalize_cd_list(cds or [])
    ces_busqueda = _normalize_ce_list(ces or [])
    
    for idx, ruta in enumerate(rutas_tipo):
        # Formato nuevo (dict con cds, ces, camiones_permitidos)
        if isinstance(ruta, dict):
            ruta_cds = _normalize_cd_list(ruta.get('cds', []))
            ruta_ces = _normalize_ce_list(ruta.get('ces', []))
            
            if ruta_cds == cds_busqueda and ruta_ces == ces_busqueda:
                tipos_str = ruta.get('camiones_permitidos', [])
                return [TipoCamion(t) for t in tipos_str]
        
        # Formato legacy (tupla)
        elif isinstance(ruta, tuple) and len(ruta) == 2:
            if ruta[0] == cds and ruta[1] == ces:
                return [TipoCamion.PAQUETERA, TipoCamion.RAMPLA_DIRECTA]
    
    # Si no se encuentra, retornar todos los tipos Nestlé por defecto
    print(f"[DEBUG] ⚠️ No se encontró match exacto, usando default: PAQUETERA + RAMPLA_DIRECTA")
    return [TipoCamion.PAQUETERA, TipoCamion.RAMPLA_DIRECTA]
