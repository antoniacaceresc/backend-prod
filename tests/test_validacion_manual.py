"""Test manual del validador de altura con datos reales"""

from models.domain import Camion, Pedido, TruckCapacity, SKU
from models.enums import TipoRuta, TipoCamion
from optimization.validation.height_validator import HeightValidator


def test_caso_valido():
    """Test con camión que SÍ debería pasar validación"""
    print("\n" + "="*80)
    print("TEST 1: Camión VÁLIDO (debería pasar)")
    print("="*80)
    
    capacidad = TruckCapacity(
        cap_weight=23000,
        cap_volume=70000,
        max_positions=30,
        max_pallets=60,
        altura_cm=270
    )
    
    # SKU 1: 2 pallets completos de 150cm
    sku1 = SKU(
        sku_id="SKU001",
        pedido_id="PED001",
        cantidad_pallets=2.0,
        altura_full_pallet_cm=150.0,
        altura_picking_cm=0.0,
        peso_kg=1000.0,
        volumen_m3=5.0,
        base=2.0
    )
    
    # SKU 2: 1.5 pallets (1 full + 0.5 picking)
    sku2 = SKU(
        sku_id="SKU002",
        pedido_id="PED001",
        cantidad_pallets=1.5,
        altura_full_pallet_cm=120.0,
        altura_picking_cm=60.0,  # 0.5 × 120
        peso_kg=750.0,
        volumen_m3=3.75,
        superior=1.5
    )
    
    pedido = Pedido(
        pedido="PED001",
        cd="CD1",
        ce="0088",
        po="PO001",
        peso=1750.0,
        volumen=8.75,
        pallets=3.5,
        valor=87500,
        base=2.0,
        superior=1.5,
        skus=[sku1, sku2]
    )
    
    camion = Camion(
        id="CAM001",
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
    
    print(f"\n📦 Camión: {camion.id}")
    print(f"   Pedidos: {len(camion.pedidos)}")
    print(f"   Total SKUs: {sum(len(p.skus) for p in camion.pedidos)}")
    
    # VALIDAR
    valido, errores, layout = validator.validar_camion_rapido(camion)
    
    print(f"\n🔍 Resultado de Validación:")
    print(f"   Válido: {valido}")
    
    if errores:
        print(f"   Errores ({len(errores)}):")
        for error in errores:
            print(f"      - {error}")
    else:
        print(f"   ✅ Sin errores")
    
    if layout:
        print(f"\n📊 Layout del Camión:")
        print(f"   Posiciones totales: {layout.max_posiciones}")
        print(f"   Posiciones usadas: {layout.posiciones_usadas}")
        print(f"   Posiciones vacías: {layout.posiciones_disponibles}")
        print(f"   Altura máxima: {layout.altura_maxima_cm}cm")
        
        print(f"\n   Detalle de posiciones ocupadas:")
        for posicion in layout.posiciones:
            if not posicion.esta_vacia:
                print(f"      Posición {posicion.id}:")
                print(f"         - Pallets: {posicion.num_pallets}")
                print(f"         - Altura: {posicion.altura_usada_cm:.1f}cm / {posicion.altura_maxima_cm}cm")
                print(f"         - Disponible: {posicion.espacio_disponible_cm:.1f}cm")
                
                for i, pallet in enumerate(posicion.pallets_apilados):
                    skus_info = ", ".join([f"{f.sku_id}" for f in pallet.fragmentos])
                    print(f"            Nivel {i}: {skus_info} ({pallet.altura_total_cm:.1f}cm)")
    
    assert valido, f"Debería ser válido: {errores}"
    print("\n✅ Test VÁLIDO pasó correctamente\n")


def test_caso_invalido_excede_altura():
    """Test con camión que NO debería pasar (excede altura)"""
    print("\n" + "="*80)
    print("TEST 2: Camión INVÁLIDO (excede altura)")
    print("="*80)
    
    capacidad = TruckCapacity(
        cap_weight=23000,
        cap_volume=70000,
        max_positions=30,
        max_pallets=60,
        altura_cm=270
    )
    
    # SKU con altura que excede el camión
    sku = SKU(
        sku_id="SKU_ALTO",
        pedido_id="PED002",
        cantidad_pallets=1.0,
        altura_full_pallet_cm=300.0,  # 300cm > 270cm del camión
        altura_picking_cm=0.0,
        peso_kg=500.0,
        volumen_m3=2.5,
        base=1.0
    )
    
    pedido = Pedido(
        pedido="PED002",
        cd="CD1",
        ce="0088",
        po="PO002",
        peso=500.0,
        volumen=2.5,
        pallets=1.0,
        valor=25000,
        base=1.0,
        skus=[sku]
    )
    
    camion = Camion(
        id="CAM002",
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
    
    print(f"\n📦 Camión: {camion.id}")
    print(f"   Pedidos: {len(camion.pedidos)}")
    print(f"   SKU: {sku.sku_id} - Altura: {sku.altura_full_pallet_cm}cm")
    print(f"   Altura máxima camión: {capacidad.altura_cm}cm")
    
    # VALIDAR
    valido, errores, layout = validator.validar_camion_rapido(camion)
    
    print(f"\n🔍 Resultado de Validación:")
    print(f"   Válido: {valido}")
    
    if errores:
        print(f"   ❌ Errores encontrados ({len(errores)}):")
        for error in errores:
            print(f"      - {error}")
    
    assert not valido, "Debería ser INVÁLIDO (excede altura)"
    assert len(errores) > 0, "Debería tener errores"
    assert "excede altura" in errores[0].lower(), "Error debería mencionar altura"
    
    print("\n✅ Test INVÁLIDO detectó el problema correctamente\n")


def test_caso_invalido_muchos_pedidos():
    """Test con camión que NO debería pasar (demasiados pallets para posiciones)"""
    print("\n" + "="*80)
    print("TEST 3: Camión INVÁLIDO (excede posiciones)")
    print("="*80)
    
    capacidad = TruckCapacity(
        cap_weight=23000,
        cap_volume=70000,
        max_positions=5,  # Solo 5 posiciones
        max_pallets=60,
        altura_cm=270
    )
    
    # Crear 10 pedidos con 1 pallet NO_APILABLE cada uno
    # (NO_APILABLE necesita su propia posición)
    pedidos = []
    for i in range(10):
        sku = SKU(
            sku_id=f"SKU_{i:03d}",
            pedido_id=f"PED_{i:03d}",
            cantidad_pallets=1.0,
            altura_full_pallet_cm=200.0,
            altura_picking_cm=0.0,
            peso_kg=500.0,
            volumen_m3=2.5,
            no_apilable=1.0  # NO_APILABLE
        )
        
        pedido = Pedido(
            pedido=f"PED_{i:03d}",
            cd="CD1",
            ce="0088",
            po=f"PO_{i:03d}",
            peso=500.0,
            volumen=2.5,
            pallets=1.0,
            valor=25000,
            no_apilable=1.0,
            skus=[sku]
        )
        pedidos.append(pedido)
    
    camion = Camion(
        id="CAM003",
        tipo_ruta=TipoRuta.NORMAL,
        tipo_camion=TipoCamion.NORMAL,
        cd=["CD1"],
        ce=["0088"],
        grupo="test",
        capacidad=capacidad,
        pedidos=pedidos
    )
    
    validator = HeightValidator(
        altura_maxima_cm=capacidad.altura_cm,
        permite_consolidacion=False
    )
    
    print(f"\n📦 Camión: {camion.id}")
    print(f"   Pedidos: {len(camion.pedidos)}")
    print(f"   Total pallets NO_APILABLE: {len(pedidos)}")
    print(f"   Posiciones disponibles: {capacidad.max_positions}")
    print(f"   Problema esperado: 10 pallets NO_APILABLE necesitan 10 posiciones, pero solo hay 5")
    
    # VALIDAR
    valido, errores, layout = validator.validar_camion_rapido(camion)
    
    print(f"\n🔍 Resultado de Validación:")
    print(f"   Válido: {valido}")
    
    if errores:
        print(f"   ❌ Errores encontrados ({len(errores)}):")
        for error in errores:
            print(f"      - {error}")
    
    assert not valido, "Debería ser INVÁLIDO (excede posiciones)"
    assert len(errores) > 0, "Debería tener errores"
    
    print("\n✅ Test INVÁLIDO detectó el problema correctamente\n")


if __name__ == "__main__":
    print("\n" + "🧪"*40)
    print("TESTS MANUALES DE VALIDACIÓN DE ALTURA")
    print("🧪"*40)
    
    try:
        test_caso_valido()
        test_caso_invalido_excede_altura()
        test_caso_invalido_muchos_pedidos()
        
        print("\n" + "✅"*40)
        print("TODOS LOS TESTS PASARON CORRECTAMENTE")
        print("✅"*40 + "\n")
    
    except AssertionError as e:
        print(f"\n❌ TEST FALLÓ: {e}\n")
    except Exception as e:
        print(f"\n💥 ERROR INESPERADO: {e}\n")
        import traceback
        traceback.print_exc()