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
    scale: int
) -> Any:
    """
    Agrega restricciones de apilabilidad para un camión.
    Retorna la variable total_stack para tracking.
    
    Args:
        model: Modelo CP-SAT
        x: Variables de asignación
        datos: Datos de pedidos preparados
        pedidos_ids: IDs de pedidos en el grupo
        j: Índice del camión
        y_truck_j: Variable booleana del camión
        max_positions: Máximo de posiciones
        levels: Niveles de apilamiento
        scale: Factor de escala (SCALE_PALLETS)
    
    Returns:
        Variable total_stack (para debugging/tracking)
    """
    lim_pos_scaled = max_positions * scale
    
    # Sumas por tipo de apilabilidad
    base_sum = sum(datos[pid]['base_int'] * x[(pid, j)] for pid in pedidos_ids if (pid, j) in x)
    sup_sum = sum(datos[pid]['superior_int'] * x[(pid, j)] for pid in pedidos_ids if (pid, j) in x)
    flex_sum = sum(datos[pid]['flexible_int'] * x[(pid, j)] for pid in pedidos_ids if (pid, j) in x)
    noap_sum = sum(datos[pid]['no_apil_int'] * x[(pid, j)] for pid in pedidos_ids if (pid, j) in x)
    self_sum = sum(datos[pid]['si_mismo_int'] * x[(pid, j)] for pid in pedidos_ids if (pid, j) in x)
    
    # Límites individuales
    model.Add(base_sum <= lim_pos_scaled * y_truck_j)
    model.Add(sup_sum <= lim_pos_scaled * y_truck_j)
    model.Add(noap_sum <= lim_pos_scaled * y_truck_j)
    model.Add(flex_sum <= max_positions * levels * scale * y_truck_j)
    
    # Combinaciones
    model.Add((base_sum + noap_sum) <= lim_pos_scaled * y_truck_j)
    model.Add((sup_sum + noap_sum) <= lim_pos_scaled * y_truck_j)
    
    # Cálculo de total_stack (fórmula compleja de apilabilidad)
    diff = model.NewIntVar(-lim_pos_scaled, lim_pos_scaled, f"diff_{j}")
    model.Add(diff == base_sum + (-1) * sup_sum)
    
    abs_diff = model.NewIntVar(0, lim_pos_scaled, f"abs_diff_{j}")
    model.AddAbsEquality(abs_diff, diff)
    
    # m0 = min(base_sum, superior_sum)
    m0 = model.NewIntVar(0, lim_pos_scaled, f"m0_{j}")
    b0 = model.NewBoolVar(f"b0_{j}")
    model.Add(base_sum <= sup_sum).OnlyEnforceIf(b0)
    model.Add(base_sum > sup_sum).OnlyEnforceIf(b0.Not())
    model.Add(m0 == base_sum).OnlyEnforceIf(b0)
    model.Add(m0 == sup_sum).OnlyEnforceIf(b0.Not())
    
    # m1 = min(abs_diff, flex_sum)
    m1 = model.NewIntVar(0, lim_pos_scaled, f"m1_{j}")
    b1 = model.NewBoolVar(f"b1_{j}")
    model.Add(abs_diff <= flex_sum).OnlyEnforceIf(b1)
    model.Add(abs_diff > flex_sum).OnlyEnforceIf(b1.Not())
    model.Add(m1 == abs_diff).OnlyEnforceIf(b1)
    model.Add(m1 == flex_sum).OnlyEnforceIf(b1.Not())
    
    # rem = flex_sum - m1
    rem = model.NewIntVar(0, lim_pos_scaled, f"rem_{j}")
    model.Add(rem == flex_sum + (-1) * m1)
    
    # half = ceil(rem/2)
    half = model.NewIntVar(0, lim_pos_scaled, f"half_{j}")
    model.Add(2 * half >= rem)
    model.Add(2 * half <= rem + 1)
    
    # m2 = max(abs_diff - flex_sum, 0)
    m2 = model.NewIntVar(0, lim_pos_scaled, f"m2_{j}")
    b2 = model.NewBoolVar(f"b2_{j}")
    model.Add(abs_diff >= flex_sum).OnlyEnforceIf(b2)
    model.Add(abs_diff < flex_sum).OnlyEnforceIf(b2.Not())
    model.Add(m2 == abs_diff + (-1) * flex_sum).OnlyEnforceIf(b2)
    model.Add(m2 == 0).OnlyEnforceIf(b2.Not())
    
    # SI_MISMO: pares cuentan como posiciones
    self_sum_var = model.NewIntVar(0, max_positions * scale * levels * 2, f"self_sum_{j}")
    model.Add(self_sum_var == self_sum)
    
    pair_q = model.NewIntVar(0, max_positions, f"self_pairs_q_{j}")
    model.AddDivisionEquality(pair_q, self_sum_var, 2 * scale)
    
    self_rem = model.NewIntVar(0, 2 * scale - 1, f"self_rem_{j}")
    model.Add(self_rem == self_sum_var + (-1) * (pair_q * (2 * scale)))
    
    self_pairs_scaled = model.NewIntVar(0, lim_pos_scaled, f"self_pairs_scaled_{j}")
    model.Add(self_pairs_scaled == pair_q * scale)
    
    # Total stack
    total_stack = model.NewIntVar(
        -lim_pos_scaled * 2,
        lim_pos_scaled * 4,
        f"total_stack_{j}"
    )
    model.Add(total_stack == m0 + m1 + half + m2 + noap_sum + self_pairs_scaled + self_rem)
    
    # Límite final
    model.Add(total_stack <= lim_pos_scaled * y_truck_j)
    
    return total_stack


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