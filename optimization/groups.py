# services/optimizer_groups.py
"""
Generación de grupos y rutas para optimización.
Particiona pedidos en grupos disjuntos según CD, CE, OC y tipo de ruta.
"""

from typing import List, Tuple, Iterator, Set
from models.domain import Pedido, ConfiguracionGrupo
from models.enums import TipoRuta
from core.constants import CD_LO_AGUIRRE

def _generar_grupos_para_tipo(
    pedidos_disponibles: List[Pedido],
    client_config,
    tipo: str
) -> List[Tuple[ConfiguracionGrupo, List[Pedido]]]:
    """
    Genera grupos de un tipo específico SOLO con los pedidos disponibles.
    
    Args:
        pedidos_disponibles: Pedidos aún NO asignados
        client_config: Configuración del cliente
        tipo: Tipo de ruta ("multi_ce", "multi_cd", "bh", etc.)
    
    Returns:
        Lista de (ConfiguracionGrupo, pedidos) para este tipo
    """
    if not pedidos_disponibles:
        return []
    
    # Obtener rutas del tipo solicitado
    rutas = client_config.RUTAS_POSIBLES.get(tipo, [])
    if not rutas:
        return []
    
    usa_oc = getattr(client_config, "USA_OC", False)
    mix_grupos = getattr(client_config, "MIX_GRUPOS", [])
    
    grupos = []
    
    # Generar grupos según el tipo
    if tipo == "normal":
        grupos_tipo, _ = _build_normal_groups(
            pedidos_disponibles, rutas, mix_grupos, usa_oc
        )
    else:
        grupos_tipo, _ = _build_other_groups(
            pedidos_disponibles, rutas, tipo, usa_oc, mix_grupos
        )
    
    return grupos_tipo


def generar_grupos_optimizacion(
    pedidos: List[Pedido],
    client_config,
    modo: str
) -> List[Tuple[ConfiguracionGrupo, List[Pedido]]]:
    """
    Genera grupos para optimizar.
    
    Args:
        pedidos: Lista de pedidos disponibles
        client_config: Configuración del cliente
        modo: "vcu", "binpacking", o "normal" (solo grupos normales)
    
    Returns:
        Lista de (ConfiguracionGrupo, pedidos)
    """
    usa_oc = getattr(client_config, "USA_OC", False)
    mix_grupos = getattr(client_config, "MIX_GRUPOS", [])
    
    # ✅ Caso especial: solo generar grupos normales
    if modo == "normal":
        rutas_normal = client_config.RUTAS_POSIBLES.get("normal", [])
        if rutas_normal:
            grupos, _ = _build_normal_groups(pedidos, rutas_normal, mix_grupos, usa_oc)
            return grupos
        return []
    
    # Determinar tipos de ruta según modo
    if modo == "binpacking":
        tipos_ruta = getattr(client_config, "BINPACKING_TIPOS_RUTA", ["normal"]) or ["normal"]
        rutas_func = lambda t: getattr(client_config, "RUTAS_BINPACKING", {}).get(
            t, client_config.RUTAS_POSIBLES.get(t, [])
        )
    else:  # VCU
        tipos_ruta = ["multi_ce_prioridad", "normal", "multi_ce", "multi_cd", "bh"]
        rutas_func = lambda t: client_config.RUTAS_POSIBLES.get(t, [])
    
    fases = [(t, rutas_func(t)) for t in tipos_ruta if rutas_func(t)]
    
    grupos = []
    pedidos_restantes = pedidos.copy()
    
    # Procesar cada fase (para binpacking que sigue siendo secuencial)
    for tipo, rutas in fases:
        if tipo == "normal":
            grupos_fase, pedidos_restantes = _build_normal_groups(
                pedidos_restantes, rutas, mix_grupos, usa_oc
            )
        else:
            grupos_fase, pedidos_restantes = _build_other_groups(
                pedidos_restantes, rutas, tipo, usa_oc, mix_grupos
            )
        
        grupos.extend(grupos_fase)
    
    return grupos


