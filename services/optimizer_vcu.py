# services/optimizer_vcu.py
"""
Solver CP-SAT para optimización en modo VCU.
Maximiza el VCU de los camiones priorizando incluir más pedidos.
"""

import time
from typing import List, Dict, Any
from ortools.sat.python import cp_model

from services.models import Pedido, ConfiguracionGrupo, Camion, TruckCapacity, TipoCamion, TipoRuta
from services.constants import SCALE_VCU, MAX_CAMIONES_CP_SAT
from services.optimizer_constraints import (
    agregar_restriccion_po_agrupado,
    agregar_restricciones_apilabilidad,
    agregar_restricciones_walmart_multicd,
    agregar_restricciones_capacidad_dura
)
from services.solver_helpers import heuristica_ffd, preparar_datos_solver
from services.optimizer_output import construir_camiones_desde_solver


def optimizar_grupo_vcu(
    pedidos: List[Pedido],
    grupo_cfg: ConfiguracionGrupo,
    client_config,
    capacidad: TruckCapacity,
    tiempo_max_seg: int
) -> Dict[str, Any]:
    """
    Optimiza un grupo de pedidos usando CP-SAT en modo VCU.
    
    Objetivo:
    - Maximizar VCU promedio de camiones
    - Incluir la mayor cantidad de pedidos posible
    - Minimizar número de camiones
    
    Args:
        pedidos: Lista de pedidos del grupo
        grupo_cfg: Configuración del grupo
        client_config: Configuración del cliente
        capacidad: Capacidad del camión
        tiempo_max_seg: Tiempo máximo de ejecución
    
    Returns:
        Dict con status, camiones, pedidos_asignados, pedidos_excluidos
    """
    if not pedidos:
        return {
            'status': 'NO_SOLUTION',
            'pedidos_asignados_ids': [],
            'pedidos_asignados': [],
            'pedidos_excluidos': [],
            'camiones': []
        }
    
    # Preparar datos
    datos = preparar_datos_solver(pedidos, capacidad)
    pedidos_ids = [p.pedido for p in pedidos]
    
    # Estimar número de camiones con heurística FFD
    n_cam_heur = heuristica_ffd(
        pedidos,
        {p.pedido: p.peso for p in pedidos},
        {p.pedido: p.volumen for p in pedidos},
        capacidad
    )
    n_cam = min(len(pedidos), n_cam_heur, MAX_CAMIONES_CP_SAT)
    
    # Construir modelo CP-SAT
    model = cp_model.CpModel()
    
    # Variables de asignación: x[(pedido_id, camion_idx)]
    x = {}
    for pid in pedidos_ids:
        if datos[pid]['vol_raw'] <= capacidad.cap_volume and datos[pid]['peso_raw'] <= capacidad.cap_weight:
            for j in range(n_cam):
                x[(pid, j)] = model.NewBoolVar(f"x_vcu_{pid}_{j}")
    
    # Restricción: agrupar por PO si está habilitado
    if getattr(client_config, 'AGRUPAR_POR_PO', False):
        po_map = {p.pedido: p.po for p in pedidos}
        agregar_restriccion_po_agrupado(model, x, pedidos_ids, po_map, n_cam)
    
    # Variables de camión usado
    y_truck = {j: model.NewBoolVar(f"y_vcu_truck_{j}") for j in range(n_cam)}
    
    # Acumuladores de volumen y peso (escalados)
    vol_cam_int = {}
    peso_cam_int = {}
    for j in range(n_cam):
        vol_cam_int[j] = sum(
            datos[pid]['vcu_vol_int'] * x[(pid, j)]
            for pid in pedidos_ids if (pid, j) in x
        )
        peso_cam_int[j] = sum(
            datos[pid]['vcu_peso_int'] * x[(pid, j)]
            for pid in pedidos_ids if (pid, j) in x
        )
    
    # VCU máximo por camión
    vcu_max_int = {}
    for j in range(n_cam):
        v = model.NewIntVar(0, SCALE_VCU, f"vcu_max_int_{j}")
        model.AddMaxEquality(v, [vol_cam_int[j], peso_cam_int[j]])
        vcu_max_int[j] = v
    
    # Restricciones DURAS de capacidad (VCU ≤ 100%)
    agregar_restricciones_capacidad_dura(
        model, vol_cam_int, peso_cam_int, vcu_max_int,
        y_truck, n_cam, SCALE_VCU
    )
    
    # Restricciones generales
    _agregar_restricciones_generales_vcu(
        model, x, y_truck, vcu_max_int, pedidos_ids, datos,
        n_cam, capacidad, client_config, grupo_cfg
    )
    
    # Función objetivo
    _definir_objetivo_vcu(model, x, y_truck, vcu_max_int, n_cam)
    
    # Resolver
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(tiempo_max_seg)
    solver.parameters.num_search_workers = 1
    
    t0 = time.time()
    resultado = solver.Solve(model)
    t1 = time.time()
    
    status_map = {cp_model.OPTIMAL: 'OPTIMAL', cp_model.FEASIBLE: 'FEASIBLE'}
    estado = status_map.get(resultado, 'NO_SOLUTION')
    
    print(f"[TIMING] CP-SAT (VCU) grupo {grupo_cfg.id}: {t1 - t0:.3f}s (límite: {tiempo_max_seg}s), estado: {estado}")
    
    # Construir salida
    if estado in ('OPTIMAL', 'FEASIBLE'):
        return construir_camiones_desde_solver(
            solver, x, y_truck, pedidos, pedidos_ids, grupo_cfg,
            capacidad, datos, n_cam, 'vcu'
        )
    else:
        return {
            'status': estado,
            'pedidos_asignados_ids': [],
            'pedidos_asignados': [],
            'pedidos_excluidos': [_pedido_a_dict_excluido(p, capacidad) for p in pedidos],
            'camiones': []
        }


