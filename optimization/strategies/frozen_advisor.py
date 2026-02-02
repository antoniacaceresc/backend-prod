# optimization/frozen_advisor.py
"""
Módulo para canales Helados/Refrigerados de Walmart.
Reutiliza el solver VCU existente pero trabajando a nivel SKU.

Fase Pre-BOP:
  1. Pre-proceso: Expande cada SKU a un pseudo-pedido
  2. Optimización: Usa optimizar_grupo_vcu existente
  3. Post-proceso: Analiza splits y genera guía

Todo va a piso (no_apilable), sin restricción de agrupar por PO.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple
from enum import Enum
import copy
import math

from models.domain import Pedido, SKU, TruckCapacity, ConfiguracionGrupo
from models.enums import TipoCamion, TipoRuta
from optimization.solvers.vcu import optimizar_grupo_vcu


class FaseOptimizacion(str, Enum):
    PRE_BOP = "pre_bop"
    POST_BOP = "post_bop"


# ════════════════════════════════════════════════════════════════════════════
# PRE-PROCESO: SKU → PSEUDO-PEDIDO
# ════════════════════════════════════════════════════════════════════════════

def expandir_pedidos_a_skus(
    pedidos: List[Pedido],
    usar_estimados: bool = True
) -> Tuple[List[Pedido], Dict[str, Dict[str, Any]]]:
    """
    Convierte cada SKU de cada pedido en un pseudo-pedido independiente.
    
    Para Pre-BOP usa: pallets_estimados y calcula peso/vol proporcional
    basado en solicitados (factor = estimados / solicitados).
    """
    pseudo_pedidos = []
    mapeo = {}
    
    for pedido in pedidos:
        if pedido.tiene_skus:
            for sku in pedido.skus:

                pseudo_id = f"{pedido.pedido}__{sku.sku_id}"
                
                # Valores confirmados (default)
                pallets_conf = sku.cantidad_pallets
                peso_conf = sku.peso_kg
                vol_conf = sku.volumen_m3
                valor_conf = sku.valor
                
                # Valores solicitados
                pallets_solic = sku.pallets_solicitados or 0
                peso_solic = sku.peso_solicitado or 0
                vol_solic = sku.volumen_solicitado or 0
                
                # Valores estimados
                pallets_est = sku.pallets_estimados
                
                if usar_estimados and pallets_est and pallets_est > 0:
                    pallets_sku = pallets_est
                    
                    # Calcular factor basado en solicitados
                    if pallets_solic > 0:
                        factor = pallets_est / pallets_solic
                        peso_sku = peso_solic * factor
                        vol_sku = vol_solic * factor
                        # Valor proporcional desde confirmados si hay, sino desde factor
                        valor_sku = valor_conf * (pallets_est / pallets_conf) if pallets_conf > 0 else 0
                        
                    elif pallets_conf > 0:
                        # Fallback: usar confirmados si no hay solicitados
                        factor = pallets_est / pallets_conf
                        peso_sku = peso_conf * factor
                        vol_sku = vol_conf * factor
                        valor_sku = valor_conf * factor
                    else:
                        # No hay base para calcular - skip este SKU
                        print(f"  ⚠️ SKU {sku.sku_id}: sin solicitados ni confirmados, saltando")
                        continue
                else:
                    # Sin estimados - usar confirmados
                    pallets_sku = pallets_conf
                    peso_sku = peso_conf
                    vol_sku = vol_conf
                    valor_sku = valor_conf
                
                # Saltar SKUs sin pallets
                if pallets_sku <= 0:
                    continue
                
                pseudo = Pedido(
                    pedido=pseudo_id,
                    cd=pedido.cd,
                    ce=pedido.ce,
                    po=pedido.po,
                    peso=peso_sku,
                    volumen=vol_sku,
                    pallets=pallets_sku,
                    valor=valor_sku,
                    oc=pedido.oc,
                    no_apilable=pallets_sku,
                    base=0,
                    superior=0,
                    flexible=0,
                    si_mismo=0,
                    metadata={
                        'pedido_original': pedido.pedido,
                        'sku_id': sku.sku_id,
                        'po_original': pedido.po,
                        'es_pseudo_sku': True,
                        'pallets_conf': pallets_conf,
                        'pallets_solic': pallets_solic,
                        'pallets_est': pallets_est,
                    }
                )
                pseudo_pedidos.append(pseudo)
                
                mapeo[pseudo_id] = {
                    'pedido_original': pedido.pedido,
                    'sku_id': sku.sku_id,
                    'po': pedido.po,
                    'pallets': pallets_sku,
                    'peso': peso_sku,
                    'volumen': vol_sku,
                }
        else:
            # Pedido sin SKUs - usar metadata a nivel pedido
            pseudo_id = f"{pedido.pedido}__VIRTUAL"
            
            pallets_est = pedido.metadata.get('pallets_estimados') or pedido.metadata.get('PALLETS_ESTIMADOS')
            pallets_solic = pedido.metadata.get('PALLETS_SOLIC', 0)
            
            if usar_estimados and pallets_est and float(pallets_est) > 0:
                pallets_p = float(pallets_est)
                if pallets_solic and float(pallets_solic) > 0:
                    factor = pallets_p / float(pallets_solic)
                    peso_p = float(pedido.metadata.get('PESO_SOLIC', 0)) * factor
                    vol_p = float(pedido.metadata.get('VOL_SOLIC', 0)) * factor
                elif pedido.pallets > 0:
                    factor = pallets_p / pedido.pallets
                    peso_p = pedido.peso * factor
                    vol_p = pedido.volumen * factor
                else:
                    peso_p = pedido.peso
                    vol_p = pedido.volumen
                valor_p = pedido.valor * (pallets_p / pedido.pallets) if pedido.pallets > 0 else 0
            else:
                pallets_p = pedido.pallets
                peso_p = pedido.peso
                vol_p = pedido.volumen
                valor_p = pedido.valor
            
            if pallets_p <= 0:
                continue
            
            pseudo = Pedido(
                pedido=pseudo_id,
                cd=pedido.cd,
                ce=pedido.ce,
                po=pedido.po,
                peso=peso_p,
                volumen=vol_p,
                pallets=pallets_p,
                valor=valor_p,
                oc=pedido.oc,
                no_apilable=pallets_p,
                metadata={
                    'pedido_original': pedido.pedido,
                    'sku_id': 'VIRTUAL',
                    'po_original': pedido.po,
                    'es_pseudo_sku': True,
                }
            )
            pseudo_pedidos.append(pseudo)
            
            mapeo[pseudo_id] = {
                'pedido_original': pedido.pedido,
                'sku_id': 'VIRTUAL',
                'po': pedido.po,
                'pallets': pallets_p,
                'peso': peso_p,
                'volumen': vol_p,
            }
    
    return pseudo_pedidos, mapeo

# ════════════════════════════════════════════════════════════════════════════
# POST-PROCESO: ANALIZAR SPLITS
# ════════════════════════════════════════════════════════════════════════════

def analizar_splits(
    pedidos_originales: List[Pedido],
    resultado_solver: Dict[str, Any],
    mapeo: Dict[str, Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Analiza cómo quedaron distribuidos los SKUs de cada pedido original.
    
    Returns:
        Lista de splits con detalle por pedido original
    """
    # Inicializar tracking por pedido original
    pedido_info: Dict[str, Dict[str, Any]] = {}
    
    for pedido in pedidos_originales:
        # Calcular pallets estimados desde SKUs
        if pedido.tiene_skus:
            pallets_est = sum(
                sku.pallets_estimados if sku.pallets_estimados else sku.cantidad_pallets
                for sku in pedido.skus
            )
        else:
            pallets_est = pedido.metadata.get('pallets_estimado') or pedido.metadata.get('PALLETS_ESTIMADO') or pedido.pallets
        
        pedido_info[pedido.pedido] = {
            'po': pedido.po,
            'pallets_total': float(pallets_est),
            'camiones': {},  # {camion_idx: {'pallets': X, 'skus': [...]}}
            'rechazos': [],
        }
    
    # Procesar camiones del resultado
    # NOTA: camiones son objetos Camion, no dicts
    camiones = resultado_solver.get('camiones', [])
    for cam_idx, cam in enumerate(camiones):
        # cam es un objeto Camion, acceder a sus atributos directamente
        pedidos_en_camion = cam.pedidos if hasattr(cam, 'pedidos') else []
        
        for p in pedidos_en_camion:
            # p es un objeto Pedido
            pseudo_id = p.pedido if hasattr(p, 'pedido') else None
            if not pseudo_id or pseudo_id not in mapeo:
                continue
            
            info = mapeo[pseudo_id]
            ped_orig = info['pedido_original']
            
            if ped_orig not in pedido_info:
                continue
            
            if cam_idx not in pedido_info[ped_orig]['camiones']:
                pedido_info[ped_orig]['camiones'][cam_idx] = {
                    'pallets': 0,
                    'skus': [],
                }
            
            pedido_info[ped_orig]['camiones'][cam_idx]['pallets'] += info['pallets']
            pedido_info[ped_orig]['camiones'][cam_idx]['skus'].append(info['sku_id'])
    
    # Procesar rechazados (estos SÍ son dicts)
    excluidos = resultado_solver.get('pedidos_excluidos', [])
    for exc in excluidos:
        pseudo_id = exc.get('PEDIDO') or exc.get('pedido')
        if not pseudo_id or pseudo_id not in mapeo:
            continue
        
        info = mapeo[pseudo_id]
        ped_orig = info['pedido_original']
        
        if ped_orig in pedido_info:
            pedido_info[ped_orig]['rechazos'].append({
                'sku_id': info['sku_id'],
                'pallets': info['pallets'],
            })
    
    # Construir resultado
    splits = []
    for ped_id, data in pedido_info.items():
        pallets_asignados = sum(c['pallets'] for c in data['camiones'].values())
        pallets_rechazados = sum(r['pallets'] for r in data['rechazos'])
        num_camiones = len(data['camiones'])
        
        # Determinar estado
        if pallets_rechazados >= data['pallets_total'] - 0.01:
            estado = 'rechazado'
        elif pallets_rechazados > 0.01:
            estado = 'parcial'
        else:
            estado = 'completo'
        
        splits.append({
            'pedido': ped_id,
            'po': data['po'],
            'pallets_total': round(data['pallets_total'], 2),
            'pallets_asignados': round(pallets_asignados, 2),
            'pallets_rechazados': round(pallets_rechazados, 2),
            'num_camiones': num_camiones,
            'detalle_camiones': [
                {
                    'camion': idx + 1,
                    'pallets': round(info['pallets'], 2),
                    'skus': info['skus'],
                }
                for idx, info in sorted(data['camiones'].items())
            ],
            'detalle_rechazos': [
                {'sku': r['sku_id'], 'pallets': round(r['pallets'], 2)}
                for r in data['rechazos']
            ],
            'estado': estado,
        })
    
    # Ordenar: parciales primero, luego rechazados, luego completos
    splits.sort(key=lambda s: (
        0 if s['estado'] == 'parcial' else (1 if s['estado'] == 'rechazado' else 2),
        -s['pallets_rechazados'],
        s['pedido']
    ))
    
    return splits