def _build_normal_groups(
    pedidos: List[Pedido],
    rutas: List[Tuple[List[str], List[str]]],
    mix_grupos: List[List[str]],
    usa_oc: bool
) -> Tuple[List[Tuple[ConfiguracionGrupo, List[Pedido]]], List[Pedido]]:
    """
    Construye grupos para rutas normales sin solapamiento.
    """
    grupos = []
    asignados: Set[str] = set()  # ✅ RESTAURAR
    
    for cds, ces, oc in _generar_iterador_rutas("normal", rutas, pedidos, mix_grupos, usa_oc):
        # Filtrar pedidos que coinciden y no están asignados
        pedidos_grupo = [
            p for p in pedidos
            if p.pedido not in asignados  # ✅ RESTAURAR
            and p.cd in cds
            and p.ce in ces
            and _match_oc(p.oc, oc)
        ]
        
        if not pedidos_grupo:
            continue
        
        oc_str = _format_oc_str(oc)
        cfg = ConfiguracionGrupo(
            id=f"normal__{'-'.join(cds)}__{'-'.join(map(str, ces))}{oc_str}",
            tipo=TipoRuta.NORMAL,
            cd=cds,
            ce=ces,
            oc=oc
        )
        
        grupos.append((cfg, pedidos_grupo))
        asignados.update(p.pedido for p in pedidos_grupo)  # ✅ RESTAURAR
    
    pedidos_restantes = [p for p in pedidos if p.pedido not in asignados]
    return grupos, pedidos_restantes


def _build_other_groups(
    pedidos: List[Pedido],
    rutas: List[Tuple[List[str], List[str]]],
    tipo: str,
    usa_oc: bool,
    mix_grupos: List[List[str]]
) -> Tuple[List[Tuple[ConfiguracionGrupo, List[Pedido]]], List[Pedido]]:
    """
    Construye grupos para otros tipos de ruta.
    """
    grupos = []
    asignados: Set[str] = set()  # ✅ RESTAURAR
    
    for cds, ces, oc in _generar_iterador_rutas(tipo, rutas, pedidos, mix_grupos, usa_oc):
        pedidos_grupo = [
            p for p in pedidos
            if p.pedido not in asignados  # ✅ RESTAURAR
            and p.cd in cds
            and p.ce in ces
            and _match_oc(p.oc, oc)
        ]
        
        if not pedidos_grupo:
            continue
        
        if not _validar_grupo_por_tipo(tipo, pedidos_grupo, cds, ces):
            continue
        
        oc_str = _format_oc_str(oc)
        cfg = ConfiguracionGrupo(
            id=f"{tipo}__{'-'.join(cds)}__{'-'.join(map(str, ces))}{oc_str}",
            tipo=TipoRuta(tipo),
            cd=cds,
            ce=ces,
            oc=oc
        )
        
        grupos.append((cfg, pedidos_grupo))
        asignados.update(p.pedido for p in pedidos_grupo)  # ✅ RESTAURAR
    
    pedidos_restantes = [p for p in pedidos if p.pedido not in asignados]
    return grupos, pedidos_restantes


def _generar_iterador_rutas(
    tipo: str,
    rutas: List[Tuple[List[str], List[str]]],
    pedidos: List[Pedido],
    mix_grupos: List[List[str]],
    usa_oc: bool
) -> Iterator[Tuple[List[str], List[str], any]]:
    """
    Genera iterador de rutas con lógica específica por tipo.
    Yields: (cds, ces, oc)
    """
    if tipo == "normal":
        yield from _iter_normal_routes(rutas, pedidos, mix_grupos, usa_oc)
    elif tipo == "bh":
        yield from _iter_bh_routes(rutas, pedidos, usa_oc)
    else:  # multi_ce, multi_cd, multi_ce_prioridad
        yield from _iter_multi_routes(rutas, pedidos, usa_oc)


