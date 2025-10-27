# services/optimizer.py
import uuid
import math
import os
import time
from typing import List, Dict, Any, Optional, Iterable, Tuple

import pandas as pd
from ortools.sat.python import cp_model

from services.file_processor import read_file, process_dataframe
from services.math_utils import format_dates
from config import get_client_config
from concurrent.futures import ThreadPoolExecutor, as_completed

# ---------------------------------------------------------
# Constantes (capping)
# ---------------------------------------------------------
MAX_CAMIONES_CP_SAT = int(os.getenv("MAX_CAMIONES_CP_SAT", "20"))
MAX_TIEMPO_POR_GRUPO = int(os.getenv("MAX_TIEMPO_POR_GRUPO", "30"))
SCALE = 1000  # para VCU
GROUP_MAX_WORKERS = max((os.cpu_count() or 4) - 1, 1)
GROUP_MAX_WORKERS = int(os.getenv("GROUP_MAX_WORKERS", str(GROUP_MAX_WORKERS)))
THREAD_WORKERS_NORMAL = int(os.getenv("THREAD_WORKERS_NORMAL", str(min(8, (os.cpu_count() or 4)))))



# ---------------------------------------------------------
# Helpers de timing
# ---------------------------------------------------------

def calcular_tiempo_por_grupo(df: pd.DataFrame, config, total_timeout: int, max_por_grupo: int) -> int:
    num_grupos = _contar_grupos(df, config)
    tiempo_total_disponible = max(total_timeout - 5, 1)
    if num_grupos > 0:
        tpg = tiempo_total_disponible // num_grupos
        return min(max(tpg, 1), max_por_grupo)
    return min(1, max_por_grupo)


# ---------------------------------------------------------
# Orquestación multi-modo
# ---------------------------------------------------------

def _build_normal_groups_disjoint(df: pd.DataFrame, rutas: list, mix_grupos: list, usa_oc: bool) -> list:
    """Particiona *exclusivamente* los pedidos en grupos disjuntos para rutas 'normal'.
    Mantiene el mismo orden de `generar_rutas` para compatibilidad de negocio.
    """
    grupos = []  # [(cfg, df_grp)]
    asignado = pd.Series(False, index=df.index)
    for cds, ces, oc in generar_rutas("normal", rutas, df, mix_grupos, usa_oc):
        mask = df["CD"].isin(cds) & df["CE"].isin(ces)
        if oc is not None:
            if isinstance(oc, list):
                mask &= df["OC"].isin(oc)
            else:
                mask &= df["OC"].eq(oc)
        mask &= ~asignado
        sub = df[mask]
        if sub.empty:
            continue
        cfg = {"id": f"normal__{'-'.join(cds)}__{'-'.join(map(str, ces))}" + (f"__{oc}" if oc else ""),
               "tipo": "normal", "ce": ces, "cd": cds, "oc": oc}
        grupos.append((cfg, sub.copy()))
        asignado.loc[sub.index] = True
    return grupos

def run_optimizacion(df: pd.DataFrame, raw_pedidos: List[Dict[str, Any]], config, modo: str, tpg: int, timeout: int) -> Dict[str, Any]:
    """Ejecuta optimización por fases según `modo` y postprocesa camiones."""
    res = ejecutar_optimizacion(df.copy(), raw_pedidos, config, modo, tpg, timeout)
    res["camiones"] = postprocesar_camiones(res.get("camiones", []), config)
    return res


# ---------------------------------------------------------
# Flujo principal expuesto
# ---------------------------------------------------------

def optimizar_con_dos_fases(raw_df: pd.DataFrame, client_config, cliente: str, venta: str, request_timeout: int, max_tpg: int) -> Dict[str, Any]:
    # 1) Preprocesamiento
    df_proc, pedidos = process_dataframe(raw_df, client_config, cliente, venta)
    pedidos = [{**p, "Fecha preferente de entrega": format_dates(p.get("Fecha preferente de entrega"))} for p in pedidos]

    # 2) Tiempo por grupo
    tpg = calcular_tiempo_por_grupo(df_proc, client_config, request_timeout, max_tpg)

    # 3) Modos
    resultado_vcu = run_optimizacion(df_proc, pedidos, client_config, "vcu", tpg, request_timeout)
    resultado_bp = run_optimizacion(df_proc, pedidos, client_config, "binpacking", tpg, request_timeout)

    # Objetivo suave de proporción BH por cliente
    try:
        from services.postprocess import enforce_bh_target
        target_ratio = getattr(client_config, "BH_TRUCK_TARGET_RATIO", None)
        if isinstance(target_ratio, (int, float)) and target_ratio > 0:
            # VCU
            cam, pni = enforce_bh_target(
                resultado_vcu.get("camiones", []),
                resultado_vcu.get("pedidos_no_incluidos", []),
                cliente, 
                float(target_ratio),
            )
            resultado_vcu["camiones"] = cam
            resultado_vcu["pedidos_no_incluidos"] = pni

            # BinPacking
            cam_b, pni_b = enforce_bh_target(
                resultado_bp.get("camiones", []),
                resultado_bp.get("pedidos_no_incluidos", []),
                cliente,
                float(target_ratio),
            )
            resultado_bp["camiones"] = cam_b
            resultado_bp["pedidos_no_incluidos"] = pni_b
    except Exception:
        # si algo falla, no rompemos el flujo principal
        pass

    # 4) Etiquetado BH en BinPacking

    if (getattr(client_config, "PERMITE_BH", False)
            and type(client_config).__name__ != "CencosudConfig"
            and str(cliente).strip().lower() != "cencosud"):
        for cam in resultado_bp.get("camiones", []):
            if (
                cam.get("cd", [None])[0] in getattr(client_config, "CD_CON_BH", [])
                and cam.get("flujo_oc") != "MIX"
                and cam.get("vcu_max", 0) <= getattr(client_config, "BH_VCU_MAX", 1)
                and cam.get("tipo_ruta") == "normal"
            ):
                cam["tipo_camion"] = "bh"


    return {"vcu": resultado_vcu, "binpacking": resultado_bp}


def procesar(content, filename, client, venta, REQUEST_TIMEOUT, vcuTarget, vcuTargetBH) -> Dict[str, Any]:
    """API interna (mantener firma): lee Excel, aplica overrides y ejecuta dos fases."""
    try:
        config = get_client_config(client)
        df_full = read_file(content, filename, config, venta)

        # Overrides de thresholds (si vienen del front)
        if vcuTarget is not None:
            try:
                vcuTarget = int(vcuTarget)
                vcuTarget = max(1, min(100, vcuTarget))
                config.VCU_MIN = float(vcuTarget) / 100.0
            except Exception:
                pass
        if vcuTargetBH is not None:
            try:
                vcuTargetBH = int(vcuTargetBH)
                vcuTargetBH = max(1, min(100, vcuTargetBH))
                config.BH_VCU_MIN = float(vcuTargetBH) / 100.0
            except Exception:
                pass

        return optimizar_con_dos_fases(df_full, config, client, venta, REQUEST_TIMEOUT, MAX_TIEMPO_POR_GRUPO)

    except Exception as e:
        import traceback as _tb
        return {"error": {"message": str(e), "traceback": _tb.format_exc()[:5000]}}


# ---------------------------------------------------------
# Cálculo de grupos
# ---------------------------------------------------------

def _contar_grupos(df: pd.DataFrame, config) -> int:
    tipos_ruta = ["multi_ce_prioridad", "normal", "multi_ce", "multi_cd", "bh"]
    fases = [(tipo, config.RUTAS_POSIBLES[tipo]) for tipo in tipos_ruta if tipo in config.RUTAS_POSIBLES]

    lo_ag = "6009 Lo Aguirre"
    total = 0
    mix_grupos = getattr(config, "MIX_GRUPOS", [])

    for tipo, rutas in fases:
        if tipo == "normal":
            for cds, ces in rutas:
                if cds == [lo_ag]:
                    df_cd = df[df["CD"] == lo_ag]
                    for ce in ces:
                        df_sub = df_cd[df_cd["CE"] == ce]
                        if getattr(config, "USA_OC", False):
                            oc_unique = df_sub["OC"].unique().tolist()
                            total += len(oc_unique)
                            for ocg in mix_grupos:
                                if all(o in oc_unique for o in ocg):
                                    total += 1
                        else:
                            total += 1
                else:
                    mask = df["CD"].isin(cds) & df["CE"].isin(ces)
                    if not df[mask].empty:
                        total += 1

        elif tipo == "bh":
            for cds, ces in rutas:
                mask = df["CD"].isin(cds) & df["CE"].isin(ces)
                df_sub = df[mask]
                total += len(df_sub["OC"].unique()) if getattr(config, "USA_OC", False) else 1

        else:  # multi_ce y multi_cd
            for cds, ces in rutas:
                mask = df["CD"].isin(cds) & df["CE"].isin(ces)
                df_sub = df[mask]
                if cds == [lo_ag] and getattr(config, "USA_OC", False):
                    total += len(df_sub["OC"].unique()) if not df_sub.empty else 0
                elif not df_sub.empty:
                    total += 1

    return total


