# optimization/solvers/constraints.py
"""
Restricciones compartidas para modelos CP-SAT.
Funciones reutilizables para agregar restricciones comunes.
"""

from ortools.sat.python import cp_model
from typing import Dict, List, Any
from core.constants import SCALE_PALLETS


def agregar_restriccion_po_agrupado(
    model: cp_model.CpModel,
    x: Dict,
    pedidos_ids: List[str],
    po_map: Dict[str, str],
    n_cam: int
):
    """
    Agrega restricción de agrupación por PO.
    Todos los pedidos del mismo PO deben ir en el mismo camión.
    
    Args:
        model: Modelo CP-SAT
        x: Variables de asignación {(pedido_id, camion_idx): BoolVar}
        pedidos_ids: Lista de IDs de pedidos
        po_map: Mapeo pedido_id -> PO
        n_cam: Número de camiones
    """
    # Agrupar pedidos por PO
    po_grupos = {}
    for pid in pedidos_ids:
        po = po_map[pid]
        po_grupos.setdefault(po, []).append(pid)
    
    # Agregar restricciones
    for po, items in po_grupos.items():
        if len(items) <= 1:
            continue
        
        # Todos los pedidos del PO deben estar en el mismo camión
        for j in range(n_cam):
            for idx in range(1, len(items)):
                i1, i2 = items[0], items[idx]
                if (i1, j) in x and (i2, j) in x:
                    model.Add(x[(i1, j)] == x[(i2, j)])