def _iter_normal_routes(
    rutas: List[Tuple[List[str], List[str]]],
    pedidos: List[Pedido],
    mix_grupos: List[List[str]],
    usa_oc: bool
) -> Iterator[Tuple[List[str], List[str], any]]:
    """Iterador para rutas normales"""
    for cds, ces in rutas:
        if cds == [CD_LO_AGUIRRE]:
            # Caso especial: Lo Aguirre por CE individual
            pedidos_cd = [p for p in pedidos if p.cd == CD_LO_AGUIRRE]
            for ce in ces:
                pedidos_ce = [p for p in pedidos_cd if p.ce == ce]
                
                if usa_oc:
                    oc_unique = list(set(p.oc for p in pedidos_ce if p.oc))
                    
                    # OCs individuales
                    for oc in oc_unique:
                        yield ([CD_LO_AGUIRRE], [ce], oc)
                    
                    # OCs mixtas
                    for ocg in mix_grupos:
                        if all(o in oc_unique for o in ocg):
                            yield ([CD_LO_AGUIRRE], [ce], ocg)
                    
                    # ✅ NUEVO: Pedidos SIN OC (None) van juntos
                    pedidos_sin_oc = [p for p in pedidos_ce if p.oc is None]
                    if pedidos_sin_oc:
                        yield ([CD_LO_AGUIRRE], [ce], "SIN_OC")  # ✅ Grupo especial
                else:
                    if pedidos_ce:
                        yield ([CD_LO_AGUIRRE], [ce], None)
        else:
            # Caso general
            pedidos_ruta = [p for p in pedidos if p.cd in cds and p.ce in ces]
            
            if usa_oc:
                # ✅ NUEVO: Agrupar por OC
                oc_unique = list(set(p.oc for p in pedidos_ruta if p.oc))
                
                for oc in oc_unique:
                    yield (cds, ces, oc)
                
                # ✅ NUEVO: Pedidos SIN OC van juntos
                pedidos_sin_oc = [p for p in pedidos_ruta if p.oc is None]
                if pedidos_sin_oc:
                    yield (cds, ces, "SIN_OC")
            else:
                if pedidos_ruta:
                    yield (cds, ces, None)


def _iter_bh_routes(
    rutas: List[Tuple[List[str], List[str]]],
    pedidos: List[Pedido],
    usa_oc: bool) -> Iterator[Tuple[List[str], List[str], any]]:
    """Iterador para rutas BH"""
    for cds, ces in rutas:
        pedidos_ruta = [p for p in pedidos if p.cd in cds and p.ce in ces]
        
        if usa_oc:
            # OCs existentes
            for oc in set(p.oc for p in pedidos_ruta if p.oc):
                yield (cds, ces, oc)
            
            # ✅ NUEVO: Pedidos sin OC
            pedidos_sin_oc = [p for p in pedidos_ruta if p.oc is None]
            if pedidos_sin_oc:
                yield (cds, ces, "SIN_OC")
        else:
            if pedidos_ruta:
                yield (cds, ces, None)


def _iter_multi_routes(
    rutas: List[Tuple[List[str], List[str]]],
    pedidos: List[Pedido],
    usa_oc: bool
) -> Iterator[Tuple[List[str], List[str], any]]:
    """Iterador para rutas multi (multi_ce, multi_cd)"""
    for cds, ces in rutas:
        pedidos_ruta = [p for p in pedidos if p.cd in cds and p.ce in ces]
        
        if not pedidos_ruta:
            continue
        
        if CD_LO_AGUIRRE in cds and usa_oc:
            # OCs existentes
            for oc in set(p.oc for p in pedidos_ruta if p.oc):
                if [p for p in pedidos_ruta if p.oc == oc]:
                    yield (cds, ces, oc)
            
            # ✅ NUEVO: Pedidos sin OC
            pedidos_sin_oc = [p for p in pedidos_ruta if p.oc is None]
            if pedidos_sin_oc:
                yield (cds, ces, "SIN_OC")
        else:
            yield (cds, ces, None)


