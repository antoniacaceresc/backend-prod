"""
Test de integración para Fase 3
Prueba la conexión completa: file_processor → optimizer → stacking_validator
"""

import pytest
import pandas as pd
from typing import Dict, List
import sys
import os

# Agregar el directorio raíz al path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from services.file_processor import agregar_skus_por_pedido, expandir_pedidos_con_skus
from services.optimizer import validar_camiones_fisicamente, _recalcular_metricas_camion
from config.walmart import WalmartConfig


# ============================================================================
# FIXTURES - Datos de prueba
# ============================================================================

@pytest.fixture
def df_skus_walmart():
    """DataFrame que simula un Excel de Walmart con SKUs detallados"""
    return pd.DataFrame([
        {
            # Columnas del Excel (nombres originales de Walmart)
            'Número PO': 'PO001',
            'N° Pedido': 'P001',
            'SKU': 'SKU_A',
            'Flujo OC': 'INV',
            'Ce.': '0088',
            'CD': '6009 Lo Aguirre',
            'Pal. Conf.': 5.0,
            'Peso neto Conf.': 500,
            'Vol. Conf.': 2500,
            '$$ Conf.': 100000,
            'Valor Cafe': 0,
            'Chocolates': 0,
            'Tipo Apilabilidad': 'BASE',
            'ALtura': 120,
            'PDQ': 0,
            'Saldo INV WM': 0
        },
        {
            'Número PO': 'PO001',
            'N° Pedido': 'P001',
            'SKU': 'SKU_B',
            'Flujo OC': 'INV',
            'Ce.': '0088',
            'CD': '6009 Lo Aguirre',
            'Pal. Conf.': 5.0,
            'Peso neto Conf.': 400,
            'Vol. Conf.': 2000,
            '$$ Conf.': 80000,
            'Valor Cafe': 0,
            'Chocolates': 0,
            'Tipo Apilabilidad': 'SUPERIOR',
            'ALtura': 100,
            'PDQ': 0,
            'Saldo INV WM': 0
        },
        {
            'Número PO': 'PO002',
            'N° Pedido': 'P002',
            'SKU': 'SKU_C',
            'Flujo OC': 'INV',
            'Ce.': '0088',
            'CD': '6009 Lo Aguirre',
            'Pal. Conf.': 3.0,
            'Peso neto Conf.': 300,
            'Vol. Conf.': 1500,
            '$$ Conf.': 60000,
            'Valor Cafe': 0,
            'Chocolates': 0,
            'Tipo Apilabilidad': 'FLEXIBLE',
            'ALtura': 110,
            'PDQ': 0,
            'Saldo INV WM': 0
        }
    ])


@pytest.fixture
def df_procesado_simple():
    """DataFrame ya procesado con columnas internas"""
    return pd.DataFrame([
        {
            'PEDIDO': 'P001',
            'SKU': 'SKU_A',
            'CD': '6009 Lo Aguirre',
            'CE': '0088',
            'OC': 'INV',
            'PO': 'PO001',
            'PALLETS': 5.0,
            'TIPO_APILABILIDAD': 'BASE',
            'ALTURA_PALLET': 120,
            'PESO': 500,
            'VOL': 2500,
            'VALOR': 100000,
            'VALOR_CAFE': 0,
            'CHOCOLATES': 0,
            'VALIOSO': 0,
            'PDQ': 0,
            'BAJA_VU': 0,
            'LOTE_DIR': 0,
            'SALDO_INV': 0
        },
        {
            'PEDIDO': 'P001',
            'SKU': 'SKU_B',
            'CD': '6009 Lo Aguirre',
            'CE': '0088',
            'OC': 'INV',
            'PO': 'PO001',
            'PALLETS': 5.0,
            'TIPO_APILABILIDAD': 'SUPERIOR',
            'ALTURA_PALLET': 100,
            'PESO': 400,
            'VOL': 2000,
            'VALOR': 80000,
            'VALOR_CAFE': 0,
            'CHOCOLATES': 0,
            'VALIOSO': 0,
            'PDQ': 0,
            'BAJA_VU': 0,
            'LOTE_DIR': 0,
            'SALDO_INV': 0
        },
        {
            'PEDIDO': 'P002',
            'SKU': 'SKU_C',
            'CD': '6009 Lo Aguirre',
            'CE': '0088',
            'OC': 'INV',
            'PO': 'PO002',
            'PALLETS': 3.0,
            'TIPO_APILABILIDAD': 'FLEXIBLE',
            'ALTURA_PALLET': 110,
            'PESO': 300,
            'VOL': 1500,
            'VALOR': 60000,
            'VALOR_CAFE': 0,
            'CHOCOLATES': 0,
            'VALIOSO': 0,
            'PDQ': 0,
            'BAJA_VU': 0,
            'LOTE_DIR': 0,
            'SALDO_INV': 0
        }
    ])


