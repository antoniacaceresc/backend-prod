# optimization/validation/height_validator.py
"""
Validador de altura con performance optimizado.
Complejidad: O(n×m) donde n = pedidos, m = posiciones
Overhead estimado: 10-50ms por camión
"""

from __future__ import annotations
from typing import List, Tuple, Optional, Dict
from collections import defaultdict

from models.domain import Camion, Pedido, TruckCapacity
from models.stacking import (
    LayoutCamion,
    PosicionCamion,
    PalletFisico,
    FragmentoSKU,
    CategoriaApilamiento
)


class HeightValidator:
    """
    Valida altura de apilamiento en camiones.
    Optimizado para bajo overhead (<50ms por camión).
    """
    
    def __init__(
        self,
        altura_maxima_cm: float = 270,
        permite_consolidacion: bool = False,
        max_skus_por_pallet: int = 3
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
    
    def validar_camion_rapido(
    self,
    camion: Camion
    ) -> Tuple[bool, List[str], Optional[LayoutCamion]]:
        """Validación RÁPIDA de altura..."""
        
        errores = []
        
        # 1. Extraer fragmentos
        fragmentos = self._extraer_fragmentos_batch(camion.pedidos)
        
        if not fragmentos:
            print("NO hay fragmentosssss")
            return True, [], None
        
        # 2. Validación rápida
        for frag in fragmentos:
            if frag.altura_cm > self.altura_maxima_cm:
                errores.append(f"SKU {frag.sku_id} del pedido {frag.pedido_id} excede altura: " 
                               f"{frag.altura_cm:.1f}cm > {self.altura_maxima_cm:.1f}cm")
        
        if errores:
            print(f"[VALIDATOR]    ❌ Fragmentos exceden altura")
            return False, errores, None
        
        # 3. Agrupar por categoría
        grupos = self._agrupar_por_categoria(fragmentos)
        
        # 4. Estimar posiciones
        posiciones_necesarias = self._estimar_posiciones_necesarias(grupos)
        
        # ✅ AGREGAR LOG
        print(f"[VALIDATOR]    Posiciones estimadas: {posiciones_necesarias}")
        print(f"[VALIDATOR]    Posiciones disponibles: {camion.capacidad.max_positions}")
        """
        if posiciones_necesarias > camion.capacidad.max_positions:
            errores.append(f"Posiciones necesarias exceden capacidad")
            print(f"[VALIDATOR]    ❌ Excede posiciones")
            return False, errores, None
        """
        # 5. Construir layout
        layout = self._construir_layout(camion, fragmentos)
        
        if layout is None:
            errores.append(f"Layout is none")
            print(f"[VALIDATOR]    ❌ No se pudo construir layout")
            return False, errores, None
        
        print(f"[VALIDATOR]    ✅ Layout construido: {layout.posiciones_usadas} posiciones usadas")
        
        return True, [], layout

    def _extraer_fragmentos_batch(
    self,
    pedidos: List[Pedido]
    ) -> List[FragmentoSKU]:
        """
        Extrae fragmentos de todos los pedidos.
        
        """
        fragmentos = []
        
        for pedido in pedidos:
            if pedido.tiene_skus:
                # Pedido con SKUs detallados
                for sku in pedido.skus:
                    cantidad_pallets = sku.cantidad_pallets
                    
                    # CASO 1: Cantidad < 1 (solo picking)
                    if cantidad_pallets < 1.0:
                        # Es un picking parcial
                        
                        #  Usar altura_picking directamente si existe
                        if sku.altura_picking_cm is not None and sku.altura_picking_cm > 0:
                            altura_cm = sku.altura_picking_cm
                        else:
                            # Fallback: calcular proporcionalmente
                            altura_cm = sku.altura_full_pallet_cm * cantidad_pallets
                        
                        if altura_cm <= 0:
                            print(f"[WARN] SKU {sku.sku_id}: altura calculada = 0, usando 1cm mínimo")
                            altura_cm = 1.0
                        
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
                    
                    # CASO 2: Cantidad >= 1 (pallets completos + picking)
                    pallets_completos = int(cantidad_pallets)
                    fraccion_picking = cantidad_pallets - pallets_completos
                    
                    # Pallets completos (full pallet)
                    for _ in range(pallets_completos):
                        altura_cm = sku.altura_full_pallet_cm
                        
                        if altura_cm <= 0:
                            print(f"[WARN] SKU {sku.sku_id}: altura full pallet = 0, usando 1cm")
                            altura_cm = 1.0
                        
                        frag = FragmentoSKU(
                            sku_id=sku.sku_id,
                            pedido_id=pedido.pedido,
                            fraccion=1.0,
                            altura_cm=altura_cm,
                            peso_kg=sku.peso_kg / cantidad_pallets,
                            volumen_m3=sku.volumen_m3 / cantidad_pallets,
                            categoria=CategoriaApilamiento(sku.categoria_apilamiento_dominante),
                            max_altura_apilable_cm=sku.max_altura_apilable_cm,
                            descripcion=sku.descripcion,
                            es_picking=False
                        )
                        fragmentos.append(frag)
                    
                    # PICKING: Usar altura_picking directamente
                    if fraccion_picking > 0.01:
                        # CORRECCIÓN: Usar altura_picking directamente si existe
                        if sku.altura_picking_cm is not None and sku.altura_picking_cm > 0:
                            altura_picking = sku.altura_picking_cm
                        else:
                            # Fallback: calcular proporcionalmente
                            altura_picking = sku.altura_full_pallet_cm * fraccion_picking
                        
                        if altura_picking <= 0:
                            print(f"[WARN] SKU {sku.sku_id}: altura picking = 0, usando 1cm")
                            altura_picking = 1.0
                        
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
            
            else:
                # Pedido legacy (sin SKUs): crear fragmento único
                frag = self._pedido_a_fragmento_legacy(pedido)
                fragmentos.append(frag)
        
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
        posiciones += abs(len(bases) - len(superiores))  # Los que sobraron
        
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
        
        # FLEXIBLE: estimación conservadora (1 por cada)
        flexibles = grupos.get(CategoriaApilamiento.FLEXIBLE, [])
        posiciones += len(flexibles)
        
        return posiciones
    
    def _construir_layout(self, camion: Camion, fragmentos: List[FragmentoSKU]) -> Optional[LayoutCamion]:
        """Construye layout real usando algoritmo greedy."""
        
        layout = LayoutCamion(
            camion_id=camion.id,
            max_posiciones=camion.capacidad.max_positions,
            altura_maxima_cm=self.altura_maxima_cm
        )
        
        # Ordenar fragmentos por prioridad
        fragmentos_ordenados = sorted(
            fragmentos,
            key=lambda f: self._prioridad_colocacion(f)
        )
        
        pallet_id_counter = 0
        
        for frag in fragmentos_ordenados:
            colocado = False
            
            # CASO 1: Intentar apilar en posición existente
            for posicion in layout.posiciones:
                if posicion.esta_vacia:
                    continue

                # SOLO consolidar pickings, NO pallets completos
                if frag.es_picking and posicion.pallets_apilados:
                    pallet_superior = posicion.pallets_apilados[-1]
                    
                    # Verificar si se puede agregar a este pallet (solo para pickings)
                    if self._puede_agregar_a_pallet(pallet_superior, frag):
                        # Intentar agregar al pallet existente
                        pallet_superior.agregar_fragmento(frag)
                        
                        # Verificar que no exceda altura
                        if posicion.altura_usada_cm <= self.altura_maxima_cm:
                            colocado = True
                            break
                        else:
                            # Rollback: quitar el fragmento
                            pallet_superior.fragmentos.remove(frag)
                
                
                # Si no se pudo agregar al pallet existente,
                # intentar crear nuevo nivel en esta posición
                if not colocado and len(posicion.pallets_apilados) < 2:  # Máximo 2 niveles
                    pallet_nuevo = PalletFisico(
                        id=f"pallet_{pallet_id_counter}",
                        posicion_id=posicion.id,
                        nivel=len(posicion.pallets_apilados)
                    )
                    pallet_nuevo.agregar_fragmento(frag)
                    
                    if posicion.apilar(pallet_nuevo):
                        pallet_id_counter += 1
                        colocado = True
                        break
            
            if colocado:
                continue
            
            # CASO 2: Buscar posición vacía
            posicion_vacia = next(
                (p for p in layout.posiciones if p.esta_vacia),
                None
            )
            
            if posicion_vacia is None:
                # No hay más posiciones disponibles
                return None
            
            # Colocar en posición vacía
            pallet = PalletFisico(
                id=f"pallet_{pallet_id_counter}",
                posicion_id=posicion_vacia.id,
                nivel=0
            )
            pallet.agregar_fragmento(frag)
            
            if not posicion_vacia.apilar(pallet):
                return None
            
            pallet_id_counter += 1
        
        return layout
    
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
            # Regla 1: No exceder límite de SKUs diferentes
            skus_en_pallet = pallet.skus_unicos
            if fragmento.sku_id not in skus_en_pallet:
                if len(skus_en_pallet) >= self.max_skus_por_pallet:
                    return False  # Ya alcanzó el máximo
            
            # Regla 2: Solo pickings del mismo tipo pueden consolidarse
            if fragmento.es_picking and pallet.tiene_pickings:
                # Verificar que sean del mismo tipo de apilamiento
                tipos_en_pallet = {frag.categoria for frag in pallet.fragmentos}
                if fragmento.categoria not in tipos_en_pallet:
                    return False  # Diferentes tipos de apilamiento
            
            # Regla 3: No mezclar pickings con full pallets
            if fragmento.es_picking and pallet.tiene_full_pallets:
                return False
            if not fragmento.es_picking and pallet.tiene_pickings:
                return False
            
            return True


    def _prioridad_colocacion(self, frag: FragmentoSKU) -> int:
        """
        Determina prioridad de colocación (menor = primero).
        
        Orden de prioridad:
        1. NO_APILABLE (más restrictivos)
        2. BASE (necesitan ir al fondo)
        3. SI_MISMO (se benefician de apilamiento temprano)
        4. FLEXIBLE
        5. SUPERIOR (van al final, encima de otros)
        """
        prioridades = {
            CategoriaApilamiento.NO_APILABLE: 0,
            CategoriaApilamiento.BASE: 1,
            CategoriaApilamiento.SI_MISMO: 2,
            CategoriaApilamiento.FLEXIBLE: 3,
            CategoriaApilamiento.SUPERIOR: 4,
        }
        return prioridades[frag.categoria]
    