# ---------------------------------------------------------
# Rutas, reconstrucción y heurística
# ---------------------------------------------------------

def generar_rutas(tipo: str, rutas: Iterable[Tuple[List[str], List[str]]], df: pd.DataFrame, mix_grupos: List[List[str]], usa_oc: bool):
    lo_ag = "6009 Lo Aguirre"
    rutas_iter = []

    if tipo == "normal":
        for cds, ces in rutas:
            if cds == [lo_ag]:
                df_cd = df[df["CD"] == lo_ag]
                for ce in ces:
                    df_sub = df_cd[df_cd["CE"] == ce]
                    if usa_oc:
                        oc_unique = df_sub["OC"].unique().tolist()
                        for oc in oc_unique:
                            rutas_iter.append(([lo_ag], [ce], oc))
                        for ocg in mix_grupos:
                            if all(o in oc_unique for o in ocg):
                                rutas_iter.append(([lo_ag], [ce], ocg))
                    else:
                        rutas_iter.append(([lo_ag], [ce], None))
            else:
                mask = df["CD"].isin(cds) & df["CE"].isin(ces)
                if not df[mask].empty:
                    rutas_iter.append((cds, ces, None))

    elif tipo == "bh":
        for cds, ces in rutas:
            mask = df["CD"].isin(cds) & df["CE"].isin(ces)
            df_sub = df[mask]
            if usa_oc:
                for oc in df_sub["OC"].unique().tolist():
                    rutas_iter.append((cds, ces, oc))
            else:
                rutas_iter.append((cds, ces, None))

    else:  # multi_ce y multi_cd
        for cds, ces in rutas:
            df_sub = df[df["CD"].isin(cds) & df["CE"].isin(ces)]
            if df_sub.empty:
                continue
            ce_presentes = set(df_sub["CE"].unique())
            cd_presentes = set(df_sub["CD"].unique())
            if tipo in ("multi_ce", "multi_ce_prioridad") and not all(ce in ce_presentes for ce in ces):
                continue
            if tipo == "multi_cd" and not all(cd in cd_presentes for cd in cds):
                continue
            if lo_ag in cds and usa_oc:
                for oc in df_sub["OC"].unique():
                    if not df_sub[df_sub["OC"] == oc].empty:
                        rutas_iter.append((cds, ces, oc))
            else:
                rutas_iter.append((cds, ces, None))

    return rutas_iter


def completar_metadata_pedido(pedido_minimal: dict, raw_map: dict) -> dict:
    p = pedido_minimal["PEDIDO"]
    completo = pedido_minimal.copy()
    if p not in raw_map:
        return completo
    for clave, valor in raw_map[p].items():
        if clave not in completo:
            completo[clave] = valor
    return completo


def heuristica_ffd(pedidos: List[Any], peso_raw: Dict[Any, float], vol_raw: Dict[Any, float], truck_caps: Dict[str, float]) -> int:
    cap_weight = truck_caps["cap_weight"]
    cap_volume = truck_caps["cap_volume"]
    pedidos_orden = sorted(
        pedidos,
        key=lambda i: max(peso_raw[i] / cap_weight, vol_raw[i] / cap_volume),
        reverse=True,
    )
    camiones: List[Tuple[float, float]] = []
    for i in pedidos_orden:
        for idx in range(len(camiones)):
            if camiones[idx][0] + peso_raw[i] <= cap_weight and camiones[idx][1] + vol_raw[i] <= cap_volume:
                camiones[idx] = (camiones[idx][0] + peso_raw[i], camiones[idx][1] + vol_raw[i])
                break
        else:
            camiones.append((peso_raw[i], vol_raw[i]))
    return len(camiones)


# ---------------------------------------------------------
# Núcleo: CP-SAT VCU y BinPacking
# ---------------------------------------------------------

def ejecutar_optimizacion(df: pd.DataFrame, raw_pedidos: List[Dict[str, Any]], config, modo: str, tiempo_por_grupo: int, REQUEST_TIMEOUT: int) -> Dict[str, Any]:
    raw_map = {r["PEDIDO"]: r.copy() for r in raw_pedidos}

    pedidos_all = df["PEDIDO"].tolist()
    vol_raw_all = dict(zip(pedidos_all, df["VOL"]))
    peso_raw_all = dict(zip(pedidos_all, df["PESO"]))

    # Selección de camión base (normal)
    if isinstance(config.TRUCK_TYPES, dict):
        truck_types = config.TRUCK_TYPES
    else:
        truck_types = {t.get("type"): t for t in config.TRUCK_TYPES}
    truck = truck_types.get("normal") or next(iter(truck_types.values()))
    cap_volume = float(truck["cap_volume"]) or 1.0
    cap_weight = float(truck["cap_weight"]) or 1.0

    # Precalcular fracciones escaladas VCU
    vcu_vol_int_all = {}
    vcu_peso_int_all = {}
    for i in pedidos_all:
        frac_vol = vol_raw_all[i] / cap_volume
        frac_peso = peso_raw_all[i] / cap_weight
        vcu_vol_int_all[i] = max(0, min(SCALE, int(math.ceil(frac_vol * SCALE))))
        vcu_peso_int_all[i] = max(0, min(SCALE, int(math.ceil(frac_peso * SCALE))))

    pedidos_rest = df.copy()
    resultados = []
    start_total = time.time()

    # Tipos/rutas por modo
    if modo == "binpacking":
        tipos_ruta = getattr(config, "BINPACKING_TIPOS_RUTA", ["normal"]) or ["normal"]
        rutas_bp = getattr(config, "RUTAS_BINPACKING", {})
        rutas_for = lambda t: rutas_bp.get(t, config.RUTAS_POSIBLES.get(t, []))
    else:
        tipos_ruta = ["multi_ce_prioridad", "normal", "multi_ce", "multi_cd", "bh"]
        rutas_for = lambda t: config.RUTAS_POSIBLES.get(t, [])

    fases = [(t, rutas_for(t)) for t in tipos_ruta if rutas_for(t)]

    total_orders = len(pedidos_all)
    mix_grupos = getattr(config, "MIX_GRUPOS", [])

    for tipo, rutas in fases:

        if tipo == "normal":
            # --- paralelización sólo para rutas normales ---
            grupos = _build_normal_groups_disjoint(pedidos_rest, rutas, mix_grupos, getattr(config, "USA_OC", False))
            if grupos:
                futures = []
                assigned_ids_all: List[str] = []
                with ThreadPoolExecutor(max_workers=min(THREAD_WORKERS_NORMAL, len(grupos))) as pool:
                    for cfg, df_g in grupos:
                        if df_g.empty:
                            continue
                        group_orders = len(df_g)
                        tiempo_group = max(1, int(tiempo_por_grupo * group_orders / 10))
                        if time.time() - start_total + tiempo_group > (REQUEST_TIMEOUT - 2):
                            continue
                        if modo == "vcu":
                            fut = pool.submit(
                                optimizar_vcu,
                                df_g, raw_pedidos, cfg, config, tiempo_group,
                                vol_raw_all, peso_raw_all, vcu_vol_int_all, vcu_peso_int_all,
                            )
                        else:
                            fut = pool.submit(
                                optimizar_bin,
                                df_g, raw_pedidos, cfg, config, tiempo_group,
                                vol_raw_all, peso_raw_all,
                            )
                        futures.append(fut)
                    # recoger resultados asegurando no duplicados
                    for fut in as_completed(futures, timeout=max(1, REQUEST_TIMEOUT - int(time.time() - start_total))):
                        try:
                            res = fut.result()
                        except Exception:
                            continue
                        if res.get("status") in ("OPTIMAL", "FEASIBLE") and res.get("camiones"):
                            nuevos = [p for p in res.get("pedidos_asignados_ids", []) if p not in assigned_ids_all]
                            if not nuevos:
                                continue
                            assigned_ids_all.extend(nuevos)
                            resultados.append(res)
                if assigned_ids_all:
                    pedidos_rest = pedidos_rest[~pedidos_rest["PEDIDO"].isin(assigned_ids_all)]
            if time.time() - start_total > (REQUEST_TIMEOUT - 2):
                break
        else:
            for cds, ces, oc in generar_rutas(tipo, rutas, pedidos_rest, mix_grupos, getattr(config, "USA_OC", False)):
                df_g = pedidos_rest[(pedidos_rest["CD"].isin(cds)) & (pedidos_rest["CE"].isin(ces))]
                if oc:
                    df_g = df_g[df_g["OC"].isin(oc if isinstance(oc, list) else [oc])]
                if df_g.empty:
                    continue

                group_orders = len(df_g)
                # asignación proporcional simple (evita exceder timeout total)
                tiempo_group = max(1, int(tiempo_por_grupo * group_orders / 10))

                cfg = {"id": f"{tipo}__{'-'.join(cds)}__{'-'.join(map(str, ces))}" + (f"__{oc}" if oc else ""),
                    "tipo": tipo, "ce": ces, "cd": cds, "oc": oc}
                if time.time() - start_total + tiempo_group > (REQUEST_TIMEOUT - 2):
                    break

                if modo == "vcu":
                    res = optimizar_vcu(
                        df_g, raw_pedidos, cfg, config,
                        tiempo_group, vol_raw_all, peso_raw_all,
                        vcu_vol_int_all, vcu_peso_int_all,
                    )
                else:
                    res = optimizar_bin(
                        df_g, raw_pedidos, cfg, config, tiempo_group, vol_raw_all, peso_raw_all
                    )

                if res.get("status") in ("OPTIMAL", "FEASIBLE") and res.get("camiones"):
                    resultados.append(res)
                    pedidos_rest = pedidos_rest[~pedidos_rest["PEDIDO"].isin(res["pedidos_asignados_ids"])]
            if time.time() - start_total > (REQUEST_TIMEOUT - 2):
                break

    all_cam = [c for r in resultados for c in r.get("camiones", [])]

    pedidos_no_incl: List[Dict[str, Any]] = []
    for pid in pedidos_rest["PEDIDO"].tolist():
        raw = raw_map.get(pid)
        if not raw:
            continue
        pedido = {
            "PEDIDO": pid,
            "CE": raw.get("CE"),
            "CD": raw.get("CD"),
            "OC": raw.get("OC") if "OC" in raw else None,
            "VCU_VOL": vol_raw_all[pid] / cap_volume,
            "VCU_PESO": peso_raw_all[pid] / cap_weight,
            "PO": raw.get("PO"),
            "CHOCOLATES": raw.get("CHOCOLATES"),
            "Fecha preferente de entrega": raw.get("Fecha preferente de entrega"),
        }
        pedidos_no_incl.append(completar_metadata_pedido(pedido, raw_map))

    return {"camiones": all_cam, "pedidos_no_incluidos": pedidos_no_incl}


