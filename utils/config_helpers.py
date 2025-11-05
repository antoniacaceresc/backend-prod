# services/config_helpers.py
"""Helpers para extraer información de configuraciones de cliente"""

from typing import Dict, Any
from models.domain import TruckCapacity
from models.enums import TipoCamion


def extract_truck_capacities(client_config) -> Dict[TipoCamion, TruckCapacity]:
    """
    Extrae capacidades de camiones desde configuración de cliente.
    
    Returns:
        Dict con capacidades por tipo de camión (NORMAL y opcionalmente BH)
    """
    # Normalizar config a dict
    if isinstance(client_config.TRUCK_TYPES, dict):
        truck_types = client_config.TRUCK_TYPES
    else:
        truck_types = {t.get('type'): t for t in client_config.TRUCK_TYPES}
    
    capacidades = {}
    
    # Capacidad normal (siempre existe)
    if 'normal' in truck_types:
        capacidades[TipoCamion.NORMAL] = TruckCapacity.from_config(truck_types['normal'])
    else:
        # Fallback al primer tipo disponible
        first_type = next(iter(truck_types.values()))
        capacidades[TipoCamion.NORMAL] = TruckCapacity.from_config(first_type)
    
    # Capacidad BH (opcional)
    if 'bh' in truck_types:
        capacidades[TipoCamion.BH] = TruckCapacity.from_config(truck_types['bh'])
    
    return capacidades


def get_capacity_for_type(
    client_config, 
    tipo: str = "normal"
) -> TruckCapacity:
    """
    Obtiene capacidad específica para un tipo de camión.
    
    Args:
        client_config: Configuración del cliente
        tipo: Tipo de camión ("normal" o "bh")
    
    Returns:
        TruckCapacity para el tipo solicitado
    """
    capacidades = extract_truck_capacities(client_config)
    
    tipo_enum = TipoCamion.NORMAL if tipo.lower() == "normal" else TipoCamion.BH
    
    # Si pide BH pero no existe, devolver normal
    return capacidades.get(tipo_enum, capacidades[TipoCamion.NORMAL])


