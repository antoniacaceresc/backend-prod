# services/postprocess.py
from __future__ import annotations

from typing import List, Dict, Any, Optional
import uuid

from config import get_client_config

PALLETS_SCALE = 10


def compute_stats(
    camiones: Optional[List[Dict[str, Any]]],
    pedidos_no: Optional[List[Dict[str, Any]]],
    cliente: Optional[str] = None,
) -> Dict[str, Any]:
    camiones = camiones or []
    pedidos_no = pedidos_no or []

    cantidad_camiones = len(camiones)
    cantidad_normal = sum(1 for c in camiones if (c.get("tipo_camion") or "") != "bh")
    cantidad_bh = cantidad_camiones - cantidad_normal

    cantidad_asig = sum(len(c.get("pedidos") or []) for c in camiones)
    total_pedidos = cantidad_asig + len(pedidos_no)

    vcu_vals = [(c.get("vcu_max") or 0) for c in camiones]
    promedio_vcu = (sum(vcu_vals) / cantidad_camiones) if cantidad_camiones else 0

    norm_vals = [v for c in camiones if (c.get("tipo_camion") or "") != "bh" for v in [(c.get("vcu_max") or 0)]]
    promedio_norm = (sum(norm_vals) / cantidad_normal) if cantidad_normal else 0

    bh_vals = [v for c in camiones if (c.get("tipo_camion") or "") == "bh" for v in [(c.get("vcu_max") or 0)]]
    promedio_bh = (sum(bh_vals) / cantidad_bh) if cantidad_bh else 0

    valorizado = sum((c.get("valor_total") or 0) for c in camiones)

    return {
        "cantidad_camiones": cantidad_camiones,
        "cantidad_camiones_normal": cantidad_normal,
        "cantidad_camiones_bh": cantidad_bh,
        "cantidad_pedidos_asignados": cantidad_asig,
        "total_pedidos": total_pedidos,
        "promedio_vcu": promedio_vcu,
        "promedio_vcu_normal": promedio_norm,
        "promedio_vcu_bh": promedio_bh,
        "valorizado": valorizado,
    }


def _ceil_div2(x: int) -> int:
    return (x + 1) // 2


def _compute_apilabilidad(pedidos_cam: List[Dict[str, Any]], cliente: Optional[str], tipo_camion: str) -> Dict[str, Any]:
    """Reproduce la métrica `total_stack` del solver y valida contra el umbral
    de posiciones del camión según cliente/tipo (normal vs bh).
    """
    if not (cliente and str(cliente).strip()):
        return {"ok": False, "motivo": "Falta 'cliente' para validar apilabilidad"}

    cfg = get_client_config(cliente)
    if isinstance(cfg.TRUCK_TYPES, dict):
        truck_types = cfg.TRUCK_TYPES
    else:
        truck_types = {t.get("type"): t for t in cfg.TRUCK_TYPES}

    tipo = (tipo_camion or "normal").lower()
    tsel = truck_types.get(tipo) or truck_types.get("normal") or next(iter(truck_types.values()))

    levels = int(tsel.get("levels", 2))
    max_positions = int(tsel.get("max_positions", 30))

    def s(col: str, default: float = 0.0) -> int:
        return int(round(sum(float(p.get(col, default) or 0.0) for p in pedidos_cam) * PALLETS_SCALE))

    base_sum = s("BASE")
    sup_sum = s("SUPERIOR")
    flex_sum = s("FLEXIBLE")
    noap_sum = s("NO_APILABLE")
    self_sum = s("SI_MISMO")

    lim_pos_scaled = max_positions * PALLETS_SCALE
    if base_sum > lim_pos_scaled:
        return {"ok": False, "motivo": f"BASE usa {base_sum/PALLETS_SCALE:.2f} > {max_positions} posiciones"}
    if sup_sum > lim_pos_scaled:
        return {"ok": False, "motivo": f"SUPERIOR usa {sup_sum/PALLETS_SCALE:.2f} > {max_positions} posiciones"}
    if noap_sum > lim_pos_scaled:
        return {"ok": False, "motivo": f"NO_APILABLE usa {noap_sum/PALLETS_SCALE:.2f} > {max_positions} posiciones"}
    if flex_sum > (max_positions * levels * PALLETS_SCALE):
        return {"ok": False, "motivo": f"FLEXIBLE usa {flex_sum/PALLETS_SCALE:.2f} > {max_positions*levels} niveles"}

    if base_sum + noap_sum > lim_pos_scaled:
        return {"ok": False, "motivo": "BASE + NO_APILABLE exceden posiciones"}
    if sup_sum + noap_sum > lim_pos_scaled:
        return {"ok": False, "motivo": "SUPERIOR + NO_APILABLE exceden posiciones"}

    diff = base_sum - sup_sum
    abs_diff = abs(diff)

    m0 = min(base_sum, sup_sum)
    m1 = min(abs_diff, flex_sum)
    rem = flex_sum - m1
    half = _ceil_div2(rem)
    m2 = max(abs_diff - flex_sum, 0)

    pair_q = self_sum // (2 * PALLETS_SCALE)
    self_pairs_scaled = pair_q * PALLETS_SCALE
    self_rem = self_sum - pair_q * (2 * PALLETS_SCALE)

    total_stack = m0 + m1 + half + m2 + noap_sum + self_pairs_scaled + self_rem
    ok = total_stack <= lim_pos_scaled
    usado = total_stack / PALLETS_SCALE

    return {"ok": ok, "motivo": (None if ok else f"Usa {usado:.2f} posiciones > {max_positions}"), "pos_usadas": usado, "pos_max": max_positions}


