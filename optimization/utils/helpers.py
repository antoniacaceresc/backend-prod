# services/solver_helpers.py
"""
Helpers para los solvers CP-SAT.
Funciones que preparan datos y reconstruyen resultados.
"""

from typing import List, Dict, Any, Tuple
from models.domain import Pedido, Camion, TruckCapacity, ConfiguracionGrupo
from models.enums import TipoCamion, TipoRuta
from core.constants import SCALE_VCU, MAX_CAMIONES_CP_SAT, SCALE_PALLETS
import uuid
import math


def reconstruir_camion_desde_solver(
    pedidos_asignados: List[str],
    datos_solver: Dict[str, Dict[str, Any]],
    grupo_cfg: ConfiguracionGrupo,
    capacidad: TruckCapacity,
    numero_camion: int
) -> Camion:
    """
    Reconstruye un objeto Camion desde la soluciÃ³n del solver.
    
    Args:
        pedidos_asignados: IDs de pedidos asignados a este camiÃ³n
        datos_solver: Datos preparados por preparar_datos_solver
        grupo_cfg: ConfiguraciÃ³n del grupo (ruta)
        capacidad: Capacidad del camiÃ³n
        numero_camion: NÃºmero secuencial del camiÃ³n
    
    Returns:
        Objeto Camion completamente construido
    """
    # Obtener objetos Pedido originales
    pedidos_objs = [
        datos_solver[pid]['pedido_obj'] 
        for pid in pedidos_asignados
    ]
    
    # Determinar tipo de camiÃ³n
    if grupo_cfg.tipo == TipoRuta.BH:
        tipo_camion = TipoCamion.BH
    else:
        tipo_camion = TipoCamion.NORMAL
    
    # Crear ID Ãºnico
    camion_id = uuid.uuid4().hex
    
    # Crear camiÃ³n
    camion = Camion(
        id=camion_id,
        tipo_ruta=grupo_cfg.tipo,
        tipo_camion=tipo_camion,
        cd=grupo_cfg.cd,
        ce=grupo_cfg.ce,
        grupo=grupo_cfg.id,
        capacidad=capacidad,
        pedidos=[]  # Se agregarÃ¡n despuÃ©s
    )
    
    # Agregar pedidos (esto tambiÃ©n los asigna automÃ¡ticamente)
    camion.agregar_pedidos(pedidos_objs)
    
    return camion


def calcular_posiciones_apilabilidad(
    pedidos: List[Pedido],
    max_positions: int
) -> float:
    """
    Calcula las posiciones totales usadas segÃºn reglas de apilabilidad.
    Replica la lÃ³gica del solver CP-SAT.
    
    Returns:
        Posiciones totales usadas (float)
    """
    def suma_escalada(attr: str) -> int:
        return int(sum(getattr(p, attr, 0) for p in pedidos) * SCALE_PALLETS)
    
    base_sum = suma_escalada('base')
    sup_sum = suma_escalada('superior')
    flex_sum = suma_escalada('flexible')
    noap_sum = suma_escalada('no_apilable')
    self_sum = suma_escalada('si_mismo')
    
    # CÃ¡lculo segÃºn lÃ³gica del solver
    diff = base_sum - sup_sum
    abs_diff = abs(diff)
    
    m0 = min(base_sum, sup_sum)
    m1 = min(abs_diff, flex_sum)
    rem = flex_sum - m1
    half = (rem + 1) // 2  # ceil(rem/2)
    m2 = max(abs_diff - flex_sum, 0)
    
    # SI_MISMO: pares cuentan como posiciones
    pair_q = self_sum // (2 * SCALE_PALLETS)
    self_pairs_scaled = pair_q * SCALE_PALLETS
    self_rem = self_sum - pair_q * (2 * SCALE_PALLETS)
    
    total_stack = m0 + m1 + half + m2 + noap_sum + self_pairs_scaled + self_rem
    
    return total_stack / SCALE_PALLETS


def filtrar_pedidos_validos(
    pedidos: List[Pedido],
    capacidad: TruckCapacity
) -> List[Pedido]:
    """
    Filtra pedidos que pueden caber fÃ­sicamente en un camiÃ³n.
    
    Returns:
        Lista de pedidos que no exceden capacidad individual
    """
    validos = []
    for p in pedidos:
        if p.volumen <= capacidad.cap_volume and p.peso <= capacidad.cap_weight:
            validos.append(p)
    
    return validos


