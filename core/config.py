# core/config.py
"""
Configuración central del sistema.
Registro y obtención de configuraciones de clientes.
"""

from typing import Dict, Any

# Imports de configuraciones de clientes
from clients.walmart import WalmartConfig
from clients.cencosud import CencosudConfig
from clients.disvet import DisvetConfig
from clients.smu import SmuConfig

# Registro de clientes
_CLIENT_REGISTRY: Dict[str, Any] = {
    "walmart": WalmartConfig,
    "cencosud": CencosudConfig,
    "disvet": DisvetConfig,
    "smu": SmuConfig,
}


def get_client_config(client: str):
    """
    Obtiene la configuración para un cliente específico.
    
    Args:
        client: Nombre del cliente (case-insensitive)
    
    Returns:
        Clase de configuración del cliente
    
    Raises:
        ValueError: Si el cliente no existe
    """
    client_lower = client.strip().lower()
    
    if client_lower not in _CLIENT_REGISTRY:
        available = ", ".join(_CLIENT_REGISTRY.keys())
        raise ValueError(
            f"Cliente desconocido: '{client}'. "
            f"Clientes disponibles: {available}"
        )
    
    return _CLIENT_REGISTRY[client_lower]


def register_client(name: str, config_class):
    """
    Registra un nuevo cliente en el sistema.
    
    Args:
        name: Nombre del cliente
        config_class: Clase de configuración
    """
    _CLIENT_REGISTRY[name.lower()] = config_class


def list_clients() -> list:
    """Retorna lista de clientes registrados"""
    return list(_CLIENT_REGISTRY.keys())