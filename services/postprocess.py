# services/postprocess.py
from __future__ import annotations

from typing import List, Dict, Any, Optional, Tuple
import uuid
import math

from config import get_client_config
from collections import Counter

PALLETS_SCALE = 10


def _ruta_coincide_con_bh(cds_cam: List[str], ces_cam: List[int], rutas_bh: List) -> bool:
    # Normalizadores para comparar siempre como string
    def _norm_cd(x) -> str:
        return ('' if x is None else str(x).strip())
    def _norm_ce(x) -> str:
        s = ('' if x is None else str(x).strip())
        return s.lstrip('0') or '0'

    set_cd = {_norm_cd(c) for c in (cds_cam or [])}
    set_ce = {_norm_ce(e) for e in (ces_cam or [])}

    for cds, ces in rutas_bh or []:
        cds_norm = {_norm_cd(c) for c in (cds or [])}
        ces_norm = {_norm_ce(e) for e in (ces or [])}
        if set_cd.issubset(cds_norm) and set_ce.issubset(ces_norm):
            return True
    return False


def _compute_switch_options(truck: Dict[str, Any], client_config) -> Dict[str, Any]:
    """
    Calcula opciones de tipo de camión para un camión concreto.
    NOTA: NO validamos BH_VCU_MIN aquí (pediste quitar esa exigencia para el cambio).
          Sí respetamos BH_VCU_MAX y las reglas de ruta/CD/flujo.
    """
    actual = (truck.get('tipo_camion') or 'normal').lower()
    opciones = ['normal']  # siempre se puede volver a normal

    if getattr(client_config, 'PERMITE_BH', False):
        rutas_bh = getattr(client_config, 'RUTAS_POSIBLES', {}).get('bh', [])
        ruta_ok = _ruta_coincide_con_bh(truck.get('cd'), truck.get('ce'), rutas_bh)

        # CDs habilitados (si existe lista)
        cd_ok = True
        if hasattr(client_config, 'CD_CON_BH'):
            cd_ok = all(cd in client_config.CD_CON_BH for cd in (truck.get('cd') or []))

        # Mezcla de flujos
        permite_mix = getattr(client_config, 'BH_PERMITE_MIX', False)
        flujo_ok = True if permite_mix else (truck.get('flujo_oc') not in ('MIX',))

        # Ventana VCU: solo revisamos BH_VCU_MAX (NO mínimo)
        vcu = float(truck.get('vcu_max') or 0.0)
        vcu_ok = True
        if hasattr(client_config, 'BH_VCU_MAX'):
            vcu_ok = vcu_ok and (vcu <= float(client_config.BH_VCU_MAX))

        if ruta_ok and cd_ok and flujo_ok and vcu_ok:
            opciones.append('bh')

    # Devolver con el tipo actual primero
    seen = set()
    opciones = [o for o in ([actual] + [o for o in opciones if o != actual]) if not (o in seen or seen.add(o))]
    return {'can_switch': len(opciones) > 1, 'opciones': opciones}


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
    cliente: str ) -> Dict[str, Any]:
    """Mueve pedidos entre camiones y valída reglas del cliente"""
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

        # 0) Regla de Walmart: máximo 10 pedidos por camión en postproceso por CD
        if (cliente).strip().lower() == "walmart":
            cfg_wm = get_client_config("Walmart")  # para leer MAX_ORDENES si aplica

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

        # 0) Chequeo capacidad de pallets (Cencosud usa PALLETS_REAL)
        if (cliente).strip().lower() == "cencosud":
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
    else:
        sim_no_incl.extend(pedidos_sel)
        # de-duplicar por PEDIDO (por si reingresan)
        seen = set()
        sim_no_incl = [p for p in sim_no_incl
                    if not (p.get("PEDIDO") in seen or seen.add(p.get("PEDIDO")))]
    # Recalcular atributos por camión
    for cam in sim_camiones:
        pedidos_cam = cam.get("pedidos") or []
        cam["pallets_conf"] = float(sum(p.get("PALLETS") or 0 for p in pedidos_cam))
        cam["valor_total"] = float(sum(p.get("VALOR") or 0 for p in pedidos_cam))
        cam["vcu_vol"] = float(sum(p.get("VCU_VOL") or 0 for p in pedidos_cam))
        cam["vcu_peso"] = float(sum(p.get("VCU_PESO") or 0 for p in pedidos_cam))
        cam["vcu_max"] = max(cam["vcu_vol"], cam["vcu_peso"])
        cam["chocolates"] = 1 if any(p.get("CHOCOLATES") == 1 for p in pedidos_cam) else 0
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