def agregar_restricciones_apilabilidad(
    model: cp_model.CpModel,
    x: Dict,
    datos: Dict[str, Dict[str, Any]],
    pedidos_ids: List[str],
    j: int,
    y_truck_j,
    max_positions: int,
    levels: int,
    scale: int,
    separar_por_valor: bool = False,
) -> Any:
    """
    Agrega restricciones de apilabilidad para un camión.
    Retorna la variable total_stack para tracking.

    Si separar_por_valor=True, calcula posiciones de forma independiente para
    pallets valiosos y no-valiosos (no se apilan entre sí) y suma ambos totales.
    """
    lim_pos_scaled = max_positions * scale

    def _calc_total_stack(suffix, base_sum, sup_sum, flex_sum, noap_sum, self_sum,
                          base_sim_sum=0, sup_sim_sum=0):
        """
        Cascada con AddMinEquality (sin BoolVars → más rápido).
        """
        # ── Paso 0: Separar pura vs composite ──
        base_pura = model.NewIntVar(0, lim_pos_scaled, f"bp_{j}_{suffix}")
        model.Add(base_pura == base_sum - base_sim_sum)

        sup_pura = model.NewIntVar(0, lim_pos_scaled, f"sp_{j}_{suffix}")
        model.Add(sup_pura == sup_sum - sup_sim_sum)

        # ── Paso 1: min(base_pura, sup_pura) ──
        pares1 = model.NewIntVar(0, lim_pos_scaled, f"p1_{j}_{suffix}")
        model.AddMinEquality(pares1, [base_pura, sup_pura])

        base_sob1 = model.NewIntVar(0, lim_pos_scaled, f"bs1_{j}_{suffix}")
        model.Add(base_sob1 == base_pura - pares1)

        sup_sob1 = model.NewIntVar(0, lim_pos_scaled, f"ss1_{j}_{suffix}")
        model.Add(sup_sob1 == sup_pura - pares1)

        # ── Paso 2: Composites llenan huecos ──
        uso_sup_sim = model.NewIntVar(0, lim_pos_scaled, f"uss_{j}_{suffix}")
        model.Add(uso_sup_sim <= sup_sim_sum)
        model.Add(uso_sup_sim <= base_sob1)

        base_sob2 = model.NewIntVar(0, lim_pos_scaled, f"bs2_{j}_{suffix}")
        model.Add(base_sob2 == base_sob1 - uso_sup_sim)

        sup_sim_rest = model.NewIntVar(0, lim_pos_scaled * 3, f"ssr_{j}_{suffix}")
        model.Add(sup_sim_rest == sup_sim_sum - uso_sup_sim)

        uso_base_sim = model.NewIntVar(0, lim_pos_scaled, f"ubs_{j}_{suffix}")
        model.Add(uso_base_sim <= base_sim_sum)
        model.Add(uso_base_sim <= sup_sob1)

        sup_sob2 = model.NewIntVar(0, lim_pos_scaled, f"ss2_{j}_{suffix}")
        model.Add(sup_sob2 == sup_sob1 - uso_base_sim)

        base_sim_rest = model.NewIntVar(0, lim_pos_scaled * 3, f"bsr_{j}_{suffix}")
        model.Add(base_sim_rest == base_sim_sum - uso_base_sim)

        # ── Paso 3: Composites sobrantes → pool si_mismo ──
        pool_self = model.NewIntVar(0, lim_pos_scaled * 4, f"ps_{j}_{suffix}")
        model.Add(pool_self == self_sum + base_sim_rest + sup_sim_rest)

        # ── Paso 4: Flexible cubre sobrantes ──
        sobrante = model.NewIntVar(0, lim_pos_scaled, f"sob_{j}_{suffix}")
        model.Add(sobrante == base_sob2 + sup_sob2)

        uso_flex = model.NewIntVar(0, lim_pos_scaled, f"uf_{j}_{suffix}")
        model.Add(uso_flex <= flex_sum)
        model.Add(uso_flex <= sobrante)

        sobrante_sin_flex = model.NewIntVar(0, lim_pos_scaled, f"ssf_{j}_{suffix}")
        model.Add(sobrante_sin_flex == sobrante - uso_flex)

        flex_restante = model.NewIntVar(0, lim_pos_scaled, f"fr_{j}_{suffix}")
        model.Add(flex_restante == flex_sum - uso_flex)

        half_flex = model.NewIntVar(0, lim_pos_scaled, f"hf_{j}_{suffix}")
        model.Add(2 * half_flex >= flex_restante)
        model.Add(2 * half_flex <= flex_restante + 1)

        # ── Paso 5: Si_mismo en pares ──
        pair_q = model.NewIntVar(0, max_positions * 4, f"pq_{j}_{suffix}")
        model.AddDivisionEquality(pair_q, pool_self, 2 * scale)

        self_pairs_scaled = model.NewIntVar(0, lim_pos_scaled * 3, f"sps_{j}_{suffix}")
        model.Add(self_pairs_scaled == pair_q * scale)

        self_rem = model.NewIntVar(0, lim_pos_scaled * 3, f"sr_{j}_{suffix}")
        model.Add(self_rem == pool_self - pair_q * (2 * scale))

        # ── Total ──
        total_stack = model.NewIntVar(
            0, lim_pos_scaled * 4, f"ts_{j}_{suffix}"
        )
        model.Add(
            total_stack == pares1 + uso_sup_sim + uso_base_sim
                         + uso_flex + half_flex + sobrante_sin_flex
                         + noap_sum + self_pairs_scaled + self_rem
        )
        return total_stack

    # ── Caso 1: universo único ──
    if not separar_por_valor:
        base_sum = sum(datos[pid]['base_int'] * x[(pid, j)] for pid in pedidos_ids if (pid, j) in x)
        sup_sum  = sum(datos[pid]['superior_int'] * x[(pid, j)] for pid in pedidos_ids if (pid, j) in x)
        flex_sum = sum(datos[pid]['flexible_int'] * x[(pid, j)] for pid in pedidos_ids if (pid, j) in x)
        noap_sum = sum(datos[pid]['no_apil_int'] * x[(pid, j)] for pid in pedidos_ids if (pid, j) in x)
        self_sum = sum(datos[pid]['si_mismo_int'] * x[(pid, j)] for pid in pedidos_ids if (pid, j) in x)
        base_sim_sum = sum(datos[pid]['base_sim_int'] * x[(pid, j)] for pid in pedidos_ids if (pid, j) in x)
        sup_sim_sum  = sum(datos[pid]['sup_sim_int'] * x[(pid, j)] for pid in pedidos_ids if (pid, j) in x)

        # Límites individuales (solo categorías puras, no composites)
        base_pura_lim = model.NewIntVar(0, lim_pos_scaled, f"bpl_{j}")
        model.Add(base_pura_lim == base_sum - base_sim_sum)
        sup_pura_lim = model.NewIntVar(0, lim_pos_scaled, f"spl_{j}")
        model.Add(sup_pura_lim == sup_sum - sup_sim_sum)

        model.Add(base_pura_lim <= lim_pos_scaled * y_truck_j)
        model.Add(sup_pura_lim <= lim_pos_scaled * y_truck_j)
        model.Add(noap_sum <= lim_pos_scaled * y_truck_j)
        model.Add(flex_sum <= max_positions * levels * scale * y_truck_j)

        # Combinaciones (con puras)
        model.Add((base_pura_lim + noap_sum) <= lim_pos_scaled * y_truck_j)
        model.Add((sup_pura_lim + noap_sum) <= lim_pos_scaled * y_truck_j)

        total_stack = _calc_total_stack("all", base_sum, sup_sum, flex_sum, noap_sum, self_sum, base_sim_sum, sup_sim_sum)
        model.Add(total_stack <= lim_pos_scaled * y_truck_j)
        return total_stack

    # ── Caso 2: universos separados valioso / no-valioso ──
    totales = []
    for suf in ('val', 'noval'):
        base_sum = sum(datos[pid][f'base_{suf}_int'] * x[(pid, j)] for pid in pedidos_ids if (pid, j) in x)
        sup_sum  = sum(datos[pid][f'superior_{suf}_int'] * x[(pid, j)] for pid in pedidos_ids if (pid, j) in x)
        flex_sum = sum(datos[pid][f'flexible_{suf}_int'] * x[(pid, j)] for pid in pedidos_ids if (pid, j) in x)
        noap_sum = sum(datos[pid][f'no_apil_{suf}_int'] * x[(pid, j)] for pid in pedidos_ids if (pid, j) in x)
        self_sum = sum(datos[pid][f'si_mismo_{suf}_int'] * x[(pid, j)] for pid in pedidos_ids if (pid, j) in x)
        base_sim_sum = sum(datos[pid][f'base_sim_{suf}_int'] * x[(pid, j)] for pid in pedidos_ids if (pid, j) in x)
        sup_sim_sum = sum(datos[pid][f'sup_sim_{suf}_int'] * x[(pid, j)] for pid in pedidos_ids if (pid, j) in x)

        # Límites individuales (solo puras)
        base_pura_lim = model.NewIntVar(0, lim_pos_scaled, f"bpl_{j}_{suf}")
        model.Add(base_pura_lim == base_sum - base_sim_sum)
        sup_pura_lim = model.NewIntVar(0, lim_pos_scaled, f"spl_{j}_{suf}")
        model.Add(sup_pura_lim == sup_sum - sup_sim_sum)

        # Combinaciones DENTRO del universo (con puras)
        model.Add((base_pura_lim + noap_sum) <= lim_pos_scaled * y_truck_j)
        model.Add((sup_pura_lim + noap_sum) <= lim_pos_scaled * y_truck_j)

        totales.append(_calc_total_stack(suf, base_sum, sup_sum, flex_sum, noap_sum, self_sum, base_sim_sum, sup_sim_sum))

    # La suma de posiciones de ambos universos ocupa el camión
    model.Add(sum(totales) <= lim_pos_scaled * y_truck_j)
    return totales

