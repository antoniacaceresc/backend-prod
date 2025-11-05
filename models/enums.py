from enum import Enum

class TipoRuta(str, Enum):
    """Tipos de rutas soportados"""
    NORMAL = "normal"
    MULTI_CE = "multi_ce"
    MULTI_CE_PRIORIDAD = "multi_ce_prioridad"
    MULTI_CD = "multi_cd"
    BH = "bh"


class TipoCamion(str, Enum):
    """Tipos de camiones disponibles"""
    NORMAL = "normal"
    BH = "bh"


class StatusOptimizacion(str, Enum):
    """Estados del solver CP-SAT"""
    OPTIMAL = "OPTIMAL"
    FEASIBLE = "FEASIBLE"
    NO_SOLUTION = "NO_SOLUTION"