# tests/test_stacking_validator.py
import pytest
import math
from services.stacking_validator import (
    FragmentoSKU, PalletFisico, TipoApilabilidad,
    StackingValidator, Posicion,
    extraer_fragmentos_de_pedidos, validar_pedidos_en_camion
)


# === Tests de FragmentoSKU ===

def test_fragmento_sku_valido():
    """Test creación de fragmento válido"""
    frag = FragmentoSKU(
        sku='SKU001',
        pedido='PED123',
        cantidad=0.5,
        tipo=TipoApilabilidad.BASE,
        altura=120
    )
    assert frag.cantidad == 0.5
    assert frag.tipo == TipoApilabilidad.BASE


def test_fragmento_cantidad_invalida():
    """Test validación de cantidad"""
    with pytest.raises(ValueError, match="Cantidad debe estar en"):
        FragmentoSKU('SKU', 'PED', cantidad=1.5, tipo=TipoApilabilidad.BASE, altura=120)


# === Tests de PalletFisico ===

def test_pallet_fisico_unico_sku():
    """Test pallet con 1 SKU"""
    frag = FragmentoSKU('SKU001', 'PED1', 0.8, TipoApilabilidad.BASE, 120)
    pallet = PalletFisico('P1', (frag,), TipoApilabilidad.BASE, 120)
    
    assert len(pallet.skus_unicos) == 1
    assert pallet.sku_dominante == 'SKU001'
    assert not pallet.es_completo  # 0.8 < 0.95


def test_pallet_fisico_consolidado():
    """Test pallet consolidado con múltiples SKUs"""
    frags = (
        FragmentoSKU('SKU001', 'PED1', 0.4, TipoApilabilidad.FLEXIBLE, 120),
        FragmentoSKU('SKU002', 'PED2', 0.3, TipoApilabilidad.FLEXIBLE, 120),
        FragmentoSKU('SKU003', 'PED1', 0.3, TipoApilabilidad.FLEXIBLE, 120),
    )
    pallet = PalletFisico('P1', frags, TipoApilabilidad.FLEXIBLE, 120)
    
    assert len(pallet.skus_unicos) == 3
    assert len(pallet.pedidos) == 2  # PED1 y PED2
    assert math.isclose(pallet.cantidad_total, 1.0, rel_tol=1e-9)
    assert pallet.es_completo


def test_pallet_puede_agregar_fragmento():
    """Test validación de agregar fragmento"""
    frags = (
        FragmentoSKU('SKU001', 'PED1', 0.4, TipoApilabilidad.BASE, 120),
    )
    pallet = PalletFisico('P1', frags, TipoApilabilidad.BASE, 120)
    
    # Mismo tipo, espacio disponible → OK
    frag_nuevo = FragmentoSKU('SKU002', 'PED2', 0.3, TipoApilabilidad.BASE, 120)
    assert pallet.puede_agregar_fragmento(frag_nuevo, max_skus=5)
    
    # Diferente tipo → NO
    frag_otro_tipo = FragmentoSKU('SKU003', 'PED3', 0.3, TipoApilabilidad.SUPERIOR, 120)
    assert not pallet.puede_agregar_fragmento(frag_otro_tipo, max_skus=5)


def test_pallet_limite_skus():
    """Test límite de SKUs diferentes por pallet"""
    frags = tuple(
        FragmentoSKU(f'SKU{i}', 'PED1', 0.15, TipoApilabilidad.FLEXIBLE, 120)
        for i in range(5)  # 5 SKUs = 0.75 total
    )
    pallet = PalletFisico('P1', frags, TipoApilabilidad.FLEXIBLE, 120)
    
    # Ya tiene 5 SKUs → no puede agregar otro diferente
    frag_nuevo = FragmentoSKU('SKU_EXTRA', 'PED2', 0.2, TipoApilabilidad.FLEXIBLE, 120)
    assert not pallet.puede_agregar_fragmento(frag_nuevo, max_skus=5)
    
    # Pero SÍ puede agregar si es SKU existente
    frag_existente = FragmentoSKU('SKU0', 'PED3', 0.1, TipoApilabilidad.FLEXIBLE, 120)
    assert pallet.puede_agregar_fragmento(frag_existente, max_skus=5)


# === Tests de Posicion ===

