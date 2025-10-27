# scripts/test_compute_apilabilidad.py
"""
Test manual de la nueva función _compute_apilabilidad.
"""
import sys
from pathlib import Path

# Agregar raíz al path
root = Path(__file__).parent.parent
sys.path.insert(0, str(root))

from services.postprocess import _compute_apilabilidad, _compute_apilabilidad_legacy


def test_caso_simple():
    """Test con caso simple que debe caber"""
    print("\n" + "="*60)
    print("TEST 1: Caso Simple (2 pedidos BASE + SUPERIOR)")
    print("="*60)
    
    pedidos_cam = [
        {
            'PEDIDO': 'PED001',
            'SKUS': [
                {'sku': 'SKU_A', 'pallets': 1.0, 'tipo_apilabilidad': 'BASE', 'altura_pallet': 120}
            ]
        },
        {
            'PEDIDO': 'PED002',
            'SKUS': [
                {'sku': 'SKU_B', 'pallets': 1.0, 'tipo_apilabilidad': 'SUPERIOR', 'altura_pallet': 100}
            ]
        }
    ]
    
    # Probar con validación física (nueva)
    resultado_fisica = _compute_apilabilidad(pedidos_cam, 'walmart', 'normal')
    print("\n--- Validación Física ---")
    print(f"OK: {resultado_fisica.get('ok')}")
    print(f"Posiciones usadas: {resultado_fisica.get('pos_usadas')}")
    print(f"Altura máxima: {resultado_fisica.get('altura_maxima')}")
    print(f"Eficiencia posiciones: {resultado_fisica.get('eficiencia_posiciones'):.2f}%")
    
    # Probar con legacy (comparación)
    resultado_legacy = _compute_apilabilidad_legacy(pedidos_cam, 'walmart', 'normal')
    print("\n--- Validación Legacy ---")
    print(f"OK: {resultado_legacy.get('ok')}")
    print(f"Posiciones usadas: {resultado_legacy.get('pos_usadas', 'N/A')}")
    
    # Verificar
    assert resultado_fisica['ok'], "Física debería dar OK"
    assert resultado_legacy['ok'], "Legacy debería dar OK"
    print("\n✅ Test 1 PASADO")


def test_caso_no_cabe():
    """Test con caso que NO debe caber"""
    print("\n" + "="*60)
    print("TEST 2: Caso que NO Cabe (35 NO_APILABLE en camión de 30 posiciones)")
    print("="*60)
    
    pedidos_cam = [
        {
            'PEDIDO': f'PED{i:03d}',
            'SKUS': [
                {'sku': f'SKU_{i}', 'pallets': 1.0, 'tipo_apilabilidad': 'NO_APILABLE', 'altura_pallet': 120}
            ]
        }
        for i in range(35)  # 35 pedidos NO_APILABLE
    ]
    
    resultado = _compute_apilabilidad(pedidos_cam, 'walmart', 'normal')
    print(f"\nOK: {resultado.get('ok')}")
    print(f"Motivo: {resultado.get('motivo')}")
    
    assert not resultado['ok'], "Debería rechazar (no caben 35 NO_APILABLE en 30 posiciones)"
    print("\n✅ Test 2 PASADO")


def test_fallback_a_legacy():
    """Test que el fallback funciona"""
    print("\n" + "="*60)
    print("TEST 3: Fallback a Legacy (con feature flag)")
    print("="*60)
    
    import os
    os.environ['DISABLE_PHYSICAL_STACKING'] = 'true'
    
    pedidos_cam = [
        {
            'PEDIDO': 'PED001',
            'PALLETS': 1,
            'BASE': 1,
            'ALTURA_PALLET': 120
        }
    ]
    
    resultado = _compute_apilabilidad(pedidos_cam, 'walmart', 'normal')
    print(f"\nUsó legacy (por feature flag)")
    print(f"OK: {resultado.get('ok')}")
    
    # Limpiar
    os.environ['DISABLE_PHYSICAL_STACKING'] = 'false'
    
    print("\n✅ Test 3 PASADO")


def test_camion_vacio():
    """Test con camión vacío"""
    print("\n" + "="*60)
    print("TEST 4: Camión Vacío")
    print("="*60)
    
    pedidos_cam = []
    
    resultado = _compute_apilabilidad(pedidos_cam, 'walmart', 'normal')
    print(f"\nOK: {resultado.get('ok')}")
    print(f"Posiciones usadas: {resultado.get('pos_usadas')}")
    
    assert resultado['ok'], "Camión vacío debería ser válido"
    assert resultado['pos_usadas'] == 0
    print("\n✅ Test 4 PASADO")


if __name__ == '__main__':
    print("\n" + "="*70)
    print("🧪 TESTS DE _compute_apilabilidad (Validación Física)")
    print("="*70)
    
    try:
        test_caso_simple()
        test_caso_no_cabe()
        test_fallback_a_legacy()
        test_camion_vacio()
        
        print("\n" + "="*70)
        print("✅ TODOS LOS TESTS PASARON")
        print("="*70)
    
    except AssertionError as e:
        print(f"\n❌ TEST FALLÓ: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n💥 ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)