def apply_truck_type_change(state: Dict[str, Any], truck_id: str, new_type: str, cliente: str) -> Dict[str, Any]:
    """
    Cambia el tipo de camión reusando compute_stats para estadísticas.
    Valida que el cambio sea permitido y que 'quepa' con el nuevo tipo
    (peso, volumen, pallets, posiciones y reglas del cliente).
    *NO* valida VCU mínimo por tu requerimiento.
    """
    camiones = state.get("camiones") or []
    pni      = state.get("pedidos_no_incluidos") or []
    if new_type not in ("normal", "bh"):
        raise ValueError("tipo_camion inválido (use 'normal' o 'bh').")

    # 1) localizar camión
    truck = next((t for t in camiones if t.get("id") == truck_id), None)
    if truck is None:
        raise ValueError("Camión no encontrado.")
    
    # Obtener config y asegurar opciones antes de validar
    client_config = get_client_config(cliente)
    try:
        sw_calc = _compute_switch_options(truck, client_config)
        if sw_calc:
            truck.setdefault("can_switch_tipo_camion", sw_calc["can_switch"])
            truck.setdefault("opciones_tipo_camion",   sw_calc["opciones"])
    except Exception:
        pass

    # 2) validar permiso básico (opciones calculadas previamente)
    opciones = truck.get("opciones_tipo_camion") or []
    can_switch = bool(truck.get("can_switch_tipo_camion", False))
    if opciones and new_type not in opciones:
        raise ValueError("Cambio no permitido para este camión.")
    if not opciones and not can_switch and new_type != truck.get("tipo_camion"):
        raise ValueError("Este camión no permite cambio de tipo.")

    # 3) capacidades del nuevo tipo
    if isinstance(client_config.TRUCK_TYPES, dict):
        tdict = client_config.TRUCK_TYPES
    else:
        tdict = {t.get('type'): t for t in client_config.TRUCK_TYPES}
    tsel  = tdict.get(new_type) or tdict.get('normal') or next(iter(tdict.values()))
    tnorm = tdict.get('normal') or tsel

    cap_weight    = float(tsel.get('cap_weight', tnorm['cap_weight']))
    cap_volume    = float(tsel.get('cap_volume', tnorm['cap_volume']))
    max_positions = int(tsel.get('max_positions', 30))
    max_pallets   = int(tsel.get('max_pallets', getattr(client_config, 'MAX_PALLETS_CONF', 60)))
    # vcu_min       = float(tsel.get('vcu_min', getattr(client_config, 'BH_VCU_MIN' if new_type=='bh' else 'VCU_MIN', 0.85)))  # <- ya no se usa
    vcu_max       = float(getattr(client_config, 'BH_VCU_MAX', 1.0)) if new_type == 'bh' else 1.0

    # 4) totalizadores (usar camión o re-sumar desde pedidos)
    def _sum_from_orders(trk: Dict[str, Any], key_truck: str, key_order: str) -> float:
        if trk.get(key_truck) is not None:
            return float(trk[key_truck])
        return float(sum((p.get(key_order) or 0) for p in trk.get('pedidos', [])))

    vol_total    = _sum_from_orders(truck, 'vol_total',  'VOL')
    peso_total   = _sum_from_orders(truck, 'peso_total', 'PESO')
    pallets_conf = truck.get('pallets_conf')
    if pallets_conf is None:
        pallets_conf = sum((p.get('PALLETS') or 0) for p in truck.get('pedidos', []))
    pos_total    = truck.get('pos_total', 0)

    # 5) VALIDACIONES compactas (sin helpers extra)
    # Capacidad dura por tipo
    if peso_total > cap_weight + 1e-6:
        raise ValueError("El peso total del camión excede la capacidad del nuevo tipo.")
    if vol_total > cap_volume + 1e-6:
        raise ValueError("El volumen total del camión excede la capacidad del nuevo tipo.")
    if float(pallets_conf) > float(max_pallets) + 1e-6:
        raise ValueError("El total de pallets del camión excede el máximo permitido para el nuevo tipo.")
    if int(pos_total) > int(max_positions):
        raise ValueError("Las posiciones ocupadas exceden el máximo permitido para el nuevo tipo.")

    # Reglas especiales Walmart
    if getattr(client_config, '__name__', '') == 'WalmartConfig':
        lista_p = truck.get('pedidos', [])
        if truck.get('tipo_ruta') == 'multi_cd':
            # 10 por CD y 20 total
            por_cd = {}
            for p in lista_p:
                cd = p.get('CD')
                if cd is None:
                    continue
                por_cd[cd] = por_cd.get(cd, 0) + 1
            for cd, cnt in por_cd.items():
                if cnt > 10:
                    raise ValueError(f"Camión excede 10 órdenes para el CD {cd} (Walmart multi_cd).")
            if len(lista_p) > 20:
                raise ValueError("Camión excede 20 órdenes totales (Walmart multi_cd).")
        else:
            max_ordenes = getattr(client_config, 'MAX_ORDENES', None)
            if max_ordenes is not None and len(lista_p) > int(max_ordenes):
                raise ValueError(f"Camión excede {int(max_ordenes)} órdenes (Walmart).")

    # Reglas BH (sin VCU mínimo)
    if new_type == 'bh':
        rutas_bh = getattr(client_config, 'RUTAS_POSIBLES', {}).get('bh', [])
        if not _ruta_coincide_con_bh(truck.get('cd'), truck.get('ce'), rutas_bh):
            raise ValueError("La ruta del camión no está habilitada para BH según la configuración del cliente.")
        if hasattr(client_config, 'CD_CON_BH'):
            for cd in (truck.get('cd') or []):
                if cd not in client_config.CD_CON_BH:
                    raise ValueError(f"El CD {cd} no admite BH para este cliente.")
        permite_mix = getattr(client_config, 'BH_PERMITE_MIX', False)
        if (not permite_mix) and (truck.get('flujo_oc') == 'MIX'):
            raise ValueError("BH no permite mezcla de flujos OC para este cliente.")


    # 6) Recalcular VCU del camión con capacidades del tipo nuevo (sin chequear mínimo)
    vcu_vol  = vol_total  / cap_volume if cap_volume > 0 else 0.0
    vcu_peso = peso_total / cap_weight if cap_weight > 0 else 0.0
    vcu_maxv = max(vcu_vol, vcu_peso)
    # if vcu_maxv < vcu_min:  # <- Eliminado por requerimiento
    #     raise ValueError("VCU por debajo del mínimo del tipo destino.")
    if new_type == 'bh' and vcu_maxv > vcu_max + 1e-9:
        raise ValueError("El VCU del camión excede el máximo permitido para BH.")

    # 7) Aplicar el cambio y refrescar métricas
    truck['tipo_camion'] = new_type
    truck['vcu_vol']     = vcu_vol
    truck['vcu_peso']    = vcu_peso
    truck['vcu_max']     = vcu_maxv

    # Rescatar opciones tras el cambio
    try:
        sw = _compute_switch_options(truck, client_config)
        truck['can_switch_tipo_camion'] = sw['can_switch']
        truck['opciones_tipo_camion']   = sw['opciones']
    except Exception:
        pass

    # 8) Recalcular estadísticas globales con la misma función de siempre
    stats = compute_stats(camiones, pni, cliente)
    return {"camiones": camiones, "pedidos_no_incluidos": pni, "estadisticas": stats}