def generar_guia_bop(splits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Genera guía accionable para dividir pedidos en BOP.
    """
    guia = []
    
    for split in splits:
        necesita_division = split['num_camiones'] > 1 or split['pallets_rechazados'] > 0
        
        if necesita_division and split['detalle_camiones']:
            # Una línea por cada parte asignada
            for i, det in enumerate(split['detalle_camiones']):
                guia.append({
                    'po_original': split['po'],
                    'pedido_original': split['pedido'],
                    'pedido_sugerido': f"{split['pedido']}_P{i+1}",
                    'pallets': det['pallets'],
                    'skus': det['skus'],
                    'camion_destino': det['camion'],
                    'estado': 'asignado',
                })
            
            # Rechazados
            if split['detalle_rechazos']:
                guia.append({
                    'po_original': split['po'],
                    'pedido_original': split['pedido'],
                    'pedido_sugerido': f"{split['pedido']}_EXCEDENTE",
                    'pallets': split['pallets_rechazados'],
                    'skus': [r['sku'] for r in split['detalle_rechazos']],
                    'camion_destino': None,
                    'estado': 'rechazado',
                })
        
        elif split['estado'] == 'completo' and split['detalle_camiones']:
            # Pedido completo en un camión
            guia.append({
                'po_original': split['po'],
                'pedido_original': split['pedido'],
                'pedido_sugerido': split['pedido'],
                'pallets': split['pallets_asignados'],
                'skus': split['detalle_camiones'][0]['skus'] if split['detalle_camiones'] else [],
                'camion_destino': split['detalle_camiones'][0]['camion'] if split['detalle_camiones'] else None,
                'estado': 'completo',
            })
        
        elif split['estado'] == 'rechazado':
            # Pedido completamente rechazado
            guia.append({
                'po_original': split['po'],
                'pedido_original': split['pedido'],
                'pedido_sugerido': f"{split['pedido']}_RECHAZADO",
                'pallets': split['pallets_total'],
                'skus': [r['sku'] for r in split['detalle_rechazos']],
                'camion_destino': None,
                'estado': 'rechazado',
            })
    
    # Ordenar
    guia.sort(key=lambda x: (
        0 if x['estado'] == 'completo' else (1 if x['estado'] == 'asignado' else 2),
        x['po_original'],
        x.get('camion_destino') or 999
    ))
    
    return guia


# ════════════════════════════════════════════════════════════════════════════
# PRE-BOP ADVISOR
# ════════════════════════════════════════════════════════════════════════════

class PreBOPAdvisor:
    """
    Genera plan de envío Pre-BOP usando el solver VCU a nivel SKU.
    """
    
    def __init__(self, effective_config: dict):
        self.config = effective_config
        
        # Extraer capacidad del camión
        truck_types = effective_config.get("TRUCK_TYPES", {})
        truck_ref = truck_types.get("paquetera", truck_types.get("rampla_directa", {}))

        vcu_min = 0.7
        
        self.capacidad = TruckCapacity(
            cap_weight=truck_ref.get("cap_weight", 20000),
            cap_volume=truck_ref.get("cap_volume", 58612),
            max_pallets=truck_ref.get("max_pallets", 30),
            max_positions=truck_ref.get("max_positions", 30),
            levels=1,  # Todo a piso
            vcu_min=vcu_min,
        )

        # Capacidad backhaul
        truck_bh = truck_types.get("backhaul", {})
        self.capacidad_bh = TruckCapacity(
            cap_weight=truck_bh.get("cap_weight", 20000),
            cap_volume=truck_bh.get("cap_volume", 58612),
            max_pallets=truck_bh.get("max_pallets", 28),
            max_positions=truck_bh.get("max_positions", 28),
            levels=1,
            vcu_min=truck_bh.get("vcu_min", 0.50),
        )
    
    def process(self, pedidos: List[Pedido], tiempo_max: int = 150) -> Dict[str, Any]:
        """
        Procesa pedidos y genera plan de envío optimizado.
        Fase 1: Optimiza con camiones nestlé
        Fase 2: Intenta backhaul con los excluidos
        """
        if not pedidos:
            return self._empty_result()
        
        # 1. Expandir pedidos a pseudo-pedidos (nivel SKU)
        pseudo_pedidos, mapeo = expandir_pedidos_a_skus(pedidos)
        
        if not pseudo_pedidos:
            return self._empty_result()
        
        total_pallets_input = sum(m['pallets'] for m in mapeo.values())
        
        # 2. Configuración de grupo
        grupo_cfg = ConfiguracionGrupo(
            id="frozen_prebop",
            tipo=TipoRuta.NORMAL,
            ce=[pedidos[0].ce] if pedidos else [],
            cd=[pedidos[0].cd] if pedidos else [],
        )
        
        # 3. Config para el solver
        solver_config = {
            **self.config,
            'AGRUPAR_POR_PO': False,
            'PERMITE_APILAMIENTO': False,
            'RESTRICT_PO_GROUP': False,
            'MAX_ORDENES': None,
        }
        
        # FASE 1: Optimizar con camiones Nestlé
        resultado_nestle = optimizar_grupo_vcu(
            pedidos=pseudo_pedidos,
            grupo_cfg=grupo_cfg,
            effective_config=solver_config,
            capacidad=self.capacidad,
            tiempo_max_seg=tiempo_max // 2,  # Mitad del tiempo para cada fase
        )
        
        camiones_nestle = resultado_nestle.get('camiones', [])
        excluidos_nestle = resultado_nestle.get('pedidos_excluidos', [])
        
        # FASE 2: Optimizar excluidos con BACKHAUL
        camiones_backhaul = []
        excluidos_final = excluidos_nestle
        
        if excluidos_nestle:
            # Reconstruir pseudo-pedidos excluidos
            pseudo_excluidos = []
            for exc in excluidos_nestle:
                pseudo_id = exc.get('PEDIDO') or exc.get('pedido')
                if pseudo_id:
                    # Buscar el pseudo-pedido original
                    for pp in pseudo_pedidos:
                        if pp.pedido == pseudo_id:
                            pseudo_excluidos.append(pp)
                            break
            
            if pseudo_excluidos:
                
                resultado_backhaul = optimizar_grupo_vcu(
                    pedidos=pseudo_excluidos,
                    grupo_cfg=grupo_cfg,
                    effective_config=solver_config,
                    capacidad=self.capacidad_bh,
                    tiempo_max_seg=tiempo_max // 2,
                )
                
                camiones_backhaul = resultado_backhaul.get('camiones', [])
                excluidos_final = resultado_backhaul.get('pedidos_excluidos', [])
                
        # Combinar resultados
        resultado_combinado = {
            'status': resultado_nestle.get('status', 'NO_SOLUTION'),
            'camiones': camiones_nestle + camiones_backhaul,
            'pedidos_asignados_ids': (
                resultado_nestle.get('pedidos_asignados_ids', []) +
                [p.pedido for cam in camiones_backhaul for p in cam.pedidos]
            ),
            'pedidos_excluidos': excluidos_final,
        }
        
        # Marcar tipo de camión en cada uno
        for cam in camiones_nestle:
            cam.metadata = cam.metadata or {}
            cam.metadata['tipo_asignado'] = 'nestle'
        
        for cam in camiones_backhaul:
            cam.metadata = cam.metadata or {}
            cam.metadata['tipo_asignado'] = 'backhaul'
        
        # 5. Analizar splits
        splits = analizar_splits(pedidos, resultado_combinado, mapeo)
        
        # 6. Generar guía BOP
        guia = generar_guia_bop(splits)
        
        # 7. Construir resultado
        return self._construir_resultado(
            pedidos, 
            resultado_combinado, 
            splits, 
            guia,
            total_pallets_input,
            mapeo,
            len(camiones_nestle),
            len(camiones_backhaul)
        )


    def _construir_resultado(
        self,
        pedidos_originales: List[Pedido],
        resultado_solver: Dict[str, Any],
        splits: List[Dict[str, Any]],
        guia: List[Dict[str, Any]],
        total_pallets_input: float,
        mapeo: Dict[str, Dict[str, Any]],
        num_nestle: int = 0,
        num_backhaul: int = 0
    ) -> Dict[str, Any]:
        """Construye resultado final."""
        
        # camiones son objetos Camion, no dicts
        camiones_raw = resultado_solver.get('camiones', [])
        
        # Calcular totales
        total_asignados = sum(s['pallets_asignados'] for s in splits)
        total_rechazados = sum(s['pallets_rechazados'] for s in splits)
        
        ## VCU promedio separado por tipo
        vcu_promedio = 0
        vcu_promedio_nestle = 0
        vcu_promedio_backhaul = 0
        
        if camiones_raw:
            vcus_nestle = []
            vcus_backhaul = []
            
            for cam in camiones_raw:
                vcu = getattr(cam, 'vcu_max', 0) or 0
                tipo = cam.metadata.get('tipo_asignado', 'nestle') if cam.metadata else 'nestle'
                
                if tipo == 'backhaul':
                    vcus_backhaul.append(vcu)
                else:
                    vcus_nestle.append(vcu)
            
            if vcus_nestle:
                vcu_promedio_nestle = sum(vcus_nestle) / len(vcus_nestle)
            if vcus_backhaul:
                vcu_promedio_backhaul = sum(vcus_backhaul) / len(vcus_backhaul)
            
            todos_vcus = vcus_nestle + vcus_backhaul
            if todos_vcus:
                vcu_promedio = sum(todos_vcus) / len(todos_vcus)
        
        # Preview de camiones (convertir objetos Camion a dicts)
        camiones_preview = []
        for idx, cam in enumerate(camiones_raw):
            # Agrupar pedidos por pedido original
            pedidos_por_original: Dict[str, List[str]] = {}
            
            # cam.pedidos son objetos Pedido
            for p in cam.pedidos:
                pseudo_id = p.pedido  # Atributo, no .get()
                if pseudo_id in mapeo:
                    ped_orig = mapeo[pseudo_id]['pedido_original']
                    sku_id = mapeo[pseudo_id]['sku_id']
                    if ped_orig not in pedidos_por_original:
                        pedidos_por_original[ped_orig] = []
                    pedidos_por_original[ped_orig].append(sku_id)
            
            # Acceder a atributos del objeto Camion
            vcu_peso = getattr(cam, 'vcu_peso', 0) or 0
            vcu_vol = getattr(cam, 'vcu_vol', 0) or 0
            vcu_max = getattr(cam, 'vcu_max', 0) or max(vcu_peso, vcu_vol)
            pos_total = getattr(cam, 'pos_total', 0) or getattr(cam, 'pallets_conf', 0) or 0
            peso_total = getattr(cam, 'peso_total', 0) or sum(p.peso for p in cam.pedidos)
            vol_total = getattr(cam, 'volumen_total', 0) or sum(p.volumen for p in cam.pedidos)
            
            camiones_preview.append({
                'camion': idx + 1,
                'tipo_camion': cam.metadata.get('tipo_asignado', 'paquetera') if cam.metadata else 'paquetera',
                'posiciones': round(pos_total, 1),
                'peso_kg': round(peso_total, 1),
                'volumen_m3': round(vol_total, 1),
                'vcu_peso': round(vcu_peso, 3),
                'vcu_volumen': round(vcu_vol, 3),
                'vcu_max': round(vcu_max, 3),
                'cumple_vcu': vcu_max >= self.capacidad.vcu_min,
                'pedidos': list(pedidos_por_original.keys()),
                'skus_por_pedido': pedidos_por_original,
            })
        
        # Alertas
        alertas = []
        if total_rechazados > 0.01:
            pct = total_rechazados / total_pallets_input * 100 if total_pallets_input > 0 else 0
            alertas.append(f"⚠️ {round(total_rechazados, 1)} pallets ({pct:.1f}%) no pudieron asignarse")
        
        pedidos_con_split = [s for s in splits if s['num_camiones'] > 1]
        if pedidos_con_split:
            alertas.append(f"📋 {len(pedidos_con_split)} pedidos quedan divididos entre múltiples camiones")
        
        return {
            'fase': 'pre_bop',
            'resumen': {
                'total_pedidos': len(pedidos_originales),
                'total_pallets_input': round(total_pallets_input, 1),
                'total_pallets_asignados': round(total_asignados, 1),
                'total_pallets_rechazados': round(total_rechazados, 1),
                'porcentaje_asignado': round(total_asignados / total_pallets_input * 100, 1) if total_pallets_input > 0 else 0,
                'camiones_necesarios': len(camiones_preview),
                'camiones_nestle': num_nestle,
                'camiones_backhaul': num_backhaul,
                'vcu_promedio_nestle': round(vcu_promedio_nestle, 3),
                'vcu_promedio_backhaul': round(vcu_promedio_backhaul, 3),
                'vcu_promedio': round(vcu_promedio, 3),
                'vcu_target': self.capacidad.vcu_min,
                'vcu_target_backhaul': self.capacidad_bh.vcu_min,
                'pedidos_con_split': len(pedidos_con_split),
                'pedidos_con_rechazo': len([s for s in splits if s['pallets_rechazados'] > 0]),
            },
            'camiones_preview': camiones_preview,
            'splits_recomendados': splits,
            'guia_para_bop': guia,
            'alertas': alertas,
            'status': resultado_solver.get('status', 'NO_SOLUTION'),
        }
    
    def _empty_result(self) -> Dict[str, Any]:
        """Resultado vacío."""
        return {
            'fase': 'pre_bop',
            'resumen': {
                'total_pedidos': 0,
                'total_pallets_input': 0,
                'total_pallets_asignados': 0,
                'total_pallets_rechazados': 0,
                'porcentaje_asignado': 0,
                'camiones_necesarios': 0,
                'vcu_promedio': 0,
                'vcu_target': self.capacidad.vcu_min,
                'pedidos_con_split': 0,
                'pedidos_con_rechazo': 0,
            },
            'camiones_preview': [],
            'splits_recomendados': [],
            'guia_para_bop': [],
            'alertas': [],
            'status': 'NO_SOLUTION',
        }


# ════════════════════════════════════════════════════════════════════════════
# POST-BOP PROCESSOR
# ════════════════════════════════════════════════════════════════════════════

class PostBOPProcessor:
    """Procesa datos Post-BOP para optimización normal."""
    
    def __init__(self, effective_config: dict):
        self.config = effective_config
    
    def process(self, pedidos: List[Pedido]) -> Dict[str, Any]:
        """
        Procesa pedidos post-BOP.
        Identifica hermanos (mismo PO) y los marca para restricción.
        """
        grupos_hermanos = self._identificar_hermanos(pedidos)
        
        # Marcar hermanos en metadata
        for pedido in pedidos:
            if pedido.po in grupos_hermanos:
                hermanos = [h for h in grupos_hermanos[pedido.po] if h != pedido.pedido]
                if hermanos:
                    pedido.metadata['hermanos_prohibidos'] = hermanos
        
        alertas = []
        grupos_con_hermanos = len([k for k, v in grupos_hermanos.items() if len(v) > 1])
        if grupos_con_hermanos > 0:
            alertas.append(f"📋 {grupos_con_hermanos} POs tienen pedidos hermanos que NO deben ir juntos")
        
        return {
            'fase': 'post_bop',
            'grupos_hermanos': grupos_hermanos,
            'pedidos_para_optimizador': pedidos,
            'alertas': alertas,
        }
    
    def _identificar_hermanos(self, pedidos: List[Pedido]) -> Dict[str, List[str]]:
        """Identifica pedidos con mismo PO."""
        po_pedidos: Dict[str, List[str]] = {}
        for pedido in pedidos:
            if pedido.po not in po_pedidos:
                po_pedidos[pedido.po] = []
            po_pedidos[pedido.po].append(pedido.pedido)
        
        return {po: pids for po, pids in po_pedidos.items() if len(pids) > 1}


# ════════════════════════════════════════════════════════════════════════════
# FUNCIÓN PRINCIPAL
# ════════════════════════════════════════════════════════════════════════════

def procesar_frozen_channel(
    pedidos: List[Pedido],
    effective_config: dict,
    fase: str,
) -> Dict[str, Any]:
    """
    Función principal para procesar canales Helados/Refrigerados.
    
    Args:
        pedidos: Lista de pedidos a procesar
        effective_config: Configuración efectiva del canal
        fase: "pre_bop" o "post_bop"
    
    Returns:
        Resultado según la fase
    """
    if fase == "pre_bop":
        advisor = PreBOPAdvisor(effective_config)
        return advisor.process(pedidos)
    
    else:  # post_bop
        processor = PostBOPProcessor(effective_config)
        return processor.process(pedidos)