@pytest.fixture
def camion_test_simple():
    """Camión simple para testing"""
    return {
        'id': 'test_cam_001',
        'tipo_camion': 'normal',
        'grupo': 'test_group',
        'tipo_ruta': 'normal',
        'ce': [88],
        'cd': ['6009 Lo Aguirre'],
        'vcu_vol': 0.5,
        'vcu_peso': 0.4,
        'vcu_max': 0.5,
        'pallets_conf': 10,
        'valor_total': 180000,
        'pedidos': [
            {
                'PEDIDO': 'P001',
                'CD': '6009 Lo Aguirre',
                'CE': '0088',
                'PALLETS': 10.0,
                'PESO': 900,
                'VOL': 4500,
                'VALOR': 180000,
                'SKUS': [
                    {'sku': 'SKU_A', 'pallets': 5.0, 'tipo_apilabilidad': 'BASE', 'altura_pallet': 120},
                    {'sku': 'SKU_B', 'pallets': 5.0, 'tipo_apilabilidad': 'SUPERIOR', 'altura_pallet': 100}
                ]
            }
        ]
    }


# ============================================================================
# TESTS: FILE PROCESSOR
# ============================================================================

def test_agregar_skus_por_pedido(df_procesado_simple):
    """Test de agregación de SKUs por pedido"""
    df_agregado, skus_detalle = agregar_skus_por_pedido(df_procesado_simple)
    
    # Verificar agregación
    assert len(df_agregado) == 2, "Debe haber 2 pedidos únicos"
    
    # Verificar P001
    p001 = df_agregado[df_agregado['PEDIDO'] == 'P001'].iloc[0]
    assert p001['PALLETS'] == 10.0, "P001 debe tener 10 pallets"
    assert p001['BASE'] == 5.0, "P001 debe tener 5 BASE"
    assert p001['SUPERIOR'] == 5.0, "P001 debe tener 5 SUPERIOR"
    
    # Verificar skus_detalle
    assert 'P001' in skus_detalle
    assert len(skus_detalle['P001']) == 2


def test_expandir_pedidos_con_skus(df_procesado_simple):
    """Test de expansión de pedidos con SKUs"""
    df_agregado, skus_detalle = agregar_skus_por_pedido(df_procesado_simple)
    
    pedidos_agregados = [
        {'PEDIDO': 'P001', 'CAMION': 1, 'PALLETS': 10.0},
        {'PEDIDO': 'P002', 'CAMION': 1, 'PALLETS': 3.0}
    ]
    
    pedidos_expandidos = expandir_pedidos_con_skus(pedidos_agregados, skus_detalle)
    
    assert len(pedidos_expandidos) == 2
    assert 'SKUS' in pedidos_expandidos[0]
    assert len(pedidos_expandidos[0]['SKUS']) == 2


# ============================================================================
# TESTS: VALIDACIÓN FÍSICA
# ============================================================================

def test_validar_camion_simple(camion_test_simple):
    """Test de validación física de un camión simple"""
    camiones_validados, pedidos_rechazados = validar_camiones_fisicamente(
        [camion_test_simple],
        cliente='walmart'
    )
    
    assert len(camiones_validados) == 1, "Debe haber 1 camión validado"
    assert len(pedidos_rechazados) == 0, "No debe haber pedidos rechazados"
    
    cam = camiones_validados[0]
    assert 'pos_usadas_reales' in cam
    assert 'altura_maxima' in cam
    assert 'validacion_fisica' in cam
    assert cam['validacion_fisica'] in ['OK', 'AJUSTADO', 'ERROR']


