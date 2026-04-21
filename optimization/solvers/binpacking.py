# optimization/solvers/binpacking.py
"""
Solver CP-SAT para optimización en modo BinPacking.
Minimiza el número de camiones necesarios.
"""

import time
from typing import List, Dict, Any
from ortools.sat.python import cp_model

from models.domain import Pedido, Camion, TruckCapacity, ConfiguracionGrupo
from models.enums import TipoRuta, TipoCamion

from core.constants import SCALE_VCU, MAX_CAMIONES_CP_SAT
from optimization.solvers.constraints import (
    agregar_restriccion_po_agrupado,                            
    agregar_restricciones_apilabilidad,
    agregar_restricciones_walmart_multicd,
    agregar_restriccion_misma_po_diferente_camion,
    agregar_restricciones_crr_walmart)
from optimization.utils.helpers import preparar_datos_solver, heuristica_ffd
from optimization.solvers.output import construir_camiones_desde_solver


def optimizar_grupo_binpacking(
    pedidos: List[Pedido],
    grupo_cfg: ConfiguracionGrupo,
    effective_config: dict,
    capacidad: TruckCapacity,
    tiempo_max_seg: int,
    tipo_camion: TipoCamion = None
) -> Dict[str, Any]:
    """
    Optimiza un grupo de pedidos usando CP-SAT en modo BinPacking.
    
    Objetivo:
    - Minimizar nÃºmero de camiones
    - Todos los pedidos DEBEN ser asignados
    
    Args:
        pedidos: Lista de pedidos del grupo
        grupo_cfg: ConfiguraciÃ³n del grupo
        effective_config: ConfiguraciÃ³n del cliente
        capacidad: Capacidad del camiÃ³n
        tiempo_max_seg: Tiempo mÃ¡ximo de ejecuciÃ³n
    
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
        else:
            pedidos_validos.append(p)
    
    # Si TODOS son inviables, retornar inmediatamente
    if not pedidos_validos:
        return {
            'status': 'NO_SOLUTION',
            'pedidos_asignados_ids': [],
            'pedidos_asignados': [],
            'pedidos_excluidos': [_pedido_a_dict_excluido(p, capacidad) for p in pedidos_inviables],
            'camiones': []
        }
    
    # Continuar SOLO con válidos
    pedidos = pedidos_validos
    # Preparar datos
    datos = preparar_datos_solver(pedidos, capacidad)
    pedidos_ids = [p.pedido for p in pedidos]

    # Enriquecer datos con campos CRR (oc, sku_ids, cajas)
    pedidos_map_enrich = {p.pedido: p for p in pedidos}
    for pid in pedidos_ids:
        p = pedidos_map_enrich[pid]
        datos[pid]['oc'] = p.oc
        datos[pid]['sku_ids'] = {sku.sku_id for sku in p.skus} if p.skus else set()
        datos[pid]['cajas'] = int(round(p.metadata.get('CJ Conf.', 0)))
    
    # Obtener max_ordenes si existe
    max_ordenes = effective_config.get("MAX_ORDENES")
    
    n_cam_heur = heuristica_ffd(
        pedidos,
        {p.pedido: p.peso for p in pedidos},
        {p.pedido: p.volumen for p in pedidos},
        capacidad,
        max_ordenes
    )
    n_cam = min(len(pedidos), n_cam_heur + 3, MAX_CAMIONES_CP_SAT)
    
    # Construir modelo CP-SAT
    model = cp_model.CpModel()
    
    # Variables de asignaciÃ³n
    x = {}
    for pid in pedidos_ids:
        for j in range(n_cam):
            x[(pid, j)] = model.NewBoolVar(f"x_bin_{pid}_{j}")
    
    # RestricciÃ³n: agrupar por PO si estÃ¡ habilitado
    agrupar_por_po = effective_config.get("AGRUPAR_POR_PO", False)
    if agrupar_por_po:
        po_map = {p.pedido: p.po for p in pedidos}
        agregar_restriccion_po_agrupado(model, x, pedidos_ids, po_map, n_cam)
    
    # Variables de camiÃ³n usado
    y_truck = {j: model.NewBoolVar(f"y_bin_{j}") for j in range(n_cam)}
    
    # Restricciones generales
    _agregar_restricciones_generales_binpacking(
        model, x, y_truck, pedidos_ids, datos,
        n_cam, capacidad, effective_config, grupo_cfg
    )
    
    # FunciÃ³n objetivo: minimizar camiones
    model.Minimize(sum(y_truck[j] for j in range(n_cam)))
    
    # Resolver
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(tiempo_max_seg)
    solver.parameters.num_search_workers = 8
    t0 = time.time()
    resultado = solver.Solve(model)
    t1 = time.time()
    
    status_map = {cp_model.OPTIMAL: 'OPTIMAL', cp_model.FEASIBLE: 'FEASIBLE'}
    estado = status_map.get(resultado, 'NO_SOLUTION')
        
    # Construir salida
    if estado in ('OPTIMAL', 'FEASIBLE'):
        resultado = construir_camiones_desde_solver(
            solver, x, y_truck, pedidos, pedidos_ids, grupo_cfg,
            capacidad, datos, n_cam, 'binpacking', tipo_camion
        )

        # Agregar inviables a excluidos
        if pedidos_inviables:
            excluidos_inviables = [_pedido_a_dict_excluido(p, capacidad) for p in pedidos_inviables]
            resultado['pedidos_excluidos'].extend(excluidos_inviables)
        
        return resultado

    else:

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


def _agregar_restricciones_generales_binpacking(
    model: cp_model.CpModel,
    x: Dict,
    y_truck: Dict,
    pedidos_ids: List[str],
    datos: Dict,
    n_cam: int,
    capacidad: TruckCapacity,
    effective_config: dict,
    grupo_cfg: ConfiguracionGrupo
):
    """
    Agrega restricciones generales del modelo BinPacking.
    """
    # Cada pedido EXACTAMENTE en 1 camiÃ³n (diferencia clave con VCU)
    for pid in pedidos_ids:
        model.Add(sum(x[(pid, j)] for j in range(n_cam)) == 1)
    
    # Restricciones por camiÃ³n
    for j in range(n_cam):
        # AsignaciÃ³n solo si camiÃ³n usado
        for pid in pedidos_ids:
            model.Add(x[(pid, j)] <= y_truck[j])
        
        # Al menos 1 pedido para abrir camiÃ³n
        model.Add(sum(x[(pid, j)] for pid in pedidos_ids) >= y_truck[j])
        
        # Capacidad peso/volumen (enteros redondeados)
        suma_peso = sum(
            int(round(datos[pid]['peso_raw'])) * x[(pid, j)]
            for pid in pedidos_ids
        )
        suma_vol = sum(
            int(round(datos[pid]['vol_raw'])) * x[(pid, j)]
            for pid in pedidos_ids
        )
        
        # Convertir capacidades a enteros para CP-SAT
        cap_weight_int = int(round(capacidad.cap_weight))
        cap_volume_int = int(round(capacidad.cap_volume))
        
        model.Add(suma_peso <= cap_weight_int * y_truck[j])
        model.Add(suma_vol <= cap_volume_int * y_truck[j])
        
        # Pallets
        model.Add(
            sum(datos[pid]['pallets_cap_int'] * x[(pid, j)] for pid in pedidos_ids)
            <= capacidad.max_pallets * datos['PALLETS_SCALE'] * y_truck[j]
        )

        # Monotoní­a (opcional pero ayuda al solver)
        if j >= 1:
            model.Add(y_truck[j] <= y_truck[j - 1])
        
        # Restricciones de Walmart
        max_walmart = effective_config.get("MAX_ORDENES") is not None
        if grupo_cfg.tipo == TipoRuta.MULTI_CD and max_walmart:
            cd_map = {pid: datos[pid]['cd'] for pid in pedidos_ids}
            agregar_restricciones_walmart_multicd(model, x, pedidos_ids, cd_map, j, y_truck[j])
        elif max_walmart:
            max_ordenes = effective_config.get("MAX_ORDENES")
            model.Add(sum(x[(pid, j)] for pid in pedidos_ids) <= max_ordenes * y_truck[j])

        # Restricciones CRR Walmart
        agregar_restricciones_crr_walmart(
            model, x, datos, pedidos_ids, j, y_truck[j], effective_config
        )
        
        # Apilabilidad - solo si permite apilamiento
        permite_apilamiento = effective_config.get("PERMITE_APILAMIENTO", True)
        
        if permite_apilamiento:
            agregar_restricciones_apilabilidad(
                model, x, datos, pedidos_ids, j, y_truck[j],
                capacidad.max_positions, capacidad.levels, datos['PALLETS_SCALE']
            )

        # Restricción de pedidos divididos (misma PO) no van en el mismo camión
    if effective_config.get("RESTRICT_PO_GROUP", False):
        agregar_restriccion_misma_po_diferente_camion(
            model, x, datos, pedidos_ids, n_cam
        )

        


def _pedido_a_dict_excluido(pedido: Pedido, capacidad: TruckCapacity) -> Dict[str, Any]:
    vcu_peso, vcu_vol, _ = pedido.calcular_vcu(capacidad)
    
    # Serializar SKUs si existen
    skus_serializados = []
    if pedido.tiene_skus:
        for sku in pedido.skus:
            skus_serializados.append({
                "sku_id": sku.sku_id,
                "pedido_id": sku.pedido_id,
                "cantidad_pallets": sku.cantidad_pallets,
                "altura_full_pallet_cm": sku.altura_full_pallet_cm,
                "altura_picking_cm": sku.altura_picking_cm,
                "peso_kg": sku.peso_kg,
                "volumen_m3": sku.volumen_m3,
                "valor": sku.valor,
                "base": sku.base,
                "superior": sku.superior,
                "flexible": sku.flexible,
                "no_apilable": sku.no_apilable,
                "si_mismo": sku.si_mismo,
                "max_altura_apilable_cm": sku.max_altura_apilable_cm,
                "descripcion": sku.descripcion,
            })
    
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
        'SKUS': skus_serializados,   # ← NUEVO
        **pedido.metadata
    }
