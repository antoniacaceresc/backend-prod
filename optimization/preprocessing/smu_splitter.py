# optimization/preprocessing/smu_splitter.py
"""
Pre-procesador de pedidos para SMU: divide pedidos SOLO cuando la división
permite armar un camión de alto VCU con otros pedidos de la misma ruta.

Idea:
  Los pedidos SMU se quedan sin posiciones antes de llenar el camión por peso o
  volumen (alturas máximas bajas). Un pedido "host" deja huecos (posiciones
  libres y pallets base/flexible sin nada encima); otros pedidos de la misma
  ruta (CD, CE, flujo) pueden ceder BLOQUES de SKUs que llenen esos huecos.

Cómo decide:
  1. Para cada pedido se simula su layout real con el HeightValidator (altura y
     consolidación del subcliente, picking, CD sin apilamiento) y se arma en
     BLOQUES atómicos: líneas de SKU que comparten posición nunca se separan.
  2. Por ruta, se toma cada pedido como host (más posiciones primero) y se
     intenta completar su camión:
       a) primero con pedidos completos (sin dividir),
       b) luego con bloques de otros pedidos, priorizando los que apilan sobre
          los huecos del host (superior/flexible) y los de más volumen por
          posición.
     Cada agregado se valida con el HeightValidator sobre el camión real.
  3. La división se confirma solo si el camión resultante alcanza vcu_objetivo.
     Si no, no se divide nada (rollback).
  4. Un pedido puede ceder bloques a varios hosts (dividirse más de una vez),
     hasta max_partes.
  5. Pedidos que no caben en un camión se dividen siempre (si no, no se asignan).

El splitter solo PROPONE cortes; el solver decide la asignación final.
reconstruir_splits_en_resultado marca las divisiones que no se aprovecharon.

Reglas:
  - Solo se dividen líneas completas de SKU (atómicas, no se parten pallets).
  - No se combinan pedidos con picking del mismo SKU (PROHIBIR_PICKING_DUPLICADO).
  - Se preserva trazabilidad: pedido_original → sub-pedidos (+ host sugerido).
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field, replace
from typing import List, Dict, Any, Tuple, Optional

from models.domain import Pedido, SKU, TruckCapacity, Camion
from models.enums import TipoRuta, TipoCamion


# ============================================================================
# ESTRUCTURAS
# ============================================================================

@dataclass
class SplitInfo:
    """Información de un pedido dividido para el frontend."""
    pedido_original: str
    po: str
    cd: str
    ce: str
    total_skus: int
    total_pallets: float
    posiciones_reales: int = 0
    sub_pedidos: List[Dict[str, Any]] = field(default_factory=list)


@dataclass(eq=False)
class _Bloque:
    """Grupo atómico de líneas de SKU que comparten posiciones en el layout."""
    skus: List[SKU]
    posiciones: int
    volumen: float
    peso: float
    pallets: float
    complemento: float  # pallets superior + flexible (pueden ir sobre huecos)


@dataclass(eq=False)
class _Pieza:
    """Porción de un pedido original (el pedido completo o una parte cedida)."""
    origen: Pedido
    bloques: List[_Bloque]
    destino: Optional[str] = None  # pedido host al que se cedió (None = resto)

    @property
    def skus(self) -> List[SKU]:
        return [s for b in self.bloques for s in b.skus]

    @property
    def posiciones(self) -> int:
        return sum(b.posiciones for b in self.bloques)


class _Simulador:
    """Valida camiones con las reglas reales de SMU para una ruta."""

    def __init__(self, client_config, venta: str, muestra: Pedido):
        from utils.config_helpers import (
            get_consolidacion_config, get_effective_config, permite_apilamiento_cd,
        )
        self.config = client_config
        self.venta = venta
        self.cap = _capacidad_ruta(muestra, client_config, venta)

        sub = (muestra.metadata or {}).get("SUBCLIENTE", "") or ""
        self.altura = self.cap.altura_cm
        if hasattr(client_config, "get_altura_maxima"):
            self.altura = client_config.get_altura_maxima(sub, self.altura, venta)

        cap = self.cap
        if not permite_apilamiento_cd(client_config, muestra.cd, venta):
            cap = cap.sin_apilamiento()
        self.cap_real = replace(cap, altura_cm=self.altura)

        cons = get_consolidacion_config(client_config, subcliente=sub, oc=muestra.oc, venta=venta)
        effective = get_effective_config(client_config, venta)
        self._kwargs = dict(
            altura_maxima_cm=self.altura,
            permite_consolidacion=cons.get("PERMITE_CONSOLIDACION", True),
            max_skus_por_pallet=cons.get("MAX_SKUS_POR_PALLET", 3),
            max_altura_picking_apilado_cm=cons.get("ALTURA_MAX_PICKING_APILADO_CM"),
            flujo_config=effective.get("FLUJO_CONFIG", {}) or {},
        )
        self.prohibir_picking_dup = bool(effective.get("PROHIBIR_PICKING_DUPLICADO", False))

    # ------------------------------------------------------------------ #
    def layout(self, piezas: List[_Pieza], medir: bool = False):
        """
        Simula las piezas en un camión. Con medir=True no limita posiciones
        (sirve para medir un pedido solo). Retorna (es_valido, layout).
        """
        from optimization.validation.height_validator import HeightValidator

        pedidos_tmp = [_pedido_temporal(p, i) for i, p in enumerate(piezas)]
        cap = self.cap_real
        if medir:
            cota = sum(math.ceil(s.cantidad_pallets) for p in piezas for s in p.skus) + 2
            cap = replace(cap, max_positions=max(cota, 1))

        camion = Camion(
            id="smu_splitter_tmp",
            tipo_ruta=TipoRuta.NORMAL,
            tipo_camion=TipoCamion.PAQUETERA,
            cd=[piezas[0].origen.cd],
            ce=[piezas[0].origen.ce],
            grupo="smu_splitter",
            capacidad=cap,
            pedidos=pedidos_tmp,
        )
        try:
            ok, _, layout, debug = HeightValidator(**self._kwargs).validar_camion_rapido(camion)
        except Exception as e:
            print(f"[SMU-SPLITTER] Error simulando layout: {e}")
            return False, None
        return ok, layout or (debug or {}).get("layout_parcial")

    def cabe(self, piezas: List[_Pieza]) -> Tuple[bool, Optional[Any]]:
        """Capacidad (peso/vol/pallets), picking duplicado y layout real."""
        skus = [s for p in piezas for s in p.skus]
        if sum(s.peso_kg for s in skus) > self.cap_real.cap_weight:
            return False, None
        if sum(s.volumen_m3 for s in skus) > self.cap_real.cap_volume:
            return False, None
        if self.cap_real.max_pallets and sum(s.cantidad_pallets for s in skus) > self.cap_real.max_pallets:
            return False, None
        if self.prohibir_picking_dup and _picking_duplicado(piezas):
            return False, None
        return self.layout(piezas)

    def vcu(self, piezas: List[_Pieza]) -> float:
        skus = [s for p in piezas for s in p.skus]
        return max(
            sum(s.peso_kg for s in skus) / self.cap_real.cap_weight if self.cap_real.cap_weight else 0.0,
            sum(s.volumen_m3 for s in skus) / self.cap_real.cap_volume if self.cap_real.cap_volume else 0.0,
        )


# ============================================================================
# API PÚBLICA
# ============================================================================

def dividir_pedidos_smu(
    pedidos: List[Pedido],
    client_config,
    venta: str,
    vcu_objetivo: float = 0.8,
    max_partes: int = 3,
    max_intentos_por_host: int = 40,
) -> Tuple[List[Pedido], List[SplitInfo]]:
    """
    Divide pedidos solo cuando el corte permite armar un camión con
    VCU >= vcu_objetivo junto a otros pedidos de la misma ruta.

    Args:
        pedidos: Pedidos con SKUs.
        client_config: Config del cliente (SmuConfig).
        venta: Canal de venta.
        vcu_objetivo: VCU mínimo del camión que justifica dividir
            (se usa el mayor entre este valor y el vcu_min del camión).
        max_partes: Máximo de partes en que se puede dividir un pedido.
        max_intentos_por_host: Tope de bloques a probar por camión (rendimiento).

    Returns:
        (pedidos_procesados, splits_info)
    """
    sin_skus = [p for p in pedidos if not p.tiene_skus]
    por_ruta: Dict[Tuple[str, str, str], List[Pedido]] = defaultdict(list)
    for p in pedidos:
        if p.tiene_skus:
            por_ruta[(p.cd, p.ce, (p.oc or "").upper())].append(p)

    piezas_por_pedido: Dict[str, List[_Pieza]] = {}
    posiciones_reales: Dict[str, int] = {}

    for ruta, pedidos_ruta in por_ruta.items():
        sim = _Simulador(client_config, venta, pedidos_ruta[0])
        objetivo = max(vcu_objetivo, sim.cap.vcu_min or 0.0)

        # 1) Medir cada pedido y armar bloques
        piezas: List[_Pieza] = []
        for pedido in pedidos_ruta:
            entera = _Pieza(origen=pedido, bloques=[])
            _, layout = sim.layout([_Pieza(pedido, [_bloque_unico(pedido.skus)])], medir=True)
            entera.bloques = _bloques_desde_layout(pedido, layout)
            posiciones_reales[pedido.pedido] = layout.posiciones_usadas if layout else entera.posiciones
            piezas.append(entera)
            piezas_por_pedido[pedido.pedido] = [entera]

        # 2) Pedidos que no caben en un camión: división forzada
        for pieza in list(piezas):
            if pieza.posiciones > sim.cap_real.max_positions and len(pieza.bloques) > 1:
                partes = _repartir_bloques(pieza.bloques, pieza.posiciones, sim.cap_real.max_positions)
                nuevas = [_Pieza(pieza.origen, bs) for bs in partes]
                piezas.remove(pieza)
                piezas.extend(nuevas)
                piezas_por_pedido[pieza.origen.pedido] = nuevas
                print(f"[SMU-SPLITTER] Pedido {pieza.origen.pedido}: no cabe en un camión "
                      f"({pieza.posiciones} pos) → {len(nuevas)} partes")

        # 3) Completar camiones con huecos usando bloques de otros pedidos
        _consolidar_ruta(piezas, piezas_por_pedido, sim, objetivo,
                         max_partes, max_intentos_por_host)

    # 4) Construir salida respetando el orden original
    pedidos_resultado: List[Pedido] = []
    splits: List[SplitInfo] = []
    for pedido in pedidos:
        piezas_p = piezas_por_pedido.get(pedido.pedido)
        if not piezas_p or len(piezas_p) == 1:
            pedidos_resultado.append(pedido)
            continue
        subs, info = _construir_sub_pedidos(pedido, piezas_p, posiciones_reales.get(pedido.pedido, 0))
        pedidos_resultado.extend(subs)
        splits.append(info)

    print(f"[SMU-SPLITTER] {len(pedidos)} pedidos → {len(pedidos_resultado)} "
          f"({len(splits)} divididos, {len(sin_skus)} sin SKUs)")
    return pedidos_resultado, splits


def reconstruir_splits_en_resultado(
    camiones_api: List[Dict],
    pedidos_no_incluidos: List[Dict],
    splits_info: List[SplitInfo],
) -> List[Dict[str, Any]]:
    """
    Agrega a cada sub-pedido el número de camión donde quedó (None si no asignado)
    y marca si la división fue realmente necesaria. Se usa tras optimizar.
    """
    if not splits_info:
        return []

    ids_sub = {sp["pedido_id"] for si in splits_info for sp in si.sub_pedidos}
    sub_a_camion: Dict[str, int] = {}
    for cam in camiones_api:
        for p in cam.get("pedidos", []):
            pid = str(p.get("PEDIDO", ""))
            if pid in ids_sub:
                sub_a_camion[pid] = cam.get("numero", 0)

    return _resumir_splits(splits_info, sub_a_camion)


def splits_info_desde_estado(camiones: List[Camion], pedidos_no_incluidos: List[Pedido]) -> List[Dict[str, Any]]:
    """
    Reconstruye la info de divisiones desde la metadata de los pedidos
    (_split_from, _split_part, ...). Se usa en postprocess, que es stateless
    y no recibe el splits_info original.
    """
    partes: Dict[str, List[Tuple[Pedido, Optional[int]]]] = defaultdict(list)
    for cam in camiones:
        for p in cam.pedidos:
            if (p.metadata or {}).get("_split_from"):
                partes[str(p.metadata["_split_from"])].append((p, cam.numero))
    for p in pedidos_no_incluidos:
        if (p.metadata or {}).get("_split_from"):
            partes[str(p.metadata["_split_from"])].append((p, None))

    if not partes:
        return []

    splits_info: List[SplitInfo] = []
    sub_a_camion: Dict[str, Optional[int]] = {}
    for original, lista in partes.items():
        lista.sort(key=lambda x: int(x[0].metadata.get("_split_part", 0) or 0))
        p0 = lista[0][0]
        info = SplitInfo(
            pedido_original=original,
            po=p0.po,
            cd=p0.cd,
            ce=p0.ce,
            total_skus=sum(len(p.skus) for p, _ in lista),
            total_pallets=round(sum(p.pallets for p, _ in lista), 1),
            posiciones_reales=int(p0.metadata.get("_split_pos_reales", 0) or 0),
        )
        for p, numero in lista:
            info.sub_pedidos.append(_parte_dict(
                p.pedido, p.skus, p.pallets, p.peso, p.volumen,
                int(p.metadata.get("_split_posiciones", 0) or 0),
                p.metadata.get("_split_destino"),
            ))
            sub_a_camion[p.pedido] = numero
        splits_info.append(info)

    return _resumir_splits(splits_info, sub_a_camion, log=False)


def _resumir_splits(
    splits_info: List[SplitInfo],
    sub_a_camion: Dict[str, Optional[int]],
    log: bool = True,
) -> List[Dict[str, Any]]:
    """Arma la salida para el frontend y marca divisiones innecesarias."""
    resultado = []
    for si in splits_info:
        partes = []
        for sp in si.sub_pedidos:
            parte = dict(sp)
            parte["camion_numero"] = sub_a_camion.get(sp["pedido_id"])
            partes.append(parte)

        camiones = {p["camion_numero"] for p in partes}
        if camiones == {None}:
            requiere, motivo = False, "Ninguna parte quedó asignada"
        elif len(camiones) == 1:
            requiere, motivo = False, "Todas las partes quedaron en el mismo camión"
        else:
            requiere, motivo = True, None

        resultado.append({
            "pedido_original": si.pedido_original,
            "po": si.po,
            "cd": si.cd,
            "ce": si.ce,
            "total_skus": si.total_skus,
            "total_pallets": si.total_pallets,
            "posiciones_reales": si.posiciones_reales,
            "cantidad_partes": len(si.sub_pedidos),
            "requiere_division": requiere,
            "motivo_sin_division": motivo,
            "partes": partes,
        })

    n_innecesarios = sum(1 for r in resultado if not r["requiere_division"])
    if log and n_innecesarios:
        print(f"[SMU-SPLITTER] {n_innecesarios}/{len(resultado)} divisiones no fueron necesarias")

    return resultado


def _parte_dict(pedido_id, skus, pallets, peso, volumen, posiciones, destino) -> Dict[str, Any]:
    return {
        "pedido_id": pedido_id,
        "pallets": round(pallets, 1),
        "peso": round(peso, 0),
        "volumen": round(volumen, 0),
        "posiciones": posiciones,
        "destino_sugerido": destino,
        "skus": [
            {
                "sku_id": s.sku_id,
                "pallets": s.cantidad_pallets,
                "descripcion": s.descripcion or "",
                "categoria": s.categoria_apilamiento_dominante,
            }
            for s in skus
        ],
    }


# ============================================================================
# CONSOLIDACIÓN POR RUTA
# ============================================================================

def _consolidar_ruta(
    piezas: List[_Pieza],
    piezas_por_pedido: Dict[str, List[_Pieza]],
    sim: _Simulador,
    objetivo: float,
    max_partes: int,
    max_intentos: int,
) -> None:
    """
    Greedy por host: completa el camión del host con pedidos completos y luego
    con bloques cedidos por otros pedidos. Confirma solo si VCU >= objetivo.
    Modifica piezas / piezas_por_pedido in-place.
    """
    usadas: set = set()  # ids de piezas ya comprometidas en un camión

    hosts = sorted(piezas, key=lambda p: (p.posiciones, sim.vcu([p])), reverse=True)
    for host in hosts:
        if id(host) in usadas or host.destino is not None or not host.bloques:
            continue

        ok, layout = sim.cabe([host])
        if not ok:
            continue
        if sim.vcu([host]) >= objetivo:
            usadas.add(id(host))  # ya llena solo
            continue

        miembros: List[_Pieza] = [host]

        # a) Pedidos completos (no requieren división)
        otras = [p for p in piezas if p is not host and id(p) not in usadas
                 and p.destino is None and p.bloques]
        for p in sorted(otras, key=lambda p: sim.vcu([p]), reverse=True):
            ok, lay = sim.cabe(miembros + [p])
            if ok:
                miembros.append(p)
                layout = lay

        if sim.vcu(miembros) >= objetivo:
            usadas.update(id(m) for m in miembros)
            continue

        # b) Bloques cedidos por otros pedidos
        donaciones: Dict[int, List[_Bloque]] = defaultdict(list)
        donantes: Dict[int, _Pieza] = {}
        huecos = _huecos_apilables(layout)

        candidatos = []
        for p in piezas:
            if p in miembros or id(p) in usadas or p.destino is not None or len(p.bloques) < 2:
                continue
            if len(piezas_por_pedido[p.origen.pedido]) >= max_partes:
                continue
            for b in p.bloques:
                candidatos.append((p, b))

        candidatos.sort(key=lambda pb: (
            -(pb[1].complemento if huecos else 0.0),
            -(pb[1].volumen / max(pb[1].posiciones, 1)),
        ))

        actual = list(miembros)
        intentos = 0
        for p, b in candidatos:
            if intentos >= max_intentos:
                break
            # No vaciar al donante: debe quedar al menos un bloque (si no, sería pedido completo)
            if len(donaciones[id(p)]) + 1 >= len(p.bloques):
                continue
            intentos += 1
            prueba = actual + [_Pieza(p.origen, [b], destino=host.origen.pedido)]
            ok, lay = sim.cabe(_fusionar(prueba))
            if not ok:
                continue
            actual = prueba
            donaciones[id(p)].append(b)
            donantes[id(p)] = p
            if lay is not None and lay.posiciones_usadas >= sim.cap_real.max_positions:
                break

        vcu_final = sim.vcu(actual)
        if not donaciones or vcu_final < objetivo:
            continue  # rollback: no se divide nada

        # Confirmar: cada donante cede sus bloques como una pieza nueva
        for pid, bloques in donaciones.items():
            donante = donantes[pid]
            cedida = _Pieza(donante.origen, bloques, destino=host.origen.pedido)
            ids_cedidos = {id(b) for b in bloques}
            donante.bloques = [b for b in donante.bloques if id(b) not in ids_cedidos]
            piezas.append(cedida)
            piezas_por_pedido[donante.origen.pedido].append(cedida)
            usadas.add(id(cedida))
        usadas.update(id(m) for m in miembros)

        cedidos = ", ".join(
            f"{donantes[k].origen.pedido}:{sum(b.posiciones for b in v)}pos"
            for k, v in donaciones.items()
        )
        print(f"[SMU-SPLITTER] Host {host.origen.pedido}: VCU {sim.vcu(miembros):.0%} → "
              f"{vcu_final:.0%} con bloques de [{cedidos}]")


def _fusionar(piezas: List[_Pieza]) -> List[_Pieza]:
    """Une piezas del mismo pedido y destino (para simular como un solo pedido)."""
    agrupadas: Dict[Tuple[str, Optional[str]], _Pieza] = {}
    for p in piezas:
        clave = (p.origen.pedido, p.destino)
        if clave in agrupadas:
            agrupadas[clave] = _Pieza(p.origen, agrupadas[clave].bloques + p.bloques, p.destino)
        else:
            agrupadas[clave] = p
    return list(agrupadas.values())


def _huecos_apilables(layout) -> int:
    """Posiciones con un solo pallet (podrían recibir un superior/flexible encima)."""
    if layout is None:
        return 0
    return sum(1 for pos in layout.posiciones if len(pos.pallets_apilados) == 1)


def _picking_duplicado(piezas: List[_Pieza]) -> bool:
    """True si dos pedidos distintos traen picking del mismo SKU."""
    visto: Dict[str, str] = {}
    for p in piezas:
        for s in p.skus:
            if s.cantidad_pallets % 1 > 0.001:
                previo = visto.get(s.sku_id)
                if previo is not None and previo != p.origen.pedido:
                    return True
                visto[s.sku_id] = p.origen.pedido
    return False


# ============================================================================
# CAPACIDAD, BLOQUES Y REPARTO
# ============================================================================

def _capacidad_ruta(pedido: Pedido, client_config, venta: str) -> TruckCapacity:
    """Camión más grande permitido para la ruta y flujo del pedido."""
    from utils.config_helpers import get_camiones_permitidos_para_ruta, get_capacity_for_type

    tipos = get_camiones_permitidos_para_ruta(
        client_config, [pedido.cd], [pedido.ce], "normal", venta, pedido.oc
    ) or [TipoCamion.PAQUETERA]
    caps = [get_capacity_for_type(client_config, t, venta) for t in tipos]
    return max(caps, key=lambda c: (c.max_positions, c.cap_volume))


def _nuevo_bloque(skus: List[SKU], posiciones: int) -> _Bloque:
    return _Bloque(
        skus=skus,
        posiciones=posiciones,
        volumen=sum(s.volumen_m3 for s in skus),
        peso=sum(s.peso_kg for s in skus),
        pallets=sum(s.cantidad_pallets for s in skus),
        complemento=sum(s.superior + s.flexible for s in skus),
    )


def _bloque_unico(skus: List[SKU]) -> _Bloque:
    return _nuevo_bloque(skus, sum(math.ceil(s.cantidad_pallets) for s in skus))


def _bloques_desde_layout(pedido: Pedido, layout) -> List[_Bloque]:
    """
    Une (union-find) las líneas de SKU que comparten alguna posición.
    Cada componente es un bloque atómico con sus posiciones reales.
    """
    skus_por_id: Dict[str, SKU] = {s.sku_id: s for s in pedido.skus}

    if layout is None:
        return [_nuevo_bloque([s], math.ceil(s.cantidad_pallets)) for s in pedido.skus]

    padre: Dict[str, str] = {sid: sid for sid in skus_por_id}

    def raiz(x: str) -> str:
        while padre[x] != x:
            padre[x] = padre[padre[x]]
            x = padre[x]
        return x

    skus_por_posicion: List[set] = []
    for pos in layout.posiciones:
        if pos.esta_vacia:
            continue
        ids = [f.sku_id for pallet in pos.pallets_apilados for f in pallet.fragmentos
               if f.sku_id in skus_por_id]
        skus_por_posicion.append(set(ids))
        for otro in ids[1:]:
            ra, rb = raiz(ids[0]), raiz(otro)
            if ra != rb:
                padre[rb] = ra

    pos_por_raiz: Dict[str, int] = defaultdict(int)
    for ids in skus_por_posicion:
        if ids:
            pos_por_raiz[raiz(next(iter(ids)))] += 1

    skus_por_raiz: Dict[str, List[SKU]] = defaultdict(list)
    for sid, sku in skus_por_id.items():
        skus_por_raiz[raiz(sid)].append(sku)

    return [
        _nuevo_bloque(skus, pos_por_raiz.get(r) or sum(math.ceil(s.cantidad_pallets) for s in skus))
        for r, skus in skus_por_raiz.items()
    ]


def _repartir_bloques(
    bloques: List[_Bloque],
    posiciones_total: int,
    max_positions: int,
) -> List[List[_Bloque]]:
    """Reparte bloques en k partes balanceadas por posiciones (LPT)."""
    if len(bloques) < 2:
        return [bloques]
    k = min(len(bloques), max(2, math.ceil(posiciones_total / max_positions)))
    partes: List[List[_Bloque]] = [[] for _ in range(k)]
    carga = [0] * k
    for b in sorted(bloques, key=lambda b: (b.posiciones, b.volumen), reverse=True):
        i = carga.index(min(carga))
        partes[i].append(b)
        carga[i] += b.posiciones
    return [p for p in partes if p]


# ============================================================================
# CONSTRUCCIÓN DE PEDIDOS
# ============================================================================

def _pedido_temporal(pieza: _Pieza, idx: int) -> Pedido:
    """Pedido liviano para simular una pieza en el HeightValidator."""
    skus = pieza.skus
    sufijo = f"__{pieza.destino or 'resto'}_{idx}"
    return replace(
        pieza.origen,
        pedido=f"{pieza.origen.pedido}{sufijo}",
        peso=sum(s.peso_kg for s in skus),
        volumen=sum(s.volumen_m3 for s in skus),
        pallets=sum(s.cantidad_pallets for s in skus),
        base=sum(s.base for s in skus),
        superior=sum(s.superior for s in skus),
        flexible=sum(s.flexible for s in skus),
        no_apilable=sum(s.no_apilable for s in skus),
        si_mismo=sum(s.si_mismo for s in skus),
        skus=skus,
    )


def _construir_sub_pedidos(
    pedido: Pedido,
    piezas: List[_Pieza],
    posiciones_reales: int,
) -> Tuple[List[Pedido], SplitInfo]:
    split_info = SplitInfo(
        pedido_original=pedido.pedido,
        po=pedido.po,
        cd=pedido.cd,
        ce=pedido.ce,
        total_skus=len(pedido.skus),
        total_pallets=round(pedido.pallets_capacidad, 1),
        posiciones_reales=posiciones_reales,
    )
    sub_pedidos: List[Pedido] = []
    piezas = [p for p in piezas if p.bloques]

    for idx, pieza in enumerate(piezas, start=1):
        skus_parte = pieza.skus
        sub_id = f"{pedido.pedido}_P{idx}"

        peso = sum(s.peso_kg for s in skus_parte)
        volumen = sum(s.volumen_m3 for s in skus_parte)
        pallets = sum(s.cantidad_pallets for s in skus_parte)
        valor = sum(s.valor for s in skus_parte)

        meta = dict(pedido.metadata or {})
        meta["_split_from"] = pedido.pedido
        meta["_split_part"] = idx
        meta["_split_total"] = len(piezas)
        meta["_split_posiciones"] = pieza.posiciones
        meta["_split_pos_reales"] = posiciones_reales
        if pieza.destino:
            meta["_split_destino"] = pieza.destino

        sub_pedidos.append(Pedido(
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
            base=sum(s.base for s in skus_parte),
            superior=sum(s.superior for s in skus_parte),
            flexible=sum(s.flexible for s in skus_parte),
            no_apilable=sum(s.no_apilable for s in skus_parte),
            si_mismo=sum(s.si_mismo for s in skus_parte),
            skus=skus_parte,
            metadata=meta,
        ))

        split_info.sub_pedidos.append(_parte_dict(
            sub_id, skus_parte, pallets, peso, volumen, pieza.posiciones, pieza.destino,
        ))

    return sub_pedidos, split_info