def _match_oc(pedido_oc: str, grupo_oc: any) -> bool:
    """Verifica si un pedido coincide con el OC del grupo"""
    if grupo_oc is None:
        return True  # Grupo sin filtro OC acepta todos
    
    # ✅ NUEVO: Grupo especial "SIN_OC"
    if grupo_oc == "SIN_OC":
        return pedido_oc is None
    
    if isinstance(grupo_oc, list):
        return pedido_oc in grupo_oc
    
    return pedido_oc == grupo_oc


def _validar_grupo_por_tipo(
    tipo: str,
    pedidos: List[Pedido],
    cds: List[str],
    ces: List[str]
) -> bool:
    """Valida que un grupo cumpla requisitos específicos por tipo"""
    if tipo in ("multi_ce", "multi_ce_prioridad"):
        ce_presentes = {p.ce for p in pedidos}
        return all(ce in ce_presentes for ce in ces)
    
    if tipo == "multi_cd":
        cd_presentes = {p.cd for p in pedidos}
        return all(cd in cd_presentes for cd in cds)
    
    return True


def _format_oc_str(oc: any) -> str:
    """Formatea OC para ID del grupo"""
    if oc is None:
        return ""
    if isinstance(oc, list):
        return f"__{'_'.join(oc)}"
    return f"__{oc}"


def calcular_tiempo_por_grupo(
    pedidos: List[Pedido],
    client_config,
    total_timeout: int,
    max_por_grupo: int
) -> int:
    """
    Calcula tiempo máximo por grupo de optimización CON TIEMPOS ADAPTATIVOS.
    
    VERSIÓN MEJORADA: Considera distribución de grupos grandes para ajustar base.
    
    Args:
        pedidos: Lista de pedidos
        client_config: Configuración del cliente
        total_timeout: Timeout total disponible
        max_por_grupo: Máximo tiempo por grupo
    
    Returns:
        Tiempo BASE en segundos por grupo
    """
    num_grupos, distribucion = _estimar_cantidad_grupos_mejorado(pedidos, client_config)
    tiempo_disponible = max(total_timeout - 5, 1)
    
    if num_grupos == 0:
        return min(5, max_por_grupo)
    
    # Calcular tiempo base (distribución uniforme)
    tpg_base = tiempo_disponible // num_grupos
    tpg_base = min(max(tpg_base, 2), max_por_grupo)
    
    # ✅ NUEVO: Ajustar base según proporción de grupos grandes
    num_grandes = distribucion.get('grandes', 0)
    num_muy_grandes = distribucion.get('muy_grandes', 0)
    proporcion_grandes = (num_grandes + num_muy_grandes) / max(num_grupos, 1)
    
    # Si hay muchos grupos grandes (>30%), aumentar tiempo base
    if proporcion_grandes > 0.3:
        factor = 1.2 if proporcion_grandes > 0.5 else 1.1
        tpg_base = min(int(tpg_base * factor), max_por_grupo)
        print(f"[TIMING] Ajuste por grupos grandes: {proporcion_grandes:.1%} → factor {factor}x")
    
    # Si hay pocos grupos totales, dar más tiempo
    if num_grupos <= 5:
        tpg_base = min(int(tpg_base * 1.5), max_por_grupo)
    
    # Si hay muchos grupos pequeños, el tiempo base está bien
    if num_grupos > 50 and distribucion.get('pequeños', 0) > 30:
        tpg_base = max(2, int(tpg_base * 0.9))
    
    print(f"[TIMING] Grupos: {num_grupos}, Base: {tpg_base}s, Dist: {distribucion}")
    
    return tpg_base


