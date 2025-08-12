from typing import List, Dict, Any, Optional
import uuid
from config import get_client_config

PALLETS_SCALE = 10

def compute_stats(
    camiones: Optional[List[Dict[str, Any]]],
    pedidos_no: Optional[List[Dict[str, Any]]]
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
        "valorizado": valorizado
    }


def _ceil_div2(x: int) -> int:
    # ceil(x/2) para enteros
    return (x + 1) // 2


def _compute_apilabilidad(pedidos_cam: List[Dict[str, Any]], cliente: Optional[str], tipo_camion: str) -> Dict[str, Any]:
    """
    Reproduce la métrica 'total_stack' del solver:
      total_stack = m0 + m1 + half + m2 + noap_sum + self_pairs_scaled + self_rem
    y valida contra el umbral de posiciones del camión según cliente/tipo (normal vs bh).
    """
    cfg = get_client_config(cliente) if cliente else get_client_config("Cencosud")  # fallback
    truck = cfg.TRUCK_TYPES[0]
    levels = int(truck.get("levels", 2))

    if (tipo_camion or "").lower() == "bh":
        max_positions = int(cfg.BH_MAX_POSICIONES)
    else:
        max_positions = int(truck.get("max_positions", 30))

    # Sumar por tipo (escalado)
    def s(col, default=0.0):
        return int(round(sum(float(p.get(col, default) or 0.0) for p in pedidos_cam) * PALLETS_SCALE))

    base_sum     = s("BASE")
    sup_sum      = s("SUPERIOR")
    flex_sum     = s("FLEXIBLE")
    noap_sum     = s("NO_APILABLE")
    self_sum     = s("SI_MISMO")

    # Restricicones duras
    lim_pos_scaled = max_positions * PALLETS_SCALE
    if base_sum > lim_pos_scaled:
        return {"ok": False, "motivo": f"BASE usa {base_sum/PALLETS_SCALE:.2f} > {max_positions} posiciones"}
    if sup_sum > lim_pos_scaled:
        return {"ok": False, "motivo": f"SUPERIOR usa {sup_sum/PALLETS_SCALE:.2f} > {max_positions} posiciones"}
    if noap_sum > lim_pos_scaled:
        return {"ok": False, "motivo": f"NO_APILABLE usa {noap_sum/PALLETS_SCALE:.2f} > {max_positions} posiciones"}
    if flex_sum > (max_positions * levels * PALLETS_SCALE):
        return {"ok": False, "motivo": f"FLEXIBLE usa {flex_sum/PALLETS_SCALE:.2f} > {max_positions*levels} niveles"}

    # Combinaciones
    if base_sum + noap_sum > lim_pos_scaled:
        return {"ok": False, "motivo": "BASE + NO_APILABLE exceden posiciones"}
    if sup_sum + noap_sum > lim_pos_scaled:
        return {"ok": False, "motivo": "SUPERIOR + NO_APILABLE exceden posiciones"}

    # Fórmula agregada (igual al solver)
    diff = base_sum - sup_sum
    abs_diff = abs(diff)

    m0 = min(base_sum, sup_sum)                # min(BASE, SUPERIOR)
    m1 = min(abs_diff, flex_sum)               # min(|diff|, FLEX)
    rem = flex_sum - m1                        # remanente flexible
    half = _ceil_div2(rem)                     # ceil(rem/2)
    m2 = max(abs_diff - flex_sum, 0)           # max(|diff|-FLEX,0)

    # SI_MISMO -> pares cuentan como una posición, resto ocupa posición completa
    pair_q = self_sum // (2 * PALLETS_SCALE)   # cantidad de pares
    self_pairs_scaled = pair_q * PALLETS_SCALE
    self_rem = self_sum - pair_q * (2 * PALLETS_SCALE) # resto de pares

    total_stack = m0 + m1 + half + m2 + noap_sum + self_pairs_scaled + self_rem
    ok = total_stack <= lim_pos_scaled
    usado = total_stack / PALLETS_SCALE

    return {
        "ok": ok,
        "motivo": (None if ok else f"Usa {usado:.2f} posiciones > {max_positions}"),
        "pos_usadas": usado,
        "pos_max": max_positions
    }

def _check_vcu_cap(pedidos_cam):
    vvol = sum(p.get("VCU_VOL") or 0 for p in pedidos_cam)
    vpes = sum(p.get("VCU_PESO") or 0 for p in pedidos_cam)
    vcu_max = max(vvol, vpes)

    # porcentajes
    vvol_pct = vvol * 100.0
    vpes_pct = vpes * 100.0
    vcu_max_pct = vcu_max * 100.0

    ok = vcu_max <= 1 + 1e-9
    motivo = None
    if not ok:
        motivo = f"VCU excedido: peso {vpes_pct:.2f}%, volumen {vvol_pct:.2f}% (máx {vcu_max_pct:.2f}%)"

    return {
        "ok": ok, "motivo": motivo, "vcu_vol": vvol, "vcu_peso": vpes, "vcu_max": vcu_max,
    }