def test_validar_camion_exceso_posiciones():
    """Test con camión que excede posiciones máximas"""
    # Crear 35 pedidos NO_APILABLE (excede 30 posiciones)
    skus = []
    for i in range(35):
        skus.append({
            'sku': f'SKU_{i}',
            'pallets': 1.0,
            'tipo_apilabilidad': 'NO_APILABLE',
            'altura_pallet': 120
        })
    
    camion = {
        'id': 'cam_sobrecargado',
        'tipo_camion': 'normal',
        'ce': [88],
        'cd': ['6009 Lo Aguirre'],
        'vcu_vol': 0.9,
        'vcu_peso': 0.8,
        'vcu_max': 0.9,
        'pallets_conf': 35,
        'pedidos': [
            {
                'PEDIDO': 'P_MULTIPLE',
                'CD': '6009 Lo Aguirre',
                'CE': '0088',
                'SKUS': skus
            }
        ]
    }
    
    camiones_validados, pedidos_rechazados = validar_camiones_fisicamente(
        [camion],
        cliente='walmart'
    )
    
    # Debe haber camión validado pero con pedidos filtrados o rechazados
    if camiones_validados:
        cam = camiones_validados[0]
        # Si se ajustó, debe tener marca
        if len(pedidos_rechazados) > 0:
            assert cam.get('validacion_fisica') in ['AJUSTADO', 'OK']
        # Las posiciones usadas no deben exceder 30
        assert cam.get('pos_usadas_reales', 0) <= 30


def test_recalcular_metricas():
    """Test de recálculo de métricas"""
    camion = {
        'vcu_vol': 0.8,
        'vcu_peso': 0.7,
        'vcu_max': 0.8,
        'pallets_conf': 20,
        'valor_total': 200000,
        'pedidos': [
            {'PEDIDO': 'P1', 'PALLETS': 10, 'VALOR': 100000},
            {'PEDIDO': 'P2', 'PALLETS': 10, 'VALOR': 100000}
        ]
    }
    
    pedidos_validos = [camion['pedidos'][0]]
    cam_recalculado = _recalcular_metricas_camion(camion, pedidos_validos)
    
    assert cam_recalculado['pallets_conf'] == 10
    assert cam_recalculado['valor_total'] == 100000


# ============================================================================
# TESTS: INTEGRACIÓN COMPLETA
# ============================================================================

def test_flujo_completo_con_process_dataframe():
    """Test del flujo completo usando process_dataframe"""
    from services.file_processor import process_dataframe
    
    # Crear DataFrame con nombres de columnas del Excel de Walmart
    df_raw = pd.DataFrame([
        {
            'Número PO': 'PO001',
            'N° Pedido': 'P001',
            'SKU': 'SKU_A',
            'Flujo OC': 'INV',
            'Ce.': '0088',
            'CD': '6009 Lo Aguirre',
            'Pal. Conf.': 5.0,
            'Peso neto Conf.': 500,
            'Vol. Conf.': 2500,
            '$$ Conf.': 100000,
            'Valor Cafe': 0,
            'Chocolates': 0,
            'Tipo Apilabilidad': 'BASE',
            'ALtura': 120,
            'PDQ': 0,
            'Saldo INV WM': 0
        }
    ])
    
    config = WalmartConfig()
    
    try:
        df_agregado, raw_pedidos, skus_detalle = process_dataframe(
            df_raw, 
            config, 
            'walmart', 
            'Secos'
        )
        
        assert len(df_agregado) > 0, "Debe tener pedidos agregados"
        assert len(skus_detalle) > 0, "Debe tener detalle de SKUs"
        assert 'P001' in skus_detalle
        
        print("✅ Test de process_dataframe OK")
        
    except Exception as e:
        pytest.fail(f"Error en process_dataframe: {e}")


def test_flujo_agregacion_expansion_validacion(df_procesado_simple):
    """Test del flujo: agregar → expandir → validar"""
    
    # 1. Agregar
    df_agregado, skus_detalle = agregar_skus_por_pedido(df_procesado_simple)
    assert len(df_agregado) == 2
    
    # 2. Simular resultado de CP-SAT
    pedidos_cpsat = [
        {'PEDIDO': 'P001', 'CAMION': 1, 'PALLETS': 10.0, 'CD': '6009 Lo Aguirre', 'CE': '0088'}
    ]
    
    # 3. Expandir
    pedidos_expandidos = expandir_pedidos_con_skus(pedidos_cpsat, skus_detalle)
    assert 'SKUS' in pedidos_expandidos[0]
    
    # 4. Crear camión para validar
    camion = {
        'id': 'cam001',
        'tipo_camion': 'normal',
        'ce': [88],
        'cd': ['6009 Lo Aguirre'],
        'vcu_vol': 0.5,
        'vcu_peso': 0.4,
        'vcu_max': 0.5,
        'pallets_conf': 10,
        'pedidos': pedidos_expandidos
    }
    
    # 5. Validar
    camiones_validados, rechazados = validar_camiones_fisicamente([camion], 'walmart')
    
    assert len(camiones_validados) > 0
    assert 'validacion_fisica' in camiones_validados[0]
    
    print("✅ Test de flujo completo OK")