def _estimar_cantidad_grupos_mejorado(
    pedidos: List[Pedido], 
    config
) -> tuple:
    """
    Estima cantidad de grupos QUE SE GENERARÁN (incluyendo SIN_OC).
    
    Returns:
        (total_grupos: int, distribucion: dict)
        
        donde distribucion es:
        {
            'pequeños': int,   # < 5 pedidos
            'medianos': int,   # 5-20 pedidos
            'grandes': int     # > 20 pedidos
        }
    """
    tipos_ruta = ["multi_ce_prioridad", "normal", "multi_ce", "multi_cd", "bh"]
    fases = [
        (tipo, config.RUTAS_POSIBLES.get(tipo, []))
        for tipo in tipos_ruta
        if config.RUTAS_POSIBLES.get(tipo)
    ]
    
    total = 0
    distribucion = {'pequeños': 0, 'medianos': 0, 'grandes': 0}
    
    usa_oc = getattr(config, "USA_OC", False)
    mix_grupos = getattr(config, "MIX_GRUPOS", [])
    
    for tipo, rutas in fases:
        if tipo == "normal":
            for cds, ces in rutas:
                if cds == [CD_LO_AGUIRRE]:
                    pedidos_cd = [p for p in pedidos if p.cd == CD_LO_AGUIRRE]
                    
                    for ce in ces:
                        pedidos_ce = [p for p in pedidos_cd if p.ce == ce]
                        
                        if not pedidos_ce:
                            continue
                        
                        if usa_oc:
                            # ✅ Contar OCs existentes
                            oc_unique = list(set(p.oc for p in pedidos_ce if p.oc))
                            
                            for oc in oc_unique:
                                pedidos_oc = [p for p in pedidos_ce if p.oc == oc]
                                total += 1
                                _clasificar_grupo(pedidos_oc, distribucion)
                            
                            # ✅ Contar grupos MIX
                            for ocg in mix_grupos:
                                if all(o in oc_unique for o in ocg):
                                    pedidos_mix = [p for p in pedidos_ce if p.oc in ocg]
                                    total += 1
                                    _clasificar_grupo(pedidos_mix, distribucion)
                            
                            # ✅ CRÍTICO: Contar SIN_OC
                            pedidos_sin_oc = [p for p in pedidos_ce if p.oc is None]
                            if pedidos_sin_oc:
                                total += 1
                                _clasificar_grupo(pedidos_sin_oc, distribucion)
                        else:
                            total += 1
                            _clasificar_grupo(pedidos_ce, distribucion)
                else:
                    # Ruta normal (no Lo Aguirre)
                    pedidos_ruta = [p for p in pedidos if p.cd in cds and p.ce in ces]
                    
                    if not pedidos_ruta:
                        continue
                    
                    if usa_oc:
                        # ✅ Contar por OC
                        oc_unique = list(set(p.oc for p in pedidos_ruta if p.oc))
                        
                        for oc in oc_unique:
                            pedidos_oc = [p for p in pedidos_ruta if p.oc == oc]
                            total += 1
                            _clasificar_grupo(pedidos_oc, distribucion)
                        
                        # ✅ CRÍTICO: Contar SIN_OC
                        pedidos_sin_oc = [p for p in pedidos_ruta if p.oc is None]
                        if pedidos_sin_oc:
                            total += 1
                            _clasificar_grupo(pedidos_sin_oc, distribucion)
                    else:
                        total += 1
                        _clasificar_grupo(pedidos_ruta, distribucion)
        
        elif tipo == "bh":
            for cds, ces in rutas:
                pedidos_ruta = [p for p in pedidos if p.cd in cds and p.ce in ces]
                
                if not pedidos_ruta:
                    continue
                
                if usa_oc:
                    # ✅ Contar por OC
                    oc_unique = list(set(p.oc for p in pedidos_ruta if p.oc))
                    
                    for oc in oc_unique:
                        pedidos_oc = [p for p in pedidos_ruta if p.oc == oc]
                        total += 1
                        _clasificar_grupo(pedidos_oc, distribucion)
                    
                    # ✅ CRÍTICO: Contar SIN_OC
                    pedidos_sin_oc = [p for p in pedidos_ruta if p.oc is None]
                    if pedidos_sin_oc:
                        total += 1
                        _clasificar_grupo(pedidos_sin_oc, distribucion)
                else:
                    total += 1
                    _clasificar_grupo(pedidos_ruta, distribucion)
        
        else:  # multi_ce, multi_cd, multi_ce_prioridad
            for cds, ces in rutas:
                pedidos_ruta = [p for p in pedidos if p.cd in cds and p.ce in ces]
                
                if not pedidos_ruta:
                    continue
                
                if CD_LO_AGUIRRE in cds and usa_oc:
                    # ✅ Contar por OC
                    oc_unique = list(set(p.oc for p in pedidos_ruta if p.oc))
                    
                    for oc in oc_unique:
                        pedidos_oc = [p for p in pedidos_ruta if p.oc == oc]
                        total += 1
                        _clasificar_grupo(pedidos_oc, distribucion)
                    
                    # ✅ CRÍTICO: Contar SIN_OC
                    pedidos_sin_oc = [p for p in pedidos_ruta if p.oc is None]
                    if pedidos_sin_oc:
                        total += 1
                        _clasificar_grupo(pedidos_sin_oc, distribucion)
                else:
                    total += 1
                    _clasificar_grupo(pedidos_ruta, distribucion)
    
    return total, distribucion


