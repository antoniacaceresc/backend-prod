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
from collections import defaultdict


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
    Calcula posiciones usando lógica en cascada con categorías compuestas.
    
    Cascada:
    1. Emparejar base pura + superior pura
    2. Composites llenan huecos (sup_simismo como superior, base_simismo como base)
    3. Composites sobrantes → pool si_mismo
    4. Flexible cubre diferencias
    5. Si_mismo en pares
    6. No_apilable
    """
    base_total = sum(getattr(p, 'base', 0) for p in pedidos)
    sup_total = sum(getattr(p, 'superior', 0) for p in pedidos)
    flex_total = sum(getattr(p, 'flexible', 0) for p in pedidos)
    noap_total = sum(getattr(p, 'no_apilable', 0) for p in pedidos)
    self_total = sum(getattr(p, 'si_mismo', 0) for p in pedidos)
    base_sim_total = sum(getattr(p, 'base_simismo', 0) for p in pedidos)
    sup_sim_total = sum(getattr(p, 'superior_simismo', 0) for p in pedidos)

    return _calcular_posiciones_cascada(
        base_total, sup_total, flex_total, noap_total, self_total,
        base_sim_total, sup_sim_total
    )


def _calcular_posiciones_cascada(
    base: float, superior: float, flexible: float,
    no_apilable: float, si_mismo: float,
    base_simismo: float = 0.0, superior_simismo: float = 0.0,
) -> float:
    """
    Fórmula pura de posiciones con categorías compuestas.
    Reutilizable desde helpers, constraints, smu_splitter, etc.
    """
    s = SCALE_PALLETS

    # Paso 0: Separar base pura y composite
    # base ya incluye base_simismo (se asignó en el parser)
    # Necesitamos saber cuánto es "solo base" vs "base que también es si_mismo"
    base_pura = base - base_simismo
    sup_pura = superior - superior_simismo

    # Escalar todo
    base_pura_s = int(base_pura * s)
    sup_pura_s = int(sup_pura * s)
    base_sim_s = int(base_simismo * s)
    sup_sim_s = int(superior_simismo * s)
    flex_s = int(flexible * s)
    noap_s = int(no_apilable * s)
    self_s = int(si_mismo * s)

    # Paso 1: Emparejar base pura + superior pura
    pares1 = min(base_pura_s, sup_pura_s)
    base_sob = base_pura_s - pares1
    sup_sob = sup_pura_s - pares1

    # Paso 2 en adelante: evaluar las combinaciones y quedarse con la mejor
    cand_sup = {0, min(sup_sim_s, base_sob)}
    cand_base = {0, min(base_sim_s, sup_sob)}

    mejor = None
    for uso_sup_sim in cand_sup:
        for uso_base_sim in cand_base:
            b_sob = base_sob - uso_sup_sim
            s_sob = sup_sob - uso_base_sim
            pool = self_s + (base_sim_s - uso_base_sim) + (sup_sim_s - uso_sup_sim)

            sobrante = b_sob + s_sob
            uso_flex = min(flex_s, sobrante)
            sobrante_sin_flex = sobrante - uso_flex
            half_flex = (flex_s - uso_flex + 1) // 2

            pair_q = pool // (2 * s)
            self_pairs = pair_q * s
            self_rem = pool - pair_q * (2 * s)

            total = (pares1 + uso_sup_sim + uso_base_sim + uso_flex
                     + half_flex + sobrante_sin_flex + noap_s
                     + self_pairs + self_rem)

            if mejor is None or total < mejor:
                mejor = total

    return mejor / s


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
        datos[pid]['base_sim_int'] = int(round(pedido.base_simismo * SCALE_PALLETS))
        datos[pid]['sup_sim_int'] = int(round(pedido.superior_simismo * SCALE_PALLETS))

        # Apilabilidad separada por valor (para SEPARAR_APILABILIDAD_POR_VALOR)
        for suf in ('val', 'noval'):
            datos[pid][f'base_{suf}_int']     = int(round(getattr(pedido, f'base_{suf}', 0) * SCALE_PALLETS))
            datos[pid][f'superior_{suf}_int'] = int(round(getattr(pedido, f'superior_{suf}', 0) * SCALE_PALLETS))
            datos[pid][f'flexible_{suf}_int'] = int(round(getattr(pedido, f'flexible_{suf}', 0) * SCALE_PALLETS))
            datos[pid][f'no_apil_{suf}_int']  = int(round(getattr(pedido, f'no_apilable_{suf}', 0) * SCALE_PALLETS))
            datos[pid][f'si_mismo_{suf}_int'] = int(round(getattr(pedido, f'si_mismo_{suf}', 0) * SCALE_PALLETS))
            datos[pid][f'base_sim_{suf}_int']  = int(round(getattr(pedido, f'base_simismo_{suf}', 0) * SCALE_PALLETS))
            datos[pid][f'sup_sim_{suf}_int']   = int(round(getattr(pedido, f'superior_simismo_{suf}', 0) * SCALE_PALLETS))
    
    return datos


def heuristica_ffd(
    pedidos: List[Pedido],
    peso_map: Dict[str, float],
    vol_map: Dict[str, float],
    capacidad: TruckCapacity,
    max_ordenes: int = None
) -> int:
    """
    Heurística First Fit Decreasing para estimar número de camiones.
    
    Args:
        pedidos: Lista de pedidos
        peso_map: Mapeo pedido_id -> peso
        vol_map: Mapeo pedido_id -> volumen
        capacidad: Capacidad del camión
        max_ordenes: Máximo de pedidos por camión (opcional)
    
    Returns:
        Número estimado de camiones necesarios
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
    camiones = []  # [(peso_usado, vol_usado, n_pedidos)]
    
    for pedido in pedidos_orden:
        pid = pedido.pedido
        peso = peso_map.get(pid, 0)
        vol = vol_map.get(pid, 0)
        
        # Intentar asignar a camión existente
        asignado = False
        for idx in range(len(camiones)):
            peso_usado, vol_usado, n_pedidos = camiones[idx]
            
            # Verificar capacidad y max_ordenes
            cabe_peso_vol = peso_usado + peso <= cap_weight and vol_usado + vol <= cap_volume
            cabe_ordenes = max_ordenes is None or n_pedidos < max_ordenes
            
            if cabe_peso_vol and cabe_ordenes:
                camiones[idx] = (peso_usado + peso, vol_usado + vol, n_pedidos + 1)
                asignado = True
                break
        
        # Si no cabe, crear nuevo camión
        if not asignado:
            camiones.append((peso, vol, 1))
    
    return len(camiones)