def _agregar_restricciones_generales_vcu(
    model: cp_model.CpModel,
    x: Dict,
    y_truck: Dict,
    vcu_max_int: Dict,
    pedidos_ids: List[str],
    datos: Dict,
    n_cam: int,
    capacidad: TruckCapacity,
    client_config,
    grupo_cfg: ConfiguracionGrupo
):
    """
    Agrega restricciones generales del modelo VCU.
    """
    # Cada pedido en máximo 1 camión
    for pid in pedidos_ids:
        vars_i = [x[(pid, j)] for j in range(n_cam) if (pid, j) in x]
        if vars_i:
            model.Add(sum(vars_i) <= 1)
    
    # Asignación solo si camión está usado
    for (pid, j), vx in x.items():
        model.Add(vx <= y_truck[j])
    
    # Monotonía: camiones usados de forma consecutiva
    for j in range(1, n_cam):
        model.Add(y_truck[j] <= y_truck[j - 1])
    
    # VCU mínimo: solo si camión está usado
    vcu_min_int = int(round(capacidad.vcu_min * SCALE_VCU))
    for j in range(n_cam):
        model.Add(vcu_max_int[j] >= vcu_min_int).OnlyEnforceIf(y_truck[j])
    
    # Restricciones por camión
    for j in range(n_cam):
        lista_i = [pid for pid in pedidos_ids if (pid, j) in x]
        
        # Camión abierto debe tener al menos un pedido
        if lista_i:
            model.Add(sum(x[(pid, j)] for pid in lista_i) >= y_truck[j])
        
        # Pallets
        model.Add(
            sum(datos[pid]['pallets_cap_int'] * x[(pid, j)] for pid in lista_i)
            <= capacidad.max_pallets * datos['PALLETS_SCALE'] * y_truck[j]
        )
        
        # Restricciones de Walmart multi_cd
        if (grupo_cfg.tipo == TipoRuta.MULTI_CD 
            and getattr(client_config, '__name__', '') == 'WalmartConfig'):
            cd_map = {pid: datos[pid]['cd'] for pid in lista_i}
            agregar_restricciones_walmart_multicd(model, x, lista_i, cd_map, j, y_truck[j])
        elif getattr(client_config, '__name__', '') == 'WalmartConfig':
            # Límite general de órdenes
            max_ordenes = getattr(client_config, 'MAX_ORDENES', 10)
            model.Add(sum(x[(pid, j)] for pid in lista_i) <= max_ordenes * y_truck[j])
        
        # Apilabilidad
        agregar_restricciones_apilabilidad(
            model, x, datos, lista_i, j, y_truck[j],
            capacidad.max_positions, capacidad.levels, datos['PALLETS_SCALE']
        )


def _definir_objetivo_vcu(
    model: cp_model.CpModel,
    x: Dict,
    y_truck: Dict,
    vcu_max_int: Dict,
    n_cam: int
):
    """
    Define función objetivo para modo VCU:
    - Maximizar VCU promedio (peso alto)
    - Incluir más pedidos (peso medio)
    - Minimizar número de camiones (peso bajo)
    """
    PESO_VCU = 1000
    PESO_CAMIONES = 200
    PESO_PEDIDOS = 3000
    
    obj_terms = []
    
    # Maximizar VCU
    for j in range(n_cam):
        obj_terms.append(PESO_VCU * vcu_max_int[j])
    
    # Incluir más pedidos
    for vx in x.values():
        obj_terms.append(PESO_PEDIDOS * vx)
    
    # Minimizar camiones
    for j in range(n_cam):
        obj_terms.append(-(PESO_CAMIONES * SCALE_VCU) * y_truck[j])
    
    model.Maximize(sum(obj_terms))


def _pedido_a_dict_excluido(pedido: Pedido, capacidad: TruckCapacity) -> Dict[str, Any]:
    """Convierte pedido excluido a dict para salida"""
    vcu_peso, vcu_vol, _ = pedido.calcular_vcu(capacidad)
    
    return {
        'PEDIDO': pedido.pedido,
        'CE': pedido.ce,
        'CD': pedido.cd,
        'OC': pedido.oc,
        'VCU_VOL': vcu_vol,
        'VCU_PESO': vcu_peso,
        'PO': pedido.po,
        'PALLETS': pedido.pallets,
        'VALOR': pedido.valor,
        **pedido.metadata
    }