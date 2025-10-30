# services/optimizer_groups.py
"""
Generación de grupos y rutas para optimización.
Particiona pedidos en grupos disjuntos según CD, CE, OC y tipo de ruta.
"""

from typing import List, Tuple, Iterator, Set
from services.models import Pedido, ConfiguracionGrupo, TipoRuta
from services.constants import CD_LO_AGUIRRE


def generar_grupos_optimizacion(
    pedidos: List[Pedido],
    client_config,
    modo: str
) -> List[Tuple[ConfiguracionGrupo, List[Pedido]]]:
    """
    Genera grupos disjuntos de pedidos para optimizar.
    
    Args:
        pedidos: Lista completa de pedidos
        client_config: Configuración del cliente
        modo: "vcu" o "binpacking"
    
    Returns:
        Lista de tuplas (configuración_grupo, pedidos_del_grupo)
    """
    # Determinar tipos de ruta según modo
    if modo == "binpacking":
        tipos_ruta = getattr(client_config, "BINPACKING_TIPOS_RUTA", ["normal"]) or ["normal"]
        rutas_func = lambda t: getattr(client_config, "RUTAS_BINPACKING", {}).get(
            t, client_config.RUTAS_POSIBLES.get(t, [])
        )
    else:
        tipos_ruta = ["multi_ce_prioridad", "normal", "multi_ce", "multi_cd", "bh"]
        rutas_func = lambda t: client_config.RUTAS_POSIBLES.get(t, [])
    
    fases = [(t, rutas_func(t)) for t in tipos_ruta if rutas_func(t)]
    
    grupos = []
    pedidos_restantes = pedidos.copy()
    usa_oc = getattr(client_config, "USA_OC", False)
    mix_grupos = getattr(client_config, "MIX_GRUPOS", [])
    
    # Procesar cada fase
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
    asignados: Set[str] = set()
    
    for cds, ces, oc in _generar_iterador_rutas("normal", rutas, pedidos, mix_grupos, usa_oc):
        # Filtrar pedidos que coinciden y no están asignados
        pedidos_grupo = [
            p for p in pedidos
            if p.pedido not in asignados
            and p.cd in cds
            and p.ce in ces
            and _match_oc(p.oc, oc)
        ]
        
        if not pedidos_grupo:
            continue
        
        # Crear configuración del grupo
        oc_str = _format_oc_str(oc)
        cfg = ConfiguracionGrupo(
            id=f"normal__{'-'.join(cds)}__{'-'.join(map(str, ces))}{oc_str}",
            tipo=TipoRuta.NORMAL,
            cd=cds,
            ce=ces,
            oc=oc
        )
        
        grupos.append((cfg, pedidos_grupo))
        asignados.update(p.pedido for p in pedidos_grupo)
    
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
    Construye grupos para otros tipos de ruta (multi_ce, multi_cd, bh).
    """
    grupos = []
    asignados: Set[str] = set()
    
    for cds, ces, oc in _generar_iterador_rutas(tipo, rutas, pedidos, mix_grupos, usa_oc):
        pedidos_grupo = [
            p for p in pedidos
            if p.pedido not in asignados
            and p.cd in cds
            and p.ce in ces
            and _match_oc(p.oc, oc)
        ]
        
        if not pedidos_grupo:
            continue
        
        # Validaciones específicas por tipo
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
        asignados.update(p.pedido for p in pedidos_grupo)
    
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
                else:
                    if pedidos_ce:
                        yield ([CD_LO_AGUIRRE], [ce], None)
        else:
            # Caso general
            pedidos_ruta = [p for p in pedidos if p.cd in cds and p.ce in ces]
            if pedidos_ruta:
                yield (cds, ces, None)


def _iter_bh_routes(
    rutas: List[Tuple[List[str], List[str]]],
    pedidos: List[Pedido],
    usa_oc: bool
) -> Iterator[Tuple[List[str], List[str], any]]:
    """Iterador para rutas BH"""
    for cds, ces in rutas:
        pedidos_ruta = [p for p in pedidos if p.cd in cds and p.ce in ces]
        
        if usa_oc:
            for oc in set(p.oc for p in pedidos_ruta if p.oc):
                yield (cds, ces, oc)
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
            for oc in set(p.oc for p in pedidos_ruta if p.oc):
                if [p for p in pedidos_ruta if p.oc == oc]:
                    yield (cds, ces, oc)
        else:
            yield (cds, ces, None)


def _match_oc(pedido_oc: str, grupo_oc: any) -> bool:
    """Verifica si un pedido coincide con el OC del grupo"""
    if grupo_oc is None:
        return True
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
    Calcula tiempo máximo por grupo de optimización.
    
    Args:
        pedidos: Lista de pedidos
        client_config: Configuración del cliente
        total_timeout: Timeout total disponible
        max_por_grupo: Máximo tiempo por grupo
    
    Returns:
        Tiempo en segundos por grupo
    """
    num_grupos = _estimar_cantidad_grupos(pedidos, client_config)
    tiempo_disponible = max(total_timeout - 5, 1)
    
    if num_grupos > 0:
        tpg = tiempo_disponible // num_grupos
        return min(max(tpg, 1), max_por_grupo)
    
    return min(1, max_por_grupo)


def _estimar_cantidad_grupos(pedidos: List[Pedido], config) -> int:
    """Estima cantidad de grupos que se generarán"""
    tipos_ruta = ["multi_ce_prioridad", "normal", "multi_ce", "multi_cd", "bh"]
    fases = [
        (tipo, config.RUTAS_POSIBLES.get(tipo, []))
        for tipo in tipos_ruta
        if config.RUTAS_POSIBLES.get(tipo)
    ]
    
    total = 0
    usa_oc = getattr(config, "USA_OC", False)
    mix_grupos = getattr(config, "MIX_GRUPOS", [])
    
    for tipo, rutas in fases:
        if tipo == "normal":
            for cds, ces in rutas:
                if cds == [CD_LO_AGUIRRE]:
                    pedidos_cd = [p for p in pedidos if p.cd == CD_LO_AGUIRRE]
                    for ce in ces:
                        pedidos_ce = [p for p in pedidos_cd if p.ce == ce]
                        if usa_oc:
                            oc_unique = list(set(p.oc for p in pedidos_ce if p.oc))
                            total += len(oc_unique)
                            for ocg in mix_grupos:
                                if all(o in oc_unique for o in ocg):
                                    total += 1
                        else:
                            if pedidos_ce:
                                total += 1
                else:
                    if [p for p in pedidos if p.cd in cds and p.ce in ces]:
                        total += 1
        
        elif tipo == "bh":
            for cds, ces in rutas:
                pedidos_ruta = [p for p in pedidos if p.cd in cds and p.ce in ces]
                if usa_oc:
                    total += len(set(p.oc for p in pedidos_ruta if p.oc))
                else:
                    if pedidos_ruta:
                        total += 1
        
        else:  # multi_ce, multi_cd
            for cds, ces in rutas:
                pedidos_ruta = [p for p in pedidos if p.cd in cds and p.ce in ces]
                if CD_LO_AGUIRRE in cds and usa_oc:
                    total += len(set(p.oc for p in pedidos_ruta if p.oc))
                else:
                    if pedidos_ruta:
                        total += 1
    
    return total