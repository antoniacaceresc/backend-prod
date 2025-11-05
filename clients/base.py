from abc import ABC
from typing import Dict, List, Any

class ClientConfig(ABC):
    """Clase base para configuraciones de clientes"""
    HEADER_ROW: int = 0
    USA_OC: bool = False
    AGRUPAR_POR_PO: bool = False
    PERMITE_BH: bool = False
    
    COLUMN_MAPPING: Dict[str, Dict[str, str]]
    EXTRA_MAPPING: Dict[str, str]
    TRUCK_TYPES: Dict[str, Dict[str, Any]]
    RUTAS_POSIBLES: Dict[str, List]