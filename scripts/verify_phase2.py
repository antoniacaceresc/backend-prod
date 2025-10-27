# scripts/verify_phase2.py
"""
Verificación completa de Fase 2.
"""
import sys
import os
from pathlib import Path

# Agregar raíz al path
root = Path(__file__).parent.parent
sys.path.insert(0, str(root))


def verificar_imports():
    """Verifica que todos los imports funcionen"""
    print("\n--- Verificando Imports ---")
    try:
        from services.postprocess import (
            _compute_apilabilidad,
            _compute_apilabilidad_legacy,
            move_orders,
            apply_truck_type_change,
            add_truck,
            delete_truck
        )
        from services.stacking_validator import validar_pedidos_en_camion
        print("✅ Imports correctos")
        return True
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def verificar_feature_flags():
    """Verifica que feature flags funcionen"""
    print("\n--- Verificando Feature Flags ---")
    
    # Test 1: Flag desactivado (default)
    os.environ['DISABLE_PHYSICAL_STACKING'] = 'false'
    from services.postprocess import _compute_apilabilidad
    
    pedidos = [{
        'PEDIDO': 'TEST1',
        'SKUS': [
            {'sku': 'SKU1', 'pallets': 1.0, 'tipo_apilabilidad': 'BASE', 'altura_pallet': 120}
        ]
    }]
    
    resultado = _compute_apilabilidad(pedidos, 'walmart', 'normal')
    if not resultado.get('ok'):
        print(f"❌ Validación física falló inesperadamente: {resultado}")
        return False
    
    print("✅ Validación física funciona (flag=false)")
    
    # Test 2: Flag activado
    os.environ['DISABLE_PHYSICAL_STACKING'] = 'true'
    
    # Reimportar para que tome el cambio
    import importlib
    import services.postprocess
    importlib.reload(services.postprocess)
    from services.postprocess import _compute_apilabilidad as _compute_apilabilidad_2
    
    resultado2 = _compute_apilabilidad_2(pedidos, 'walmart', 'normal')
    if not resultado2.get('ok'):
        print(f"❌ Validación legacy falló: {resultado2}")
        return False
    
    print("✅ Fallback a legacy funciona (flag=true)")
    
    # Restaurar
    os.environ['DISABLE_PHYSICAL_STACKING'] = 'false'
    
    return True


def verificar_metricas_fisicas():
    """Verifica que métricas físicas se calculen correctamente"""
    print("\n--- Verificando Métricas Físicas ---")
    from services.postprocess import _compute_apilabilidad
    
    pedidos = [
        {
            'PEDIDO': 'PED1',
            'SKUS': [
                {'sku': 'SKU1', 'pallets': 2.0, 'tipo_apilabilidad': 'BASE', 'altura_pallet': 120}
            ]
        },
        {
            'PEDIDO': 'PED2',
            'SKUS': [
                {'sku': 'SKU2', 'pallets': 2.0, 'tipo_apilabilidad': 'SUPERIOR', 'altura_pallet': 100}
            ]
        }
    ]
    
    resultado = _compute_apilabilidad(pedidos, 'walmart', 'normal')
    
    if not resultado.get('ok'):
        print(f"❌ Validación falló: {resultado}")
        return False
    
    # Verificar que métricas existan
    metricas_requeridas = [
        'pos_usadas',
        'altura_maxima',
        'eficiencia_posiciones',
        'eficiencia_altura',
        'pallets_fisicos'
    ]
    
    for metrica in metricas_requeridas:
        if metrica not in resultado:
            print(f"❌ Falta métrica: {metrica}")
            return False
    
    print(f"✅ Métricas calculadas:")
    print(f"   - Posiciones: {resultado['pos_usadas']}")
    print(f"   - Altura: {resultado['altura_maxima']:.2f} cm")
    print(f"   - Pallets físicos: {resultado['pallets_fisicos']}")
    print(f"   - Eficiencia pos: {resultado['eficiencia_posiciones']:.2f}%")
    
    return True


def verificar_tests_unitarios():
    """Ejecuta tests unitarios"""
    print("\n--- Ejecutando Tests Unitarios ---")
    import subprocess
    
    # Test de compute_apilabilidad
    result1 = subprocess.run(
        [sys.executable, '-m', 'pytest', 'tests/test_compute_apilabilidad.py', '-v'],
        capture_output=True,
        text=True
    )
    
    if result1.returncode != 0:
        print("❌ Tests de compute_apilabilidad fallaron")
        print(result1.stdout)
        return False
    
    print("✅ Tests de compute_apilabilidad pasaron")
    
    return True


def verificar_tests_integracion():
    """Ejecuta tests de integración"""
    print("\n--- Ejecutando Tests de Integración ---")
    import subprocess
    
    result = subprocess.run(
        [sys.executable, '-m', 'pytest', 'tests/test_postprocess_integration.py', '-v'],
        capture_output=True,
        text=True
    )
    
    if result.returncode != 0:
        print("❌ Tests de integración fallaron")
        print(result.stdout)
        return False
    
    print("✅ Tests de integración pasaron")
    
    return True


if __name__ == '__main__':
    print("\n" + "="*70)
    print("🔍 VERIFICACIÓN FASE 2: Integración con Postproceso")
    print("="*70)
    
    checks = [
        ("Imports", verificar_imports),
        ("Feature Flags", verificar_feature_flags),
        ("Métricas Físicas", verificar_metricas_fisicas),
        ("Tests Unitarios", verificar_tests_unitarios),
        ("Tests Integración", verificar_tests_integracion),
    ]
    
    resultados = []
    for nombre, fn in checks:
        resultado = fn()
        resultados.append(resultado)
        if not resultado:
            print(f"\n⚠️  Deteniendo en '{nombre}' (falló)")
            break
    
    print("\n" + "="*70)
    if all(resultados):
        print("✅ FASE 2 COMPLETADA EXITOSAMENTE")
        print("="*70)
        print("\n📊 Resumen:")
        print("   - Validación física integrada en postproceso")
        print("   - Feature flags configurados")
        print("   - Métricas físicas expuestas")
        print("   - Tests pasando")
        print("\n🚀 Listo para Fase 3: Integración con Optimizer")
        sys.exit(0)
    else:
        print("❌ FASE 2 TIENE ERRORES")
        print("="*70)
        sys.exit(1)