def test_posicion_no_apilable_solo():
    """Test NO_APILABLE nunca recibe nada encima"""
    pos = Posicion(0)
    
    frag_no_apil = FragmentoSKU('SKU1', 'PED1', 1.0, TipoApilabilidad.NO_APILABLE, 120)
    pallet_no_apil = PalletFisico('P1', (frag_no_apil,), TipoApilabilidad.NO_APILABLE, 120)
    
    pos.agregar(pallet_no_apil)
    
    # Intentar agregar cualquier cosa encima → NO
    frag_flexible = FragmentoSKU('SKU2', 'PED2', 1.0, TipoApilabilidad.FLEXIBLE, 100)
    pallet_flexible = PalletFisico('P2', (frag_flexible,), TipoApilabilidad.FLEXIBLE, 100)
    
    assert not pos.puede_apilar(pallet_flexible, 240)


def test_posicion_base_superior():
    """Test BASE acepta SUPERIOR encima (1 nivel)"""
    pos = Posicion(0)
    
    frag_base = FragmentoSKU('SKU1', 'PED1', 1.0, TipoApilabilidad.BASE, 120)
    pallet_base = PalletFisico('P1', (frag_base,), TipoApilabilidad.BASE, 120)
    
    frag_sup = FragmentoSKU('SKU2', 'PED2', 1.0, TipoApilabilidad.SUPERIOR, 100)
    pallet_sup = PalletFisico('P2', (frag_sup,), TipoApilabilidad.SUPERIOR, 100)
    
    pos.agregar(pallet_base)
    
    # SUPERIOR puede ir encima de BASE
    assert pos.puede_apilar(pallet_sup, 240)
    
    pos.agregar(pallet_sup)
    
    # Pero no se puede agregar nada más (solo 1 nivel)
    frag_otro = FragmentoSKU('SKU3', 'PED3', 1.0, TipoApilabilidad.FLEXIBLE, 80)
    pallet_otro = PalletFisico('P3', (frag_otro,), TipoApilabilidad.FLEXIBLE, 80)
    
    assert not pos.puede_apilar(pallet_otro, 240)


def test_posicion_si_mismo_apilado():
    """Test SI_MISMO se apila verticalmente con mismo SKU"""
    pos = Posicion(0)
    
    frag1 = FragmentoSKU('SKU_A', 'PED1', 1.0, TipoApilabilidad.SI_MISMO, 100)
    pallet1 = PalletFisico('P1', (frag1,), TipoApilabilidad.SI_MISMO, 100)
    
    frag2_mismo = FragmentoSKU('SKU_A', 'PED2', 1.0, TipoApilabilidad.SI_MISMO, 100)
    pallet2_mismo = PalletFisico('P2', (frag2_mismo,), TipoApilabilidad.SI_MISMO, 100)
    
    frag2_otro = FragmentoSKU('SKU_B', 'PED3', 1.0, TipoApilabilidad.SI_MISMO, 100)
    pallet2_otro = PalletFisico('P3', (frag2_otro,), TipoApilabilidad.SI_MISMO, 100)
    
    pos.agregar(pallet1)
    
    # Mismo SKU → OK
    assert pos.puede_apilar(pallet2_mismo, 300)
    
    # Otro SKU → NO
    assert not pos.puede_apilar(pallet2_otro, 300)


def test_posicion_flexible_adaptativo():
    """Test FLEXIBLE puede ir al suelo o encima de BASE"""
    pos1 = Posicion(0)
    pos2 = Posicion(1)
    
    frag_flex = FragmentoSKU('SKU1', 'PED1', 1.0, TipoApilabilidad.FLEXIBLE, 120)
    pallet_flex = PalletFisico('P1', (frag_flex,), TipoApilabilidad.FLEXIBLE, 120)
    
    # Puede ir al suelo
    assert pos1.puede_apilar(pallet_flex, 240)
    
    # Puede ir encima de BASE
    frag_base = FragmentoSKU('SKU2', 'PED2', 1.0, TipoApilabilidad.BASE, 120)
    pallet_base = PalletFisico('P2', (frag_base,), TipoApilabilidad.BASE, 120)
    
    pos2.agregar(pallet_base)
    assert pos2.puede_apilar(pallet_flex, 240)


# === Tests de StackingValidator ===

def test_consolidacion_con_limite_skus():
    """Test consolidación respeta límite de SKUs"""
    validator = StackingValidator(
        max_positions=30,
        max_altura=240,
        permite_consolidacion=True,
        max_skus_por_pallet=3  # máximo 3 SKUs por pallet
    )
    
    fragmentos_por_pedido = {
        'PED1': [
            FragmentoSKU(f'SKU{i}', 'PED1', 0.2, TipoApilabilidad.FLEXIBLE, 120)
            for i in range(6)  # 6 SKUs × 0.2 = 1.2 total
        ]
    }
    
    resultado = validator.validar_pedidos(fragmentos_por_pedido)
    
    # Con MAX_SKUS=3, necesita al menos 2 pallets
    assert resultado.cabe
    assert 'PED1' in resultado.pedidos_incluidos
    assert resultado.pallets_fisicos_usados >= 2