def add_truck(state: Dict[str, Any], cd: List[str], ce: List[int], ruta: str, cliente: str) -> Dict[str, Any]:
    """
    Crea un camión vacío para la combinación CD/CE/ruta indicada.
    Ahora incluye can_switch_tipo_camion y opciones_tipo_camion si la ruta lo permite.
    """
    camiones = state.get("camiones") or []
    pni      = state.get("pedidos_no_incluidos") or []

    client_config = get_client_config(cliente)

    # Nuevo camión (vacío)
    nuevo = {
        "id": str(uuid.uuid4()),
        "cd": cd if isinstance(cd, list) else [cd],
        "ce": ce if isinstance(ce, list) else [ce],
        "tipo_ruta": ruta or "normal",
        "tipo_camion": "normal",
        "pedidos": [],
        "vcu_vol": 0.0,
        "vcu_peso": 0.0,
        "vcu_max": 0.0,
        "pallets_conf": 0.0,
        "pos_total": 0,
        "valor_total": 0.0,
        "valor_cafe": 0.0,
        # flujo_oc: None/‘MIX’/OC específico si lo determinas después
    }

    # Calcular opciones de cambio basadas en la configuración del cliente
    sw = _compute_switch_options(nuevo, client_config)
    nuevo['can_switch_tipo_camion'] = sw['can_switch']
    nuevo['opciones_tipo_camion']   = sw['opciones']

    # Insertar al final (o donde corresponda en tu UI)
    camiones.append(nuevo)

    # Recalcular estadísticas globales
    stats = compute_stats(camiones, pni, cliente)
    for idx, cam in enumerate(camiones, start=1):
        cam["numero"] = idx
    return {"camiones": camiones, "pedidos_no_incluidos": pni, "estadisticas": stats}