# ---------------------------------------------------------
# Post-procesado de camiones (flujo OC + chocolates)
# ---------------------------------------------------------

def postprocesar_camiones(camiones: List[Dict[str, Any]], config) -> List[Dict[str, Any]]:
    for cam in camiones:
        if getattr(config, "USA_OC", False):
            ocs = {p.get("OC") for p in cam.get("pedidos", []) if p.get("OC")}
            cam["flujo_oc"] = next(iter(ocs)) if len(ocs) == 1 else ("MIX" if ocs else None)
        else:
            cam["flujo_oc"] = None
        cam["chocolates"] = 1 if any(p.get("CHOCOLATES") == 1 for p in cam.get("pedidos", [])) else 0

        # Opciones de cambio de tipo (se calculan con los campos ya presentes del camión)
        switch_info = _build_switch_options_for_truck(cam, config)
        cam['can_switch_tipo_camion'] = switch_info['can_switch']
        cam['opciones_tipo_camion'] = switch_info['opciones']
    return camiones


# =========================================================
# Helpers para opciones de cambio de tipo de camión
# =========================================================
def _ruta_coincide_con_bh(cds_cam: List[str], ces_cam: List[int], rutas_bh: List) -> bool:
    """
    Retorna True si el par (cds_cam, ces_cam) calza con alguna ruta BH declarada
    en RUTAS_POSIBLES['bh'] (subset match).
    """
    set_cd = set(cds_cam or [])
    set_ce = set(ces_cam or [])
    for cds, ces in rutas_bh or []:
        if set_cd.issubset(set(cds)) and set_ce.issubset(set(ces)):
            return True
    return False


def _build_switch_options_for_truck(cam: Dict[str, Any], client_config) -> Dict[str, Any]:
    """
    Construye las opciones de 'tipo_camion' disponibles para un camión dado,
    en base a la configuración del cliente y a los atributos del camión.
    Devuelve: {'can_switch': bool, 'opciones': [actual, ...]}
    """
    actual = (cam.get('tipo_camion') or 'normal').lower()
    opciones = ['normal']  # siempre permitir volver a 'normal'

    # Reglas BH (si el cliente lo permite)
    if getattr(client_config, 'PERMITE_BH', False):
        rutas_bh = getattr(client_config, 'RUTAS_POSIBLES', {}).get('bh', [])
        ruta_ok = _ruta_coincide_con_bh(cam.get('cd'), cam.get('ce'), rutas_bh)

        # Si existe lista de CDs que admiten BH, respetarla (si no existe, lo damos por OK)
        cd_ok = True
        if hasattr(client_config, 'CD_CON_BH'):
            cd_ok = all(cd in client_config.CD_CON_BH for cd in (cam.get('cd') or []))

        # Mezcla de flujos: por defecto no, salvo flag explícito
        permite_mix = getattr(client_config, 'BH_PERMITE_MIX', False)
        flujo = cam.get('flujo_oc')
        flujo_ok = True if permite_mix else (flujo not in ('MIX',))

        # Ventanas de VCU para BH (si existen en config)
        vcu = float(cam.get('vcu_max') or 0.0)
        vcu_ok = True
        if hasattr(client_config, 'BH_VCU_MAX'):
            vcu_ok = vcu_ok and (vcu <= float(client_config.BH_VCU_MAX))
        if hasattr(client_config, 'BH_VCU_MIN'):
            vcu_ok = vcu_ok and (vcu >= float(client_config.BH_VCU_MIN))

        if ruta_ok and cd_ok and flujo_ok and vcu_ok:
            opciones.append('bh')

    # Unificar y poner el actual primero
    seen = set()
    opciones = [o for o in ([actual] + [o for o in opciones if o != actual]) if not (o in seen or seen.add(o))]
    return {
        'can_switch': len(opciones) > 1,
        'opciones': opciones
    }

# ---------------------------------------------------------
# Modelos CP-SAT (VCU y BinPacking)
# ---------------------------------------------------------


