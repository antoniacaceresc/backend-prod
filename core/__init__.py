# core/__init__.py
"""
Configuración central del sistema.
"""

from .config import get_client_config, register_client, list_clients

__all__ = [
    "get_client_config",
    "register_client", 
    "list_clients"
]