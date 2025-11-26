# optimization/solvers/output.py
"""
Construcción de salida desde soluciones del solver.
Convierte variables del CP-SAT a objetos Camion/Pedido.
"""

import uuid
from typing import List, Dict, Any
from ortools.sat.python import cp_model
from concurrent.futures import ThreadPoolExecutor, as_completed

from models.domain import Pedido, Camion, TruckCapacity, ConfiguracionGrupo
from models.enums import TipoCamion
from optimization.utils.helpers import calcular_posiciones_apilabilidad

def construir_camiones_desde_solver(
    solver: cp_model.CpSolver,
    x: Dict,
    y_truck: Dict,
    pedidos: List[Pedido],
    pedidos_ids: List[str],
    grupo_cfg: ConfiguracionGrupo,
    capacidad: TruckCapacity,
    datos: Dict,
    n_cam: int,
    modo: str,
    client_config=None
) -> Dict[str, Any]:
    """
    Construye lista de camiones desde la solución del solver.
    
    Args:
        solver: Solver con solución
        x: Variables de asignación
        y_truck: Variables de camión usado
        pedidos: Lista original de pedidos
        pedidos_ids: IDs de pedidos
        grupo_cfg: Configuración del grupo
        capacidad: Capacidad del camión
        datos: Datos preparados del solver
        n_cam: Número de camiones
        modo: "vcu" o "binpacking"
    
    Returns:
        Dict con status, camiones, pedidos asignados/excluidos
    """
    pedidos_map = {p.pedido: p for p in pedidos}
    pedidos_incluidos_ids = []
    camiones = []
    
    # Determinar tipo de camión base
    tipo_camion = TipoCamion.PAQUETERA
    
    # Construir cada camión
    for j in range(n_cam):
        if solver.Value(y_truck[j]) < 1:
            continue
        
        # Pedidos asignados a este camión
        pedidos_camion_ids = [
            pid for pid in pedidos_ids
            if (pid, j) in x and solver.Value(x[(pid, j)]) == 1
        ]
        
        if not pedidos_camion_ids:
            continue
        
        pedidos_camion = [pedidos_map[pid] for pid in pedidos_camion_ids]
        pedidos_incluidos_ids.extend(pedidos_camion_ids)
        
        # Crear camión
        camion = Camion(
            id=uuid.uuid4().hex,
            tipo_ruta=grupo_cfg.tipo,
            tipo_camion=tipo_camion,
            cd=grupo_cfg.cd,
            ce=grupo_cfg.ce,
            grupo=grupo_cfg.id,
            capacidad=capacidad,
            pedidos=pedidos_camion,
            metadata={} 
        )
        
        # Calcular posiciones de apilabilidad
        camion.pos_total = calcular_posiciones_apilabilidad(
            pedidos_camion,
            capacidad.max_positions
        )
        
        camiones.append(camion)


    # Pedidos excluidos
    pedidos_excluidos_ids = [pid for pid in pedidos_ids if pid not in pedidos_incluidos_ids]
    pedidos_excluidos = [
        _pedido_a_dict_excluido(pedidos_map[pid], capacidad)
        for pid in pedidos_excluidos_ids
    ]
    
    # Pedidos asignados (para compatibilidad con código anterior)
    pedidos_asignados = []
    for camion in camiones:
        for pedido in camion.pedidos:
            pedidos_asignados.append(_pedido_a_dict_asignado(pedido, camion, capacidad))
    
    return {
        'status': 'OPTIMAL' if pedidos_excluidos_ids else 'FEASIBLE',
        'pedidos_asignados_ids': pedidos_incluidos_ids,
        'pedidos_asignados': pedidos_asignados,
        'pedidos_excluidos': pedidos_excluidos,
        'camiones': camiones
    }


def _pedido_a_dict_asignado(pedido: Pedido, camion: Camion, capacidad: TruckCapacity) -> Dict[str, Any]:
    """Convierte pedido asignado a dict para salida"""
    vcu_peso, vcu_vol, _ = pedido.calcular_vcu(capacidad)
    
    return {
        'PEDIDO': pedido.pedido,
        'CAMION': camion.numero,
        'GRUPO': camion.grupo,
        'TIPO_RUTA': camion.tipo_ruta.value,
        'TIPO_CAMION': camion.tipo_camion.value,
        'CE': pedido.ce,
        'CD': pedido.cd,
        'VCU_VOL': vcu_vol,
        'VCU_PESO': vcu_peso,
        'CHOCOLATES': pedido.chocolates,
        'VALIOSO': int(pedido.valioso),
        'PDQ': int(pedido.pdq),
        'BAJA_VU': int(pedido.baja_vu),
        'LOTE_DIR': int(pedido.lote_dir),
        'PO': pedido.po,
        'OC': pedido.oc,
        'PALLETS': pedido.pallets,
        'VALOR': pedido.valor,
        **pedido.metadata
    }


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