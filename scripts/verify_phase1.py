# scripts/verify_phase1.py
"""
Script de verificación completo de Fase 1.
"""
import sys
import os

# AGREGAR ESTAS LÍNEAS AL INICIO
# Agregar directorio raíz al path
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
sys.path.insert(0, project_root)

def verificar_imports():
    print("\n--- Verificando Imports ---")
    try:
        from services.stacking_validator import (
            StackingValidator, validar_pedidos_en_camion,
            FragmentoSKU, PalletFisico, TipoApilabilidad
        )
        print("✅ Imports correctos")
        return True
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def verificar_configs():
    print("\n--- Verificando Configuraciones ---")
    try:
        from config import get_client_config
    except ModuleNotFoundError:
        print("❌ No se encuentra módulo 'config'. Verifica estructura del proyecto.")
        return False
    
    clientes = {
        'walmart': {'consolidacion': True, 'max_skus': 5},
        'cencosud': {'consolidacion': False, 'max_skus': 1},
        'disvet': {'consolidacion': True, 'max_skus': 5}
    }
    
    for cliente, esperado in clientes.items():
        try:
            cfg = get_client_config(cliente)
            
            if not cfg:
                print(f"❌ {cliente}: configuración no encontrada")
                return False
            
            # Verificar PERMITE_CONSOLIDACION_PALLETS
            consol = getattr(cfg, 'PERMITE_CONSOLIDACION_PALLETS', None)
            if consol is None:
                print(f"⚠️  {cliente}: falta PERMITE_CONSOLIDACION_PALLETS (agregarlo a config)")
                return False
            
            if consol != esperado['consolidacion']:
                print(f"❌ {cliente}: consolidación esperada={esperado['consolidacion']}, actual={consol}")
                return False
            
            # Verificar MAX_SKUS_POR_PALLET
            max_skus = getattr(cfg, 'MAX_SKUS_POR_PALLET', None)
            if max_skus is None:
                print(f"⚠️  {cliente}: falta MAX_SKUS_POR_PALLET (agregarlo a config)")
                return False
            
            if max_skus != esperado['max_skus']:
                print(f"❌ {cliente}: max_skus esperado={esperado['max_skus']}, actual={max_skus}")
                return False
            
            # Verificar max_altura en TRUCK_TYPES
            for tipo in ['normal', 'bh']:
                if isinstance(cfg.TRUCK_TYPES, dict):
                    truck = cfg.TRUCK_TYPES.get(tipo)
                else:
                    truck = next((t for t in cfg.TRUCK_TYPES if t.get('type') == tipo), None)
                
                if not truck:
                    print(f"❌ {cliente}: tipo '{tipo}' no encontrado en TRUCK_TYPES")
                    return False
                
                if 'max_altura' not in truck:
                    print(f"⚠️  {cliente} tipo '{tipo}': falta max_altura (agregarlo a config)")
                    return False
            
            print(f"✅ {cliente}: config OK (consolidación={consol}, max_skus={max_skus})")
        
        except Exception as e:
            print(f"❌ {cliente}: Error al verificar - {e}")
            import traceback
            traceback.print_exc()
            return False
    
    return True