def test_sin_consolidacion_separado():
    """Test sin consolidación: cada fragmento en pallet separado"""
    validator = StackingValidator(
        max_positions=30,
        max_altura=240,
        permite_consolidacion=False,  # Cencosud
        max_skus_por_pallet=1
    )
    
    fragmentos_por_pedido = {
        'PED1': [
            FragmentoSKU('SKU1', 'PED1', 0.5, TipoApilabilidad.BASE, 120),
            FragmentoSKU('SKU2', 'PED1', 0.5, TipoApilabilidad.BASE, 120),
        ]
    }
    
    resultado = validator.validar_pedidos(fragmentos_por_pedido)
    
    # Sin consolidación: 2 fragmentos = 2 pallets físicos
    assert resultado.cabe
    assert resultado.pallets_fisicos_usados == 2


def test_pedido_parcial_rechazado():
    """Test pedido que no cabe completo es rechazado"""
    validator = StackingValidator(
        max_positions=2,  # solo 2 posiciones
        max_altura=240,
        permite_consolidacion=True,
        max_skus_por_pallet=5
    )
    
    fragmentos_por_pedido = {
        'PED1': [
            # 3 pallets NO_APILABLE → necesita 3 posiciones
            FragmentoSKU(f'SKU{i}', 'PED1', 1.0, TipoApilabilidad.NO_APILABLE, 120)
            for i in range(3)
        ]
    }
    
    resultado = validator.validar_pedidos(fragmentos_por_pedido)
    
    # Solo caben 2 pallets, pero el pedido necesita 3 → rechazado completo
    assert not resultado.cabe or 'PED1' in resultado.pedidos_rechazados


def test_extraccion_desde_skus_detallados():
    """Test extracción con formato SKUs detallados"""
    pedidos_data = [
        {
            'PEDIDO': '12345',
            'SKUS': [
                {
                    'sku': 'SKU001',
                    'pallets': 1.2,  # 1 completo + 0.2
                    'tipo_apilabilidad': 'BASE',
                    'altura_pallet': 120
                }
            ]
        }
    ]
    
    fragmentos = extraer_fragmentos_de_pedidos(pedidos_data)
    
    assert '12345' in fragmentos
    assert len(fragmentos['12345']) == 2  # 1.0 + 0.2
    
    completos = [f for f in fragmentos['12345'] if f.cantidad == 1.0]
    incompletos = [f for f in fragmentos['12345'] if f.cantidad < 1.0]
    
    assert len(completos) == 1
    assert len(incompletos) == 1
    
    # FIX: Usar pytest.approx() para comparar floats
    assert incompletos[0].cantidad == pytest.approx(0.2, rel=1e-9)


def test_integracion_completa_walmart():
    """Test integración completa: Walmart con consolidación"""
    pedidos_data = [
        {
            'PEDIDO': 'P1',
            'SKUS': [
                {'sku': 'SKU001', 'pallets': 0.5, 'tipo_apilabilidad': 'BASE', 'altura_pallet': 120},
                {'sku': 'SKU002', 'pallets': 0.5, 'tipo_apilabilidad': 'SUPERIOR', 'altura_pallet': 100}
            ]
        }
    ]
    
    resultado = validar_pedidos_en_camion(pedidos_data, 'walmart', 'normal')
    
    assert resultado.cabe
    assert 'P1' in resultado.pedidos_incluidos
    assert resultado.posiciones_usadas == 1  # BASE+SUPERIOR en 1 posición
    
    # FIX: BASE y SUPERIOR no se consolidan (son tipos diferentes)
    # Se apilan verticalmente, pero son 2 pallets físicos separados
    # La eficiencia de consolidación mide pallets con múltiples pedidos, no apilamiento vertical
    assert resultado.pallets_fisicos_usados == 2  # 1 BASE + 1 SUPERIOR


def test_integracion_completa_cencosud():
    """Test integración completa: Cencosud sin consolidación"""
    pedidos_data = [
        {
            'PEDIDO': 'P1',
            'PALLETS': 2,
            'BASE': 1,
            'SUPERIOR': 1,
            'ALTURA_PALLET': 120
        }
    ]
    
    resultado = validar_pedidos_en_camion(pedidos_data, 'cencosud', 'normal')
    
    assert resultado.cabe
    assert 'P1' in resultado.pedidos_incluidos
    # Sin consolidación, pero BASE+SUPERIOR pueden apilarse
    assert resultado.posiciones_usadas <= 2


# Ejecutar: python -m pytest tests/test_stacking_validator.py -v