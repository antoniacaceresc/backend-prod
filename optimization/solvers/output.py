# optimization/solvers/output.py
"""
Construcción de salida desde soluciones del solver.
Convierte variables del CP-SAT a objetos Camion/Pedido.
"""

import uuid
from typing import List, Dict, Any
from ortools.sat.python import cp_model

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
    if grupo_cfg.tipo.value == 'bh':
        tipo_camion = TipoCamion.BH
    else:
        tipo_camion = TipoCamion.NORMAL
    
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
    
    # Validar camiones si está habilitado
    if client_config and getattr(client_config, 'VALIDAR_ALTURA', False):
        camiones = _validar_camiones_generados(camiones, capacidad, client_config)

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


# Validar camiones generados
def _validar_camiones_generados(
    camiones: List[Camion],
    capacidad: TruckCapacity,
    client_config
) -> List[Camion]:
    """
    Valida altura de los camiones generados.
    
    Args:
        camiones: Lista de camiones a validar
        capacidad: Capacidad del camión
        client_config: Configuración del cliente
    
    Returns:
        Lista de camiones con metadata de validación agregada
    """
    from optimization.validation.height_validator import HeightValidator
    
    # Crear validador
    validator = HeightValidator(
        altura_maxima_cm=capacidad.altura_cm,
        permite_consolidacion=getattr(client_config, 'PERMITE_CONSOLIDACION', False),
        max_skus_por_pallet=getattr(client_config, 'MAX_SKUS_POR_PALLET', 3)
    )
    
    validos = 0
    invalidos = 0
    
    for camion in camiones:
        # Solo validar si tiene pedidos con SKUs
        tiene_skus = any(p.tiene_skus for p in camion.pedidos)
        
        if not tiene_skus:
            # Skip validación para pedidos legacy
            camion.metadata['altura_validada'] = None  # No aplicable
            continue
        
        # Validar
        valido, errores, layout = validator.validar_camion_rapido(camion)
        
        # Guardar resultado en metadata
        camion.metadata['altura_validada'] = valido
        
        if valido:
            validos += 1
            if layout:
                # Guardar layout completo detallado
                camion.metadata['layout_info'] = {
                    'posiciones_usadas': layout.posiciones_usadas,
                    'posiciones_disponibles': layout.posiciones_disponibles,
                    'altura_maxima_cm': layout.altura_maxima_cm,
                    'posiciones': [  # Detalle por posición
                        {
                            'id': pos.id,
                            'altura_usada_cm': pos.altura_usada_cm,
                            'altura_disponible_cm': pos.espacio_disponible_cm,
                            'num_pallets': pos.num_pallets,
                            'pallets': [  # Detalle de cada pallet
                                {
                                    'id': pallet.id,
                                    'nivel': pallet.nivel,
                                    'altura_cm': pallet.altura_total_cm,
                                    'skus': [ # SKUs en este pallet
                                        {
                                            'sku_id': frag.sku_id,
                                            'pedido_id': frag.pedido_id,
                                            'altura_cm': frag.altura_cm,
                                            'categoria': frag.categoria.value,
                                            'es_picking': frag.es_picking
                                        }
                                        for frag in pallet.fragmentos
                                    ]
                                }
                                for pallet in pos.pallets_apilados
                            ]
                        }
                        for pos in layout.posiciones
                        if not pos.esta_vacia
                    ]
                }
        else:
            invalidos += 1
            
            # ✅ FILTRAR cualquier Ellipsis y convertir a string
            errores_limpios = []
            for e in errores:
                if e is not ... and e is not Ellipsis:  # Filtrar Ellipsis
                    errores_limpios.append(str(e))
            
            camion.metadata['errores_validacion'] = errores_limpios
            
            # Log
            print(f"[VALIDATION] ⚠️  Camión {camion.id} INVÁLIDO:")
            for error in errores_limpios[:3]:  # Primeros 3
                print(f"             - {error}")
            
            if len(errores_limpios) > 3:
                print(f"             ... y {len(errores_limpios) - 3} errores más")
    
    if validos > 0 or invalidos > 0:
        print(f"[VALIDATION] Validados: {validos} ✅ válidos, {invalidos} ⚠️ inválidos")
    
    return camiones


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