# tests/test_height_validator.py
"""Tests para el validador de altura"""

import pytest
from models.domain import Camion, Pedido, TruckCapacity, SKU
from models.enums import TipoRuta, TipoCamion
from optimization.validation.height_validator import HeightValidator


class TestHeightValidatorBasico:
    """Tests básicos del validador"""
    
    def test_camion_vacio_es_valido(self):
        """Camión vacío siempre es válido"""
        capacidad = TruckCapacity(
            cap_weight=23000,
            cap_volume=70000,
            max_positions=30,
            max_pallets=60,
            altura_cm=270
        )
        
        camion = Camion(
            id="test",
            tipo_ruta=TipoRuta.NORMAL,
            tipo_camion=TipoCamion.NORMAL,
            cd=["CD1"],
            ce=["0088"],
            grupo="test",
            capacidad=capacidad,
            pedidos=[]
        )
        
        validator = HeightValidator(
            altura_maxima_cm=capacidad.altura_cm,
            permite_consolidacion=False
        )
        
        valido, errores, layout = validator.validar_camion_rapido(camion)
        
        assert valido is True
        assert len(errores) == 0
        assert layout is None  # No hay layout si está vacío
    
    def test_pedido_simple_con_skus(self):
        """Pedido con SKUs que caben correctamente"""
        capacidad = TruckCapacity(
            cap_weight=23000,
            cap_volume=70000,
            max_positions=30,
            max_pallets=60,
            altura_cm=270
        )
        
        # Crear SKU
        sku = SKU(
            sku_id="SKU001",
            pedido_id="PED001",
            cantidad_pallets=2.0,
            altura_full_pallet_cm=120.0,
            peso_kg=1000.0,
            volumen_m3=3.0,
            base=2.0  # Ambos pallets son BASE
        )
        
        # Crear pedido con SKU
        pedido = Pedido(
            pedido="PED001",
            cd="CD1",
            ce="0088",
            po="PO001",
            peso=1000.0,
            volumen=3.0,
            pallets=2.0,
            valor=50000,
            base=2.0,
            skus=[sku]
        )
        
        camion = Camion(
            id="test",
            tipo_ruta=TipoRuta.NORMAL,
            tipo_camion=TipoCamion.NORMAL,
            cd=["CD1"],
            ce=["0088"],
            grupo="test",
            capacidad=capacidad,
            pedidos=[pedido]
        )
        
        validator = HeightValidator(
            altura_maxima_cm=capacidad.altura_cm,
            permite_consolidacion=False
        )
        
        valido, errores, layout = validator.validar_camion_rapido(camion)
        
        assert valido is True
        assert len(errores) == 0
        assert layout is not None
        assert layout.posiciones_usadas == 2  # 2 pallets en 2 posiciones


