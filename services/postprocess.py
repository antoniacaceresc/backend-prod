from typing import List, Dict, Any, Optional
import uuid


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


def move_orders(
    state: Dict[str, Any],
    pedidos: Optional[List[Dict[str, Any]]],
    target_truck_id: Optional[str]
) -> Dict[str, Any]:
    camiones = state.get("camiones") or []
    no_incl = state.get("pedidos_no_incluidos") or []
    pedidos_sel = pedidos or []

    # 1) Eliminar pedidos seleccionados de camiones existentes
    seleccion_ids = {p.get("PEDIDO") for p in pedidos_sel}
    for cam in camiones:
        cam["pedidos"] = [p for p in cam.get("pedidos") or [] if p.get("PEDIDO") not in seleccion_ids]

    # 2) Eliminar pedidos seleccionados de no_incluidos
    no_incl = [p for p in no_incl if p.get("PEDIDO") not in seleccion_ids]

    # 3) Reinsertar pedidos en camión destino o en no_incluidos
    if target_truck_id:
        for cam in camiones:
            if cam.get("id") == target_truck_id:
                cam.setdefault("pedidos", []).extend(pedidos_sel)
                break
    else:
        no_incl.extend(pedidos_sel)

    # 4) Recalcular métricas de cada camión
    for cam in camiones:
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

        # Flujo OC
        oc_vals = {p.get("OC") for p in pedidos_cam if p.get("OC") not in (None, "")}      
        if not oc_vals:
            cam["flujo_oc"] = ""
        elif len(oc_vals) == 1:
            cam["flujo_oc"] = oc_vals.pop()
        else:
            cam["flujo_oc"] = "MIX"

        # Tipo de ruta
        ce_vals = {p.get("CE") for p in pedidos_cam if p.get("CE") not in (None, "")}        
        cd_vals = {p.get("CD") for p in pedidos_cam if p.get("CD") not in (None, "")}        
        if len(ce_vals) > 1:
            cam["tipo_ruta"] = "multi_ce"
        elif len(cd_vals) > 1:
            cam["tipo_ruta"] = "multi_cd"
        else:
            cam["tipo_ruta"] = "normal"

    # 5) Reenumerar números de camión
    for idx, cam in enumerate(camiones, start=1):
        cam["numero"] = idx

    # 6) Recalcular estadísticas globales
    stats = compute_stats(camiones, no_incl)
    return {"camiones": camiones, "pedidos_no_incluidos": no_incl, "estadisticas": stats}


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