def agregar_restricciones_walmart_multicd(
    model: cp_model.CpModel,
    x: Dict,
    pedidos_ids: List[str],
    cd_map: Dict[str, str],
    j: int,
    y_truck_j
):
    """
    Restricciones específicas de Walmart para rutas multi_cd:
    - Máximo 10 pedidos por CD
    - Máximo 20 pedidos totales
    
    Args:
        model: Modelo CP-SAT
        x: Variables de asignación
        pedidos_ids: IDs de pedidos
        cd_map: Mapeo pedido_id -> CD
        j: Índice del camión
        y_truck_j: Variable booleana del camión
    """
    cds_en_grupo = {cd_map[pid] for pid in pedidos_ids}
    
    # Máximo 10 por CD
    for cd in cds_en_grupo:
        pedidos_de_cd = [pid for pid in pedidos_ids if cd_map[pid] == cd]
        if pedidos_de_cd:
            model.Add(
                sum(x[(pid, j)] for pid in pedidos_de_cd if (pid, j) in x)
                <= 10 * y_truck_j
            )
    
    # Máximo 20 total
    model.Add(
        sum(x[(pid, j)] for pid in pedidos_ids if (pid, j) in x)
        <= 20 * y_truck_j
    )


def agregar_restricciones_capacidad_dura(
    model: cp_model.CpModel,
    vol_cam_int: Dict,
    peso_cam_int: Dict,
    vcu_max_int: Dict,
    y_truck: Dict,
    n_cam: int,
    scale: int
):
    """
    Agrega restricciones DURAS de capacidad (VCU ≤ 100%).
    
    Args:
        model: Modelo CP-SAT
        vol_cam_int: Variables de volumen por camión
        peso_cam_int: Variables de peso por camión
        vcu_max_int: Variables de VCU máximo por camión
        y_truck: Variables booleanas de camión usado
        n_cam: Número de camiones
        scale: Factor de escala (SCALE_VCU)
    """
    for j in range(n_cam):
        # Volumen y peso no pueden superar 100% (SCALE)
        model.Add(vol_cam_int[j] <= scale * y_truck[j])
        model.Add(peso_cam_int[j] <= scale * y_truck[j])
        
        # VCU máximo tampoco puede superar
        model.Add(vcu_max_int[j] <= scale * y_truck[j])