def agrupar_pedidos_por_criterio(
    pedidos: List[Pedido],
    grupo_cfg: ConfiguracionGrupo
) -> List[Pedido]:
    """
    Filtra pedidos que pertenecen a un grupo especÃ­fico.
    
    Args:
        pedidos: Lista completa de pedidos
        grupo_cfg: ConfiguraciÃ³n del grupo (CD, CE, OC)
    
    Returns:
        Pedidos que coinciden con los criterios del grupo
    """
    resultado = []
    
    for p in pedidos:
        # Filtrar por CD
        if p.cd not in grupo_cfg.cd:
            continue
        
        # Filtrar por CE
        if p.ce not in grupo_cfg.ce:
            continue
        
        # Filtrar por OC si aplica
        if grupo_cfg.oc is not None:
            if isinstance(grupo_cfg.oc, list):
                if p.oc not in grupo_cfg.oc:
                    continue
            else:
                if p.oc != grupo_cfg.oc:
                    continue
        
        resultado.append(p)
    
    return resultado


def preparar_datos_solver(
    pedidos: List[Pedido],
    capacidad: TruckCapacity
) -> Dict[str, Any]:
    """
    Prepara datos de pedidos para el solver CP-SAT.
    Escala valores y pre-calcula mapeos.
    
    Returns:
        Dict con datos escalados y mapeos
    """
    datos = {
        'PALLETS_SCALE': SCALE_PALLETS
    }
    
    for pedido in pedidos:
        pid = pedido.pedido
        
        # Datos crudos
        datos[pid] = {
            'vol_raw': pedido.volumen,
            'peso_raw': pedido.peso,
            'cd': pedido.cd,
            'ce': pedido.ce,
            'po': pedido.po,
            'oc': pedido.oc,
            'pedido_obj': pedido,  # Agregar objeto pedido original
        }
        
        # VCU escalado (para modo VCU)
        frac_vol = pedido.volumen / capacidad.cap_volume
        frac_peso = pedido.peso / capacidad.cap_weight
        
        datos[pid]['vcu_vol_int'] = int(max(0, min(SCALE_VCU, round(frac_vol * SCALE_VCU))))
        datos[pid]['vcu_peso_int'] = int(max(0, min(SCALE_VCU, round(frac_peso * SCALE_VCU))))
        
        # Pallets escalados
        datos[pid]['pallets_cap_int'] = int(round(pedido.pallets_capacidad * SCALE_PALLETS))
        
        # Apilabilidad escalada
        datos[pid]['base_int'] = int(round(pedido.base * SCALE_PALLETS))
        datos[pid]['superior_int'] = int(round(pedido.superior * SCALE_PALLETS))
        datos[pid]['flexible_int'] = int(round(pedido.flexible * SCALE_PALLETS))
        datos[pid]['no_apil_int'] = int(round(pedido.no_apilable * SCALE_PALLETS))
        datos[pid]['si_mismo_int'] = int(round(pedido.si_mismo * SCALE_PALLETS))
    
    return datos


def heuristica_ffd(
    pedidos: List[Pedido],
    peso_map: Dict[str, float],
    vol_map: Dict[str, float],
    capacidad: TruckCapacity
) -> int:
    """
    HeurÃ­stica First Fit Decreasing para estimar nÃºmero de camiones.
    
    Args:
        pedidos: Lista de pedidos
        peso_map: Mapeo pedido_id -> peso
        vol_map: Mapeo pedido_id -> volumen
        capacidad: Capacidad del camiÃ³n
    
    Returns:
        NÃºmero estimado de camiones necesarios
    """
    cap_weight = capacidad.cap_weight
    cap_volume = capacidad.cap_volume
    
    # Ordenar por "densidad" (el que más consume proporcionalmente)
    pedidos_orden = sorted(
        pedidos,
        key=lambda p: max(
            peso_map.get(p.pedido, 0) / cap_weight,
            vol_map.get(p.pedido, 0) / cap_volume
        ),
        reverse=True
    )
    
    # First Fit Decreasing
    camiones = []  # [(peso_usado, vol_usado)]
    
    for pedido in pedidos_orden:
        pid = pedido.pedido
        peso = peso_map.get(pid, 0)
        vol = vol_map.get(pid, 0)
        
        # Intentar asignar a camiÃ³n existente
        asignado = False
        for idx in range(len(camiones)):
            peso_usado, vol_usado = camiones[idx]
            if peso_usado + peso <= cap_weight and vol_usado + vol <= cap_volume:
                camiones[idx] = (peso_usado + peso, vol_usado + vol)
                asignado = True
                break
        
        # Si no cabe, crear nuevo camiÃ³n
        if not asignado:
            camiones.append((peso, vol))
    
    return len(camiones)