def optimizar_vcu( df_g, raw_pedidos, grupo_cfg, client_config, tiempo_max_seg,
    vol_raw, peso_raw, vcu_vol_int, vcu_peso_int, PESO_VCU=1000, PESO_CAMIONES=200, PESO_PEDIDOS=3000):
    """
    Se parametriza `tiempo_max_seg` como tiempo límite para este CP-SAT.
    Además, limitamos n_cam nunca por encima de MAX_CAMIONES_CP_SAT.
    """
    raw_map = { r['PEDIDO']: r.copy() for r in raw_pedidos }
    df = df_g.copy()
    pedidos    = df['PEDIDO'].tolist()
    po_map     = dict(zip(pedidos, df['PO']))
    ce_map     = dict(zip(pedidos, df['CE']))
    cd_map     = dict(zip(pedidos, df['CD']))
    valor_map = dict(zip(pedidos, df['VALOR']))
    cafe_map = dict(zip(pedidos, df['VALOR_CAFE']))
    if 'CHOCOLATES' in df.columns:
        chocolates_map = dict(zip(pedidos, df['CHOCOLATES']))
    else:
        chocolates_map = {i: 0 for i in pedidos}
    if 'OC' in df.columns:
        oc_map = dict(zip(pedidos, df['OC']))
    else:
        oc_map = {i: None for i in pedidos}
    
    valuable_map = dict(zip(pedidos, df_g['VALIOSO']))
    pdq_map = dict(zip(pedidos, df["PDQ"]))
    pallets_conf_map    = dict(zip(pedidos, df['PALLETS']))
    pallets_real_map = dict(zip(pedidos, df['PALLETS_REAL'])) if 'PALLETS_REAL' in df.columns else None
    pallets_cap_map = pallets_real_map if pallets_real_map is not None else pallets_conf_map

    baja_vu_map = dict(zip(pedidos, df_g["BAJA_VU"]))
    lote_dir_map = dict(zip(pedidos, df_g["LOTE_DIR"]))
    saldo_inv_map = dict(zip(pedidos, df_g["SALDO_INV"]))

    # MAPEOS DE APILABILIDAD
    base_map        = dict(zip(pedidos, df['BASE']))
    superior_map    = dict(zip(pedidos, df['SUPERIOR']))
    flexible_map    = dict(zip(pedidos, df['FLEXIBLE']))
    no_apil_map     = dict(zip(pedidos, df['NO_APILABLE']))
    si_mismo_map    = dict(zip(pedidos, df['SI_MISMO']))


    # Escalamiento a enteros (igual que haces con pallets_conf)
    PALLETS_SCALE = 10
    base_int     = {i: int(base_map[i]      * PALLETS_SCALE) for i in pedidos}
    superior_int = {i: int(superior_map[i]  * PALLETS_SCALE) for i in pedidos}
    flex_int     = {i: int(flexible_map[i]  * PALLETS_SCALE) for i in pedidos}
    noap_int     = {i: int(no_apil_map[i]   * PALLETS_SCALE) for i in pedidos}
    self_int     = {i: int(si_mismo_map[i]  * PALLETS_SCALE) for i in pedidos}
 
    # Información camión
    # Normalización a dict + selección por tipo
    if isinstance(client_config.TRUCK_TYPES, dict):
        truck_types = client_config.TRUCK_TYPES
    else:
        truck_types = {t.get('type'): t for t in client_config.TRUCK_TYPES}

    tipo = (grupo_cfg.get('tipo') or 'normal').lower()
    tsel  = truck_types.get(tipo)    or truck_types.get('normal') or next(iter(truck_types.values()))
    tnorm = truck_types.get('normal') or tsel

    # Capacidades (si BH tiene mismas capacidades no importa; si difiere, se respeta lo que tenga tsel)
    cap_volume  = tsel.get('cap_volume', tnorm['cap_volume'])
    cap_weight  = tsel.get('cap_weight', tnorm['cap_weight'])

    # Umbrales/param
    VCU_MIN         = tsel.get('vcu_min', getattr(client_config, 'BH_VCU_MIN' if tipo=='bh' else 'VCU_MIN', 0.85))
    MAX_POSITIONS   = int(tsel.get('max_positions', 30))
    MAX_PALLETS_CONF= int(tsel.get('max_pallets', getattr(client_config, 'MAX_PALLETS_CONF', 60)))
    levels          = int(tsel.get('levels', 2))

 
    # --- Escalamiento a enteros ---
    VCU_MIN_int     = int(round(VCU_MIN * SCALE))
    pallets_conf_int = { i: int(pallets_conf_map[i] * PALLETS_SCALE) for i in pedidos}
    pallets_cap_int = { i: int(pallets_cap_map[i] * PALLETS_SCALE) for i in pedidos }

 
    # 1) Estimamos n_cam con heurística FFD
    n_cam_heur = heuristica_ffd( pedidos, peso_raw, vol_raw, {'cap_weight': cap_weight, 'cap_volume': cap_volume} )
    # 2) Limitamos a MAX_CAMIONES_CP_SAT
    n_cam      = min(len(pedidos), n_cam_heur, MAX_CAMIONES_CP_SAT)
 
    model = cp_model.CpModel()
 
    # Variables x[(i, j)]
    x = {}
    for i in pedidos:
        if vol_raw[i] <= cap_volume and peso_raw[i] <= cap_weight:
            for j in range(n_cam):
                x[(i, j)] = model.NewBoolVar(f"x_vcu_{i}_{j}")
 
    if client_config.AGRUPAR_POR_PO:
        agregar_restricciones_agrupacion_por_po(model, x, pedidos, po_map, n_cam)
 
    # Variables y_truck[j]
    y_truck = {j: model.NewBoolVar(f"y_vcu_truck_{j}") for j in range(n_cam)}
 
    # Acumulados (enteros)
    vol_cam_int  = {}
    peso_cam_int = {}
    for j in range(n_cam):
        lista_i = [i for i in pedidos if (i, j) in x]
        vol_cam_int[j]  = sum(vcu_vol_int[i]  * x[(i, j)] for i in lista_i)
        peso_cam_int[j] = sum(vcu_peso_int[i] * x[(i, j)] for i in lista_i)
 
    # vcu_max_int[j]
    vcu_max_int = {}
    for j in range(n_cam):
        v = model.NewIntVar(0, SCALE, f"vcu_max_int_{j}")
        model.AddMaxEquality(v, [vol_cam_int[j], peso_cam_int[j]])
        vcu_max_int[j] = v
    
    # --- NUEVO: límites duros de capacidad por camión (no exceder 100%) ---
    for j in range(n_cam):
        # si el camión j está activo (y_truck[j] = 1), la suma no puede superar SCALE
        model.Add(vol_cam_int[j]  <= SCALE * y_truck[j])
        model.Add(peso_cam_int[j] <= SCALE * y_truck[j])

        # (opcional pero redundante) Acotar también vcu_max_int por seguridad:
        model.Add(vcu_max_int[j] <= SCALE * y_truck[j])
    
 
 
    # 6) Restricciones
    for i in pedidos:
        vars_i = [x[(i, j)] for j in range(n_cam) if (i, j) in x]
        model.Add(sum(vars_i) <= 1)
 
    for (i, j), vx in x.items():
        model.Add(vx <= y_truck[j])
 
    for j in range(1, n_cam):
        model.Add(y_truck[j] <= y_truck[j - 1])
 
    # VCU mínimo: solo si y_truck[j] = 1
    for j in range(n_cam):
        model.Add(vcu_max_int[j] >= VCU_MIN_int).OnlyEnforceIf(y_truck[j])
 
    total_stack_vars = {}
    # Restricción de pallets y número de órdenes
    for j in range(n_cam):
        lista_i = [i for i in pedidos if (i, j) in x]
        
        # Camión abierto debe tener mínimo un pedido
        if lista_i:
            model.Add(sum(x[(i, j)] for i in lista_i) >= y_truck[j])
    
        model.Add(sum(pallets_cap_int[i] * x[(i,j)] for i in lista_i) <= MAX_PALLETS_CONF * PALLETS_SCALE * y_truck[j])

        # ——— SOLO WALMART + multi_cd: máx. 10 por CD y 20 total ———
        if (grupo_cfg['tipo'] == 'multi_cd') and (client_config.__name__ == 'WalmartConfig'):
            cds_en_grupo = {cd_map[i] for i in lista_i}
            for cd in cds_en_grupo:
                pedidos_de_cd = [i for i in lista_i if cd_map[i] == cd]
                if pedidos_de_cd:
                    model.Add(sum(x[(i, j)] for i in pedidos_de_cd) <= 10 * y_truck[j])
            model.Add(sum(x[(i, j)] for i in lista_i) <= 20 * y_truck[j])
        elif (client_config.__name__ == 'WalmartConfig'):
            model.Add(sum(x[(i, j)] for i in lista_i) <= client_config.MAX_ORDENES * y_truck[j])

        # —– NUEVAS RESTRICCIONES DE APILABILIDAD —–
        # 1) totales de cada tipo
        model.Add( sum(base_int[i]     * x[(i,j)] for i in lista_i)
                   <= MAX_POSITIONS * PALLETS_SCALE * y_truck[j] )
        model.Add( sum(superior_int[i] * x[(i,j)] for i in lista_i)
                   <= MAX_POSITIONS * PALLETS_SCALE * y_truck[j] )
        model.Add( sum(noap_int[i]     * x[(i,j)] for i in lista_i)
                   <= MAX_POSITIONS * PALLETS_SCALE * y_truck[j] )
        model.Add( sum(flex_int[i]     * x[(i,j)] for i in lista_i)
                   <= MAX_POSITIONS * levels * PALLETS_SCALE * y_truck[j] )

        # 2) combinaciones
        model.Add( sum((base_int[i] + noap_int[i]) * x[(i,j)] for i in lista_i)
                   <= MAX_POSITIONS * PALLETS_SCALE * y_truck[j] )
        model.Add( sum((superior_int[i] + noap_int[i]) * x[(i,j)] for i in lista_i)
                   <= MAX_POSITIONS * PALLETS_SCALE * y_truck[j] )
        
        # —– CÁLCULO COMPONENTES DEL LÍMITE DE APILABILIDAD —–
        # suma por tipo
        base_sum     = sum(base_int[i]     * x[(i,j)] for i in lista_i)
        superior_sum = sum(superior_int[i] * x[(i,j)] for i in lista_i)
        flex_sum     = sum(flex_int[i]     * x[(i,j)] for i in lista_i)
        noap_sum     = sum(noap_int[i]     * x[(i,j)] for i in lista_i)

        # —– 0) diff = BASE − SUPERIOR; abs_diff = |diff| —–
        diff     = model.NewIntVar(-MAX_POSITIONS*PALLETS_SCALE,
                                MAX_POSITIONS*PALLETS_SCALE,
                                f"diff_{j}")
        abs_diff = model.NewIntVar(0,
                                MAX_POSITIONS*PALLETS_SCALE,
                                f"abs_diff_{j}")
        model.Add(diff == base_sum + (-1) * superior_sum)
        model.AddAbsEquality(abs_diff, diff)

        # —– 1) a = min(base_sum, superior_sum) —–
        m0 = model.NewIntVar(0,
                            MAX_POSITIONS*PALLETS_SCALE,
                            f"m0_{j}")
        b0 = model.NewBoolVar(f"b0_{j}")
        model.Add(base_sum <= superior_sum).OnlyEnforceIf(b0)
        model.Add(base_sum >  superior_sum).OnlyEnforceIf(b0.Not())
        model.Add(m0 == base_sum).OnlyEnforceIf(b0)
        model.Add(m0 == superior_sum).OnlyEnforceIf(b0.Not())

        # —– 2) b = min(abs_diff, flex_sum) —–
        m1 = model.NewIntVar(0,
                            MAX_POSITIONS*PALLETS_SCALE,
                            f"m1_{j}")
        b1 = model.NewBoolVar(f"b1_{j}")
        model.Add(abs_diff <= flex_sum).OnlyEnforceIf(b1)
        model.Add(abs_diff >  flex_sum).OnlyEnforceIf(b1.Not())
        model.Add(m1 == abs_diff).OnlyEnforceIf(b1)
        model.Add(m1 == flex_sum).OnlyEnforceIf(b1.Not())

        # —– 3) c = round((flex_sum − m1)/2) —–
        rem  = model.NewIntVar(0,
                            MAX_POSITIONS*PALLETS_SCALE,
                            f"rem_{j}")
        half = model.NewIntVar(0,
                            MAX_POSITIONS*PALLETS_SCALE,
                            f"half_{j}")
        model.Add(rem == flex_sum + (-1) * m1)
        # half = ceil(rem/2):
        model.Add(2 * half >= rem)
        model.Add(2 * half <= rem + 1)

        # —– 4) d = max(abs_diff − flex_sum, 0) —–
        m2 = model.NewIntVar(0,
                            MAX_POSITIONS*PALLETS_SCALE,
                            f"m2_{j}")
        b2 = model.NewBoolVar(f"b2_{j}")
        model.Add(abs_diff >= flex_sum).OnlyEnforceIf(b2)
        model.Add(abs_diff <  flex_sum).OnlyEnforceIf(b2.Not())
        model.Add(m2 == abs_diff + (-1) * flex_sum).OnlyEnforceIf(b2)
        model.Add(m2 == 0).OnlyEnforceIf(b2.Not())

        # SI_MISMO: pares cuentan como posiciones, el resto se suma a NO_APILABLE
        self_sum_expr = sum(self_int[i] * x[(i,j)] for i in lista_i)

        # Para usar AddDivisionEquality, ligamos la suma a una IntVar
        self_sum = model.NewIntVar(0, MAX_POSITIONS * PALLETS_SCALE * levels * 2, f"self_sum_{j}")
        model.Add(self_sum == self_sum_expr)

        pair_q = model.NewIntVar(0, MAX_POSITIONS, f"self_pairs_q_{j}")  # cantidad de pares (no escalado)
        model.AddDivisionEquality(pair_q, self_sum, 2 * PALLETS_SCALE)    # q = floor(self_sum / (2*scale))

        self_rem = model.NewIntVar(0, 2 * PALLETS_SCALE - 1, f"self_rem_{j}")  # resto en unidades PALLETS_SCALE
        model.Add(self_rem == self_sum - pair_q * (2 * PALLETS_SCALE))

        # pares expresados en "posiciones escaladas"
        self_pairs_scaled = model.NewIntVar(0, MAX_POSITIONS * PALLETS_SCALE, f"self_pairs_scaled_{j}")
        model.Add(self_pairs_scaled == pair_q * PALLETS_SCALE)

        
        # 6) total_stack = m0 + m1 + half + m2
        total_stack = model.NewIntVar(
            -MAX_POSITIONS*PALLETS_SCALE*2,
            MAX_POSITIONS*PALLETS_SCALE*4,
            f"total_stack_{j}"
        )
        model.Add(total_stack == m0 + m1 + half + m2 + noap_sum + self_pairs_scaled + self_rem)

        # 7) umbral: total_stack ≤ max_positions * PALLETS_SCALE  si el camión está usado
        model.Add(
            total_stack 
            <= (MAX_POSITIONS * PALLETS_SCALE) * y_truck[j]
        )
        total_stack_vars[j] = total_stack

 
    # 7) Función objetivo
    obj_terms = []
    for j in range(n_cam): #max vcu
        obj_terms.append(PESO_VCU * vcu_max_int[j])
    for vx in x.values(): #incluir más pedidos
        obj_terms.append(PESO_PEDIDOS * vx)
    for j in range(n_cam): #minim camiones
        obj_terms.append(- (PESO_CAMIONES * SCALE) * y_truck[j])
 
    model.Maximize(sum(obj_terms))
 
    # 8) Ejecución del solver con parámetro de tiempo
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(tiempo_max_seg)
    #solver.parameters.relative_gap_limit = 0.01
    solver.parameters.num_search_workers  = 1  # Para no usar CPU extra en Render
    t0 = time.time()
    resultado = solver.Solve(model)
    t1 = time.time()
    status_map = {cp_model.OPTIMAL: 'OPTIMAL', cp_model.FEASIBLE: 'FEASIBLE'}
    estado     = status_map.get(resultado, 'NO_SOLUTION')
    print(f"[TIMING] CP-SAT (VCU) grupo {grupo_cfg['id']}: {t1 - t0:.3f} s (límite: {tiempo_max_seg}s), estado: {estado}")
 
 
    # 9) Reconstruir salida
    pedidos_incluidos = []
    camiones = []
    idx_cam = 1
    if grupo_cfg['tipo'] == 'bh':
        tt = 'bh'
    else:
        tt = 'normal'

    for j, ts_var in total_stack_vars.items():
        # Sólo imprime si el camión j está usado (opcional)
        if solver.Value(y_truck[j]):
            print(f"Camión {j} → total_stack = {solver.Value(ts_var)}")
    
    for j in range(n_cam):
        if solver.Value(y_truck[j]) < 1:
            continue
        grp = []
        for (i2, j2), vx in x.items():
            if j2 == j and solver.Value(vx) == 1:
                grp.append(i2)
                pedidos_incluidos.append(i2)
 
        vol_sum   = sum(vol_raw[i]  for i in grp)
        peso_sum  = sum(peso_raw[i] for i in grp)
        vcu_vol_j  = (vol_sum  / float(cap_volume))  if cap_volume  else 0.0
        vcu_peso_j = (peso_sum / float(cap_weight))  if cap_weight  else 0.0
        vcu_max_j  = max(vcu_vol_j, vcu_peso_j)
 
        datos_asig = []
        for i in grp:
            vcu_vol_i  = (vol_raw[i]  / float(cap_volume))  if cap_volume  else 0.0
            vcu_peso_i = (peso_raw[i] / float(cap_weight))  if cap_weight  else 0.0
 
            pedido_min = {
                'PEDIDO':       i,
                'CAMION':       idx_cam,
                'GRUPO':        grupo_cfg['id'],
                'TIPO_RUTA':    grupo_cfg['tipo'],
                'TIPO_CAMION':  tt,
                'CE':           ce_map[i],
                'CD':           cd_map[i],
                'VCU_VOL':      vcu_vol_i,
                'VCU_PESO':     vcu_peso_i,
                'CHOCOLATES':   chocolates_map[i],
                'VALIOSO':      valuable_map[i],
                'PDQ':          pdq_map[i],
                'BAJA_VU':      baja_vu_map[i],
                'LOTE_DIR':     lote_dir_map[i],
                'SALDO_INV':    saldo_inv_map[i], 
                'PO':           po_map[i],
                'OC':           oc_map[i],
                'PALLETS':      pallets_conf_map[i],
                'VALOR': valor_map[i],
            }
 
            pedido_completo = completar_metadata_pedido(pedido_min, raw_map)
            datos_asig.append(pedido_completo)
       
        valor_total = sum(valor_map.get(i, 0) or 0 for i in grp)
        valor_cafe = sum(cafe_map.get(i, 0) or 0 for i in grp)
        tiene_chocolates = any(chocolates_map.get(i) == 1 for i in grp)
        pallets_conf = sum(pallets_conf_map[i] for i in grp)
        valioso = any(valuable_map.get(i) == 1 for i in grp)
        pdq = any(pdq_map.get(i) == 1 for i in grp)
        baja_vu = any(baja_vu_map.get(i) == 1 for i in grp)
        lote_dir = any(lote_dir_map.get(i) == 1 for i in grp)
        saldo_inv = any(saldo_inv_map.get(i) == 1 for i in grp)
        ts_val = solver.Value(total_stack_vars[j]) if j in total_stack_vars else 0
        pos_total = ts_val / PALLETS_SCALE
       
        camiones.append({
            'id':               uuid.uuid4().hex,
            'grupo':            grupo_cfg['id'],
            'tipo_ruta':        grupo_cfg['tipo'],
            'ce':               grupo_cfg['ce'],
            'cd':               grupo_cfg['cd'],
            'tipo_camion':      tt,
            'vcu_vol':          vcu_vol_j,
            'vcu_peso':         vcu_peso_j,
            'vcu_max':          vcu_max_j,
            'chocolates':       1 if tiene_chocolates else 0,
            'skus_valiosos':    valioso,
            'pdq':              pdq,
            'baja_vu':          baja_vu,
            'lote_dir':         lote_dir,
            'saldo_inv':        saldo_inv,
            'valor_total':      valor_total,
            'valor_cafe':       valor_cafe,
            'pallets_conf':     pallets_conf,
            'pedidos':          datos_asig,
            'pos_total':        pos_total,
        })
        idx_cam += 1
 
    pedidos_excluidos_ids = [i for i in pedidos if i not in pedidos_incluidos]
    pedidos_excluidos = []
    for i in pedidos_excluidos_ids:
        pedido_min = {
            'PEDIDO':       i,
            'CE':           ce_map[i],
            'CD':           cd_map[i],
            'OC':           oc_map[i],
            'VCU_VOL':      (vol_raw[i] / float(cap_volume)) if cap_volume else 0.0,
            'VCU_PESO':     (peso_raw[i] / float(cap_weight)) if cap_weight else 0.0,
            'PO':           po_map[i],
            'PALLETS':      pallets_conf_map[i],
            'VALOR':        valor_map[i],
        }
        pedido_ex_completo = completar_metadata_pedido(pedido_min, raw_map)
        pedidos_excluidos.append(pedido_ex_completo)
 
    return {
        'status':                estado,
        'pedidos_asignados_ids': pedidos_incluidos,
        'pedidos_asignados':     [pa for cam in camiones for pa in cam['pedidos']],
        'pedidos_excluidos':     pedidos_excluidos,
        'camiones':              camiones
    }
 

