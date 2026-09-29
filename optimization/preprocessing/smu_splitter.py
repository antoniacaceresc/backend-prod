# optimization/preprocessing/smu_splitter.py
"""
Pre-procesador de pedidos para SMU.

Divide pedidos grandes en sub-pedidos por líneas completas de SKU,
agrupando por compatibilidad de stacking, para que los solvers existentes
(VCU CP-SAT, BinPacking) puedan combinarlos en camiones óptimos.

Problema: Los pedidos SMU son grandes (20-30 pal) y no caben juntos por
restricciones de posiciones de apilabilidad y altura (Alvi 230cm, Rendic 240/264cm).

Criterio de CUÁNDO dividir: posiciones de apilabilidad > 50% del max_positions.
Criterio de CÓMO dividir: separar por categoría de stacking
  - Grupo "eficiente": SKUs base + superior (se complementan al apilar)
  - Grupo "complejo": SKUs flexible + no_apilable + si_mismo + picking
La validación exacta de alturas la resuelve el solver + HeightValidator.

Reglas:
- Solo se dividen líneas completas de SKU (atómicas, no se parten pallets)
- Se minimiza la cantidad de divisiones (cada split = proceso manual en SAP)
- Se preserva trazabilidad: pedido_original → sub-pedidos
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Dict, Any, Tuple, Optional

from models.domain import Pedido, SKU, TruckCapacity
from core.constants import SCALE_PALLETS


@dataclass
class SplitInfo:
    """Información de un pedido dividido para el frontend."""
    pedido_original: str
    po: str
    cd: str
    ce: str
    total_skus: int
    total_pallets: float
    sub_pedidos: List[Dict[str, Any]] = field(default_factory=list)
    # Cada sub_pedido: { pedido_id, pallets, peso, volumen, skus: [{sku_id, pallets, descripcion, categoria}] }


def dividir_pedidos_smu(
    pedidos: List[Pedido],
    capacidad: TruckCapacity,
    target_fraccion: float = 0.5,
) -> Tuple[List[Pedido], List[SplitInfo]]:
    """
    Pre-procesa pedidos SMU: divide los que usan demasiadas posiciones de apilabilidad.

    Args:
        pedidos: Lista original de pedidos (con SKUs)
        capacidad: Capacidad del camión principal (paquetera)
        target_fraccion: Fracción de max_positions como umbral.
            0.5 = dividir si el pedido usa más del 50% de las posiciones.

    Returns:
        (pedidos_procesados, splits_info)
        - pedidos_procesados: lista con pedidos originales chicos + sub-pedidos de los grandes
        - splits_info: lista de SplitInfo para visualización en frontend
    """
    umbral_posiciones = capacidad.max_positions * target_fraccion

    pedidos_resultado: List[Pedido] = []
    splits: List[SplitInfo] = []

    for pedido in pedidos:
        if not pedido.tiene_skus:
            pedidos_resultado.append(pedido)
            continue

        posiciones = _calcular_posiciones_pedido(pedido)

        if posiciones <= umbral_posiciones:
            pedidos_resultado.append(pedido)
            continue

        sub_pedidos, split_info = _dividir_pedido(pedido, capacidad)
        pedidos_resultado.extend(sub_pedidos)
        splits.append(split_info)

    print(f"[SMU-SPLITTER] {len(pedidos)} pedidos → {len(pedidos_resultado)} "
          f"({len(splits)} divididos, umbral={umbral_posiciones:.1f} pos)")

    return pedidos_resultado, splits


def _calcular_posiciones_pedido(pedido: Pedido) -> float:
    """Calcula posiciones de apilabilidad de un pedido (misma lógica del solver)."""
    base_s = int(pedido.base * SCALE_PALLETS)
    sup_s = int(pedido.superior * SCALE_PALLETS)
    flex_s = int(pedido.flexible * SCALE_PALLETS)
    noap_s = int(pedido.no_apilable * SCALE_PALLETS)
    self_s = int(pedido.si_mismo * SCALE_PALLETS)

    diff = base_s - sup_s
    abs_diff = abs(diff)
    m0 = min(base_s, sup_s)
    m1 = min(abs_diff, flex_s)
    rem = flex_s - m1
    half = (rem + 1) // 2
    m2 = max(abs_diff - flex_s, 0)

    pair_q = self_s // (2 * SCALE_PALLETS)
    self_pairs = pair_q * SCALE_PALLETS
    self_rem = self_s - pair_q * (2 * SCALE_PALLETS)

    total = m0 + m1 + half + m2 + noap_s + self_pairs + self_rem
    return total / SCALE_PALLETS


def _categoria_sku(sku: SKU) -> str:
    """Determina la categoría de stacking dominante de un SKU."""
    # Compuestos van al grupo eficiente (actúan como base/superior)
    if sku.base_simismo > 0:
        return "base"
    if sku.superior_simismo > 0:
        return "superior"

    cats = {
        "base": sku.base,
        "superior": sku.superior,
        "flexible": sku.flexible,
        "no_apilable": sku.no_apilable,
        "si_mismo": sku.si_mismo,
    }
    return max(cats, key=cats.get)


def _dividir_pedido(
    pedido: Pedido,
    capacidad: TruckCapacity,
) -> Tuple[List[Pedido], SplitInfo]:
    """
    Divide un pedido en sub-pedidos por categoría de stacking.

    Estrategia:
    - Grupo "eficiente": SKUs base + superior (se complementan al apilar)
    - Grupo "complejo": SKUs flexible + no_apilable + si_mismo + picking
    - Si un grupo queda vacío, no se crea sub-pedido para él
    - Si un grupo sigue siendo muy grande (>50% posiciones), se sub-divide
      balanceando por posiciones
    """
    skus_eficiente: List[SKU] = []  # base + superior
    skus_complejo: List[SKU] = []   # flexible + no_apilable + si_mismo + picking

    for sku in pedido.skus:
        cat = _categoria_sku(sku)
        if cat in ("base", "superior"):
            skus_eficiente.append(sku)
        else:
            skus_complejo.append(sku)

    # Construir las partes iniciales (filtrar vacías)
    partes_skus: List[List[SKU]] = []
    if skus_eficiente:
        partes_skus.append(skus_eficiente)
    if skus_complejo:
        partes_skus.append(skus_complejo)

    # Si solo hay una categoría, dividir balanceando por posiciones
    if len(partes_skus) == 1:
        partes_skus = _subdividir_por_posiciones(partes_skus[0], capacidad)

    # Sub-dividir partes que siguen siendo muy grandes
    umbral = capacidad.max_positions * 0.5
    partes_final: List[List[SKU]] = []
    for parte in partes_skus:
        pos = _calcular_posiciones_skus(parte)
        if pos > umbral and len(parte) > 1:
            sub = _subdividir_por_posiciones(parte, capacidad)
            partes_final.extend(sub)
        else:
            partes_final.append(parte)

    # Filtrar vacías
    partes_skus = [p for p in partes_final if p]

    # Construir sub-pedidos
    sub_pedidos: List[Pedido] = []
    split_info = SplitInfo(
        pedido_original=pedido.pedido,
        po=pedido.po,
        cd=pedido.cd,
        ce=pedido.ce,
        total_skus=len(pedido.skus),
        total_pallets=round(pedido.pallets_capacidad, 1),
    )

    for idx, skus_parte in enumerate(partes_skus, start=1):
        sub_id = f"{pedido.pedido}_P{idx}"

        # Recalcular agregados desde SKUs
        peso = sum(s.peso_kg for s in skus_parte)
        volumen = sum(s.volumen_m3 for s in skus_parte)
        pallets = sum(s.cantidad_pallets for s in skus_parte)
        valor = sum(s.valor for s in skus_parte)
        base = sum(s.base for s in skus_parte)
        superior = sum(s.superior for s in skus_parte)
        flexible = sum(s.flexible for s in skus_parte)
        no_apilable = sum(s.no_apilable for s in skus_parte)
        si_mismo = sum(s.si_mismo for s in skus_parte)

        # Clonar metadata y marcar como sub-pedido
        meta = dict(pedido.metadata)
        meta["_split_from"] = pedido.pedido
        meta["_split_part"] = idx
        meta["_split_total"] = len(partes_skus)

        sub_pedido = Pedido(
            pedido=sub_id,
            cd=pedido.cd,
            ce=pedido.ce,
            po=pedido.po,
            peso=peso,
            volumen=volumen,
            pallets=pallets,
            valor=valor,
            valor_cafe=pedido.valor_cafe * (pallets / pedido.pallets) if pedido.pallets > 0 else 0,
            oc=pedido.oc,
            chocolates=pedido.chocolates,
            valioso=pedido.valioso,
            pdq=pedido.pdq,
            baja_vu=pedido.baja_vu,
            lote_dir=pedido.lote_dir,
            es_purina=pedido.es_purina,
            base=base,
            superior=superior,
            flexible=flexible,
            no_apilable=no_apilable,
            si_mismo=si_mismo,
            skus=skus_parte,
            metadata=meta,
        )
        sub_pedidos.append(sub_pedido)

        # Info para frontend
        split_info.sub_pedidos.append({
            "pedido_id": sub_id,
            "pallets": round(pallets, 1),
            "peso": round(peso, 0),
            "volumen": round(volumen, 0),
            "skus": [
                {
                    "sku_id": s.sku_id,
                    "pallets": s.cantidad_pallets,
                    "descripcion": s.descripcion or "",
                    "categoria": s.categoria_apilamiento_dominante,
                }
                for s in skus_parte
            ],
        })

    partes_pos = [_calcular_posiciones_skus(p) for p in partes_skus]
    print(f"[SMU-SPLITTER] Pedido {pedido.pedido}: {len(pedido.skus)} SKUs, "
          f"{_calcular_posiciones_pedido(pedido):.1f} pos → {len(sub_pedidos)} partes "
          f"({', '.join(f'{p:.1f}pos' for p in partes_pos)} )")

    return sub_pedidos, split_info


def _calcular_posiciones_skus(skus: List[SKU]) -> float:
    """Calcula posiciones de apilabilidad para una lista de SKUs."""
    base_s = int(sum(s.base for s in skus) * SCALE_PALLETS)
    sup_s = int(sum(s.superior for s in skus) * SCALE_PALLETS)
    flex_s = int(sum(s.flexible for s in skus) * SCALE_PALLETS)
    noap_s = int(sum(s.no_apilable for s in skus) * SCALE_PALLETS)
    self_s = int(sum(s.si_mismo for s in skus) * SCALE_PALLETS)

    diff = base_s - sup_s
    abs_diff = abs(diff)
    m0 = min(base_s, sup_s)
    m1 = min(abs_diff, flex_s)
    rem = flex_s - m1
    half = (rem + 1) // 2
    m2 = max(abs_diff - flex_s, 0)

    pair_q = self_s // (2 * SCALE_PALLETS)
    self_pairs = pair_q * SCALE_PALLETS
    self_rem = self_s - pair_q * (2 * SCALE_PALLETS)

    total = m0 + m1 + half + m2 + noap_s + self_pairs + self_rem
    return total / SCALE_PALLETS


def _subdividir_por_posiciones(
    skus: List[SKU],
    capacidad: TruckCapacity,
) -> List[List[SKU]]:
    """
    Sub-divide una lista de SKUs en 2 partes balanceando por posiciones.
    Usa best-fit: asigna cada SKU a la parte con menos posiciones acumuladas.
    """
    # Ordenar por contribución de posiciones descendente
    def pos_contribution(sku: SKU) -> float:
        return sku.no_apilable + sku.si_mismo + sku.flexible + max(sku.base, sku.superior)

    skus_sorted = sorted(skus, key=pos_contribution, reverse=True)

    parte_a: List[SKU] = []
    parte_b: List[SKU] = []
    pos_a = 0.0
    pos_b = 0.0

    for sku in skus_sorted:
        contrib = pos_contribution(sku)
        if pos_a <= pos_b:
            parte_a.append(sku)
            pos_a += contrib
        else:
            parte_b.append(sku)
            pos_b += contrib

    result = []
    if parte_a:
        result.append(parte_a)
    if parte_b:
        result.append(parte_b)
    return result if len(result) > 1 else [skus]


def reconstruir_splits_en_resultado(
    camiones_api: List[Dict],
    pedidos_no_incluidos: List[Dict],
    splits_info: List[SplitInfo],
) -> List[Dict[str, Any]]:
    """
    Post-procesa el resultado de los solvers para enriquecer la info de splits.

    Recorre camiones y pedidos_no_incluidos para determinar en qué camión
    quedó cada sub-pedido, y lo agrega al splits_info serializado.

    Returns:
        Lista de dicts con info de splits para el frontend.
    """
    if not splits_info:
        return []

    # Mapear sub-pedido_id → camión número
    sub_a_camion: Dict[str, int] = {}
    for cam in camiones_api:
        for p in cam.get("pedidos", []):
            pid = p.get("PEDIDO", "")
            if "_P" in pid:
                sub_a_camion[pid] = cam.get("numero", 0)

    resultado = []
    for si in splits_info:
        partes_con_camion = []
        for sp in si.sub_pedidos:
            parte = dict(sp)
            parte["camion_numero"] = sub_a_camion.get(sp["pedido_id"], None)
            partes_con_camion.append(parte)

        resultado.append({
            "pedido_original": si.pedido_original,
            "po": si.po,
            "cd": si.cd,
            "ce": si.ce,
            "total_skus": si.total_skus,
            "total_pallets": si.total_pallets,
            "cantidad_partes": len(si.sub_pedidos),
            "partes": partes_con_camion,
        })

    return resultado