class TestHeightValidatorApilabilidad:
    """Tests de reglas de apilabilidad"""
    
    def test_base_superior_se_apilan(self):
        """BASE + SUPERIOR deben apilarse en 1 posición"""
        capacidad = TruckCapacity(
            cap_weight=23000,
            cap_volume=70000,
            max_positions=30,
            max_pallets=60,
            altura_cm=270
        )
        
        # SKU BASE
        sku_base = SKU(
            sku_id="SKU_BASE",
            pedido_id="PED001",
            cantidad_pallets=1.0,
            altura_full_pallet_cm=150.0,
            peso_kg=500.0,
            volumen_m3=1.5,
            base=1.0
        )
        
        # SKU SUPERIOR
        sku_superior = SKU(
            sku_id="SKU_SUP",
            pedido_id="PED001",
            cantidad_pallets=1.0,
            altura_full_pallet_cm=100.0,
            peso_kg=300.0,
            volumen_m3=1.0,
            superior=1.0
        )
        
        pedido = Pedido(
            pedido="PED001",
            cd="CD1",
            ce="0088",
            po="PO001",
            peso=800.0,
            volumen=2.5,
            pallets=2.0,
            valor=50000,
            base=1.0,
            superior=1.0,
            skus=[sku_base, sku_superior]
        )
        
        camion = Camion(
            id="test",
            tipo_ruta=TipoRuta.NORMAL,
            tipo_camion=TipoCamion.NORMAL,
            cd=["CD1"],
            ce=["0088"],
            grupo="test",
            capacidad=capacidad,
            pedidos=[pedido]
        )
        
        validator = HeightValidator(
            altura_maxima_cm=capacidad.altura_cm,
            permite_consolidacion=False
        )
        
        valido, errores, layout = validator.validar_camion_rapido(camion)
        
        assert valido is True
        assert layout.posiciones_usadas == 1  # Se apilaron en 1 posición
        assert layout.posiciones[0].num_pallets == 2  # 2 pallets apilados
        assert layout.posiciones[0].altura_usada_cm == 250  # 150 + 100
    
    def test_no_apilable_va_solo(self):
        """NO_APILABLE debe ocupar posición completa solo"""
        capacidad = TruckCapacity(
            cap_weight=23000,
            cap_volume=70000,
            max_positions=30,
            max_pallets=60,
            altura_cm=270
        )
        
        sku = SKU(
            sku_id="SKU_NOAP",
            pedido_id="PED001",
            cantidad_pallets=2.0,
            altura_full_pallet_cm=200.0,
            peso_kg=1000.0,
            volumen_m3=3.0,
            no_apilable=2.0
        )
        
        pedido = Pedido(
            pedido="PED001",
            cd="CD1",
            ce="0088",
            po="PO001",
            peso=1000.0,
            volumen=3.0,
            pallets=2.0,
            valor=50000,
            no_apilable=2.0,
            skus=[sku]
        )
        
        camion = Camion(
            id="test",
            tipo_ruta=TipoRuta.NORMAL,
            tipo_camion=TipoCamion.NORMAL,
            cd=["CD1"],
            ce=["0088"],
            grupo="test",
            capacidad=capacidad,
            pedidos=[pedido]
        )
        
        validator = HeightValidator(
            altura_maxima_cm=capacidad.altura_cm,
            permite_consolidacion=False
        )
        
        valido, errores, layout = validator.validar_camion_rapido(camion)
        
        assert valido is True
        assert layout.posiciones_usadas == 2  # 2 posiciones separadas
        # Cada posición tiene 1 solo pallet (NO_APILABLE no acepta nada encima)
    
    def test_excede_altura_maxima(self):
        """SKU que excede altura máxima debe fallar"""
        capacidad = TruckCapacity(
            cap_weight=23000,
            cap_volume=70000,
            max_positions=30,
            max_pallets=60,
            altura_cm=270
        )
        
        sku = SKU(
            sku_id="SKU_ALTO",
            pedido_id="PED001",
            cantidad_pallets=1.0,
            altura_full_pallet_cm=300.0,  # Excede 270cm
            peso_kg=500.0,
            volumen_m3=1.5,
            base=1.0
        )
        
        pedido = Pedido(
            pedido="PED001",
            cd="CD1",
            ce="0088",
            po="PO001",
            peso=500.0,
            volumen=1.5,
            pallets=1.0,
            valor=50000,
            base=1.0,
            skus=[sku]
        )
        
        camion = Camion(
            id="test",
            tipo_ruta=TipoRuta.NORMAL,
            tipo_camion=TipoCamion.NORMAL,
            cd=["CD1"],
            ce=["0088"],
            grupo="test",
            capacidad=capacidad,
            pedidos=[pedido]
        )
        
        validator = HeightValidator(
            altura_maxima_cm=capacidad.altura_cm,
            permite_consolidacion=False
        )
        
        valido, errores, layout = validator.validar_camion_rapido(camion)
        
        assert valido is False
        assert len(errores) > 0
        assert "excede altura" in errores[0].lower()
        assert layout is None
    
    def test_sku_con_picking_y_full_pallet(self):
        """
        Test caso real: 4.3 pallets
        - 4 pallets completos de 150cm cada uno
        - 1 picking de 45cm (0.3 pallets)
        """
        capacidad = TruckCapacity(
            cap_weight=23000,
            cap_volume=70000,
            max_positions=30,
            max_pallets=60,
            altura_cm=270
        )
        
        # SKU con 4.3 pallets
        sku = SKU(
            sku_id="SKU_4_3",
            pedido_id="PED001",
            cantidad_pallets=4.3,
            altura_full_pallet_cm=150.0,  # Altura de cada pallet completo
            altura_picking_cm=45.0,        # Altura del picking (YA calculada en Excel)
            peso_kg=2150.0,
            volumen_m3=10.75,
            base=4.3
        )
        
        pedido = Pedido(
            pedido="PED001",
            cd="CD1",
            ce="0088",
            po="PO001",
            peso=2150.0,
            volumen=10.75,
            pallets=4.3,
            valor=100000,
            base=4.3,
            skus=[sku]
        )
        
        camion = Camion(
            id="test",
            tipo_ruta=TipoRuta.NORMAL,
            tipo_camion=TipoCamion.NORMAL,
            cd=["CD1"],
            ce=["0088"],
            grupo="test",
            capacidad=capacidad,
            pedidos=[pedido]
        )
        
        validator = HeightValidator(
            altura_maxima_cm=capacidad.altura_cm,
            permite_consolidacion=False
        )
        
        # Validar
        valido, errores, layout = validator.validar_camion_rapido(camion)
        
        # Verificaciones
        assert valido is True, f"Debería ser válido. Errores: {errores}"
        assert layout is not None
        
        # Debe usar 5 posiciones (4 full + 1 picking)
        # O menos si algunos se apilan
        print(f"Posiciones usadas: {layout.posiciones_usadas}")
        assert layout.posiciones_usadas <= 5
        
        # Verificar alturas individuales
        for posicion in layout.posiciones:
            if not posicion.esta_vacia:
                print(f"Posición {posicion.id}: altura={posicion.altura_usada_cm}cm, pallets={posicion.num_pallets}")
                assert posicion.altura_usada_cm <= 270  # No excede altura máxima
                