def _check_vcu_cap(pedidos_cam: List[Dict[str, Any]]) -> Dict[str, Any]:
    vvol = sum(p.get("VCU_VOL") or 0 for p in pedidos_cam)
    vpes = sum(p.get("VCU_PESO") or 0 for p in pedidos_cam)
    vcu_max = max(vvol, vpes)

    return {
        "ok": vcu_max <= 1 + 1e-9,
        "motivo": None if vcu_max <= 1 + 1e-9 else f"VCU excedido: peso {vpes*100:.2f}%, volumen {vvol*100:.2f}% (máx {vcu_max*100:.2f}%)",
        "vcu_vol": vvol,
        "vcu_peso": vpes,
        "vcu_max": vcu_max,
    }


def move_orders(
    state: Dict[str, Any],
    pedidos: Optional[List[Dict[str, Any]]],
    target_truck_id: Optional[str],
    cliente: str,
) -> Dict[str, Any]:
    """Mueve pedidos entre camiones y valída reglas del cliente (contrato preservado)."""
    camiones = [dict(c) for c in (state.get("camiones") or [])]
    no_incl = list(state.get("pedidos_no_incluidos") or [])
    pedidos_sel = list(pedidos or [])

    seleccion_ids = {p.get("PEDIDO") for p in pedidos_sel}
    sim_camiones = []
    for c in camiones:
        c2 = dict(c)
        c2["pedidos"] = [p for p in (c.get("pedidos") or []) if p.get("PEDIDO") not in seleccion_ids]
        sim_camiones.append(c2)
    sim_no_incl = [p for p in no_incl if p.get("PEDIDO") not in seleccion_ids]

    if target_truck_id:
        tgt = next((c for c in sim_camiones if c.get("id") == target_truck_id), None)
        if not tgt:
            raise ValueError("Camión destino no encontrado")

        candidatos = (tgt.get("pedidos") or []) + pedidos_sel

        # Reglas de Walmart postproceso
        if (cliente or "").strip().lower() == "walmart":
            from collections import Counter
            cfg_wm = get_client_config("Walmart")

            cds_candidatos = [p.get("CD") for p in candidatos if p.get("CD")]
            cds_unicos = {cd for cd in cds_candidatos if cd not in (None, "")}

            if len(cds_unicos) > 1:
                conteo_por_cd = Counter(cds_candidatos)
                for cd, cnt in conteo_por_cd.items():
                    if cnt > 10:
                        raise ValueError(f"Walmart (multi_cd): máximo 10 pedidos por CD. CD '{cd}' tiene {cnt}.")
                total = sum(conteo_por_cd.values())
                if total > 20:
                    raise ValueError("Walmart (multi_cd): máximo 20 pedidos por camión (10 por CD).")
            else:
                max_ordenes = getattr(cfg_wm, "MAX_ORDENES", 10)
                if len(candidatos) > max_ordenes:
                    raise ValueError(f"Walmart: máximo {max_ordenes} pedidos por camión.")

        # Capacidad de pallets real en Cencosud
        if (cliente or "").strip().lower() == "cencosud":
            cfg = get_client_config("Cencosud")
            tipo_cam = (tgt.get("tipo_camion") or "normal").lower()
            trucks = cfg.TRUCK_TYPES if isinstance(cfg.TRUCK_TYPES, dict) else {t.get("type"): t for t in cfg.TRUCK_TYPES}
            tsel = trucks.get(tipo_cam) or trucks.get("normal") or next(iter(trucks.values()))
            max_pallets = int(tsel.get("max_pallets", 60))
            pallets_tot = sum((p.get("PALLETS_REAL") if "PALLETS_REAL" in p else p.get("PALLETS") or 0) for p in candidatos)
            if pallets_tot > max_pallets:
                raise ValueError(f"Cencosud: pallets totales {pallets_tot} > máximo {max_pallets}.")

        cap_ok = _check_vcu_cap(candidatos)
        if not cap_ok["ok"]:
            raise ValueError(cap_ok["motivo"])

        ap_ok = _compute_apilabilidad(candidatos, cliente, tgt.get("tipo_camion") or "normal")
        if not ap_ok.get("ok"):
            raise ValueError(ap_ok.get("motivo") or "Apilabilidad inválida")

        tgt["pedidos"] = candidatos

    # Recalcular atributos por camión
    for cam in sim_camiones:
        pedidos_cam = cam.get("pedidos") or []
        cam["pallets_conf"] = float(sum(p.get("PALLETS") or 0 for p in pedidos_cam))
        cam["valor_total"] = float(sum(p.get("VALOR") or 0 for p in pedidos_cam))
        cam["vcu_vol"] = float(sum(p.get("VCU_VOL") or 0 for p in pedidos_cam))
        cam["vcu_peso"] = float(sum(p.get("VCU_PESO") or 0 for p in pedidos_cam))
        cam["vcu_max"] = max(cam["vcu_vol"], cam["vcu_peso"])
        cam["chocolates"] = "SI" if any(p.get("CHOCOLATES") == "SI" for p in pedidos_cam) else "NO"
        cam["valioso"] = any(p.get("VALIOSO") for p in pedidos_cam)
        cam["pdq"] = any(p.get("PDQ") for p in pedidos_cam)
        cam["baja_vu"] = any(p.get("BAJA_VU") for p in pedidos_cam)
        cam["lote_dir"] = any(p.get("LOTE_DIR") for p in pedidos_cam)

        ce_vals = {p.get("CE") for p in pedidos_cam if p.get("CE") not in (None, "")}
        cd_vals = {p.get("CD") for p in pedidos_cam if p.get("CD") not in (None, "")}
        if len(ce_vals) > 1:
            cam["tipo_ruta"] = "multi_ce"
        elif len(cd_vals) > 1:
            cam["tipo_ruta"] = "multi_cd"
        else:
            cam["tipo_ruta"] = "normal"

        if pedidos_cam:
            ap_det = _compute_apilabilidad(pedidos_cam, cliente, cam.get("tipo_camion") or "normal")
            cam["pos_total"] = float(ap_det.get("pos_usadas") or 0.0)
        else:
            cam["pos_total"] = 0.0

        oc_vals = {p.get("OC") for p in pedidos_cam if p.get("OC") not in (None, "")}
        cam["flujo_oc"] = ("" if not oc_vals else (next(iter(oc_vals)) if len(oc_vals) == 1 else "MIX"))

    for idx, cam in enumerate(sim_camiones, start=1):
        cam["numero"] = idx

    stats = compute_stats(sim_camiones, sim_no_incl, cliente)
    return {"camiones": sim_camiones, "pedidos_no_incluidos": sim_no_incl, "estadisticas": stats, "cliente": cliente}


