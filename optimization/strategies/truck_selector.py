# optimization/strategies/truck_selector.py
"""
Estrategias de selección de tipo de camión.

Implementa el patrón Strategy para permitir diferentes lógicas
de selección según el cliente.

Extraído de orchestrator.py para mejor extensibilidad multi-cliente.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional, Type, Dict, Any

from models.domain import ConfiguracionGrupo, TruckCapacity
from models.enums import TipoCamion, TipoRuta


class TruckSelector(ABC):
    """
    Clase base abstracta para selectores de tipo de camión.
    
    Cada cliente puede tener su propia implementación con reglas específicas.
    """
    
    def __init__(self, client_config):
        """
        Args:
            client_config: Configuración del cliente
        """
        self.config = client_config
    
    @abstractmethod
    def seleccionar_tipo_camion(
        self,
        grupo_cfg: ConfiguracionGrupo,
        camiones_permitidos: List[TipoCamion],
        contexto: Optional[Dict[str, Any]] = None
    ) -> TipoCamion:
        """
        Selecciona el tipo de camión óptimo para un grupo.
        
        Args:
            grupo_cfg: Configuración del grupo (CD, CE, tipo ruta)
            camiones_permitidos: Lista de tipos permitidos para esta ruta
            contexto: Información adicional (pedidos, fase, etc.)
        
        Returns:
            TipoCamion seleccionado
        """
        pass
    
    def filtrar_nestle(self, camiones: List[TipoCamion]) -> List[TipoCamion]:
        """Filtra solo camiones Nestlé de la lista."""
        return [c for c in camiones if c.es_nestle]
    
    def filtrar_backhaul(self, camiones: List[TipoCamion]) -> List[TipoCamion]:
        """Filtra solo camiones backhaul de la lista."""
        return [c for c in camiones if c.es_backhaul]


class DefaultTruckSelector(TruckSelector):
    """
    Selector por defecto: prioriza paquetera > rampla > backhaul.
    
    Usado para clientes sin reglas especiales.
    """
    
    # Orden de prioridad por defecto
    PRIORIDAD = [
        TipoCamion.PAQUETERA,
        TipoCamion.RAMPLA_DIRECTA,
        TipoCamion.BACKHAUL,
    ]
    
    def seleccionar_tipo_camion(
        self,
        grupo_cfg: ConfiguracionGrupo,
        camiones_permitidos: List[TipoCamion],
        contexto: Optional[Dict[str, Any]] = None
    ) -> TipoCamion:
        """Selecciona según orden de prioridad."""
        if not camiones_permitidos:
            return TipoCamion.PAQUETERA  # Fallback
        
        # Buscar el primero según prioridad
        for tipo in self.PRIORIDAD:
            if tipo in camiones_permitidos:
                return tipo
        
        # Si ninguno coincide, usar el primero disponible
        return camiones_permitidos[0]


class NestleTruckSelector(TruckSelector):
    """
    Selector para Nestlé/Cencosud: prioriza camiones Nestlé.
    
    Reglas:
    - Fase Nestlé: solo paquetera/rampla
    - Fase BH: solo backhaul
    - Default: paquetera
    """
    
    def seleccionar_tipo_camion(
        self,
        grupo_cfg: ConfiguracionGrupo,
        camiones_permitidos: List[TipoCamion],
        contexto: Optional[Dict[str, Any]] = None
    ) -> TipoCamion:
        """Selecciona priorizando Nestlé."""
        if not camiones_permitidos:
            return TipoCamion.PAQUETERA
        
        contexto = contexto or {}
        fase = contexto.get('fase', 'nestle')
        
        if fase == 'backhaul':
            # En fase BH, solo backhaul
            if TipoCamion.BACKHAUL in camiones_permitidos:
                return TipoCamion.BACKHAUL
        
        # Prioridad Nestlé: paquetera > rampla
        nestle = self.filtrar_nestle(camiones_permitidos)
        if nestle:
            if TipoCamion.PAQUETERA in nestle:
                return TipoCamion.PAQUETERA
            if TipoCamion.RAMPLA_DIRECTA in nestle:
                return TipoCamion.RAMPLA_DIRECTA
            return nestle[0]
        
        # Fallback a backhaul si no hay Nestlé
        if TipoCamion.BACKHAUL in camiones_permitidos:
            return TipoCamion.BACKHAUL
        
        return camiones_permitidos[0]


class SmuTruckSelector(TruckSelector):
    """
    Selector para SMU (Alvi/Rendic).
    
    Reglas especiales:
    - Alvi CRR: prioriza pequeño > mediano > paquetera > rampla
    - Alvi INV: solo paquetera/rampla
    - Rendic: paquetera/rampla/backhaul según ruta
    """
    
    def _es_alvi(self, grupo_cfg: ConfiguracionGrupo) -> bool:
        """Detecta si el grupo es de Alvi basándose en el CD."""
        if grupo_cfg.cd:
            cd = grupo_cfg.cd[0] if isinstance(grupo_cfg.cd, list) else grupo_cfg.cd
            return "Alvi" in cd
        return False
    
    def seleccionar_tipo_camion(
        self,
        grupo_cfg: ConfiguracionGrupo,
        camiones_permitidos: List[TipoCamion],
        contexto: Optional[Dict[str, Any]] = None
    ) -> TipoCamion:
        """Selecciona según reglas SMU."""
        if not camiones_permitidos:
            return TipoCamion.PAQUETERA
        
        oc = grupo_cfg.oc
        es_alvi = self._es_alvi(grupo_cfg)
        
        # Alvi con CRR: priorizar pequeño > mediano
        if es_alvi and oc and oc.upper() == 'CRR':
            if TipoCamion.PEQUEÑO in camiones_permitidos:
                return TipoCamion.PEQUEÑO
            if TipoCamion.MEDIANO in camiones_permitidos:
                return TipoCamion.MEDIANO
        
        # Default: priorizar Nestlé grandes
        if TipoCamion.PAQUETERA in camiones_permitidos:
            return TipoCamion.PAQUETERA
        if TipoCamion.RAMPLA_DIRECTA in camiones_permitidos:
            return TipoCamion.RAMPLA_DIRECTA
        
        return camiones_permitidos[0]

class WalmartTruckSelector(TruckSelector):
    """
    Selector para Walmart.
    
    Reglas especiales:
    - Máximo 10 órdenes por camión
    - Multi_cd: máximo 10 por CD, 20 total
    """
    
    def seleccionar_tipo_camion(
        self,
        grupo_cfg: ConfiguracionGrupo,
        camiones_permitidos: List[TipoCamion],
        contexto: Optional[Dict[str, Any]] = None
    ) -> TipoCamion:
        """Selecciona según reglas Walmart."""
        if not camiones_permitidos:
            return TipoCamion.PAQUETERA
        
        # Walmart usa principalmente Nestlé
        if TipoCamion.PAQUETERA in camiones_permitidos:
            return TipoCamion.PAQUETERA
        if TipoCamion.RAMPLA_DIRECTA in camiones_permitidos:
            return TipoCamion.RAMPLA_DIRECTA
        
        return camiones_permitidos[0]


class TruckSelectorFactory:
    """
    Factory para crear el selector apropiado según el cliente.
    """
    
    # Registro de selectores por cliente
    _SELECTORES: Dict[str, Type[TruckSelector]] = {
        'cencosud': NestleTruckSelector,
        'nestle': NestleTruckSelector,
        'walmart': WalmartTruckSelector,
        'smu': SmuTruckSelector,
        'disvet': DefaultTruckSelector,
    }
    
    @classmethod
    def create(cls, client_config) -> TruckSelector:
        """
        Crea el selector apropiado para el cliente.
        
        Args:
            client_config: Configuración del cliente
        
        Returns:
            Instancia del selector apropiado
        """
        # Intentar obtener nombre del cliente desde config
        cliente_nombre = cls._get_client_name(client_config)
        
        # Buscar selector registrado
        selector_class = cls._SELECTORES.get(
            cliente_nombre.lower(), 
            DefaultTruckSelector
        )
        
        return selector_class(client_config)
    
    @classmethod
    def _get_client_name(cls, client_config) -> str:
        """Extrae el nombre del cliente desde la configuración."""
        # Intentar varios atributos comunes
        if hasattr(client_config, '__name__'):
            name = client_config.__name__
            # Limpiar sufijos comunes
            for suffix in ['Config', 'Configuration', 'Settings']:
                if name.endswith(suffix):
                    name = name[:-len(suffix)]
            return name
        
        if hasattr(client_config, 'CLIENTE'):
            return client_config.CLIENTE
        
        if hasattr(client_config, 'nombre'):
            return client_config.nombre
        
        return 'default'
    
    @classmethod
    def register(cls, cliente: str, selector_class: Type[TruckSelector]):
        """
        Registra un nuevo selector para un cliente.
        
        Útil para agregar clientes sin modificar este archivo.
        
        Args:
            cliente: Nombre del cliente (lowercase)
            selector_class: Clase del selector
        """
        cls._SELECTORES[cliente.lower()] = selector_class


# Función de conveniencia
def seleccionar_tipo_camion(
    client_config,
    grupo_cfg: ConfiguracionGrupo,
    camiones_permitidos: List[TipoCamion],
    contexto: Optional[Dict[str, Any]] = None
) -> TipoCamion:
    """
    Función de conveniencia para seleccionar tipo de camión.
    
    Args:
        client_config: Configuración del cliente
        grupo_cfg: Configuración del grupo
        camiones_permitidos: Tipos permitidos
        contexto: Información adicional
    
    Returns:
        TipoCamion seleccionado
    """
    selector = TruckSelectorFactory.create(client_config)
    return selector.seleccionar_tipo_camion(grupo_cfg, camiones_permitidos, contexto)