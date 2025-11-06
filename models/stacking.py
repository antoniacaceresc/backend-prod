"""
Modelos de negocio para apilamiento y validación física.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Set
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models.domain import TruckCapacity

class CategoriaApilamiento(str, Enum):
    """
    Categorías de apilabilidad de SKUs.
    Mapean directamente a las columnas del Excel.
    """
    NO_APILABLE = "no_apilable"       # Columna: "No Apilable"
    BASE = "base"                      # Columna: "Base"
    SUPERIOR = "superior"              # Columna: "Superior"
    SI_MISMO = "si_mismo"              # Columna: "Apilable por si mismo"
    FLEXIBLE = "flexible"              # Columna: "Flexible"


@dataclass
class FragmentoSKU:
    """
    Porción de un SKU que va en un pallet físico.
    Permite consolidación de múltiples SKUs en un solo pallet.
    
    Ejemplo:
        Si un pedido tiene 2.5 pallets de SKU_A:
        - FragmentoSKU(sku_id="SKU_A", fraccion=1.0) → Pallet 1 completo
        - FragmentoSKU(sku_id="SKU_A", fraccion=1.0) → Pallet 2 completo
        - FragmentoSKU(sku_id="SKU_A", fraccion=0.5) → Medio pallet
    """
    sku_id: str
    pedido_id: str
    fraccion: float  # 0.0 - 1.0 (cuánto del pallet completo representa)
    
    # Dimensiones físicas
    altura_cm: float      # Altura de ESTE fragmento (fraccion × altura_pallet_completo)
    peso_kg: float        # Peso de ESTE fragmento
    volumen_m3: float     # Volumen de ESTE fragmento
    
    # Apilabilidad
    categoria: CategoriaApilamiento
    max_altura_apilable_cm: Optional[float] = None  # Solo para SI_MISMO
    
    # Metadata
    descripcion: Optional[str] = None
    es_picking: bool = False  # True si usa "Altura picking" en vez de "Altura full pallet"
    
    def __post_init__(self):
        if self.fraccion <= 0 or self.fraccion > 1.0:
            raise ValueError(
                f"Fracción debe estar entre 0 y 1, got {self.fraccion} "
                f"para SKU {self.sku_id}"
            )
        
        if self.altura_cm <= 0:
            raise ValueError(
                f"Altura debe ser positiva, got {self.altura_cm}cm "
                f"para SKU {self.sku_id}"
            )
        
        # Si es SI_MISMO y no tiene límite, asumir sin límite
        if self.categoria == CategoriaApilamiento.SI_MISMO:
            if self.max_altura_apilable_cm is None:
                self.max_altura_apilable_cm = float('inf')


@dataclass
class PalletFisico:
    """
    Unidad física en el camión.
    Puede contener fragmentos de múltiples SKUs consolidados.
    
    Base estándar: 80cm × 120cm (no se modela, es constante)
    Altura variable: suma de alturas de fragmentos
    """
    id: str
    posicion_id: int  # Índice de posición en el piso del camión (0-29)
    nivel: int        # 0 = piso, 1 = primer nivel apilado, 2 = segundo nivel, etc.
    
    fragmentos: List[FragmentoSKU] = field(default_factory=list)
    
    # Metadata calculada
    pedidos_ids: Set[str] = field(default_factory=set)
    
    @property
    def altura_total_cm(self) -> float:
        """Altura total del pallet (suma de fragmentos)"""
        return sum(f.altura_cm for f in self.fragmentos)
    
    @property
    def peso_total_kg(self) -> float:
        """Peso total del pallet"""
        return sum(f.peso_kg for f in self.fragmentos)
    
    @property
    def volumen_total_m3(self) -> float:
        """Volumen total del pallet"""
        return sum(f.volumen_m3 for f in self.fragmentos)
    
    @property
    def es_consolidado(self) -> bool:
        """Indica si tiene fragmentos de múltiples pedidos"""
        return len(self.pedidos_ids) > 1
    
    @property
    def num_skus(self) -> int:
        """Cantidad de SKUs diferentes en el pallet"""
        return len({f.sku_id for f in self.fragmentos})
    
    @property
    def num_pedidos(self) -> int:
        """Cantidad de pedidos diferentes en el pallet"""
        return len(self.pedidos_ids)
    
    @property
    def skus_unicos(self) -> Set[str]:
        """SKUs diferentes en este pallet"""
        return {frag.sku_id for frag in self.fragmentos}
    
    @property
    def num_skus_diferentes(self) -> int:
        """Cantidad de SKUs diferentes"""
        return len(self.skus_unicos)
    
    @property
    def tiene_pickings(self) -> bool:
        """Indica si contiene algún picking"""
        return any(frag.es_picking for frag in self.fragmentos)
    
    @property
    def tiene_full_pallets(self) -> bool:
        """Indica si contiene algún pallet completo"""
        return any(not frag.es_picking for frag in self.fragmentos)
    
    def agregar_fragmento(self, fragmento: FragmentoSKU):
        """Agrega un fragmento al pallet"""
        self.fragmentos.append(fragmento)
        self.pedidos_ids.add(fragmento.pedido_id)
    
    def validar_integridad(self) -> tuple[bool, Optional[str]]:
        """
        Valida que el pallet sea físicamente coherente.
        
        Returns:
            (es_valido, razon_si_no)
        """
        if not self.fragmentos:
            return False, "Pallet vacío"
        
        if self.altura_total_cm <= 0:
            return False, f"Altura inválida: {self.altura_total_cm}cm"
        
        # Validar que fragmentos no excedan fracción 1.0 por SKU
        fracciones_por_sku: Dict[str, float] = {}
        for frag in self.fragmentos:
            fracciones_por_sku[frag.sku_id] = \
                fracciones_por_sku.get(frag.sku_id, 0) + frag.fraccion
        
        for sku_id, frac_total in fracciones_por_sku.items():
            if frac_total > 1.0:
                return False, f"SKU {sku_id} excede fracción 1.0: {frac_total}"
        
        return True, None


@dataclass
class PosicionCamion:
    """
    Posición física en el piso del camión.
    Puede tener múltiples pallets apilados verticalmente.
    
    Base: 80cm × 120cm (estándar, no se modela)
    Altura: hasta altura_maxima_cm
    """
    id: int  # Índice de posición (0, 1, 2, ..., max_positions-1)
    pallets_apilados: List[PalletFisico] = field(default_factory=list)
    
    # Límites físicos
    altura_maxima_cm: float = 270  # Altura estándar de camión
    
    @property
    def altura_usada_cm(self) -> float:
        """Altura total ocupada por pallets apilados"""
        return sum(p.altura_total_cm for p in self.pallets_apilados)
    
    @property
    def espacio_disponible_cm(self) -> float:
        """Espacio vertical restante"""
        return max(0, self.altura_maxima_cm - self.altura_usada_cm)
    
    @property
    def num_pallets(self) -> int:
        """Cantidad de pallets en esta posición"""
        return len(self.pallets_apilados)
    
    @property
    def esta_vacia(self) -> bool:
        """Indica si no hay pallets en esta posición"""
        return len(self.pallets_apilados) == 0
    
    def puede_apilar(self, pallet: PalletFisico) -> tuple[bool, Optional[str]]:
        """
        Verifica si se puede apilar un pallet adicional.
        
        Returns:
            (puede_apilar, razon_si_no)
        """
        # 1. Validar espacio físico
        if pallet.altura_total_cm > self.espacio_disponible_cm:
            return False, (
                f"Excede altura: {pallet.altura_total_cm:.1f}cm > "
                f"{self.espacio_disponible_cm:.1f}cm disponibles"
            )
        
        # 2. Si posición vacía, cualquier pallet puede ir
        if self.esta_vacia:
            return True, None
        
        # 3. Validar reglas de apilamiento con pallet inferior
        pallet_inferior = self.pallets_apilados[-1]
        return self._validar_apilamiento_sobre(pallet_inferior, pallet)
    
    def _validar_apilamiento_sobre(
        self, 
        inferior: PalletFisico, 
        superior: PalletFisico
    ) -> tuple[bool, Optional[str]]:
        """
        Valida reglas de apilamiento entre dos pallets.
        
        Reglas:
        1. NO_APILABLE nunca tiene nada encima
        2. NO_APILABLE nunca va encima de nada
        3. BASE acepta SUPERIOR o FLEXIBLE encima
        4. SI_MISMO solo acepta mismo SKU encima (con límite de altura)
        5. FLEXIBLE actúa como BASE (acepta SUPERIOR/FLEXIBLE encima)
        6. SUPERIOR puede ir sobre BASE o FLEXIBLE
        
        Returns:
            (es_valido, razon_si_no)
        """
        # Obtener categorías dominantes
        cat_inf = self._categoria_dominante(inferior)
        cat_sup = self._categoria_dominante(superior)
        
        # Regla 1: NO_APILABLE nunca tiene nada encima
        if cat_inf == CategoriaApilamiento.NO_APILABLE:
            return False, "Pallet inferior es NO_APILABLE (no acepta nada encima)"
        
        # Regla 2: NO_APILABLE nunca va encima de nada
        if cat_sup == CategoriaApilamiento.NO_APILABLE:
            return False, "Pallet superior es NO_APILABLE (no puede ir encima)"
        
        # Regla 3: BASE acepta SUPERIOR o FLEXIBLE
        if cat_inf == CategoriaApilamiento.BASE:
            if cat_sup in (CategoriaApilamiento.SUPERIOR, CategoriaApilamiento.FLEXIBLE):
                return True, None
            return False, f"BASE no acepta {cat_sup.value} encima (solo SUPERIOR o FLEXIBLE)"
        
        # Regla 4: SI_MISMO solo acepta mismo SKU (validar límite de altura)
        if cat_inf == CategoriaApilamiento.SI_MISMO:
            skus_inf = {f.sku_id for f in inferior.fragmentos}
            skus_sup = {f.sku_id for f in superior.fragmentos}
            
            # Debe ser exactamente el mismo SKU único
            if skus_inf != skus_sup or len(skus_inf) != 1:
                return False, "SI_MISMO requiere exactamente el mismo SKU único en ambos pallets"
            
            # Validar límite de altura acumulada
            sku_id = next(iter(skus_inf))
            
            # Buscar límite de altura del SKU
            frag_con_limite = next(
                (f for f in inferior.fragmentos if f.sku_id == sku_id),
                None
            )
            
            if frag_con_limite and frag_con_limite.max_altura_apilable_cm:
                # Calcular altura acumulada de este SKU en esta posición
                altura_acumulada = sum(
                    p.altura_total_cm 
                    for p in self.pallets_apilados 
                    if any(f.sku_id == sku_id for f in p.fragmentos)
                ) + superior.altura_total_cm
                
                if altura_acumulada > frag_con_limite.max_altura_apilable_cm:
                    return False, (
                        f"Excede altura máxima apilable para SKU {sku_id}: "
                        f"{altura_acumulada:.1f}cm > {frag_con_limite.max_altura_apilable_cm:.1f}cm"
                    )
            
            return True, None
        
        # Regla 5: FLEXIBLE actúa como BASE
        if cat_inf == CategoriaApilamiento.FLEXIBLE:
            if cat_sup in (CategoriaApilamiento.SUPERIOR, CategoriaApilamiento.FLEXIBLE):
                return True, None
            return False, f"FLEXIBLE no acepta {cat_sup.value} encima (solo SUPERIOR o FLEXIBLE)"
        
        # Regla 6: SUPERIOR generalmente no acepta nada encima (solo si es FLEXIBLE o SUPERIOR)
        if cat_inf == CategoriaApilamiento.SUPERIOR:
            if cat_sup in (CategoriaApilamiento.FLEXIBLE, CategoriaApilamiento.SUPERIOR):
                return True, None
            return False, f"SUPERIOR no acepta {cat_sup.value} encima"
        
        # Default: no permitir
        return False, f"Combinación no permitida: {cat_inf.value} + {cat_sup.value}"
    
    def _categoria_dominante(self, pallet: PalletFisico) -> CategoriaApilamiento:
        """
        Determina la categoría dominante de un pallet consolidado.
        
        Prioridad (más restrictivo primero):
        1. NO_APILABLE (si alguno es NO_APILABLE, todo es NO_APILABLE)
        2. BASE
        3. SUPERIOR
        4. SI_MISMO
        5. FLEXIBLE (menos restrictivo)
        
        Returns:
            CategoriaApilamiento dominante
        """
        categorias = [f.categoria for f in pallet.fragmentos]
        
        if CategoriaApilamiento.NO_APILABLE in categorias:
            return CategoriaApilamiento.NO_APILABLE
        if CategoriaApilamiento.BASE in categorias:
            return CategoriaApilamiento.BASE
        if CategoriaApilamiento.SUPERIOR in categorias:
            return CategoriaApilamiento.SUPERIOR
        if CategoriaApilamiento.SI_MISMO in categorias:
            return CategoriaApilamiento.SI_MISMO
        return CategoriaApilamiento.FLEXIBLE
    
    def apilar(self, pallet: PalletFisico) -> bool:
        """
        Apila un pallet en esta posición si es posible.
        Actualiza nivel y posicion_id del pallet.
        
        Returns:
            True si se apiló exitosamente
        """
        puede, razon = self.puede_apilar(pallet)
        if not puede:
            return False
        
        pallet.nivel = len(self.pallets_apilados)
        pallet.posicion_id = self.id
        self.pallets_apilados.append(pallet)
        return True


@dataclass
class LayoutCamion:
    """
    Layout completo del camión con todas las posiciones.
    Representa el estado físico del camión después de apilamiento.
    """
    camion_id: str
    max_posiciones: int  # Capacidad de posiciones en el piso (ej: 30)
    altura_maxima_cm: float
    
    posiciones: List[PosicionCamion] = field(default_factory=list)
    
    def __post_init__(self):
        # Inicializar posiciones vacías si no existen
        if not self.posiciones:
            self.posiciones = [
                PosicionCamion(id=i, altura_maxima_cm=self.altura_maxima_cm)
                for i in range(self.max_posiciones)
            ]
    
    @property
    def posiciones_usadas(self) -> int:
        """Cantidad de posiciones con al menos un pallet"""
        return sum(1 for p in self.posiciones if not p.esta_vacia)
    
    @property
    def posiciones_disponibles(self) -> int:
        """Cantidad de posiciones vacías"""
        return self.max_posiciones - self.posiciones_usadas
    
    @property
    def total_pallets(self) -> int:
        """Total de pallets físicos en el camión"""
        return sum(p.num_pallets for p in self.posiciones)
    
    @property
    def altura_promedio_usada(self) -> float:
        """Altura promedio usada en posiciones ocupadas"""
        usadas = [p.altura_usada_cm for p in self.posiciones if not p.esta_vacia]
        return sum(usadas) / len(usadas) if usadas else 0
    
    @property
    def altura_maxima_usada(self) -> float:
        """Altura máxima usada en alguna posición"""
        usadas = [p.altura_usada_cm for p in self.posiciones if not p.esta_vacia]
        return max(usadas) if usadas else 0
    
    @property
    def aprovechamiento_altura(self) -> float:
        """Porcentaje de altura aprovechada en promedio (0-1)"""
        if self.posiciones_usadas == 0:
            return 0.0
        return self.altura_promedio_usada / self.altura_maxima_cm
    
    @property
    def aprovechamiento_posiciones(self) -> float:
        """Porcentaje de posiciones usadas (0-1)"""
        return self.posiciones_usadas / self.max_posiciones if self.max_posiciones > 0 else 0
    
    @classmethod
    def from_truck_capacity(
        cls,
        camion_id: str,
        capacidad: TruckCapacity
    ) -> LayoutCamion:
        """
        Constructor desde TruckCapacity.
        Usa la altura específica del tipo de camión.
        """
        
        return cls(
            camion_id=camion_id,
            max_posiciones=capacidad.max_positions,
            altura_maxima_cm=capacidad.altura_cm  # NUEVO: usa altura de capacidad
        )
    
    def to_dict(self) -> Dict:
        """
        Exporta a formato API para frontend.
        
        Returns:
            Dict con estructura completa del layout
        """
        return {
            'camion_id': self.camion_id,
            'max_posiciones': self.max_posiciones,
            'posiciones_usadas': self.posiciones_usadas,
            'posiciones_disponibles': self.posiciones_disponibles,
            'total_pallets': self.total_pallets,
            'altura_maxima_cm': self.altura_maxima_cm,
            'altura_promedio_usada': round(self.altura_promedio_usada, 1),
            'altura_maxima_usada': round(self.altura_maxima_usada, 1),
            'aprovechamiento_altura': round(self.aprovechamiento_altura, 3),
            'aprovechamiento_posiciones': round(self.aprovechamiento_posiciones, 3),
            'posiciones': [
                {
                    'id': pos.id,
                    'altura_usada_cm': round(pos.altura_usada_cm, 1),
                    'espacio_disponible_cm': round(pos.espacio_disponible_cm, 1),
                    'num_pallets': pos.num_pallets,
                    'pallets': [
                        {
                            'id': pallet.id,
                            'nivel': pallet.nivel,
                            'altura_cm': round(pallet.altura_total_cm, 1),
                            'peso_kg': round(pallet.peso_total_kg, 1),
                            'volumen_m3': round(pallet.volumen_total_m3, 3),
                            'consolidado': pallet.es_consolidado,
                            'num_skus': pallet.num_skus,
                            'num_pedidos': pallet.num_pedidos,
                            'pedidos': list(pallet.pedidos_ids),
                            'fragmentos': [
                                {
                                    'sku_id': f.sku_id,
                                    'pedido_id': f.pedido_id,
                                    'fraccion': round(f.fraccion, 2),
                                    'altura_cm': round(f.altura_cm, 1),
                                    'peso_kg': round(f.peso_kg, 1),
                                    'categoria': f.categoria.value,
                                    'es_picking': f.es_picking
                                }
                                for f in pallet.fragmentos
                            ]
                        }
                        for pallet in pos.pallets_apilados
                    ]
                }
                for pos in self.posiciones if not pos.esta_vacia
            ]
        }