def move_orders(
    state: Dict[str, Any],
    pedidos: Optional[List[Dict[str, Any]]],
    target_truck_id: Optional[str],
    cliente: Optional[str] = None
) -> Dict[str, Any]:
    camiones = [dict(c) for c in (state.get("camiones") or [])]  # shallow copy
    no_incl = list(state.get("pedidos_no_incluidos") or [])
    pedidos_sel = list(pedidos or [])

    # Simular eliminación (sin mutar el original)
    seleccion_ids = {p.get("PEDIDO") for p in pedidos_sel}
    sim_camiones = []
    for c in camiones:
        c2 = dict(c)
        c2["pedidos"] = [p for p in (c.get("pedidos") or []) if p.get("PEDIDO") not in seleccion_ids]
        sim_camiones.append(c2)
    sim_no_incl = [p for p in no_incl if p.get("PEDIDO") not in seleccion_ids]

    # Si hay target, evaluar factibilidad antes de confirmar
    if target_truck_id:
        tgt = next((c for c in sim_camiones if c.get("id") == target_truck_id), None)
        if not tgt:
            raise ValueError("Camión destino no encontrado")

        candidatos = (tgt.get("pedidos") or []) + pedidos_sel

        # 1) Chequeo VCU
        vcu_chk = _check_vcu_cap(candidatos)
        if not vcu_chk["ok"]:
            raise ValueError(vcu_chk["motivo"])

        # 2) Chequeo apilabilidad con config de cliente + tipo de camión
        tipo_cam = (tgt.get("tipo_camion") or "normal")
        ap_chk = _compute_apilabilidad(candidatos, cliente, tipo_cam)
        if not ap_chk["ok"]:
            raise ValueError(f"No cabe por apilabilidad: {ap_chk['motivo']}")

        # Si es factible → aplicar realmente el movimiento
        tgt["pedidos"] = candidatos
    else:
        # Sin camión destino → los mandamos a no_incluidos
        sim_no_incl.extend(pedidos_sel)

    # Recalcular métricas y tipo_ruta (igual que antes) sobre sim_camiones
    for cam in sim_camiones:
        pedidos_cam = cam.get("pedidos") or []

        # VCU y otros
        vvol = sum(p.get("VCU_VOL") or 0 for p in pedidos_cam)
        vpes = sum(p.get("VCU_PESO") or 0 for p in pedidos_cam)
        cam["vcu_vol"] = vvol
        cam["vcu_peso"] = vpes
        cam["vcu_max"] = max([vvol, vpes], default=0)
        cam["pallets_conf"] = sum(p.get("PALLETS") or 0 for p in pedidos_cam)
        cam["valor_total"] = sum(p.get("VALOR") or 0 for p in pedidos_cam)
        cam["valor_cafe"] = sum(p.get("VALOR_CAFE") or 0 for p in pedidos_cam)
        cam["chocolates"] = "SI" if any(p.get("CHOCOLATES") == "SI" for p in pedidos_cam) else "NO"
        cam["skus_valiosos"] = any(p.get("VALIOSO") for p in pedidos_cam)
        cam["pdq"] = any(p.get("PDQ") for p in pedidos_cam)
        cam["baja_vu"] = any(p.get("BAJA_VU") for p in pedidos_cam)
        cam["lote_dir"] = any(p.get("LOTE_DIR") for p in pedidos_cam)

        # Tipo de ruta
        ce_vals = {p.get("CE") for p in pedidos_cam if p.get("CE") not in (None, "")}
        cd_vals = {p.get("CD") for p in pedidos_cam if p.get("CD") not in (None, "")}
        if len(ce_vals) > 1:
            cam["tipo_ruta"] = "multi_ce"
        elif len(cd_vals) > 1:
            cam["tipo_ruta"] = "multi_cd"
        else:
            cam["tipo_ruta"] = "normal"

        # Posiciones usadas (para mostrar/Excel): recalcula solo si hay pedidos
        if pedidos_cam:
            ap_det = _compute_apilabilidad(pedidos_cam, cliente, cam.get("tipo_camion") or "normal")
            cam["pos_total"] = float(ap_det.get("pos_usadas") or 0.0)
        else:
            cam["pos_total"] = 0.0

        # Flujo OC
        oc_vals = {p.get("OC") for p in pedidos_cam if p.get("OC") not in (None, "")}
        if not oc_vals:
            cam["flujo_oc"] = ""
        elif len(oc_vals) == 1:
            cam["flujo_oc"] = next(iter(oc_vals))
        else:
            cam["flujo_oc"] = "MIX"

    # Numeración
    for idx, cam in enumerate(sim_camiones, start=1):
        cam["numero"] = idx

    # Stats globales (reusa compute_stats existente)
    stats = compute_stats(sim_camiones, sim_no_incl)
    return {"camiones": sim_camiones, "pedidos_no_incluidos": sim_no_incl, "estadisticas": stats}


def add_truck(
    state: Dict[str, Any],
    cd: Optional[List[str]],
    ce: Optional[List[str]],
    ruta: Optional[str]
) -> Dict[str, Any]:
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
        "valor_total": 0
    }
    camiones.append(new_cam)
    return move_orders({"camiones": camiones, "pedidos_no_incluidos": no_incl}, [], None)


def delete_truck(
    state: Dict[str, Any],
    truck_id: Optional[str]
) -> Dict[str, Any]:
    camiones = state.get("camiones") or []
    no_incl = state.get("pedidos_no_incluidos") or []

    if truck_id:
        eliminado = next((c for c in camiones if c.get("id") == truck_id), None)
        if eliminado:
            camiones = [c for c in camiones if c.get("id") != truck_id]
            no_incl.extend(eliminado.get("pedidos") or [])

    return move_orders({"camiones": camiones, "pedidos_no_incluidos": no_incl}, [], None)