def pedido_a_dict_excluido(pedido: Pedido, capacidad: TruckCapacity) -> Dict[str, Any]:
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
                "base_simismo": sku.base_simismo,
                "superior_simismo": sku.superior_simismo,
                "max_altura_apilable_cm": sku.max_altura_apilable_cm,
                "descripcion": sku.descripcion,
                "valioso": sku.valioso,
                "cajas_conf": sku.cajas_conf,
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

def detectar_alertas_picking_camion(camion: Camion) -> None:
    """Detecta picking duplicado y actualiza camion.metadata['alertas_picking'] in-place."""
    alertas = []
    skus_picking: Dict[str, List[tuple]] = defaultdict(list)
        
    for pedido in camion.pedidos:
        if not hasattr(pedido, 'skus') or not pedido.skus:
            continue
            
        for sku in pedido.skus:
            if sku.cantidad_pallets % 1 > 0.001:
                skus_picking[sku.sku_id].append((pedido.pedido, sku.cantidad_pallets))
        
    for sku_id, pedidos_info in skus_picking.items():
        if len(pedidos_info) > 1:
            alertas.append({
                'tipo': 'PICKING_DUPLICADO',
                'sku_id': sku_id,
                'pedidos': [
                    {'pedido_id': pid, 'cajas': round(cant, 3)}
                    for pid, cant in pedidos_info
                ]
            })
        
    if alertas:
        camion.metadata['alertas_picking'] = alertas
    elif 'alertas_picking' in camion.metadata:
        del camion.metadata['alertas_picking']  # Limpiar si ya no hay conflictos
        