# optimization/order_splitting.py
"""
Módulo genérico de división de pedidos grandes.
Detecta pedidos que exceden capacidad de camión y los divide en pedidos hijos.
Los pedidos hijos comparten el mismo PO pero tienen restricción de no ir juntos.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple
from enum import Enum
import math
import copy

from models.domain import Pedido, SKU, TruckCapacity


class SplitReason(Enum):
    EXCEEDS_PALLET_LIMIT = "exceeds_pallet_limit"
    EXCEEDS_WEIGHT_LIMIT = "exceeds_weight_limit"
    EXCEEDS_VOLUME_LIMIT = "exceeds_volume_limit"


@dataclass
class SplitConfiguration:
    max_pallets: int = 30
    max_weight: float = 23000.0
    max_volume: float = 70000.0
    threshold_factor: float = 0.95
    
    @classmethod
    def from_truck_capacity(cls, cap: TruckCapacity) -> 'SplitConfiguration':
        return cls(
            max_pallets=cap.max_pallets,
            max_weight=cap.cap_weight,
            max_volume=cap.cap_volume
        )
    
    @property
    def threshold_pallets(self) -> float:
        return self.max_pallets * self.threshold_factor


@dataclass
class SplitResult:
    original_pedido: Pedido
    requires_split: bool
    split_reason: Optional[SplitReason] = None
    child_pedidos: List[Pedido] = field(default_factory=list)
    message: str = ""
    
    @property
    def num_splits(self) -> int:
        return len(self.child_pedidos)


@dataclass
class SplitterOutput:
    pedidos_expanded: List[Pedido]
    split_results: List[SplitResult]
    total_original: int = 0
    total_expanded: int = 0
    total_splits_realizados: int = 0
    
    def get_summary_for_ui(self) -> Dict[str, Any]:
        splits_detail = []
        for sr in self.split_results:
            if sr.requires_split:
                splits_detail.append({
                    "pedido_original": sr.original_pedido.pedido,
                    "po": sr.original_pedido.po,
                    "pallets_original": sr.original_pedido.pallets,
                    "num_divisiones": sr.num_splits,
                    "razon": sr.split_reason.value if sr.split_reason else None,
                    "mensaje": sr.message,
                    "hijos": [
                        {
                            "pedido_id": child.pedido,
                            "pallets": child.pallets,
                            "peso": child.peso,
                            "volumen": child.volumen,
                            "num_skus": len(child.skus)
                        }
                        for child in sr.child_pedidos
                    ]
                })
        
        return {
            "resumen": {
                "pedidos_originales": self.total_original,
                "pedidos_expandidos": self.total_expanded,
                "pedidos_divididos": self.total_splits_realizados,
                "pedidos_sin_cambio": self.total_original - self.total_splits_realizados
            },
            "divisiones": splits_detail
        }


class OrderSplitter:
    """Divide pedidos grandes en pedidos hijos que caben en un camión."""
    
    def __init__(self, config: SplitConfiguration):
        self.config = config
    
    def process(self, pedidos: List[Pedido]) -> SplitterOutput:
        pedidos_expanded = []
        split_results = []
        splits_count = 0
        
        for pedido in pedidos:
            if self._needs_split(pedido):
                result = self._split_pedido(pedido)
                split_results.append(result)
                pedidos_expanded.extend(result.child_pedidos)
                splits_count += 1
            else:
                # Pedido normal: asignar po_group
                pedido.metadata['po_group'] = pedido.po
                pedido.metadata['is_from_split'] = False
                pedidos_expanded.append(pedido)
        
        return SplitterOutput(
            pedidos_expanded=pedidos_expanded,
            split_results=split_results,
            total_original=len(pedidos),
            total_expanded=len(pedidos_expanded),
            total_splits_realizados=splits_count
        )
    
    def assign_po_groups_only(self, pedidos: List[Pedido]) -> List[Pedido]:
        """
        Opción 2: Solo asigna po_group sin dividir.
        Para cuando los pedidos ya vienen pre-divididos.
        """
        for pedido in pedidos:
            pedido.metadata['po_group'] = pedido.po
            pedido.metadata['is_from_split'] = False
        return pedidos
    
    def _needs_split(self, pedido: Pedido) -> bool:
        return (
            pedido.pallets > self.config.threshold_pallets or
            pedido.peso > self.config.max_weight * self.config.threshold_factor or
            pedido.volumen > self.config.max_volume * self.config.threshold_factor
        )
    
    def _determine_split_reason(self, pedido: Pedido) -> SplitReason:
        if pedido.pallets > self.config.max_pallets:
            return SplitReason.EXCEEDS_PALLET_LIMIT
        if pedido.peso > self.config.max_weight:
            return SplitReason.EXCEEDS_WEIGHT_LIMIT
        return SplitReason.EXCEEDS_VOLUME_LIMIT
    
    def _split_pedido(self, pedido: Pedido) -> SplitResult:
        split_reason = self._determine_split_reason(pedido)
        
        if not pedido.tiene_skus:
            children = self._split_without_skus(pedido)
        else:
            children = self._split_with_skus(pedido)
        
        message = (
            f"Pedido {pedido.pedido} (PO: {pedido.po}) con {pedido.pallets:.1f} pallets "
            f"dividido en {len(children)} pedidos hijos."
        )
        
        return SplitResult(
            original_pedido=pedido,
            requires_split=True,
            split_reason=split_reason,
            child_pedidos=children,
            message=message
        )
    
    def _split_without_skus(self, pedido: Pedido) -> List[Pedido]:
        """División proporcional cuando no hay SKUs."""
        num_splits = math.ceil(pedido.pallets / self.config.max_pallets)
        children = []
        pallets_remaining = pedido.pallets
        
        for i in range(num_splits):
            pallets_this = min(pallets_remaining, self.config.max_pallets)
            ratio = pallets_this / pedido.pallets if pedido.pallets > 0 else 1/num_splits
            
            child = Pedido(
                pedido=f"{pedido.pedido}_SPLIT_{i+1}",
                cd=pedido.cd,
                ce=pedido.ce,
                po=pedido.po,
                peso=pedido.peso * ratio,
                volumen=pedido.volumen * ratio,
                pallets=pallets_this,
                valor=pedido.valor * ratio,
                oc=pedido.oc,
                chocolates=pedido.chocolates,
                valioso=pedido.valioso,
                pdq=pedido.pdq,
                baja_vu=pedido.baja_vu,
                lote_dir=pedido.lote_dir,
                base=pedido.base * ratio,
                superior=pedido.superior * ratio,
                flexible=pedido.flexible * ratio,
                no_apilable=pedido.no_apilable * ratio,
                si_mismo=pedido.si_mismo * ratio,
                metadata={
                    'po_group': pedido.po,
                    'is_from_split': True,
                    'split_index': i + 1,
                    'original_pedido_id': pedido.pedido,
                    'total_splits': num_splits
                }
            )
            children.append(child)
            pallets_remaining -= pallets_this
        
        return children
    
    def _split_with_skus(self, pedido: Pedido) -> List[Pedido]:
        """División manteniendo SKUs completos (bin-packing)."""
        sorted_skus = sorted(pedido.skus, key=lambda s: s.cantidad_pallets, reverse=True)
        
        # Manejar SKUs oversized
        processed_skus = []
        for sku in sorted_skus:
            if sku.cantidad_pallets > self.config.max_pallets:
                processed_skus.extend(self._split_oversized_sku(sku))
            else:
                processed_skus.append(sku)
        
        # Bin-packing
        bins: List[List[SKU]] = []
        bins_pallets: List[float] = []
        bins_peso: List[float] = []
        bins_vol: List[float] = []
        
        for sku in processed_skus:
            placed = False
            for idx in range(len(bins)):
                if self._sku_fits(sku, bins_pallets[idx], bins_peso[idx], bins_vol[idx]):
                    bins[idx].append(sku)
                    bins_pallets[idx] += sku.cantidad_pallets
                    bins_peso[idx] += sku.peso_kg
                    bins_vol[idx] += sku.volumen_m3
                    placed = True
                    break
            
            if not placed:
                bins.append([sku])
                bins_pallets.append(sku.cantidad_pallets)
                bins_peso.append(sku.peso_kg)
                bins_vol.append(sku.volumen_m3)
        
        # Crear pedidos hijos
        children = []
        for i, skus in enumerate(bins):
            child = self._create_child_from_skus(pedido, skus, i + 1, len(bins))
            children.append(child)
        
        return children
    
    def _sku_fits(self, sku: SKU, current_pallets: float, current_peso: float, current_vol: float) -> bool:
        return (
            current_pallets + sku.cantidad_pallets <= self.config.max_pallets and
            current_peso + sku.peso_kg <= self.config.max_weight and
            current_vol + sku.volumen_m3 <= self.config.max_volume
        )
    
    def _split_oversized_sku(self, sku: SKU) -> List[SKU]:
        """Divide un SKU que excede capacidad."""
        num_parts = math.ceil(sku.cantidad_pallets / self.config.max_pallets)
        parts = []
        remaining = sku.cantidad_pallets
        
        for i in range(num_parts):
            pallets_this = min(remaining, self.config.max_pallets)
            ratio = pallets_this / sku.cantidad_pallets
            
            part = SKU(
                sku_id=f"{sku.sku_id}_PART{i+1}",
                pedido_id=sku.pedido_id,
                cantidad_pallets=pallets_this,
                altura_full_pallet_cm=sku.altura_full_pallet_cm,
                altura_picking_cm=sku.altura_picking_cm,
                peso_kg=sku.peso_kg * ratio,
                volumen_m3=sku.volumen_m3 * ratio,
                valor=sku.valor * ratio,
                base=sku.base * ratio,
                superior=sku.superior * ratio,
                flexible=sku.flexible * ratio,
                no_apilable=sku.no_apilable * ratio,
                si_mismo=sku.si_mismo * ratio,
                descripcion=f"{sku.descripcion or sku.sku_id} (Parte {i+1}/{num_parts})",
                metadata={'original_sku_id': sku.sku_id, 'is_sku_part': True}
            )
            parts.append(part)
            remaining -= pallets_this
        
        return parts
    
    def _create_child_from_skus(self, original: Pedido, skus: List[SKU], index: int, total: int) -> Pedido:
        child_id = f"{original.pedido}_SPLIT_{index}"
        
        # Actualizar pedido_id en SKUs
        updated_skus = []
        for sku in skus:
            new_sku = copy.copy(sku)
            new_sku.pedido_id = child_id
            updated_skus.append(new_sku)
        
        return Pedido(
            pedido=child_id,
            cd=original.cd,
            ce=original.ce,
            po=original.po,
            peso=sum(s.peso_kg for s in updated_skus),
            volumen=sum(s.volumen_m3 for s in updated_skus),
            pallets=sum(s.cantidad_pallets for s in updated_skus),
            valor=sum(s.valor for s in updated_skus),
            oc=original.oc,
            chocolates=original.chocolates,
            valioso=original.valioso,
            pdq=original.pdq,
            baja_vu=original.baja_vu,
            lote_dir=original.lote_dir,
            base=sum(s.base for s in updated_skus),
            superior=sum(s.superior for s in updated_skus),
            flexible=sum(s.flexible for s in updated_skus),
            no_apilable=sum(s.no_apilable for s in updated_skus),
            si_mismo=sum(s.si_mismo for s in updated_skus),
            skus=updated_skus,
            metadata={
                'po_group': original.po,
                'is_from_split': True,
                'split_index': index,
                'original_pedido_id': original.pedido,
                'total_splits': total,
                'skus_en_split': [s.sku_id for s in updated_skus]
            }
        )