def add_truck(state: Dict[str, Any], cd: Optional[List[str]], ce: Optional[List[str]], ruta: Optional[str], cliente: str) -> Dict[str, Any]:
    camiones = state.get("camiones") or []
    no_incl = state.get("pedidos_no_incluidos") or []

    new_cam = {
        "id": uuid.uuid4().hex,
        "numero": len(camiones) + 1,
        "grupo": f"{','.join(cd or [])}__{','.join(ce or [])}",
        "tipo_ruta": ruta or "",
        "cd": cd or [],
        "ce": ce or [],
        "pedidos": [],
        "vcu_vol": 0,
        "vcu_peso": 0,
        "vcu_max": 0,
        "pos_total": 0,
        "flujo_oc": "",
        "tipo_camion": "normal",
        "chocolates": "NO",
        "pallets_conf": 0,
        "valor_total": 0,
    }
    camiones.append(new_cam)
    return move_orders({"camiones": camiones, "pedidos_no_incluidos": no_incl}, [], None, cliente)


def delete_truck(state: Dict[str, Any], truck_id: Optional[str], cliente: str) -> Dict[str, Any]:
    camiones = state.get("camiones") or []
    no_incl = state.get("pedidos_no_incluidos") or []

    if truck_id:
        eliminado = next((c for c in camiones if c.get("id") == truck_id), None)
        if eliminado:
            camiones = [c for c in camiones if c.get("id") != truck_id]
            no_incl.extend(eliminado.get("pedidos") or [])

    return move_orders({"camiones": camiones, "pedidos_no_incluidos": no_incl}, [], None, cliente)