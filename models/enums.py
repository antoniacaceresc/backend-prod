from enum import Enum

class TipoRuta(str, Enum):
    """Tipos de rutas soportados"""
    NORMAL = "normal"
    MULTI_CE = "multi_ce"
    MULTI_CE_PRIORIDAD = "multi_ce_prioridad"
    MULTI_CD = "multi_cd"


class TipoCamion(str, Enum):
    """Tipos de camiones disponibles"""
    PAQUETERA = "paquetera"
    RAMPLA_DIRECTA = "rampla_directa"
    BACKHAUL = "backhaul"
    MEDIANO = "mediano"
    PEQUEÑO = "pequeño" 

    @property
    def es_nestle(self) -> bool:
        """Indica si es camión de Nestlé (paquetera o rampla)"""
        return self in (TipoCamion.PAQUETERA, TipoCamion.RAMPLA_DIRECTA,
                        TipoCamion.MEDIANO, TipoCamion.PEQUEÑO)
    
    @property
    def es_backhaul(self) -> bool:
        """Indica si es camión backhaul del cliente"""
        return self == TipoCamion.BACKHAUL


class StatusOptimizacion(str, Enum):
    """Estados del solver CP-SAT"""
    OPTIMAL = "OPTIMAL"
    FEASIBLE = "FEASIBLE"
    NO_SOLUTION = "NO_SOLUTION"