# optimization/validation/height_validator.py
"""
Validador de altura con performance optimizado.
Complejidad: O(n×m) donde n = pedidos, m = posiciones
Overhead estimado: 10-50ms por camión
"""

from __future__ import annotations
from typing import List, Tuple, Optional, Dict
from collections import defaultdict

# Para guardar el debug
import json
from pathlib import Path

from models.domain import Camion, Pedido, TruckCapacity
from models.stacking import (
    LayoutCamion,
    PosicionCamion,
    PalletFisico,
    FragmentoSKU,
    CategoriaApilamiento
)

# Flag para activar/desactivar prints de debug
DEBUG_VALIDATION = False  # CAMBIAR A True TEMPORALMENTE


class HeightValidator:
    """
    Valida altura de apilamiento en camiones.
    Optimizado para bajo overhead (<50ms por camión).
    """
    
    def __init__(
        self,
        altura_maxima_cm: float = 270,
        permite_consolidacion: bool = True,
        max_skus_por_pallet: int = 3,
        max_altura_picking_apilado_cm: float = None,
    ):
        """
        Args:
            altura_maxima_cm: Altura máxima del camión (viene de TruckCapacity)
            permite_consolidacion: Si pickings pueden consolidarse en pallets físicos
            max_skus_por_pallet: Máximo SKUs diferentes en 1 pallet consolidado
        """
        self.altura_maxima_cm = altura_maxima_cm
        self.permite_consolidacion = permite_consolidacion
        self.max_skus_por_pallet = max_skus_por_pallet
        self.max_altura_picking_apilado_cm = max_altura_picking_apilado_cm
    
    def validar_camion_rapido(
        self,
        camion: Camion
    ) -> Tuple[bool, List[str], Optional[LayoutCamion], Optional[Dict]]:
        """Validación RÁPIDA con logging detallado."""
        
        errores = []
        debug_info = {
            'fragmentos_totales': 0,
            'fragmentos_colocados': 0,
            'fragmentos_fallidos': [],
            'posiciones_usadas': 0,
            'layout_parcial': None,
            'historia_colocacion': []
        }
        
        try:
            # NO imprimir aquí - se imprime en el worker con lock
            
            # 1. Extraer fragmentos
            fragmentos = self._extraer_fragmentos_batch(camion.pedidos)
            debug_info['fragmentos_totales'] = len(fragmentos)
            
            if not fragmentos:
                errores.append("No se pudieron extraer fragmentos de los pedidos")
                self._reportar_fallas_detallado(camion, debug_info, fragmentos, errores)
                return False, errores, None, debug_info
            
            # 2. Validación rápida
            for frag in fragmentos:
                if frag.altura_cm > self.altura_maxima_cm:
                    errores.append(f"SKU {frag.sku_id} del pedido {frag.pedido_id} excede altura: " 
                                f"{frag.altura_cm:.1f}cm > {self.altura_maxima_cm:.1f}cm")
                
                # Validar pickings contra su límite específico 
                if frag.es_picking and self.max_altura_picking_apilado_cm:
                    if frag.altura_cm > self.max_altura_picking_apilado_cm:
                        errores.append(
                            f"PICKING SKU {frag.sku_id} del pedido {frag.pedido_id} excede altura máxima picking: "
                            f"{frag.altura_cm:.1f}cm > {self.max_altura_picking_apilado_cm:.1f}cm"
                        )
            
            if errores and any(e is not None for e in errores):
                self._reportar_fallas_detallado(camion, debug_info, fragmentos, errores)
                return False, [e for e in errores if e is not None], None, debug_info
            
            # 3. Agrupar por categoría
            grupos = self._agrupar_por_categoria(fragmentos)
            
            # 4. Estimar posiciones
            posiciones_necesarias = self._estimar_posiciones_necesarias(grupos)
            
            # 5. Construir layout CON DEBUG
            layout, debug_info = self._construir_layout_con_debug(camion, fragmentos)
            
            # 6. Analizar resultados
            if debug_info['fragmentos_fallidos']:
                self._reportar_fallas_detallado(camion, debug_info, fragmentos, errores)
                errores.append(f"No se pudieron colocar {len(debug_info['fragmentos_fallidos'])} fragmentos")
                return False, errores, debug_info.get('layout_parcial'), debug_info
            
            if layout is None:
                errores.append("No se pudo construir layout")
                self._reportar_fallas_detallado(camion, debug_info, fragmentos, errores)
                return False, [e for e in errores if e is not None], None, debug_info
            
            return True, [], layout, debug_info
        
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            
            errores.append(f"Excepción: {type(e).__name__}: {str(e)}")
            
            
            self._reportar_fallas_detallado(camion, debug_info, [], errores)
            
            return False, errores, None, debug_info

    def _extraer_fragmentos_batch(
        self,
        pedidos: List[Pedido]
    ) -> List[FragmentoSKU]:
        """
        Extrae fragmentos de todos los pedidos.
        
        ✅ MANEJA CASOS EDGE:
        - Altura full pallet = 0 → usar altura picking o 1cm mínimo
        - Altura picking = 0 → usar altura full pallet proporcionalmente
        - Cantidad < 1 → fragmento único con altura ajustada
        """
        fragmentos = []
        
        for pedido in pedidos:
            if pedido.tiene_skus:
                # Pedido con SKUs detallados
                for sku in pedido.skus:
                    try:
                        cantidad_pallets = sku.cantidad_pallets
                        
                        # ✅ VALIDACIÓN: Verificar que haya al menos UNA altura válida
                        altura_full = sku.altura_full_pallet_cm if sku.altura_full_pallet_cm > 0 else 0
                        altura_pick = sku.altura_picking_cm if (sku.altura_picking_cm and sku.altura_picking_cm > 0) else 0
                        
                        if altura_full == 0 and altura_pick == 0:
                            # ⚠️ CASO CRÍTICO: Sin ninguna altura válida
                            print(f"[WARN] SKU {sku.sku_id} sin alturas válidas, usando 100cm por defecto")
                            altura_full = 100.0  # Altura por defecto conservadora
                        
                        # CASO 1: Cantidad < 1 (solo picking)
                        if cantidad_pallets < 1.0:
                            # Es un picking parcial
                            if altura_pick > 0:
                                altura_cm = altura_pick
                            elif altura_full > 0:
                                # Calcular proporcionalmente
                                altura_cm = altura_full * cantidad_pallets
                            else:
                                # Fallback
                                altura_cm = 50.0
                            
                            if altura_cm <= 0:
                                print(f"[WARN] PICKING SKU {sku.sku_id}: altura = 0, usando 50cm")
                                altura_cm = 50.0
                            
                            frag = FragmentoSKU(
                                sku_id=sku.sku_id,
                                pedido_id=pedido.pedido,
                                fraccion=cantidad_pallets,
                                altura_cm=altura_cm,
                                peso_kg=sku.peso_kg,
                                volumen_m3=sku.volumen_m3,
                                categoria=CategoriaApilamiento(sku.categoria_apilamiento_dominante),
                                max_altura_apilable_cm=sku.max_altura_apilable_cm,
                                descripcion=sku.descripcion,
                                es_picking=True
                            )
                            fragmentos.append(frag)
                            continue
                        
                        # CASO 2: Cantidad >= 1 (pallets completos + picking opcional)
                        pallets_completos = int(cantidad_pallets)
                        fraccion_picking = cantidad_pallets - pallets_completos
                        
                        # ✅ DETERMINAR altura para pallets completos
                        if altura_full > 0:
                            altura_full_usar = altura_full
                        elif altura_pick > 0:
                            # Si NO hay altura full pero SÍ hay picking, extrapolar
                            altura_full_usar = altura_pick / fraccion_picking if fraccion_picking > 0 else altura_pick
                            print(f"[WARN] SKU {sku.sku_id}: extrapolando altura full desde picking: {altura_full_usar:.1f}cm")
                        else:
                            altura_full_usar = 100.0
                            print(f"[WARN] SKU {sku.sku_id}: sin altura full, usando 100cm")
                        
                        # Pallets completos (full pallet)
                        for _ in range(pallets_completos):
                            frag = FragmentoSKU(
                                sku_id=sku.sku_id,
                                pedido_id=pedido.pedido,
                                fraccion=1.0,
                                altura_cm=altura_full_usar,
                                peso_kg=sku.peso_kg / cantidad_pallets,
                                volumen_m3=sku.volumen_m3 / cantidad_pallets,
                                categoria=CategoriaApilamiento(sku.categoria_apilamiento_dominante),
                                max_altura_apilable_cm=sku.max_altura_apilable_cm,
                                descripcion=sku.descripcion,
                                es_picking=False
                            )
                            fragmentos.append(frag)
                        
                        # PICKING: fracción sobrante
                        if fraccion_picking > 0.01:
                            # Usar altura_picking si existe, sino proporcional
                            if altura_pick > 0:
                                altura_picking = altura_pick
                            else:
                                altura_picking = altura_full_usar * fraccion_picking
                            
                            if altura_picking <= 0:
                                print(f"[WARN] SKU {sku.sku_id}: altura picking = 0, usando 50cm")
                                altura_picking = 50.0
                            
                            frag_picking = FragmentoSKU(
                                sku_id=sku.sku_id,
                                pedido_id=pedido.pedido,
                                fraccion=fraccion_picking,
                                altura_cm=altura_picking,
                                peso_kg=sku.peso_kg * fraccion_picking / cantidad_pallets,
                                volumen_m3=sku.volumen_m3 * fraccion_picking / cantidad_pallets,
                                categoria=CategoriaApilamiento(sku.categoria_apilamiento_dominante),
                                max_altura_apilable_cm=sku.max_altura_apilable_cm,
                                descripcion=sku.descripcion,
                                es_picking=True
                            )
                            fragmentos.append(frag_picking)
                    
                    except Exception as e:
                        # ✅ CAPTURAR errores por SKU individual
                        print(f"[ERROR] ❌ Error procesando SKU {sku.sku_id} del pedido {pedido.pedido}: {e}")
                        import traceback
                        traceback.print_exc()
                        # Continuar con siguiente SKU
                        continue
            
            else:
                # Pedido legacy (sin SKUs): crear fragmento único
                try:
                    frag = self._pedido_a_fragmento_legacy(pedido)
                    fragmentos.append(frag)
                except Exception as e:
                    continue
        
        # ✅ LOG FINAL
        if not fragmentos:
            print(f"[ERROR] ⚠️ NO se extrajeron fragmentos de {len(pedidos)} pedidos")
            for p in pedidos[:3]:
                print(f"  - Pedido {p.pedido}: tiene_skus={p.tiene_skus}, num_skus={len(p.skus) if p.tiene_skus else 0}")
        
        return fragmentos

    def _pedido_a_fragmento_legacy(self, pedido: Pedido) -> FragmentoSKU:
        """
        Convierte pedido legacy (sin SKUs) a fragmento único.
        Usa altura estimada y categoría dominante.
        """
        # Determinar categoría desde flags de pedido
        if pedido.no_apilable > 0:
            categoria = CategoriaApilamiento.NO_APILABLE
        elif pedido.base > 0:
            categoria = CategoriaApilamiento.BASE
        elif pedido.superior > 0:
            categoria = CategoriaApilamiento.SUPERIOR
        elif pedido.si_mismo > 0:
            categoria = CategoriaApilamiento.SI_MISMO
        else:
            categoria = CategoriaApilamiento.FLEXIBLE
        
        # Estimar altura desde pallets (150cm por pallet promedio)
        altura_estimada = pedido.pallets * 150
        
        return FragmentoSKU(
            sku_id=pedido.pedido,  # Usar ID de pedido como SKU
            pedido_id=pedido.pedido,
            fraccion=1.0,
            altura_cm=altura_estimada,
            peso_kg=pedido.peso,
            volumen_m3=pedido.volumen,
            categoria=categoria,
            max_altura_apilable_cm=None,
            descripcion=f"Pedido legacy {pedido.pedido}",
            es_picking=False
        )
    
    def _agrupar_por_categoria(
        self,
        fragmentos: List[FragmentoSKU]
    ) -> Dict[CategoriaApilamiento, List[FragmentoSKU]]:
        """Agrupa fragmentos por categoría de apilamiento"""
        grupos = defaultdict(list)
        
        for frag in fragmentos:
            grupos[frag.categoria].append(frag)
        
        return grupos
    
    def _estimar_posiciones_necesarias(
        self,
        grupos: Dict[CategoriaApilamiento, List[FragmentoSKU]]
    ) -> int:
        """
        Estima posiciones mínimas necesarias (heurística rápida).
        
        Heurística:
        - NO_APILABLE: 1 posición cada uno
        - BASE + SUPERIOR: se emparejan (1 posición por par válido)
        - SI_MISMO: se apilan hasta altura máxima
        - FLEXIBLE: se adapta a espacios
        
        Returns:
            Número estimado de posiciones necesarias
        """
        posiciones = 0
        
        # NO_APILABLE: cada uno va solo
        no_apilables = grupos.get(CategoriaApilamiento.NO_APILABLE, [])
        posiciones += len(no_apilables)
        
        # BASE + SUPERIOR: intentar emparejar
        bases = grupos.get(CategoriaApilamiento.BASE, [])
        superiores = grupos.get(CategoriaApilamiento.SUPERIOR, [])
        
        # Ordenar por altura para mejor emparejamiento
        bases_sorted = sorted(bases, key=lambda f: f.altura_cm, reverse=True)
        superiores_sorted = sorted(superiores, key=lambda f: f.altura_cm)
        
        pares_formados = 0
        for i in range(min(len(bases_sorted), len(superiores_sorted))):
            altura_par = bases_sorted[i].altura_cm + superiores_sorted[i].altura_cm
            if altura_par <= self.altura_maxima_cm:
                pares_formados += 1
            else:
                # No se pueden emparejar, cada uno va solo
                posiciones += 2
        
        posiciones += pares_formados
        sobrantes = abs(len(bases) - len(superiores))  # Los que sobraron
        
        # SI_MISMO: apilar verticalmente por SKU
        si_mismos = grupos.get(CategoriaApilamiento.SI_MISMO, [])
        
        # Agrupar por SKU
        por_sku = defaultdict(list)
        for frag in si_mismos:
            por_sku[frag.sku_id].append(frag)
        
        for sku_id, frags in por_sku.items():
            # Ordenar por altura (más grandes primero)
            frags_sorted = sorted(frags, key=lambda f: f.altura_cm, reverse=True)
            
            altura_acumulada = 0
            columnas = 0
            
            for frag in frags_sorted:
                if altura_acumulada + frag.altura_cm <= self.altura_maxima_cm:
                    altura_acumulada += frag.altura_cm
                else:
                    # Nueva columna
                    columnas += 1
                    altura_acumulada = frag.altura_cm
            
            if altura_acumulada > 0:
                columnas += 1
            
            posiciones += columnas
        
        # FLEXIBLE: estimación conservadora (1/2 por cada)
        flexibles = grupos.get(CategoriaApilamiento.FLEXIBLE, [])
        mix_sobrante_flexible = abs(sobrantes - len(flexibles))
        posiciones += mix_sobrante_flexible/2
        posiciones += abs(len(flexibles) - mix_sobrante_flexible)/2
        
        return posiciones
    
    def _construir_layout_con_debug(
        self, 
        camion: Camion, 
        fragmentos: List[FragmentoSKU]
    ) -> Tuple[Optional[LayoutCamion], Dict]:
        """
        Construye layout CON información de debug detallada.
        
        Returns:
            (layout, debug_info) donde debug_info contiene:
            - fragmentos_colocados: int
            - fragmentos_fallidos: List[Dict] con info de cada fallo
            - posiciones_usadas: int
            - layout_parcial: LayoutCamion con lo que se pudo colocar
            - historia_colocacion: List[Dict] con cada paso
        """

        layout = LayoutCamion(
            camion_id=camion.id,
            max_posiciones=camion.capacidad.max_positions,
            altura_maxima_cm=self.altura_maxima_cm
        )
        
        debug_info = {
            'fragmentos_colocados': 0,
            'fragmentos_fallidos': [],
            'posiciones_usadas': 0,
            'layout_parcial': layout,
            'historia_colocacion': []
        }
        
        # Ordenar fragmentos por prioridad
        fragmentos_ordenados = sorted(
            fragmentos,
            key=lambda f: self._prioridad_colocacion(f)
        )
        
        pallet_id_counter = 0
        
        for idx, frag in enumerate(fragmentos_ordenados):
            intento_info = {
                'fragmento': f"{frag.sku_id} (pedido {frag.pedido_id})",
                'altura_cm': frag.altura_cm,
                'categoria': frag.categoria.value,
                'es_picking': frag.es_picking,
                'exito': False,
                'ubicacion': None,
                'razon_fallo': None,
                'intentos': []
            }
            
            colocado = False
            
            # CASO 1: Intentar apilar en posición existente
            for pos_idx, posicion in enumerate(layout.posiciones):
                if posicion.esta_vacia:
                    continue
                
                # Intento 1a: Consolidar picking en pallet de pickings existente
                if frag.es_picking and posicion.pallets_apilados:
                    pallet_pickings = next(
                        (p for p in posicion.pallets_apilados if p.tiene_pickings and not p.tiene_full_pallets),
                        None
                    )
                    
                    if pallet_pickings and self._puede_agregar_a_pallet(pallet_pickings, frag):
                        intento_info['intentos'].append({
                            'tipo': 'consolidar_en_pallet',
                            'posicion': pos_idx,
                            'pallet': pallet_pickings.id,
                            'resultado': 'intentando'
                        })
                        
                        pallet_pickings.agregar_fragmento(frag)

                        if self.max_altura_picking_apilado_cm:
                            altura_picking_posicion = self._calcular_altura_picking_posicion(posicion)
                            if altura_picking_posicion > self.max_altura_picking_apilado_cm:
                                pallet_pickings.fragmentos.remove(frag)
                                intento_info['intentos'][-1]['resultado'] = 'excede_altura_picking'
                                continue
                        
                        if posicion.altura_usada_cm > self.altura_maxima_cm:
                            pallet_pickings.fragmentos.remove(frag)
                            intento_info['intentos'][-1]['resultado'] = 'excede_altura_camion'
                            continue
                        
                        colocado = True
                        intento_info['exito'] = True
                        intento_info['ubicacion'] = f"posicion_{pos_idx}_consolidado"
                        intento_info['intentos'][-1]['resultado'] = 'exito'
                        break
                
                # Intento 1a-bis: Crear pallet de pickings sobre full pallet existente
                if not colocado and frag.es_picking and len(posicion.pallets_apilados) > 1:
                    pallet_inferior = posicion.pallets_apilados[0]
                    
                    # No apilar sobre NO_APILABLE
                    cat_inferior = next(
                        (f.categoria for f in pallet_inferior.fragmentos),
                        None
                    )
                    if cat_inferior == CategoriaApilamiento.NO_APILABLE:
                        continue
                    
                    # Verificar altura antes de crear
                    if posicion.altura_usada_cm + frag.altura_cm > self.altura_maxima_cm:
                        continue
                    
                    # Crear pallet de pickings en nivel 1
                    pallet_nuevo = PalletFisico(
                        id=f"pallet_{pallet_id_counter}",
                        posicion_id=posicion.id,
                        nivel=1
                    )
                    pallet_nuevo.agregar_fragmento(frag)
                    
                    posicion.pallets_apilados.append(pallet_nuevo)
                    
                    # Validar altura picking
                    if self.max_altura_picking_apilado_cm:
                        altura_picking = self._calcular_altura_picking_posicion(posicion)
                        if altura_picking > self.max_altura_picking_apilado_cm:
                            posicion.pallets_apilados.remove(pallet_nuevo)
                            continue
                    
                    pallet_id_counter += 1
                    colocado = True
                    intento_info['exito'] = True
                    intento_info['ubicacion'] = f"posicion_{pos_idx}_picking_sobre_full"
                    break

                # Intento 1b: Nuevo nivel en posición existente
                if not colocado and len(posicion.pallets_apilados) < 2:
                    pallet_nuevo = PalletFisico(
                        id=f"pallet_{pallet_id_counter}",
                        posicion_id=posicion.id,
                        nivel=len(posicion.pallets_apilados)
                    )
                    pallet_nuevo.agregar_fragmento(frag)
                    
                    puede_apilar, razon = posicion.puede_apilar(pallet_nuevo, max_niveles=camion.capacidad.levels)
                    
                    intento_info['intentos'].append({
                        'tipo': 'nuevo_nivel',
                        'posicion': pos_idx,
                        'nivel': len(posicion.pallets_apilados),
                        'puede_apilar': puede_apilar,
                        'razon': razon
                    })
                    
                    if posicion.apilar(pallet_nuevo, max_niveles=camion.capacidad.levels):
                        # Validar altura máxima de picking apilado
                        picking_valido, altura_picking = self._validar_altura_picking_posicion(posicion)
                        if not picking_valido:
                            # Rollback: remover el pallet apilado
                            posicion.pallets_apilados.remove(pallet_nuevo)
                            intento_info['intentos'][-1]['resultado'] = 'excede_altura_picking'
                            intento_info['intentos'][-1]['altura_picking'] = altura_picking
                            intento_info['intentos'][-1]['max_permitido'] = self.max_altura_picking_apilado_cm
                            continue
                        
                        pallet_id_counter += 1
                        colocado = True
                        intento_info['exito'] = True
                        intento_info['ubicacion'] = f"posicion_{pos_idx}_nivel_{pallet_nuevo.nivel}"
                        intento_info['intentos'][-1]['resultado'] = 'exito'
                        break
            
            if colocado:
                debug_info['fragmentos_colocados'] += 1
                debug_info['historia_colocacion'].append(intento_info)
                continue
            
            # CASO 2: Buscar posición vacía
            posicion_vacia = next(
                (p for p in layout.posiciones if p.esta_vacia),
                None
            )
            
            if posicion_vacia is None:
                intento_info['razon_fallo'] = 'sin_posiciones_disponibles'
                intento_info['intentos'].append({
                    'tipo': 'buscar_posicion_vacia',
                    'resultado': 'no_hay_posiciones'
                })
                debug_info['fragmentos_fallidos'].append(intento_info)
                continue
            
            # Colocar en posición vacía
            pallet = PalletFisico(
                id=f"pallet_{pallet_id_counter}",
                posicion_id=posicion_vacia.id,
                nivel=0
            )
            pallet.agregar_fragmento(frag)
            
            intento_info['intentos'].append({
                'tipo': 'posicion_vacia',
                'posicion': posicion_vacia.id
            })
            
            if not posicion_vacia.apilar(pallet, camion.capacidad.levels):
                intento_info['razon_fallo'] = 'no_puede_apilar_en_vacia'
                intento_info['intentos'][-1]['resultado'] = 'fallo'
                debug_info['fragmentos_fallidos'].append(intento_info)
                continue
            
            # Validar altura máxima de picking apilado (aunque sea posición vacía, el fragmento puede ser picking)
            picking_valido, altura_picking = self._validar_altura_picking_posicion(posicion_vacia)
            if not picking_valido:
                # Rollback
                posicion_vacia.pallets_apilados.remove(pallet)
                intento_info['razon_fallo'] = 'excede_altura_picking'
                intento_info['intentos'][-1]['resultado'] = 'excede_altura_picking'
                intento_info['intentos'][-1]['altura_picking'] = altura_picking
                debug_info['fragmentos_fallidos'].append(intento_info)
                continue
            
            pallet_id_counter += 1
            colocado = True
            intento_info['exito'] = True
            intento_info['ubicacion'] = f"posicion_{posicion_vacia.id}_nivel_0"
            intento_info['intentos'][-1]['resultado'] = 'exito'
            debug_info['fragmentos_colocados'] += 1
            debug_info['historia_colocacion'].append(intento_info)
        
        debug_info['posiciones_usadas'] = layout.posiciones_usadas
        
        return layout, debug_info

    # Verificar si se puede agregar fragmento
    def _puede_agregar_a_pallet(
        self,
        pallet: PalletFisico,
        fragmento: FragmentoSKU
    ) -> bool:
        """
        Verifica si un fragmento puede agregarse a un pallet físico.
        
        Reglas:
        - Si NO permite consolidación:
          - Solo 1 SKU por pallet físico
          - Pickings NO pueden consolidarse con nada
        - Si SÍ permite consolidación:
          - Máximo N SKUs diferentes por pallet
          - Solo pickings del mismo tipo de apilamiento
        """
        # Si pallet vacío, siempre se puede agregar
        if not pallet.fragmentos:
            return True
        
        # NO PERMITE CONSOLIDACIÓN 
        if not self.permite_consolidacion:
            # Regla 1: Solo 1 SKU por pallet
            if fragmento.sku_id not in pallet.skus_unicos:
                return False  # Ya hay otro SKU
            
            # Regla 2: Si es picking, NO puede consolidarse con NADA
            # (cada picking va en su propio pallet físico)
            if fragmento.es_picking:
                return False
            
            # Regla 3: Si el pallet ya tiene pickings, no agregar más
            if pallet.tiene_pickings:
                return False
            
            return True
        
        # ✅ SÍ PERMITE CONSOLIDACIÓN
        else:
            # Regla 1: No exceder límite de fragmentos diferentes
            if len(pallet.fragmentos) >= self.max_skus_por_pallet:
                return False  # Ya alcanzó el máximo
            
            # Caso para límite por skus y no por fragmento
            #skus_en_pallet = pallet.skus_unicos
            #if fragmento.sku_id not in skus_en_pallet:
            #    if len(skus_en_pallet) >= self.max_skus_por_pallet:
            #        return False  # Ya alcanzó el máximo

            # Regla 3: No mezclar pickings con full pallets
            if fragmento.es_picking and pallet.tiene_full_pallets:
                return False
            if not fragmento.es_picking and pallet.tiene_pickings:
                return False
            
            return True

    def _validar_altura_picking_posicion(self, posicion: PosicionCamion) -> tuple[bool, float]:
        """
        Valida que si hay picking en una posición, la altura TOTAL no exceda el límite.
        
        La restricción es: si hay cualquier picking en la posición, 
        la altura total (pallets completos + picking) no puede exceder max_altura_picking_apilado_cm.
        
        Returns:
            (es_valido, altura_total_posicion)
        """
        if not self.max_altura_picking_apilado_cm:
            return True, 0.0
        
        # Verificar si hay algún picking en la posición
        tiene_picking = False
        for pallet in posicion.pallets_apilados:
            for frag in pallet.fragmentos:
                if frag.es_picking:
                    tiene_picking = True
                    break
            if tiene_picking:
                break
        
        # Si no hay picking, no aplica la restricción
        if not tiene_picking:
            return True, 0.0
        
        # Si hay picking, la altura TOTAL de la posición debe ser <= límite
        altura_total = posicion.altura_usada_cm
        
        return altura_total <= self.max_altura_picking_apilado_cm, altura_total


    def _prioridad_colocacion(self, frag: FragmentoSKU) -> int:
        """
        Determina prioridad de colocación (menor = primero).
        
        Orden de prioridad:
        1. NO_APILABLE (más restrictivos)
        2. BASE (necesitan ir al fondo)
        3. SI_MISMO (se benefician de apilamiento temprano)
        4. SUPERIOR
        5. FLEXIBLE
        """
        prioridades = {
            CategoriaApilamiento.NO_APILABLE: 0,
            CategoriaApilamiento.BASE: 1,
            CategoriaApilamiento.SI_MISMO: 2,
            CategoriaApilamiento.SUPERIOR: 3,
            CategoriaApilamiento.FLEXIBLE: 4,
        }
        return prioridades[frag.categoria]

    def _calcular_altura_picking_posicion(self, posicion: PosicionCamion) -> float:
        """
        Calcula la altura total de pickings apilados en una posición.
        Solo cuenta fragmentos marcados como es_picking=True.
        """
        altura_picking = 0.0
        for pallet in posicion.pallets_apilados:
            for frag in pallet.fragmentos:
                if frag.es_picking:
                    altura_picking += frag.altura_cm
        return altura_picking
    

    def _reportar_fallas_detallado(
        self,
        camion: Camion,
        debug_info: Dict,
        fragmentos_originales: List[FragmentoSKU],
        errores_adicionales: List[str] = None
    ):
        """
        Genera reporte detallado de por qué falló la validación.
        """

        if not DEBUG_VALIDATION:
            return
    
        print(f"\n{'='*80}")
        print(f"REPORTE DE VALIDACIÓN FALLIDA - Camión {camion.id}")
        print(f"{'='*80}")
        
        # ✅ MANEJAR caso donde debug_info puede estar incompleto
        total = debug_info.get('fragmentos_totales', 0)
        colocados = debug_info.get('fragmentos_colocados', 0)
        fallidos_list = debug_info.get('fragmentos_fallidos', [])
        fallidos = len(fallidos_list)
        
        # Si no hay fragmentos, es porque hubo error antes
        if total == 0:
            print(f"\n⚠️  ERROR TEMPRANO EN VALIDACIÓN")
            print(f"   No se pudieron extraer fragmentos de los pedidos")
            print(f"   Pedidos en camión: {len(camion.pedidos)}")
            
            # Mostrar errores adicionales
            if errores_adicionales:
                print(f"\n❌ ERRORES DETECTADOS:")
                for error in errores_adicionales:
                    print(f"   • {error}")
            
            # Analizar pedidos
            print(f"\n📦 PEDIDOS EN EL CAMIÓN:")
            for i, pedido in enumerate(camion.pedidos[:5], 1):
                tiene_skus = pedido.tiene_skus
                num_skus = len(pedido.skus) if tiene_skus else 0
                print(f"   {i}. Pedido {pedido.pedido}: SKUs={num_skus}, Pallets={pedido.pallets:.2f}")
                
                if tiene_skus and num_skus > 0:
                    for sku in pedido.skus[:3]:
                        print(f"      - SKU {sku.sku_id}: {sku.cantidad_pallets:.2f} pallets, "
                            f"h_full={sku.altura_full_pallet_cm:.1f}cm, "
                            f"h_pick={sku.altura_picking_cm if sku.altura_picking_cm else 'N/A'}")
            
            if len(camion.pedidos) > 5:
                print(f"   ... y {len(camion.pedidos) - 5} pedidos más")
            
            print(f"\n{'='*80}\n")

            return
        
        # Resumen general
        print(f"\n📊 RESUMEN:")
        print(f"   Total fragmentos: {total}")
        print(f"   ✅ Colocados: {colocados} ({colocados/total*100:.1f}%)")
        print(f"   ❌ Fallidos: {fallidos} ({fallidos/total*100:.1f}%)")
        print(f"   Posiciones usadas: {debug_info.get('posiciones_usadas', 0)}/{camion.capacidad.max_positions}")
        
        # Mostrar errores adicionales si hay
        if errores_adicionales:
            print(f"\n❌ ERRORES DETECTADOS:")
            for error in errores_adicionales:
                print(f"   • {error}")
        
        # Estado del layout parcial
        layout = debug_info.get('layout_parcial')
        if layout:
            print(f"\n📦 ESTADO DEL LAYOUT PARCIAL:")
            print(f"   Altura máxima usada: {layout.altura_maxima_usada:.1f}cm / {layout.altura_maxima_cm:.1f}cm")
            print(f"   Altura promedio: {layout.altura_promedio_usada:.1f}cm")
            print(f"   Aprovechamiento altura: {layout.aprovechamiento_altura*100:.1f}%")
            print(f"   Aprovechamiento posiciones: {layout.aprovechamiento_posiciones*100:.1f}%")
        
        # Solo mostrar análisis detallado si hay fragmentos fallidos
        if not fallidos_list:
            print(f"\n✅ No hay fragmentos fallidos específicos")
            print(f"   (El fallo puede ser por restricciones globales)")
            print(f"\n{'='*80}\n")
            return
        
        # Análisis de fragmentos fallidos
        print(f"\n❌ FRAGMENTOS QUE NO SE PUDIERON COLOCAR:")
        print(f"{'─'*80}")
        
        # Agrupar por razón de fallo
        por_razon = {}
        for frag_info in fallidos_list:
            razon = frag_info.get('razon_fallo', 'desconocida')
            por_razon.setdefault(razon, []).append(frag_info)
        
        for razon, frags in por_razon.items():
            print(f"\n🔴 Razón: {razon.upper().replace('_', ' ')} ({len(frags)} fragmentos)")
            print(f"")
            
            # Mostrar TODOS los fragmentos fallidos (no solo los primeros 5)
            for i, frag_info in enumerate(frags, 1):
                # Extraer SKU del string "SKU_ID (pedido PEDIDO_ID)"
                fragmento_str = frag_info['fragmento']
                sku_id = fragmento_str.split(' ')[0] if ' ' in fragmento_str else fragmento_str
                pedido_id = fragmento_str.split('pedido ')[-1].rstrip(')') if 'pedido' in fragmento_str else '?'
                
                print(f"   [{i}] SKU: {sku_id} | Pedido: {pedido_id}")
                print(f"       Altura: {frag_info['altura_cm']:.1f}cm | "
                    f"Categoría: {frag_info['categoria'].upper()} | "
                    f"Picking: {'Sí' if frag_info['es_picking'] else 'No'}")
                
                # Mostrar intentos solo si hay información útil
                if frag_info.get('intentos'):
                    intentos_con_razon = [i for i in frag_info['intentos'] if i.get('razon')]
                    if intentos_con_razon:
                        print(f"       Intentos con error:")
                        for intento in intentos_con_razon[:2]:  # Mostrar max 2 intentos con razón
                            print(f"         • {intento['tipo']}: {intento.get('razon', 'N/A')}")
                
                print(f"")  # Línea en blanco entre fragmentos
        
        # Análisis de pedidos afectados
        pedidos_afectados = set()
        for frag_info in fallidos_list:
            frag_str = frag_info.get('fragmento', '')
            if 'pedido' in frag_str:
                try:
                    pedido_id = frag_str.split('pedido ')[-1].rstrip(')')
                    pedidos_afectados.add(pedido_id)
                except:
                    pass
        
        if pedidos_afectados:
            print(f"\n📦 PEDIDOS AFECTADOS ({len(pedidos_afectados)} pedidos):")
            for pedido_id in sorted(list(pedidos_afectados)[:10]):
                frags_pedido = [
                    f for f in fallidos_list
                    if pedido_id in f.get('fragmento', '')
                ]
                print(f"   • Pedido {pedido_id}: {len(frags_pedido)} fragmentos no colocados")
            
            if len(pedidos_afectados) > 10:
                print(f"   ... y {len(pedidos_afectados) - 10} pedidos más")
        
        # Recomendaciones
        print(f"\n💡 RECOMENDACIONES:")
        
        if 'sin_posiciones_disponibles' in por_razon:
            print("   • Camión lleno - considerar agregar otro camión para estos pedidos")
        
        if any('excede_altura' in str(f.get('intentos', [])) for f in fallidos_list):
            print("   • Algunas combinaciones exceden altura - revisar apilabilidad de SKUs")
        
        # Buscar patrones
        categorias_problematicas = {}
        for frag_info in fallidos_list:
            cat = frag_info.get('categoria', 'desconocida')
            categorias_problematicas[cat] = categorias_problematicas.get(cat, 0) + 1
        
        if categorias_problematicas:
            print(f"   • Categorías problemáticas:")
            for cat, count in sorted(categorias_problematicas.items(), key=lambda x: -x[1]):
                print(f"     - {cat}: {count} fragmentos")
        
        print(f"\n{'='*80}\n")

    def _categoria_dominante_pallet(self, pallet: PalletFisico) -> CategoriaApilamiento:
        """Obtiene categoría dominante de un pallet."""
        categorias = [f.categoria for f in pallet.fragmentos]
        
        if CategoriaApilamiento.NO_APILABLE in categorias:
            return CategoriaApilamiento.NO_APILABLE
        if CategoriaApilamiento.BASE in categorias:
            return CategoriaApilamiento.BASE
        if CategoriaApilamiento.SUPERIOR in categorias:
            return CategoriaApilamiento.SUPERIOR
        if CategoriaApilamiento.SI_MISMO in categorias:
            return CategoriaApilamiento.SI_MISMO
        return CategoriaApilamiento.FLEXIBLE
