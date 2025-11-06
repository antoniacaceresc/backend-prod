# optimization/solvers/vcu.py
"""
Solver CP-SAT para optimización en modo VCU.
Maximiza el VCU de los camiones priorizando incluir más pedidos.
"""

import time
from typing import List, Dict, Any
from ortools.sat.python import cp_model

from models.domain import Pedido, Camion, TruckCapacity, ConfiguracionGrupo
from models.enums import TipoCamion, TipoRuta
from core.constants import SCALE_VCU, MAX_CAMIONES_CP_SAT
from optimization.solvers.constraints import (
    agregar_restriccion_po_agrupado,                            
    agregar_restricciones_apilabilidad,
    agregar_restricciones_walmart_multicd,
    agregar_restricciones_capacidad_dura)
from optimization.utils.helpers import preparar_datos_solver, heuristica_ffd
from optimization.solvers.output import construir_camiones_desde_solver

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
    
    # Validar pedidos inviables
    pedidos_validos = []
    pedidos_inviables = []
    
    for p in pedidos:
        excede_peso = p.peso > capacidad.cap_weight
        excede_vol = p.volumen > capacidad.cap_volume
        excede_pallets = p.pallets_capacidad > capacidad.max_pallets
        
        if excede_peso or excede_vol or excede_pallets:
            pedidos_inviables.append(p)
            razones = []
            if excede_peso:
                razones.append(f"Peso:{p.peso:.0f}>{capacidad.cap_weight}")
            if excede_vol:
                razones.append(f"Vol:{p.volumen:.0f}>{capacidad.cap_volume}")
            if excede_pallets:
                razones.append(f"Pallets:{p.pallets_capacidad:.1f}>{capacidad.max_pallets}")
            print(f"[VCU] ⚠️ Pedido inviable {p.pedido}: {', '.join(razones)}")
        else:
            pedidos_validos.append(p)
    
    # Si TODOS son inviables, retornar inmediatamente
    if not pedidos_validos:
        print(f"[VCU] ❌ Grupo {grupo_cfg.id}: TODOS inviables ({len(pedidos_inviables)})")
        return {
            'status': 'NO_SOLUTION',
            'pedidos_asignados_ids': [],
            'pedidos_asignados': [],
            'pedidos_excluidos': [_pedido_a_dict_excluido(p, capacidad) for p in pedidos_inviables],
            'camiones': []
        }
    
    # Si algunos son inviables, advertir
    if pedidos_inviables:
        print(f"[VCU] ⚠️ Grupo {grupo_cfg.id}: {len(pedidos_inviables)} inviables, "
              f"continuando con {len(pedidos_validos)}")
    
    # Continuar SOLO con válidos
    pedidos = pedidos_validos
    
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
    
    n_cam = min(len(pedidos), n_cam_heur + 1, MAX_CAMIONES_CP_SAT)
    
    print(f"[VCU] 📦 Grupo {grupo_cfg.id}: usando {n_cam} camiones")
    
    # Construir modelo CP-SAT
    model = cp_model.CpModel()
    
    # Variables de asignación: x[(pedido_id, camion_idx)]
    x = {}
    for pid in pedidos_ids:
        # Ya validamos antes, crear variables para todos
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
        resultado = construir_camiones_desde_solver(
            solver, x, y_truck, pedidos, pedidos_ids, grupo_cfg,
            capacidad, datos, n_cam, 'vcu', client_config=client_config
        )
        # Agregar inviables a excluidos
        if pedidos_inviables:
            excluidos_inviables = [_pedido_a_dict_excluido(p, capacidad) for p in pedidos_inviables]
            resultado['pedidos_excluidos'].extend(excluidos_inviables)
        
        return resultado
    else:

        print(f"\n[VCU] ❌ NO_SOLUTION: {grupo_cfg.id}")
        print(f"      Pedidos: {len(pedidos)}, Camiones: {n_cam}, Tiempo: {tiempo_max_seg}s")

        # ✅ Diagnóstico detallado
        total_peso = sum(p.peso for p in pedidos)
        total_vol = sum(p.volumen for p in pedidos)
        total_pallets = sum(p.pallets_capacidad for p in pedidos)
        
        cam_necesarios_peso = total_peso / capacidad.cap_weight
        cam_necesarios_vol = total_vol / capacidad.cap_volume
        cam_necesarios_pallets = total_pallets / capacidad.max_pallets
        cam_necesario = max(cam_necesarios_peso, cam_necesarios_vol, cam_necesarios_pallets)
        
        print(f"      Camiones necesarios (estimado):")
        print(f"        Por peso: {cam_necesarios_peso:.2f}")
        print(f"        Por volumen: {cam_necesarios_vol:.2f}")
        print(f"        Por pallets: {cam_necesarios_pallets:.2f}")
        print(f"        → Mínimo necesario: {cam_necesario:.2f}, Disponibles: {n_cam}")
        print(f"      VCU mín requerido: {capacidad.vcu_min*100:.0f}%")
        
        # Verificar si algún pedido casi llena un camión solo
        for p in pedidos:
            vcu_p = max(p.peso/capacidad.cap_weight, p.volumen/capacidad.cap_volume)
            if vcu_p > 0.8:
                print(f"      ⚠️ {p.pedido}: VCU individual={vcu_p*100:.0f}% (dificulta combinación)")
        
        
        # Incluir tanto los que no se asignaron como los inviables
        todos_excluidos = [_pedido_a_dict_excluido(p, capacidad) for p in pedidos]
        if pedidos_inviables:
            todos_excluidos.extend([_pedido_a_dict_excluido(p, capacidad) for p in pedidos_inviables])
        
        return {
            'status': estado,
            'pedidos_asignados_ids': [],
            'pedidos_asignados': [],
            'pedidos_excluidos': todos_excluidos,
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