def verificar_consolidacion():
    print("\n--- Verificando Consolidación ---")
    try:
        from services.stacking_validator import StackingValidator, FragmentoSKU, TipoApilabilidad
        
        validator = StackingValidator(
            max_positions=30,
            max_altura=240,
            permite_consolidacion=True,
            max_skus_por_pallet=3
        )
        
        # Caso: 5 fragmentos FLEXIBLE de 0.2 cada uno = 1.0 total
        # Con MAX_SKUS=3, debe crear 2 pallets
        fragmentos = {
            'PED1': [
                FragmentoSKU(f'SKU{i}', 'PED1', 0.2, TipoApilabilidad.FLEXIBLE, 120)
                for i in range(5)
            ]
        }
        
        resultado = validator.validar_pedidos(fragmentos)
        
        if not resultado.cabe:
            print(f"❌ Consolidación falló: {resultado.motivo_fallo}")
            return False
        
        # Debe haber usado al menos 2 pallets (3 SKUs máx por pallet)
        if resultado.pallets_fisicos_usados < 2:
            print(f"❌ Consolidación incorrecta: pallets={resultado.pallets_fisicos_usados}, esperado >= 2")
            return False
        
        print(f"✅ Consolidación funciona (pallets={resultado.pallets_fisicos_usados})")
        return True
    
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def verificar_apilamiento():
    print("\n--- Verificando Reglas de Apilamiento ---")
    try:
        from services.stacking_validator import (
            Posicion, PalletFisico, FragmentoSKU, TipoApilabilidad
        )
        
        # Test 1: BASE + SUPERIOR
        pos1 = Posicion(0)
        frag_base = FragmentoSKU('S1', 'P1', 1.0, TipoApilabilidad.BASE, 120)
        pallet_base = PalletFisico('P1', (frag_base,), TipoApilabilidad.BASE, 120)
        
        frag_sup = FragmentoSKU('S2', 'P2', 1.0, TipoApilabilidad.SUPERIOR, 100)
        pallet_sup = PalletFisico('P2', (frag_sup,), TipoApilabilidad.SUPERIOR, 100)
        
        pos1.agregar(pallet_base)
        if not pos1.puede_apilar(pallet_sup, 240):
            print("❌ BASE no acepta SUPERIOR")
            return False
        
        # Test 2: NO_APILABLE nunca recibe nada
        pos2 = Posicion(1)
        frag_no_apil = FragmentoSKU('S3', 'P3', 1.0, TipoApilabilidad.NO_APILABLE, 120)
        pallet_no_apil = PalletFisico('P3', (frag_no_apil,), TipoApilabilidad.NO_APILABLE, 120)
        
        pos2.agregar(pallet_no_apil)
        if pos2.puede_apilar(pallet_sup, 240):
            print("❌ NO_APILABLE acepta algo encima (incorrecto)")
            return False
        
        print("✅ Reglas de apilamiento correctas")
        return True
    
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def verificar_api():
    print("\n--- Verificando API de Alto Nivel ---")
    try:
        from services.stacking_validator import validar_pedidos_en_camion
        
        pedidos_data = [
            {
                'PEDIDO': 'TEST1',
                'SKUS': [
                    {'sku': 'SKU001', 'pallets': 1.0, 'tipo_apilabilidad': 'BASE', 'altura_pallet': 120},
                    {'sku': 'SKU002', 'pallets': 1.0, 'tipo_apilabilidad': 'SUPERIOR', 'altura_pallet': 100}
                ]
            }
        ]
        
        resultado = validar_pedidos_en_camion(pedidos_data, 'walmart', 'normal')
        
        if not resultado.cabe:
            print(f"❌ API falló: {resultado.motivo_fallo}")
            return False
        
        if 'TEST1' not in resultado.pedidos_incluidos:
            print("❌ Pedido no incluido")
            return False
        
        print(f"✅ API funciona (posiciones={resultado.posiciones_usadas}, pallets={resultado.pallets_fisicos_usados})")
        return True
    
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    print("\n" + "="*60)
    print("🔍 VERIFICACIÓN FASE 1: Validación de Apilabilidad Física")
    print("="*60)
    
    checks = [
        ("Imports", verificar_imports),
        ("Configuraciones", verificar_configs),
        ("Consolidación", verificar_consolidacion),
        ("Apilamiento", verificar_apilamiento),
        ("API", verificar_api)
    ]
    
    resultados = []
    for nombre, fn in checks:
        resultado = fn()
        resultados.append(resultado)
        if not resultado:
            print(f"\n⚠️  Deteniendo verificación en '{nombre}' (falló)")
            break
    
    print("\n" + "="*60)
    if all(resultados):
        print("✅ FASE 1 COMPLETADA EXITOSAMENTE")
        print("="*60)
        sys.exit(0)
    else:
        print("❌ FASE 1 TIENE ERRORES - Revisar logs arriba")
        print("="*60)
        sys.exit(1)