def optimizar_bin(df_g, raw_pedidos, grupo_cfg, client_config, tiempo_max_seg, vol_raw, peso_raw):
    """
    BinPacking (CP-SAT) con:
    - Solo camiones de tipo 'S'
    - FFD para acotar n_cam
    - índices categóricos y pre-indexado
    - eliminar rutas sin pedidos antes de llamar al solver
    """
    raw_map = { r['PEDIDO']: r.copy() for r in raw_pedidos }
 
    df_g = df_g.copy()
    df_g['CD'] = df_g['CD'].astype('category')
    df_g['CE'] = df_g['CE'].astype('category')
    pedidos = df_g['PEDIDO'].tolist()
    # Convertimos a enteros redondeando para CP-SAT
    vol_int  = {i: int(round(vol_raw[i]))  for i in pedidos}
    peso_int = {i: int(round(peso_raw[i])) for i in pedidos}
    po_map = dict(zip(pedidos, df_g['PO']))
    ce_map = dict(zip(pedidos, df_g['CE']))
    cd_map = dict(zip(pedidos, df_g['CD']))
    if 'OC' in df_g.columns:
        oc_map = dict(zip(pedidos, df_g['OC']))
    else:
        oc_map = {i: None for i in pedidos}
    valor_map = dict(zip(pedidos, df_g['VALOR']))
    cafe_map = dict(zip(pedidos, df_g['VALOR_CAFE']))
    pallets_conf_map    = dict(zip(pedidos, df_g['PALLETS']))
    pallets_real_map = dict(zip(pedidos, df_g['PALLETS_REAL'])) if 'PALLETS_REAL' in df_g.columns else None
    pallets_cap_map  = pallets_real_map if pallets_real_map is not None else pallets_conf_map # real si es Cencosud, sino Pall. Conf.

    if 'CHOCOLATES' in df_g.columns:
        chocolates_map = dict(zip(pedidos, df_g['CHOCOLATES']))
    else:
        chocolates_map = {i: 0 for i in pedidos}
    
    valuable_map = dict(zip(pedidos, df_g['VALIOSO']))
    pdq_map = dict(zip(pedidos, df_g["PDQ"]))
    baja_vu_map = dict(zip(pedidos, df_g["BAJA_VU"]))
    lote_dir_map = dict(zip(pedidos, df_g["LOTE_DIR"]))
    saldo_inv_map = dict(zip(pedidos, df_g["SALDO_INV"]))
 
    # MAPEOS DE APILABILIDAD
    base_map        = dict(zip(pedidos, df_g['BASE']))
    superior_map    = dict(zip(pedidos, df_g['SUPERIOR']))
    flexible_map    = dict(zip(pedidos, df_g['FLEXIBLE']))
    no_apil_map     = dict(zip(pedidos, df_g['NO_APILABLE']))
    si_mismo_map    = dict(zip(pedidos, df_g['SI_MISMO']))

    # Escalamiento a enteros (igual que haces con pallets_conf)
    PALLETS_SCALE = 10
    base_int     = {i: int(base_map[i]      * PALLETS_SCALE) for i in pedidos}
    superior_int = {i: int(superior_map[i]  * PALLETS_SCALE) for i in pedidos}
    flex_int     = {i: int(flexible_map[i]  * PALLETS_SCALE) for i in pedidos}
    noap_int     = {i: int(no_apil_map[i]   * PALLETS_SCALE) for i in pedidos}
    self_int     = {i: int(si_mismo_map[i]  * PALLETS_SCALE) for i in pedidos}

 
    # Información camión
    if isinstance(client_config.TRUCK_TYPES, dict):
        truck_types = client_config.TRUCK_TYPES
    else:
        truck_types = {t.get('type'): t for t in client_config.TRUCK_TYPES}

    tipo = (grupo_cfg.get('tipo') or 'normal').lower()
    tsel  = truck_types.get(tipo)    or truck_types.get('normal') or next(iter(truck_types.values()))
    tnorm = truck_types.get('normal') or tsel

    cap_volume  = tsel.get('cap_volume', tnorm['cap_volume'])
    cap_weight  = tsel.get('cap_weight', tnorm['cap_weight'])

    MAX_PALLETS_CONF = int(tsel.get('max_pallets', getattr(client_config, 'MAX_PALLETS_CONF', 60)))
    MAX_POSITIONS    = int(tsel.get('max_positions', 30))
    levels           = int(tsel.get('levels', 2))

    pallets_conf_int = {i: int((pallets_conf_map[i]) * PALLETS_SCALE) for i in pedidos}
    pallets_cap_int = {i: int((pallets_cap_map[i]) * PALLETS_SCALE) for i in pedidos} # real si es Cencosud, sino Pall. Conf.


    # 2) Heurística FFD para estimar n_cam
    n_cam_heur = heuristica_ffd(pedidos, peso_int, vol_int, {'cap_weight': cap_weight, 'cap_volume': cap_volume})
    n_cam = min(len(pedidos), n_cam_heur + 5)
 

    # 3) Construir modelo CP-SAT
    model = cp_model.CpModel()
    x = {}
    for i in pedidos:
        for j in range(n_cam):
            vid = str(i)
            x[(i, j)] = model.NewBoolVar(f"x_bin_{vid}_{j}")
 
    if client_config.AGRUPAR_POR_PO:
        agregar_restricciones_agrupacion_por_po(model, x, pedidos, po_map, n_cam)
 
    y = {j: model.NewBoolVar(f"y_bin_{j}") for j in range(n_cam)}
   
    # Cada pedido EXACTAMENTE en un camión
    for i in pedidos:
        model.Add(sum(x[(i, j2)] for j2 in range(n_cam)) == 1)
   
    total_stack_vars = {}
    # 4) Restricciones agrupadas
    for j in range(n_cam):
        for i in pedidos:
            model.Add(x[(i, j)] <= y[j])

        # Al menos un pedido para abrir el camión
        model.Add(sum(x[(i, j)] for i in pedidos) >= y[j])
        
        # Capacidad peso/vol
        suma_peso = sum(int(round(peso_int[i])) * x[(i, j)] for i in pedidos)
        suma_vol = sum(int(round(vol_int[i])) * x[(i, j)] for i in pedidos)
        model.Add(suma_peso <= cap_weight * y[j])
        model.Add(suma_vol <= cap_volume * y[j])
        # Posiciones y órdenes

        # ——— SOLO WALMART + multi_cd: máx. 10 por CD y 20 total ———
        if (grupo_cfg['tipo'] == 'multi_cd') and (client_config.__name__ == 'WalmartConfig'):
            cds_en_grupo = {cd_map[i] for i in pedidos}
            for cd in cds_en_grupo:
                pedidos_de_cd = [i for i in pedidos if cd_map[i] == cd]
                if pedidos_de_cd:
                    model.Add(sum(x[(i, j)] for i in pedidos_de_cd) <= 10 * y[j])
            model.Add(sum(x[(i, j)] for i in pedidos) <= 20 * y[j])
        elif (client_config.__name__ == 'WalmartConfig'):
            model.Add(sum(x[(i, j)] for i in pedidos) <= client_config.MAX_ORDENES * y[j])

        model.Add(sum( pallets_cap_int[i] * x[(i, j)] for i in pedidos ) <= MAX_PALLETS_CONF * PALLETS_SCALE * y[j] )
        
        # Monotonía y[j] <= y[j-1]
        if j >= 1:
            model.Add(y[j] <= y[j - 1])

        lista_i = [i for i in pedidos]  # o filtra los i con (i,j) si prefieres

        # —– NUEVAS RESTRICCIONES DE APILABILIDAD —–
        # 1) totales de cada tipo
        model.Add( sum(base_int[i]     * x[(i,j)] for i in lista_i)
                   <= MAX_POSITIONS * PALLETS_SCALE * y[j] )
        model.Add( sum(superior_int[i] * x[(i,j)] for i in lista_i)
                   <= MAX_POSITIONS * PALLETS_SCALE * y[j] )
        model.Add( sum(noap_int[i]     * x[(i,j)] for i in lista_i)
                   <= MAX_POSITIONS * PALLETS_SCALE * y[j] )
        model.Add( sum(flex_int[i]     * x[(i,j)] for i in lista_i)
                   <= MAX_POSITIONS * levels * PALLETS_SCALE * y[j] )

        # 2) combinaciones
        model.Add( sum((base_int[i] + noap_int[i]) * x[(i,j)] for i in lista_i)
                   <= MAX_POSITIONS * PALLETS_SCALE * y[j] )
        model.Add( sum((superior_int[i] + noap_int[i]) * x[(i,j)] for i in lista_i)
                   <= MAX_POSITIONS * PALLETS_SCALE * y[j] )
        
        # —– CÁLCULO COMPONENTES DEL LÍMITE DE APILABILIDAD —–
        # suma por tipo
        base_sum     = sum(base_int[i]     * x[(i,j)] for i in lista_i)
        superior_sum = sum(superior_int[i] * x[(i,j)] for i in lista_i)
        flex_sum     = sum(flex_int[i]     * x[(i,j)] for i in lista_i)
        noap_sum     = sum(noap_int[i]     * x[(i,j)] for i in lista_i)

        # —– 0) diff = BASE − SUPERIOR; abs_diff = |diff| —–
        diff     = model.NewIntVar(-MAX_POSITIONS*PALLETS_SCALE,
                                MAX_POSITIONS*PALLETS_SCALE,
                                f"diff_{j}")
        abs_diff = model.NewIntVar(0,
                                MAX_POSITIONS*PALLETS_SCALE,
                                f"abs_diff_{j}")
        model.Add(diff == base_sum + (-1) * superior_sum)
        model.AddAbsEquality(abs_diff, diff)

        # —– 1) a = min(base_sum, superior_sum) —–
        m0 = model.NewIntVar(0,
                            MAX_POSITIONS*PALLETS_SCALE,
                            f"m0_{j}")
        b0 = model.NewBoolVar(f"b0_{j}")
        model.Add(base_sum <= superior_sum).OnlyEnforceIf(b0)
        model.Add(base_sum >  superior_sum).OnlyEnforceIf(b0.Not())
        model.Add(m0 == base_sum).OnlyEnforceIf(b0)
        model.Add(m0 == superior_sum).OnlyEnforceIf(b0.Not())

        # —– 2) b = min(abs_diff, flex_sum) —–
        m1 = model.NewIntVar(0,
                            MAX_POSITIONS*PALLETS_SCALE,
                            f"m1_{j}")
        b1 = model.NewBoolVar(f"b1_{j}")
        model.Add(abs_diff <= flex_sum).OnlyEnforceIf(b1)
        model.Add(abs_diff >  flex_sum).OnlyEnforceIf(b1.Not())
        model.Add(m1 == abs_diff).OnlyEnforceIf(b1)
        model.Add(m1 == flex_sum).OnlyEnforceIf(b1.Not())

        # —– 3) c = round((flex_sum − m1)/2) —–
        rem  = model.NewIntVar(0,
                            MAX_POSITIONS*PALLETS_SCALE,
                            f"rem_{j}")
        half = model.NewIntVar(0,
                            MAX_POSITIONS*PALLETS_SCALE,
                            f"half_{j}")
        model.Add(rem == flex_sum + (-1) * m1)
        # half = ceil(rem/2):
        model.Add(2 * half >= rem)
        model.Add(2 * half <= rem + 1)

        # —– 4) d = max(abs_diff − flex_sum, 0) —–
        m2 = model.NewIntVar(0,
                            MAX_POSITIONS*PALLETS_SCALE,
                            f"m2_{j}")
        b2 = model.NewBoolVar(f"b2_{j}")
        model.Add(abs_diff >= flex_sum).OnlyEnforceIf(b2)
        model.Add(abs_diff <  flex_sum).OnlyEnforceIf(b2.Not())
        model.Add(m2 == abs_diff + (-1) * flex_sum).OnlyEnforceIf(b2)
        model.Add(m2 == 0).OnlyEnforceIf(b2.Not())

        # SI_MISMO
        self_sum_expr = sum(self_int[i] * x[(i,j)] for i in pedidos)

        self_sum = model.NewIntVar(0, MAX_POSITIONS * PALLETS_SCALE * levels * 2, f"self_sum_{j}")
        model.Add(self_sum == self_sum_expr)

        pair_q = model.NewIntVar(0, MAX_POSITIONS, f"self_pairs_q_{j}")
        model.AddDivisionEquality(pair_q, self_sum, 2 * PALLETS_SCALE)

        self_rem = model.NewIntVar(0, 2 * PALLETS_SCALE - 1, f"self_rem_{j}")
        model.Add(self_rem == self_sum - pair_q * (2 * PALLETS_SCALE))

        self_pairs_scaled = model.NewIntVar(0, MAX_POSITIONS * PALLETS_SCALE, f"self_pairs_scaled_{j}")
        model.Add(self_pairs_scaled == pair_q * PALLETS_SCALE)


        # 6) total_stack = m0 + m1 + half + m2
        total_stack = model.NewIntVar(
            -MAX_POSITIONS*PALLETS_SCALE*2,
            MAX_POSITIONS*PALLETS_SCALE*4,
            f"total_stack_{j}"
        )
        model.Add(total_stack == m0 + m1 + half + m2 + noap_sum + self_pairs_scaled + self_rem)

        # 7) umbral: total_stack ≤ max_positions * PALLETS_SCALE  si el camión está usado
        model.Add(
            total_stack 
            <= (MAX_POSITIONS * PALLETS_SCALE) * y[j]
        )
        total_stack_vars[j] = total_stack

 
    # ---------------------------------------------
    # 5) Objetivo: minimizar número de camiones
    model.Minimize(sum(y[j] for j in range(n_cam)))
 
    # ---------------------------------------------
    # 6) Resolver
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(tiempo_max_seg)
    solver.parameters.num_search_workers = 1
    t0 = time.time()
    resultado = solver.Solve(model)
    t1 = time.time()

    status_map = {cp_model.OPTIMAL: 'OPTIMAL', cp_model.FEASIBLE: 'FEASIBLE'}
    estado = status_map.get(resultado, 'NO_SOLUTION')
    print(f"[TIMING] CP-SAT (Bin) grupo {grupo_cfg['id']}: {t1 - t0:.3f} s (límite: {tiempo_max_seg}s), estado: {estado}")
 

    # ---------------------------------------------
    # 7) Reconstruir salida
    pedidos_incluidos = [i for i in pedidos if any(solver.Value(x[(i, j)]) == 1 for j in range(n_cam))]
    datos_asig = []
    camiones = []
    idx_cam = 1

    for j, ts_var in total_stack_vars.items():
        # Sólo imprime si el camión j está usado (opcional)
        if solver.Value(y[j]):
            print(f"Camión {j} → total_stack = {solver.Value(ts_var)}")
    
    for j in range(n_cam):
        if solver.Value(y[j]) < 1:
            continue
        grp = [i for i in pedidos if solver.Value(x[(i, j)]) == 1]
        vol_real = sum(vol_int[i] for i in grp)
        peso_real = sum(peso_int[i] for i in grp)
        vcu_vol_j = vol_real / float(cap_volume) if cap_volume else 0.0
        vcu_peso_j = peso_real / float(cap_weight) if cap_weight else 0.0
        vcu_max_j = max(vcu_vol_j, vcu_peso_j)
 
        for i in grp:
            vcu_vol_i  = (vol_raw[i] / float(cap_volume))  if cap_volume else 0.0
            vcu_peso_i = (peso_raw[i] / float(cap_weight)) if cap_weight else 0.0
       
            pedido_min = {
                'PEDIDO':       i,
                'CAMION':       idx_cam,
                'GRUPO':        grupo_cfg['id'],
                'TIPO_RUTA':    grupo_cfg['tipo'],
                'TIPO_CAMION': ('bh' if grupo_cfg['tipo'] == 'bh' else 'normal'),
                'CE':           ce_map[i],
                'CD':           cd_map[i],
                'VCU_VOL':      vcu_vol_i,
                'VCU_PESO':     vcu_peso_i,
                'CHOCOLATES':   chocolates_map[i],
                'VALIOSO':      valuable_map[i],
                'PDQ':          pdq_map[i],
                'BAJA_VU':      baja_vu_map[i],
                'LOTE_DIR':     lote_dir_map[i],
                'SALDO_INV':    saldo_inv_map[i], 
                'PO':           po_map[i],
                'OC':           oc_map[i],
                'PALLETS':      pallets_conf_map[i],
                'VALOR':        valor_map[i]
            }
            # 9.4) Completar con todas las columnas internas
            pedido_completo = completar_metadata_pedido(pedido_min, raw_map)
            datos_asig.append(pedido_completo)
       
        valor_total = sum(valor_map.get(i, 0) or 0 for i in grp)
        valor_cafe = sum(cafe_map.get(i, 0) or 0 for i in grp)
        tiene_chocolates = any(chocolates_map.get(i) == 1 for i in grp)
        pallets_conf = sum(pallets_conf_map[i] for i in grp)
        valioso = any(valuable_map.get(i) == 1 for i in grp)
        pdq = any(pdq_map.get(i) == 1 for i in grp)
        baja_vu = any(baja_vu_map.get(i) == 1 for i in grp)
        lote_dir = any(lote_dir_map.get(i) == 1 for i in grp)
        saldo_inv = any(saldo_inv_map.get(i) == 1 for i in grp)
        ts_val = solver.Value(total_stack_vars[j]) if j in total_stack_vars else 0
        pos_total = ts_val / PALLETS_SCALE

        camiones.append({
            'id': uuid.uuid4().hex,
            'grupo': grupo_cfg['id'],
            'tipo_ruta': grupo_cfg['tipo'],
            'ce': grupo_cfg['ce'],
            'cd': grupo_cfg['cd'],
            'tipo_camion': ('bh' if grupo_cfg['tipo'] == 'bh' else 'normal'),
            'vcu_vol': vcu_vol_j,
            'vcu_peso': vcu_peso_j,
            'vcu_max': vcu_max_j,
            'chocolates': 1 if tiene_chocolates else 0,
            'skus_valiosos': valioso,
            'pdq': pdq,
            'baja_vu': baja_vu,
            'lote_dir': lote_dir,
            'saldo_inv': saldo_inv,
            'valor_total': valor_total,
            'valor_cafe': valor_cafe,
            'pallets_conf': pallets_conf,
            'pedidos': datos_asig[-len(grp):],
            'pos_total':        pos_total,
        })
        idx_cam += 1
 
    # ----------------------------
    # 8) Detectar pedidos excluidos
    pedidos_excluidos_ids = [i for i in pedidos if i not in pedidos_incluidos]
    pedidos_excluidos = []
    for i in pedidos_excluidos_ids:
        pedido_min = {
            'PEDIDO': i,
            'CE': ce_map[i],
            'CD': cd_map[i],
            'OC': oc_map[i],
            'VCU_VOL': (vol_raw[i] / float(cap_volume)) if cap_volume else 0.0,
            'VCU_PESO': (peso_raw[i] / float(cap_weight)) if cap_weight else 0.0,
            'PO': po_map[i],
            'PALLETS': pallets_conf_map[i],
            'VALOR': valor_map[i],
        }
        pedido_ex_completo = completar_metadata_pedido(pedido_min, raw_map)
        pedidos_excluidos.append(pedido_ex_completo)
 
    return {
        'status': estado,
        'pedidos_asignados_ids': pedidos_incluidos,
        'pedidos_asignados': datos_asig,
        'pedidos_excluidos': pedidos_excluidos,
        'camiones': camiones
    }


def agregar_restricciones_agrupacion_por_po(model, x, pedidos, po_map, n_cam):
    po_grupos = {}
    for i in pedidos:
        po = po_map[i]
        po_grupos.setdefault(po, []).append(i)
 
    for po, items in po_grupos.items():
        if len(items) <= 1:
            continue
        for j in range(n_cam):
            for idx in range(1, len(items)):
                i1, i2 = items[0], items[idx]
                if (i1, j) in x and (i2, j) in x:
                    model.Add(x[(i1, j)] == x[(i2, j)])