def agregar_restriccion_misma_po_diferente_camion(
    model: cp_model.CpModel,
    x: Dict,
    datos: Dict[str, Any],
    pedidos_ids: List[str],
    n_cam: int
) -> int:
    """
    Restricción: pedidos con mismo PO NO pueden ir en el mismo camión.
    
    Estrategia eficiente: para cada camión, máximo 1 pedido por PO.
    Complejidad: O(n_cam × num_POs) en vez de O(pares × n_cam)
    """
    from collections import defaultdict
    
    # Agrupar pedidos por PO
    pedidos_por_po: Dict[str, List[str]] = defaultdict(list)
    
    for pid in pedidos_ids:
        if pid in datos and 'po' in datos[pid]:
            po = datos[pid]['po']
            if po:
                pedidos_por_po[po].append(pid)
    
    # Filtrar solo POs con múltiples pedidos
    pos_con_conflicto = {po: pids for po, pids in pedidos_por_po.items() if len(pids) > 1}
    
    if not pos_con_conflicto:
        return 0
    
    restricciones_added = 0
    
    # Para cada camión, máximo 1 pedido de cada PO
    for j in range(n_cam):
        for po, pids in pos_con_conflicto.items():
            vars_in_truck = [x[(pid, j)] for pid in pids if (pid, j) in x]
            if len(vars_in_truck) > 1:
                model.Add(sum(vars_in_truck) <= 1)
                restricciones_added += 1
    
    print(f"[PO_INCOMPATIBLE] {len(pos_con_conflicto)} POs conflictivos, "
          f"{restricciones_added} restricciones totales")
    
    return restricciones_added