# ============================================================================
# TEST PRINCIPAL - Simular optimización completa
# ============================================================================

def test_simulacion_optimizacion_completa(df_procesado_simple):
    """Test que simula una optimización completa con validación física"""
    
    print("\n" + "="*70)
    print("TEST DE SIMULACIÓN DE OPTIMIZACIÓN COMPLETA")
    print("="*70)
    
    # 1. FASE: Agregación de SKUs
    print("\n[1] Agregando SKUs por pedido...")
    df_agregado, skus_detalle = agregar_skus_por_pedido(df_procesado_simple)
    print(f"   ✅ {len(df_agregado)} pedidos agregados")
    print(f"   ✅ {len(skus_detalle)} pedidos con detalle de SKUs")
    
    # 2. FASE: Simular resultado de CP-SAT (optimizador)
    print("\n[2] Simulando resultado de CP-SAT...")
    camiones_cpsat = [
        {
            'id': 'cam001',
            'tipo_camion': 'normal',
            'tipo_ruta': 'normal',
            'ce': [88],
            'cd': ['6009 Lo Aguirre'],
            'grupo': 'normal__6009 Lo Aguirre__88',
            'vcu_vol': 0.65,
            'vcu_peso': 0.52,
            'vcu_max': 0.65,
            'pallets_conf': 13,
            'valor_total': 240000,
            'pedidos': [
                {'PEDIDO': 'P001', 'CAMION': 1, 'PALLETS': 10.0, 'CD': '6009 Lo Aguirre', 'CE': '0088'},
                {'PEDIDO': 'P002', 'CAMION': 1, 'PALLETS': 3.0, 'CD': '6009 Lo Aguirre', 'CE': '0088'}
            ]
        }
    ]
    print(f"   ✅ {len(camiones_cpsat)} camiones generados por CP-SAT")
    
    # 3. FASE: Expandir pedidos con SKUs
    print("\n[3] Expandiendo pedidos con detalle de SKUs...")
    for cam in camiones_cpsat:
        cam['pedidos'] = expandir_pedidos_con_skus(cam['pedidos'], skus_detalle)
    print(f"   ✅ Pedidos expandidos con SKUs")
    print(f"   ✅ Primer pedido tiene {len(camiones_cpsat[0]['pedidos'][0]['SKUS'])} SKUs")
    
    # 4. FASE: Validación física
    print("\n[4] Validando físicamente los camiones...")
    camiones_validados, pedidos_rechazados = validar_camiones_fisicamente(
        camiones_cpsat,
        cliente='walmart'
    )
    print(f"   ✅ {len(camiones_validados)} camiones validados")
    print(f"   ✅ {len(pedidos_rechazados)} pedidos rechazados por física")
    
    # 5. VERIFICACIÓN: Resultados finales
    print("\n[5] Verificando resultados...")
    assert len(camiones_validados) > 0, "Debe haber al menos 1 camión validado"
    
    cam = camiones_validados[0]
    print(f"\n📦 Camión validado:")
    print(f"   - ID: {cam['id']}")
    print(f"   - Validación: {cam.get('validacion_fisica', 'N/A')}")
    print(f"   - Posiciones usadas: {cam.get('pos_usadas_reales', 'N/A')}")
    print(f"   - Altura máxima: {cam.get('altura_maxima', 'N/A')} cm")
    print(f"   - Pallets físicos: {cam.get('pallets_fisicos', 'N/A')}")
    print(f"   - Eficiencia posiciones: {cam.get('eficiencia_posiciones_fisica', 'N/A'):.1f}%")
    print(f"   - Eficiencia altura: {cam.get('eficiencia_altura_fisica', 'N/A'):.1f}%")
    print(f"   - Pedidos: {len(cam['pedidos'])}")
    
    # Verificar que tiene todas las métricas
    assert 'pos_usadas_reales' in cam
    assert 'altura_maxima' in cam
    assert 'pallets_fisicos' in cam
    assert 'eficiencia_posiciones_fisica' in cam
    assert 'eficiencia_altura_fisica' in cam
    assert 'validacion_fisica' in cam
    
    # Verificar que los pedidos tienen SKUS
    for ped in cam['pedidos']:
        assert 'SKUS' in ped, f"Pedido {ped.get('PEDIDO')} no tiene SKUS"
    
    print("\n" + "="*70)
    print("✅ TEST DE SIMULACIÓN COMPLETO - EXITOSO")
    print("="*70)


# ============================================================================
# EJECUTAR TESTS
# ============================================================================

if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short', '-s'])