def delete_truck(state: Dict[str, Any], truck_id: Optional[str], cliente: str) -> Dict[str, Any]:
    camiones = state.get("camiones") or []
    no_incl = state.get("pedidos_no_incluidos") or []

    if truck_id:
        eliminado = next((c for c in camiones if c.get("id") == truck_id), None)
        if eliminado:
            camiones = [c for c in camiones if c.get("id") != truck_id]
            no_incl.extend(eliminado.get("pedidos") or [])

    return move_orders({"camiones": camiones, "pedidos_no_incluidos": no_incl}, [], None, cliente)


def enforce_bh_target(
    camiones: List[Dict[str, Any]],
    pedidos_no_incluidos: List[Dict[str, Any]],
    cliente: str,
    target_ratio: float,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Intenta alcanzar al menos 'target_ratio' de camiones BH convirtiendo
    camiones 'normal' a 'bh' cuando las reglas lo permiten.
    No fuerza nada imposible: si no hay candidatos, deja tal cual.

    Prioriza cambiar camiones con menor VCU (para minimizar riesgo).
    """
    try:
        cfg = get_client_config(cliente)
    except Exception:
        return camiones, pedidos_no_incluidos

    if not camiones or not getattr(cfg, "PERMITE_BH", False):
        return camiones, pedidos_no_incluidos
    if not (isinstance(target_ratio, (int, float)) and target_ratio > 0):
        return camiones, pedidos_no_incluidos

    total = len(camiones)
    deseado = int(math.ceil(target_ratio * total))
    actuales_bh = sum(1 for c in camiones if (c.get("tipo_camion") or "normal") == "bh")
    faltan = max(0, deseado - actuales_bh)
    if faltan == 0:
        return camiones, pedidos_no_incluidos

    # Candidatos: camiones normales que PUEDEN cambiar a BH según las reglas
    candidatos = []
    for c in camiones:
        if (c.get("tipo_camion") or "normal") == "bh":
            continue
        sw = _compute_switch_options(c, cfg)
        if "bh" in (sw.get("opciones") or []):
            candidatos.append(c)

    if not candidatos:
        return camiones, pedidos_no_incluidos

    # Orden simple: menor VCU primero (cambio “más seguro” para BH)
    candidatos.sort(key=lambda x: float(x.get("vcu_max") or 0.0))

    state = {"camiones": camiones, "pedidos_no_incluidos": pedidos_no_incluidos}
    for c in candidatos:
        if faltan <= 0:
            break
        try:
            state = apply_truck_type_change(state, c["id"], "bh", cliente)
            faltan -= 1
        except Exception:
            # si no se pudo cambiar (regla puntual), seguimos con otro
            continue

    return state.get("camiones", camiones), state.get("pedidos_no_incluidos", pedidos_no_incluidos)