def agregar_restricciones_crr_walmart(
    model: cp_model.CpModel,
    x: Dict,
    datos: Dict,
    pedidos_ids: List[str],
    j: int,
    y_truck_j,
    effective_config: dict
):
    """
    Restricciones para flujo CRR de Walmart:
    - Máximo de SKUs distintos por camión
    - Máximo de cajas totales por camión
    Solo aplica a pedidos con oc == 'CRR'.
    """
    max_skus = effective_config.get("MAX_SKUS_CRR")
    max_cajas = effective_config.get("MAX_CAJAS_CRR")
    
    if max_skus is None and max_cajas is None:
        return
    
    crr_ids = [pid for pid in pedidos_ids if datos[pid].get('oc') == 'CRR' and (pid, j) in x]
    if not crr_ids:
        return
    
    # --- Máximo cajas (restricción lineal) ---
    if max_cajas is not None:
        model.Add(
            sum(datos[pid]['cajas'] * x[(pid, j)] for pid in crr_ids)
            <= max_cajas * y_truck_j
        )
    
    # --- Máximo SKUs distintos (requiere variables auxiliares) ---
    if max_skus is not None:
        # Recopilar todos los sku_ids presentes en los pedidos CRR del grupo
        todos_skus = set()
        for pid in crr_ids:
            todos_skus |= datos[pid]['sku_ids']
        
        # Para cada sku_id: variable booleana = "¿está este SKU en el camión j?"
        sku_en_camion = {}
        for sku_id in todos_skus:
            v = model.NewBoolVar(f"sku_usado_{sku_id}_{j}")
            sku_en_camion[sku_id] = v
            
            # pids que traen este sku
            pids_con_sku = [pid for pid in crr_ids if sku_id in datos[pid]['sku_ids']]
            for pid in pids_con_sku:
                # si el pedido va al camión, el sku también está
                model.Add(v >= x[(pid, j)])
        
        # Límite total de SKUs distintos
        model.Add(
            sum(sku_en_camion.values()) <= max_skus * y_truck_j
        )