def _clasificar_grupo(pedidos: List[Pedido], distribucion: dict):
    """
    Clasifica un grupo por tamaño y actualiza distribución.
    
    CLASIFICACIÓN MÁS GRANULAR para mejor estimación de tiempos.
    
    Args:
        pedidos: Pedidos del grupo
        distribucion: Dict a actualizar con clasificación
    """
    n = len(pedidos)
    
    # Clasificación más granular
    if n < 5:
        distribucion['pequeños'] += 1
    elif n <= 20:
        distribucion['medianos'] += 1
    else:
        distribucion['grandes'] += 1
        
        # Sub-clasificación para grupos grandes (para debugging)
        if 'muy_grandes' not in distribucion:
            distribucion['muy_grandes'] = 0
        if n > 40:
            distribucion['muy_grandes'] += 1

def ajustar_tiempo_grupo(
    tiempo_base: int,
    num_pedidos: int,
    tipo_grupo: str = "normal"
) -> int:
    """
    Ajusta el tiempo de optimización según características del grupo.
    
    MULTIPLICADORES AGRESIVOS para grupos grandes.
    
    Args:
        tiempo_base: Tiempo base calculado
        num_pedidos: Número de pedidos en el grupo
        tipo_grupo: Tipo de grupo (normal, bh, multi_ce, etc.)
    
    Returns:
        Tiempo ajustado en segundos
    """
    # Grupos muy pequeños (< 3 pedidos) → tiempo mínimo
    if num_pedidos < 3:
        return max(2, int(tiempo_base * 0.5))
    
    # Grupos pequeños (3-5 pedidos) → reducir tiempo
    elif num_pedidos < 5:
        return max(2, int(tiempo_base * 0.7))
    
    # Grupos pequeños-medianos (5-10 pedidos) → tiempo base reducido
    elif num_pedidos <= 10:
        return max(3, int(tiempo_base * 0.9))
    
    # Grupos medianos (10-20 pedidos) → tiempo base completo
    elif num_pedidos <= 30:
        return tiempo_base
    
    # Grupos grandes (20-40 pedidos) → aumentar significativamente
    elif num_pedidos <= 40:
        return min(int(tiempo_base * 2.5), 50)
    
    # Grupos muy grandes (40-60 pedidos) → aumentar mucho más
    elif num_pedidos <= 60:
        return min(int(tiempo_base * 4), 120)
    
    # Grupos extremadamente grandes (> 60 pedidos) → tiempo máximo
    else:
        return min(int(tiempo_base *5), 150)
    
__all__ = [
    "generar_grupos_optimizacion",
    "calcular_tiempo_por_grupo",
    "ajustar_tiempo_grupo",
]