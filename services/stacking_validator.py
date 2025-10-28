# services/stacking_validator.py
"""
Validador de apilabilidad física de pallets en camiones.

MODELO DE NEGOCIO:
------------------
1. PALLET FÍSICO: Unidad física en el camión (puede tener múltiples SKUs)
2. FRAGMENTO: Porción de un SKU que va en un pallet físico (ej: 0.3 de SKU_A)
3. POSICIÓN: Espacio en el piso del camión (puede tener pallets apilados)

REGLAS DE APILAMIENTO:
----------------------
- NO_APILABLE: siempre solo, ocupa 1 posición
- BASE: va al suelo, puede tener SUPERIOR o FLEXIBLE encima
- SUPERIOR: va encima de BASE o FLEXIBLE
- SI_MISMO: se apila verticalmente con mismo SKU
- FLEXIBLE: se adapta según contexto (puede ser BASE, SUPERIOR o SI_MISMO)

CONSOLIDACIÓN:
--------------
- Si PERMITE_CONSOLIDACION: fragmentos de diferentes pedidos/SKUs se agrupan
- Límite: MAX_SKUS_POR_PALLET diferentes por pallet físico
- Objetivo: minimizar pallets físicos y maximizar uso de espacio
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Set
from enum import Enum
from collections import defaultdict
import math


class TipoApilabilidad(Enum):
    """Tipos de apilabilidad de pallets"""
    BASE = "BASE"
    SUPERIOR = "SUPERIOR"
    FLEXIBLE = "FLEXIBLE"
    NO_APILABLE = "NO_APILABLE"
    SI_MISMO = "SI_MISMO"
    
    @classmethod
    def from_string(cls, valor: str) -> TipoApilabilidad:
        """Convierte string a enum de forma segura"""
        valor_norm = (valor or "FLEXIBLE").strip().upper().replace(" ", "_")
        try:
            return cls[valor_norm]
        except KeyError:
            return cls.FLEXIBLE


@dataclass(frozen=True)
class FragmentoSKU:
    """
    Representa un fragmento de un SKU en un pallet físico.
    Ejemplo: 0.3 pallets del SKU_A del Pedido 12345
    """
    sku: str
    pedido: str
    cantidad: float  # fracción de pallet (0.0 - 1.0)
    tipo: TipoApilabilidad
    altura: float  # cm (altura de este fragmento)
    
    def __post_init__(self):
        if self.cantidad <= 0 or self.cantidad > 1.0:
            raise ValueError(f"Cantidad debe estar en (0, 1.0]: {self.cantidad}")
        if self.altura <= 0:
            raise ValueError(f"Altura debe ser > 0: {self.altura}")


@dataclass(frozen=True)
class PalletFisico:
    """
    Representa un PALLET FÍSICO en el camión.
    Puede contener fragmentos de múltiples SKUs (si permite consolidación).
    """
    id_pallet: str
    fragmentos: Tuple[FragmentoSKU, ...]  # inmutable
    tipo: TipoApilabilidad  # tipo dominante del pallet
    altura: float  # altura física del pallet (máxima de los fragmentos)
    
    def __post_init__(self):
        if not self.fragmentos:
            raise ValueError("Pallet debe tener al menos 1 fragmento")
        if self.altura <= 0:
            raise ValueError(f"Altura debe ser > 0: {self.altura}")
    
    @property
    def cantidad_total(self) -> float:
        """Suma de fracciones de todos los fragmentos"""
        return sum(f.cantidad for f in self.fragmentos)
    
    @property
    def es_completo(self) -> bool:
        """True si cantidad_total >= 1.0 (con tolerancia)"""
        return self.cantidad_total >= 0.95  # tolerancia 5%
    
    @property
    def skus_unicos(self) -> Set[str]:
        """Set de SKUs únicos en este pallet"""
        return {f.sku for f in self.fragmentos}
    
    @property
    def pedidos(self) -> Set[str]:
        """Set de pedidos que contribuyen a este pallet"""
        return {f.pedido for f in self.fragmentos}
    
    @property
    def sku_dominante(self) -> Optional[str]:
        """SKU con mayor cantidad en el pallet"""
        if not self.fragmentos:
            return None
        return max(self.fragmentos, key=lambda f: f.cantidad).sku
    
    def espacio_disponible(self) -> float:
        """Espacio restante en el pallet (0.0 - 1.0)"""
        return max(0.0, 1.0 - self.cantidad_total)
    
    def puede_agregar_fragmento(self, fragmento: FragmentoSKU, max_skus: int) -> bool:
        """
        Verifica si se puede agregar un fragmento a este pallet.
        
        Condiciones:
        1. Mismo tipo de apilabilidad
        2. Espacio disponible suficiente
        3. No excede límite de SKUs diferentes
        4. Si es SI_MISMO, debe ser el mismo SKU
        """
        # 1. Mismo tipo
        if self.tipo != fragmento.tipo:
            return False
        
        # 2. Espacio disponible
        if self.espacio_disponible() < fragmento.cantidad:
            return False
        
        # 3. Límite de SKUs
        skus_actuales = self.skus_unicos
        if fragmento.sku not in skus_actuales and len(skus_actuales) >= max_skus:
            return False
        
        # 4. SI_MISMO debe ser mismo SKU
        if self.tipo == TipoApilabilidad.SI_MISMO:
            if fragmento.sku != self.sku_dominante:
                return False
        
        return True
    
    def to_dict(self) -> Dict:
        """Serializa para JSON"""
        return {
            'id': self.id_pallet,
            'tipo': self.tipo.value,
            'altura': round(self.altura, 2),
            'cantidad_total': round(self.cantidad_total, 2),
            'es_completo': self.es_completo,
            'num_skus': len(self.skus_unicos),
            'num_pedidos': len(self.pedidos),
            'fragmentos': [
                {
                    'sku': f.sku,
                    'pedido': f.pedido,
                    'cantidad': round(f.cantidad, 2),
                    'tipo': f.tipo.value
                }
                for f in self.fragmentos
            ]
        }


@dataclass
class Posicion:
    """
    Representa una POSICIÓN física en el piso del camión.
    Puede contener pallets apilados verticalmente según reglas.
    """
    index: int
    stack: List[PalletFisico] = field(default_factory=list)
    altura_usada: float = 0.0
    
    def altura_disponible(self, max_altura: float) -> float:
        return max(0.0, max_altura - self.altura_usada)
    
    def esta_vacia(self) -> bool:
        return len(self.stack) == 0
    
    def pedidos_en_posicion(self) -> Set[str]:
        """Todos los pedidos en esta posición"""
        pedidos = set()
        for pallet in self.stack:
            pedidos.update(pallet.pedidos)
        return pedidos
    
    def puede_apilar(self, pallet: PalletFisico, max_altura: float) -> bool:
        """
        Valida si se puede apilar el pallet en esta posición.
        
        REGLAS DE APILAMIENTO:
        ----------------------
        1. Altura disponible suficiente
        2. Posición vacía: cualquiera puede ir a piso
        3. NO_APILABLE: NUNCA recibe nada encima
        4. BASE: acepta SUPERIOR o FLEXIBLE encima (1 nivel)
        5. SI_MISMO: acepta más pallets del MISMO SKU verticalmente
        6. FLEXIBLE: puede ir encima de BASE/FLEXIBLE, o puede tener SUPERIOR encima
        """
        # Regla 1: Altura disponible
        if self.altura_disponible(max_altura) < pallet.altura:
            return False
        
        # Regla 2: Posición vacía (va al suelo)
        if self.esta_vacia():
            return pallet.tipo in {
                TipoApilabilidad.BASE,
                TipoApilabilidad.NO_APILABLE,
                TipoApilabilidad.FLEXIBLE,
                TipoApilabilidad.SI_MISMO,
                TipoApilabilidad.SUPERIOR
            }
        
        tope = self.stack[-1]
        
        # Regla 3: NO_APILABLE nunca recibe nada
        if tope.tipo == TipoApilabilidad.NO_APILABLE:
            return False
        
        # Regla 4: BASE acepta SUPERIOR o FLEXIBLE (solo 1 nivel)
        if tope.tipo == TipoApilabilidad.BASE:
            if pallet.tipo in {TipoApilabilidad.SUPERIOR, TipoApilabilidad.FLEXIBLE}:
                # Solo si no hay nada encima ya
                return len(self.stack) == 1
            return False
        
        # Regla 5: SI_MISMO acepta más del mismo SKU
        if tope.tipo == TipoApilabilidad.SI_MISMO:
            if pallet.tipo != TipoApilabilidad.SI_MISMO:
                return False
            # Debe ser el mismo SKU dominante
            return pallet.sku_dominante == tope.sku_dominante
        
        # Regla 6: FLEXIBLE
        if tope.tipo == TipoApilabilidad.FLEXIBLE:
            # Si FLEXIBLE está en el suelo, puede recibir SUPERIOR o más FLEXIBLE
            if len(self.stack) == 1:
                return pallet.tipo in {TipoApilabilidad.SUPERIOR, TipoApilabilidad.FLEXIBLE}
            # Si FLEXIBLE está encima de algo, no recibe más
            return False
        
        # SUPERIOR no debería estar de tope (siempre va arriba)
        return False
    
    def agregar(self, pallet: PalletFisico) -> None:
        """Agrega pallet al stack"""
        self.stack.append(pallet)
        self.altura_usada += pallet.altura
    
    def to_dict(self) -> Dict:
        return {
            'index': self.index,
            'altura_usada': round(self.altura_usada, 2),
            'num_pallets': len(self.stack),
            'pedidos': list(self.pedidos_en_posicion()),
            'pallets': [p.to_dict() for p in self.stack]
        }


@dataclass
class ResultadoValidacion:
    """Resultado de la validación de colocación"""
    cabe: bool
    pedidos_incluidos: List[str] = field(default_factory=list)
    pedidos_rechazados: List[str] = field(default_factory=list)
    posiciones_usadas: int = 0
    altura_maxima: float = 0.0
    motivo_fallo: Optional[str] = None
    layout: List[Posicion] = field(default_factory=list)
    
    # Métricas
    total_pedidos: int = 0
    pallets_fisicos_usados: int = 0
    eficiencia_posiciones: float = 0.0
    eficiencia_altura: float = 0.0
    eficiencia_consolidacion: float = 0.0  # % de pallets consolidados
    
    def to_dict(self) -> Dict:
        return {
            'cabe': self.cabe,
            'pedidos_incluidos': self.pedidos_incluidos,
            'pedidos_rechazados': self.pedidos_rechazados,
            'total_pedidos': self.total_pedidos,
            'posiciones_usadas': self.posiciones_usadas,
            'pallets_fisicos': self.pallets_fisicos_usados,
            'altura_maxima': round(self.altura_maxima, 2),
            'motivo_fallo': self.motivo_fallo,
            'eficiencias': {
                'posiciones': round(self.eficiencia_posiciones, 2),
                'altura': round(self.eficiencia_altura, 2),
                'consolidacion': round(self.eficiencia_consolidacion, 2)
            },
            'layout': [pos.to_dict() for pos in self.layout if not pos.esta_vacia()]
        }


class StackingValidator:
    """
    Validador principal de apilabilidad física.
    
    Flujo:
    1. Extraer fragmentos de SKUs desde pedidos
    2. Consolidar fragmentos en pallets físicos (si permite_consolidacion)
    3. Ordenar pallets para colocación óptima
    4. Colocar pallets en posiciones según reglas de apilamiento
    5. Determinar qué pedidos caben completos
    """
    
    _config_cache: Dict[Tuple[str, str], Dict] = {}
    
    def __init__(
        self,
        max_positions: int,
        max_altura: float,
        permite_consolidacion: bool,
        max_skus_por_pallet: int,
        levels: int = 2
    ):
        if max_positions <= 0 or max_altura <= 0:
            raise ValueError("max_positions y max_altura deben ser > 0")
        if max_skus_por_pallet <= 0:
            raise ValueError("max_skus_por_pallet debe ser > 0")
        
        self.max_positions = max_positions
        self.max_altura = max_altura
        self.permite_consolidacion = permite_consolidacion
        self.max_skus_por_pallet = max_skus_por_pallet
        self.levels = levels
    
    @classmethod
    def from_config(cls, cliente: str, tipo_camion: str) -> StackingValidator:
        """Factory con cache de configuración"""
        cache_key = (cliente.lower(), tipo_camion.lower())
        
        if cache_key not in cls._config_cache:
            from config import get_client_config
            
            cfg = get_client_config(cliente)
            if not cfg:
                raise ValueError(f"Cliente '{cliente}' no configurado")
            
            if isinstance(cfg.TRUCK_TYPES, dict):
                trucks = cfg.TRUCK_TYPES
            else:
                trucks = {t.get('type'): t for t in cfg.TRUCK_TYPES}
            
            tsel = trucks.get(tipo_camion) or trucks.get('normal')
            if not tsel:
                tsel = next(iter(trucks.values()))
            
            cls._config_cache[cache_key] = {
                'max_positions': int(tsel.get('max_positions', 30)),
                'max_altura': float(tsel.get('max_altura', 240)),
                'levels': int(tsel.get('levels', 2)),
                'permite_consolidacion': getattr(cfg, 'PERMITE_CONSOLIDACION_PALLETS', True),
                'max_skus_por_pallet': int(getattr(cfg, 'MAX_SKUS_POR_PALLET', 5))
            }
        
        config = cls._config_cache[cache_key]
        return cls(
            max_positions=config['max_positions'],
            max_altura=config['max_altura'],
            permite_consolidacion=config['permite_consolidacion'],
            max_skus_por_pallet=config['max_skus_por_pallet'],
            levels=config['levels']
        )
    
    def validar_pedidos(
        self,
        fragmentos_por_pedido: Dict[str, List[FragmentoSKU]]
    ) -> ResultadoValidacion:
        """
        Valida lista de pedidos representados por sus fragmentos.
        
        Args:
            fragmentos_por_pedido: {pedido_id: [FragmentoSKU, ...]}
        
        Returns:
            ResultadoValidacion indicando qué pedidos caben
        """
        if not fragmentos_por_pedido:
            return ResultadoValidacion(cabe=True, total_pedidos=0)
        
        # 1. Consolidar fragmentos en pallets físicos
        pallets_fisicos = self._consolidar_fragmentos(fragmentos_por_pedido)
        
        # 2. Mapear cada pallet a sus pedidos
        pallet_a_pedidos = self._mapear_pallets_a_pedidos(pallets_fisicos)
        
        # 3. Ordenar pallets para colocación óptima
        pallets_ordenados = self._ordenar_pallets(pallets_fisicos)
        
        # 4. Inicializar posiciones
        posiciones = [Posicion(index=i) for i in range(self.max_positions)]
        
        # 5. Colocar pallets
        pallets_colocados = []
        pallets_rechazados = []
        
        for pallet in pallets_ordenados:
            if self._colocar_pallet(pallet, posiciones):
                pallets_colocados.append(pallet)
            else:
                pallets_rechazados.append(pallet)
        
        # 5b. Segunda pasada: intentar colocar SUPERIOR en el piso si quedaron rechazados
        pallets_aun_rechazados = []
        for pallet in pallets_rechazados:
            if pallet.tipo == TipoApilabilidad.SUPERIOR:
                if self._colocar_pallet_segunda_pasada(pallet, posiciones):
                    pallets_colocados.append(pallet)
                else:
                    pallets_aun_rechazados.append(pallet)
            else:
                pallets_aun_rechazados.append(pallet)
        
        pallets_rechazados = pallets_aun_rechazados
        
        # 6. Determinar pedidos incluidos/rechazados
        pedidos_incluidos, pedidos_rechazados = self._determinar_pedidos_validos(
            pallets_colocados,
            pallets_rechazados,
            fragmentos_por_pedido
        )
        
        # 7. Calcular métricas
        if not pedidos_incluidos:
            return ResultadoValidacion(
                cabe=False,
                pedidos_rechazados=list(fragmentos_por_pedido.keys()),
                total_pedidos=len(fragmentos_por_pedido),
                motivo_fallo="Ningún pedido cabe completo en el camión"
            )
        
        posiciones_usadas = sum(1 for p in posiciones if not p.esta_vacia())
        altura_max = max(
            (p.altura_usada for p in posiciones if not p.esta_vacia()),
            default=0.0
        )
        
        # Eficiencias
        efic_pos = (posiciones_usadas / self.max_positions) * 100
        alturas_usadas = [p.altura_usada for p in posiciones if not p.esta_vacia()]
        efic_alt = (
            (sum(alturas_usadas) / (len(alturas_usadas) * self.max_altura) * 100)
            if alturas_usadas else 0
        )
        
        # Eficiencia de consolidación: % de pallets con múltiples pedidos
        pallets_multi_pedido = sum(
            1 for p in pallets_colocados if len(p.pedidos) > 1
        )
        efic_consol = (
            (pallets_multi_pedido / len(pallets_colocados) * 100)
            if pallets_colocados else 0
        )
        
        return ResultadoValidacion(
            cabe=True,
            pedidos_incluidos=pedidos_incluidos,
            pedidos_rechazados=pedidos_rechazados,
            total_pedidos=len(fragmentos_por_pedido),
            posiciones_usadas=posiciones_usadas,
            altura_maxima=altura_max,
            pallets_fisicos_usados=len(pallets_colocados),
            eficiencia_posiciones=efic_pos,
            eficiencia_altura=efic_alt,
            eficiencia_consolidacion=efic_consol,
            layout=posiciones
        )
    
    def _separar_fragmentos_completos(
        self, 
        fragmentos: List[FragmentoSKU]
    ) -> Tuple[List[FragmentoSKU], List[FragmentoSKU]]:
        """
        Separa fragmentos completos (>=0.95) de incompletos (<0.95).
        
        Returns:
            (completos, incompletos)
        """
        completos = [f for f in fragmentos if f.cantidad >= 0.95]
        incompletos = [f for f in fragmentos if f.cantidad < 0.95]
        return completos, incompletos
    
    def _consolidar_fragmentos(
        self,
        fragmentos_por_pedido: Dict[str, List[FragmentoSKU]]
    ) -> List[PalletFisico]:
        """
        Consolida fragmentos en pallets físicos.
        
        Estrategia:
        1. Agrupar fragmentos por tipo de apilabilidad
        2. Para cada tipo, llenar pallets hasta 1.0 respetando MAX_SKUS
        3. SI_MISMO: solo mismo SKU por pallet
        4. NO_APILABLE: siempre pallets individuales
        """
        if not self.permite_consolidacion:
            # Sin consolidación: 1 fragmento = 1 pallet
            return self._crear_pallets_sin_consolidar(fragmentos_por_pedido)
        
        # Agrupar todos los fragmentos por tipo
        fragmentos_por_tipo = defaultdict(list)
        for pedido_id, fragmentos in fragmentos_por_pedido.items():
            for frag in fragmentos:
                fragmentos_por_tipo[frag.tipo].append(frag)
        
        pallets = []
        pallet_counter = 0
        
        for tipo, fragmentos in fragmentos_por_tipo.items():
            if tipo == TipoApilabilidad.NO_APILABLE:
                # NO_APILABLE: cada fragmento es un pallet separado
                for frag in fragmentos:
                    pallets.append(PalletFisico(
                        id_pallet=f"P{pallet_counter}",
                        fragmentos=(frag,),
                        tipo=tipo,
                        altura=frag.altura
                    ))
                    pallet_counter += 1
            
            elif tipo == TipoApilabilidad.SI_MISMO:
                # SI_MISMO: agrupar por SKU
                fragmentos_por_sku = defaultdict(list)
                for frag in fragmentos:
                    fragmentos_por_sku[frag.sku].append(frag)
                
                for sku, frags_sku in fragmentos_por_sku.items():
                    # Separar completos de incompletos
                    completos, incompletos = self._separar_fragmentos_completos(frags_sku)
                    
                    altura_max = max(f.altura for f in frags_sku)
                    
                    # Crear un pallet por cada fragmento completo
                    for frag in completos:
                        pallets.append(PalletFisico(
                            id_pallet=f"P{pallet_counter}",
                            fragmentos=(frag,),
                            tipo=tipo,
                            altura=altura_max
                        ))
                        pallet_counter += 1
                    
                    # Consolidar solo los incompletos
                    if incompletos:
                        # Ordenar por cantidad descendente
                        frags_ord = sorted(incompletos, key=lambda f: f.cantidad, reverse=True)
                        
                        pallet_actual = []
                        cantidad_acum = 0.0
                        
                        for frag in frags_ord:
                            if cantidad_acum + frag.cantidad <= 1.0:
                                pallet_actual.append(frag)
                                cantidad_acum += frag.cantidad
                            else:
                                # Crear pallet y empezar uno nuevo
                                if pallet_actual:
                                    pallets.append(PalletFisico(
                                        id_pallet=f"P{pallet_counter}",
                                        fragmentos=tuple(pallet_actual),
                                        tipo=tipo,
                                        altura=altura_max
                                    ))
                                    pallet_counter += 1
                                
                                pallet_actual = [frag]
                                cantidad_acum = frag.cantidad
                        
                        # Último pallet de incompletos
                        if pallet_actual:
                            pallets.append(PalletFisico(
                                id_pallet=f"P{pallet_counter}",
                                fragmentos=tuple(pallet_actual),
                                tipo=tipo,
                                altura=altura_max
                            ))
                            pallet_counter += 1
                            
            else:
                # BASE, SUPERIOR, FLEXIBLE: consolidar respetando MAX_SKUS
                pallets.extend(
                    self._consolidar_tipo_general(fragmentos, tipo, pallet_counter)
                )
                pallet_counter += len(pallets)
        
        return pallets
    
    def _consolidar_tipo_general(
        self,
        fragmentos: List[FragmentoSKU],
        tipo: TipoApilabilidad,
        start_counter: int
    ) -> List[PalletFisico]:
        """
        Consolida fragmentos de tipo general (BASE, SUPERIOR, FLEXIBLE).
        Optimización: fragmentos completos se convierten directamente en pallets.
        Solo consolida fragmentos incompletos.
        """
        # Separar completos de incompletos
        completos, incompletos = self._separar_fragmentos_completos(fragmentos)
        
        pallets = []
        counter = start_counter
        
        # 1. Crear pallets directamente para fragmentos completos
        for frag in completos:
            pallets.append(PalletFisico(
                id_pallet=f"P{counter}",
                fragmentos=(frag,),
                tipo=tipo,
                altura=frag.altura
            ))
            counter += 1
        
        # 2. Consolidar solo fragmentos incompletos usando algoritmo greedy
        if incompletos:
            # Ordenar por cantidad descendente (First Fit Decreasing)
            fragmentos_ord = sorted(incompletos, key=lambda f: f.cantidad, reverse=True)
            
            pallets_abiertos: List[List[FragmentoSKU]] = []
            
            for frag in fragmentos_ord:
                colocado = False
                
                # Intentar agregar a pallet existente
                for pallet_frags in pallets_abiertos:
                    cantidad_actual = sum(f.cantidad for f in pallet_frags)
                    skus_actuales = {f.sku for f in pallet_frags}
                    
                    # Verificar espacio y límite de SKUs
                    if cantidad_actual + frag.cantidad <= 1.0:
                        if frag.sku in skus_actuales or len(skus_actuales) < self.max_skus_por_pallet:
                            pallet_frags.append(frag)
                            colocado = True
                            break
                
                # Si no cupo en ninguno, crear nuevo pallet
                if not colocado:
                    pallets_abiertos.append([frag])
            
            # Convertir pallets abiertos a PalletFisico
            for frags in pallets_abiertos:
                altura_max = max(f.altura for f in frags)
                pallets.append(PalletFisico(
                    id_pallet=f"P{counter}",
                    fragmentos=tuple(frags),
                    tipo=tipo,
                    altura=altura_max
                ))
                counter += 1
        
        return pallets
    
    def _crear_pallets_sin_consolidar(
        self,
        fragmentos_por_pedido: Dict[str, List[FragmentoSKU]]
    ) -> List[PalletFisico]:
        """
        Sin consolidación: cada fragmento es un pallet separado.
        Usado por clientes como Cencosud.
        """
        pallets = []
        counter = 0
        
        for pedido_id, fragmentos in fragmentos_por_pedido.items():
            for frag in fragmentos:
                pallets.append(PalletFisico(
                    id_pallet=f"{pedido_id}_P{counter}",
                    fragmentos=(frag,),
                    tipo=frag.tipo,
                    altura=frag.altura
                ))
                counter += 1
        
        return pallets
    
    def _mapear_pallets_a_pedidos(
        self,
        pallets: List[PalletFisico]
    ) -> Dict[str, Set[str]]:
        """Mapea cada pallet a los pedidos que contribuyen"""
        return {
            pallet.id_pallet: pallet.pedidos
            for pallet in pallets
        }
    
    def _ordenar_pallets(self, pallets: List[PalletFisico]) -> List[PalletFisico]:
        """
        Ordena pallets para colocación óptima.
        
        Prioridad:
        1. NO_APILABLE (más restrictivos)
        2. SI_MISMO (agrupar por SKU)
        3. BASE (fundación)
        4. FLEXIBLE
        5. SUPERIOR (va arriba)
        """
        prioridades = {
            TipoApilabilidad.NO_APILABLE: 0,
            TipoApilabilidad.SI_MISMO: 1,
            TipoApilabilidad.BASE: 2,
            TipoApilabilidad.FLEXIBLE: 3,
            TipoApilabilidad.SUPERIOR: 4
        }
        
        return sorted(
            pallets,
            key=lambda p: (
                prioridades.get(p.tipo, 5),
                p.sku_dominante or "",
                -p.altura,
                -p.cantidad_total
            )
        )
    
    def _colocar_pallet(self, pallet: PalletFisico, posiciones: List[Posicion]) -> bool:
        """
        Intenta colocar un pallet en las posiciones disponibles.
        
        Estrategia:
        1. Intentar apilar en posición existente
        2. Si no, usar nueva posición vacía
        3. Para SUPERIOR: solo ir al piso si no hay BASE/FLEXIBLE disponibles
        """
        # Estrategia 1: Apilar
        for pos in posiciones:
            if not pos.esta_vacia() and pos.puede_apilar(pallet, self.max_altura):
                pos.agregar(pallet)
                return True
        
        # Estrategia 2: Nueva posición
        pos_vacia = next((p for p in posiciones if p.esta_vacia()), None)
        if pos_vacia:
            # Si es SUPERIOR, verificar si hay BASE o FLEXIBLE esperando para ir al piso
            if pallet.tipo == TipoApilabilidad.SUPERIOR:
                # Buscar si hay pallets BASE o FLEXIBLE que aún no están colocados
                # que podrían servir como base para este SUPERIOR
                # Solo permitir SUPERIOR en el piso como última opción
                return False  # No colocar SUPERIOR en piso todavía
            
            # Para otros tipos que pueden ir al suelo
            if pallet.tipo in {
                TipoApilabilidad.BASE,
                TipoApilabilidad.NO_APILABLE,
                TipoApilabilidad.FLEXIBLE,
                TipoApilabilidad.SI_MISMO
            }:
                pos_vacia.agregar(pallet)
                return True
        
        return False
    
    def _colocar_pallet_segunda_pasada(self, pallet: PalletFisico, posiciones: List[Posicion]) -> bool:
        """
        Segunda pasada: permite colocar SUPERIOR en el piso como última opción.
        """
        pos_vacia = next((p for p in posiciones if p.esta_vacia()), None)
        if pos_vacia and pallet.tipo == TipoApilabilidad.SUPERIOR:
            if pos_vacia.puede_apilar(pallet, self.max_altura):
                pos_vacia.agregar(pallet)
                return True
        return False

    def _determinar_pedidos_validos(
        self,
        pallets_colocados: List[PalletFisico],
        pallets_rechazados: List[PalletFisico],
        fragmentos_por_pedido: Dict[str, List[FragmentoSKU]]
    ) -> Tuple[List[str], List[str]]:
        """
        Determina qué pedidos están COMPLETOS (todos sus fragmentos colocados).
        
        Un pedido es válido solo si TODOS sus fragmentos están en pallets_colocados.
        """
        # Calcular fragmentos colocados por pedido
        fragmentos_colocados_por_pedido = defaultdict(float)
        for pallet in pallets_colocados:
            for frag in pallet.fragmentos:
                fragmentos_colocados_por_pedido[frag.pedido] += frag.cantidad
        
        # Calcular total de fragmentos por pedido
        total_fragmentos_por_pedido = {}
        for pedido_id, fragmentos in fragmentos_por_pedido.items():
            total_fragmentos_por_pedido[pedido_id] = sum(f.cantidad for f in fragmentos)
        
        # Clasificar pedidos
        incluidos = []
        rechazados = []
        
        for pedido_id in fragmentos_por_pedido.keys():
            colocado = fragmentos_colocados_por_pedido.get(pedido_id, 0.0)
            total = total_fragmentos_por_pedido[pedido_id]
            
            # Tolerancia: 95% colocado = completo
            if colocado >= total * 0.95:
                incluidos.append(pedido_id)
            else:
                rechazados.append(pedido_id)
        
        return incluidos, rechazados


# === Funciones Helper de Alto Nivel ===

def extraer_fragmentos_de_pedidos(pedidos_data: List[Dict]) -> Dict[str, List[FragmentoSKU]]:
    """
    Extrae fragmentos de SKUs desde datos de pedidos.
    
    Maneja dos formatos:
    1. Con detalle SKU: SKUS = [{sku, pallets, tipo_apilabilidad, altura}, ...]
    2. Sin detalle: usa agregados (BASE, SUPERIOR, PALLETS, ...)
    
    Returns:
        {pedido_id: [FragmentoSKU, ...]}
    """
    fragmentos_por_pedido = {}
    
    for data in pedidos_data:
        pedido_id = str(data['PEDIDO'])
        skus_data = data.get('SKUS', [])
        
        if skus_data:
            # Formato 1: Con detalle SKU
            fragmentos = _extraer_desde_skus_detallados(pedido_id, skus_data)
        else:
            # Formato 2: Sin detalle (fallback)
            fragmentos = _extraer_desde_agregados(pedido_id, data)
        
        fragmentos_por_pedido[pedido_id] = fragmentos
    
    return fragmentos_por_pedido


def _extraer_desde_skus_detallados(
    pedido_id: str,
    skus_data: List[Dict]
) -> List[FragmentoSKU]:
    """
    Extrae fragmentos desde SKUS detallados.
    
    Ejemplo:
    {'sku': 'SKU001', 'pallets': 1.2, 'tipo_apilabilidad': 'BASE', 'altura_pallet': 120}
    →  FragmentoSKU(sku='SKU001', cantidad=1.0, ...) +
       FragmentoSKU(sku='SKU001', cantidad=0.2, ...)
    """
    fragmentos = []
    
    for sku_info in skus_data:
        sku = str(sku_info['sku'])
        cantidad_total = float(sku_info.get('pallets', 1.0))
        tipo = TipoApilabilidad.from_string(sku_info.get('tipo_apilabilidad', 'FLEXIBLE'))
        altura = float(sku_info.get('altura_pallet', 120))
        
        # Separar en completos + fracción
        completos = int(cantidad_total)
        fraccion = cantidad_total - completos
        
        # Fragmentos completos (1.0 cada uno)
        for i in range(completos):
            fragmentos.append(FragmentoSKU(
                sku=sku,
                pedido=pedido_id,
                cantidad=1.0,
                tipo=tipo,
                altura=altura
            ))
        
        # Fragmento incompleto
        if fraccion > 0:
            fragmentos.append(FragmentoSKU(
                sku=sku,
                pedido=pedido_id,
                cantidad=fraccion,
                tipo=tipo,
                altura=altura
            ))
    
    return fragmentos


def _extraer_desde_agregados(pedido_id: str, data: Dict) -> List[FragmentoSKU]:
    """
    Extrae fragmentos desde columnas agregadas.
    
    Ejemplo:
    {'PALLETS': 3.0, 'BASE': 2.0, 'SUPERIOR': 1.0}
    → 2 fragmentos BASE + 1 fragmento SUPERIOR
    """
    altura_default = float(data.get('ALTURA_PALLET', 120))
    
    tipos_cantidades = {
        TipoApilabilidad.BASE: float(data.get('BASE', 0)),
        TipoApilabilidad.SUPERIOR: float(data.get('SUPERIOR', 0)),
        TipoApilabilidad.FLEXIBLE: float(data.get('FLEXIBLE', 0)),
        TipoApilabilidad.NO_APILABLE: float(data.get('NO_APILABLE', 0)),
        TipoApilabilidad.SI_MISMO: float(data.get('SI_MISMO', 0))
    }
    
    # Si no hay desglose, asumir todo FLEXIBLE
    suma = sum(tipos_cantidades.values())
    if suma == 0:
        total_pallets = float(data.get('PALLETS', 1))
        tipos_cantidades[TipoApilabilidad.FLEXIBLE] = total_pallets
    
    fragmentos = []
    
    for tipo, cantidad_total in tipos_cantidades.items():
        if cantidad_total <= 0:
            continue
        
        completos = int(cantidad_total)
        fraccion = cantidad_total - completos
        
        # Fragmentos completos
        for i in range(completos):
            fragmentos.append(FragmentoSKU(
                sku=f"{pedido_id}_GEN_{tipo.value}_{i}",
                pedido=pedido_id,
                cantidad=1.0,
                tipo=tipo,
                altura=altura_default
            ))
        
        # Fracción
        if fraccion > 0:
            fragmentos.append(FragmentoSKU(
                sku=f"{pedido_id}_GEN_{tipo.value}_FRAC",
                pedido=pedido_id,
                cantidad=fraccion,
                tipo=tipo,
                altura=altura_default
            ))
    
    return fragmentos


def validar_pedidos_en_camion(
    pedidos_data: List[Dict],
    cliente: str,
    tipo_camion: str = 'normal'
) -> ResultadoValidacion:
    """
    API de alto nivel: valida si pedidos caben en camión.
    
    Args:
        pedidos_data: Lista de pedidos con PEDIDO, SKUS (o agregados)
        cliente: Nombre del cliente (para config)
        tipo_camion: 'normal' o 'bh'
    
    Returns:
        ResultadoValidacion con pedidos incluidos/rechazados
    """
    validator = StackingValidator.from_config(cliente, tipo_camion)
    fragmentos_por_pedido = extraer_fragmentos_de_pedidos(pedidos_data)
    return validator.validar_pedidos(fragmentos_por_pedido)