def agregar_restricciones_apilabilidad_por_origen(
    model: cp_model.CpModel,
    x: Dict,
    datos: Dict[str, Dict[str, Any]],
    pedidos_ids: List[str],
    j: int,
    y_truck_j,
    max_positions: int,
    levels: int,
    scale: int,
    origin_key: str,
):
    """
    Restricciones de apilabilidad separadas por origen (CE o CD).
    Cada grupo de origen tiene su propio universo de apilabilidad;
    la suma de posiciones de todos los universos no puede exceder max_positions.

    Mismo cálculo que agregar_restricciones_apilabilidad (caso sin separar_por_valor),
    pero particionado por datos[pid][origin_key].

    Args:
        origin_key: 'ce' o 'cd' — campo en datos[pid] para particionar
    """
    lim_pos_scaled = max_positions * scale

    # Agrupar pedidos por origen
    origenes: Dict[str, List[str]] = {}
    for pid in pedidos_ids:
        if (pid, j) not in x:
            continue
        origen = datos[pid].get(origin_key, '__default__')
        origenes.setdefault(origen, []).append(pid)

    # Si hay un solo origen, usar la restricción estándar (sin overhead)
    if len(origenes) <= 1:
        agregar_restricciones_apilabilidad(
            model, x, datos, pedidos_ids, j, y_truck_j,
            max_positions, levels, scale
        )
        return

    def _calc_total_stack_origen(suffix, pids):
        """Calcula total_stack para un subconjunto de pedidos."""
        base_sum = sum(datos[pid]['base_int'] * x[(pid, j)] for pid in pids)
        sup_sum  = sum(datos[pid]['superior_int'] * x[(pid, j)] for pid in pids)
        flex_sum = sum(datos[pid]['flexible_int'] * x[(pid, j)] for pid in pids)
        noap_sum = sum(datos[pid]['no_apil_int'] * x[(pid, j)] for pid in pids)
        self_sum = sum(datos[pid]['si_mismo_int'] * x[(pid, j)] for pid in pids)

        # Límites individuales dentro del universo
        model.Add(base_sum <= lim_pos_scaled * y_truck_j)
        model.Add(sup_sum <= lim_pos_scaled * y_truck_j)
        model.Add(noap_sum <= lim_pos_scaled * y_truck_j)
        model.Add(flex_sum <= max_positions * levels * scale * y_truck_j)
        model.Add((base_sum + noap_sum) <= lim_pos_scaled * y_truck_j)
        model.Add((sup_sum + noap_sum) <= lim_pos_scaled * y_truck_j)

        # diff = base - sup
        diff = model.NewIntVar(-lim_pos_scaled, lim_pos_scaled, f"diff_{j}_{suffix}")
        model.Add(diff == base_sum + (-1) * sup_sum)

        abs_diff = model.NewIntVar(0, lim_pos_scaled, f"abs_diff_{j}_{suffix}")
        model.AddAbsEquality(abs_diff, diff)

        # m0 = min(base, sup)
        m0 = model.NewIntVar(0, lim_pos_scaled, f"m0_{j}_{suffix}")
        b0 = model.NewBoolVar(f"b0_{j}_{suffix}")
        model.Add(base_sum <= sup_sum).OnlyEnforceIf(b0)
        model.Add(base_sum > sup_sum).OnlyEnforceIf(b0.Not())
        model.Add(m0 == base_sum).OnlyEnforceIf(b0)
        model.Add(m0 == sup_sum).OnlyEnforceIf(b0.Not())

        # m1 = min(abs_diff, flex)
        m1 = model.NewIntVar(0, lim_pos_scaled, f"m1_{j}_{suffix}")
        b1 = model.NewBoolVar(f"b1_{j}_{suffix}")
        model.Add(abs_diff <= flex_sum).OnlyEnforceIf(b1)
        model.Add(abs_diff > flex_sum).OnlyEnforceIf(b1.Not())
        model.Add(m1 == abs_diff).OnlyEnforceIf(b1)
        model.Add(m1 == flex_sum).OnlyEnforceIf(b1.Not())

        # rem = flex - m1
        rem = model.NewIntVar(0, lim_pos_scaled, f"rem_{j}_{suffix}")
        model.Add(rem == flex_sum + (-1) * m1)

        # half = ceil(rem/2)
        half = model.NewIntVar(0, lim_pos_scaled, f"half_{j}_{suffix}")
        model.Add(2 * half >= rem)
        model.Add(2 * half <= rem + 1)

        # m2 = max(abs_diff - flex, 0)
        m2 = model.NewIntVar(0, lim_pos_scaled, f"m2_{j}_{suffix}")
        b2 = model.NewBoolVar(f"b2_{j}_{suffix}")
        model.Add(abs_diff >= flex_sum).OnlyEnforceIf(b2)
        model.Add(abs_diff < flex_sum).OnlyEnforceIf(b2.Not())
        model.Add(m2 == abs_diff + (-1) * flex_sum).OnlyEnforceIf(b2)
        model.Add(m2 == 0).OnlyEnforceIf(b2.Not())

        # SI_MISMO: pares
        self_sum_var = model.NewIntVar(
            0, max_positions * scale * levels * 2, f"self_sum_{j}_{suffix}"
        )
        model.Add(self_sum_var == self_sum)

        pair_q = model.NewIntVar(0, max_positions, f"self_pairs_q_{j}_{suffix}")
        model.AddDivisionEquality(pair_q, self_sum_var, 2 * scale)

        self_rem = model.NewIntVar(0, 2 * scale - 1, f"self_rem_{j}_{suffix}")
        model.Add(self_rem == self_sum_var + (-1) * (pair_q * (2 * scale)))

        self_pairs_scaled = model.NewIntVar(0, lim_pos_scaled, f"self_pairs_scaled_{j}_{suffix}")
        model.Add(self_pairs_scaled == pair_q * scale)

        total_stack = model.NewIntVar(
            -lim_pos_scaled * 2, lim_pos_scaled * 4, f"total_stack_{j}_{suffix}"
        )
        model.Add(
            total_stack == m0 + m1 + half + m2 + noap_sum + self_pairs_scaled + self_rem
        )
        return total_stack

    # Calcular total_stack por cada origen
    totales = []
    for origen, pids in origenes.items():
        suffix = f"orig_{origin_key}_{origen}"
        totales.append(_calc_total_stack_origen(suffix, pids))

    # La suma de posiciones de todos los orígenes no excede el camión
    model.Add(sum(totales) <= lim_pos_scaled * y_truck_j)