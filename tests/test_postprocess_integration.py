# tests/test_postprocess_integration.py
"""
Tests de integración de postproceso con validación física.
Verifica que las operaciones del usuario respeten reglas de apilabilidad.
"""
import pytest
from services.postprocess import (
    move_orders,
    apply_truck_type_change,
    add_truck,
    delete_truck,
    compute_stats
)


# ============================================================
# FIXTURES Y HELPERS
# ============================================================

@pytest.fixture
def estado_inicial_walmart():
    """Estado inicial con 2 camiones para Walmart"""
    return {
        "camiones": [
            {
                "id": "cam001",
                "tipo_camion": "normal",
                "tipo_ruta": "normal",
                "cd": ["6009 Lo Aguirre"],
                "ce": ["0088"],
                "vcu_vol": 0.5,
                "vcu_peso": 0.4,
                "vcu_max": 0.5,
                "pedidos": [
                    {
                        "PEDIDO": "PED001",
                        "CD": "6009 Lo Aguirre",
                        "CE": "0088",
                        "OC": "INV",
                        "PALLETS": 10,
                        "VOL": 35000,
                        "PESO": 11500,
                        "VCU_VOL": 0.5,
                        "VCU_PESO": 0.5,
                        "SKUS": [
                            {"sku": "SKU001", "pallets": 5.0, "tipo_apilabilidad": "BASE", "altura_pallet": 120},
                            {"sku": "SKU002", "pallets": 5.0, "tipo_apilabilidad": "SUPERIOR", "altura_pallet": 100}
                        ]
                    }
                ]
            },
            {
                "id": "cam002",
                "tipo_camion": "normal",
                "tipo_ruta": "normal",
                "cd": ["6009 Lo Aguirre"],
                "ce": ["0088"],
                "vcu_vol": 0.3,
                "vcu_peso": 0.3,
                "vcu_max": 0.3,
                "pedidos": [
                    {
                        "PEDIDO": "PED002",
                        "CD": "6009 Lo Aguirre",
                        "CE": "0088",
                        "OC": "INV",
                        "PALLETS": 5,
                        "VOL": 21000,
                        "PESO": 6900,
                        "VCU_VOL": 0.3,
                        "VCU_PESO": 0.3,
                        "SKUS": [
                            {"sku": "SKU003", "pallets": 5.0, "tipo_apilabilidad": "FLEXIBLE", "altura_pallet": 110}
                        ]
                    }
                ]
            }
        ],
        "pedidos_no_incluidos": [
            {
                "PEDIDO": "PED003",
                "CD": "6009 Lo Aguirre",
                "CE": "0088",
                "OC": "INV",
                "PALLETS": 3,
                "VOL": 12000,
                "PESO": 4500,
                "VCU_VOL": 0.17,
                "VCU_PESO": 0.19,
                "SKUS": [
                    {"sku": "SKU004", "pallets": 3.0, "tipo_apilabilidad": "BASE", "altura_pallet": 120}
                ]
            }
        ]
    }


# ============================================================
# TESTS DE move_orders
# ============================================================

def test_move_orders_caben_fisicamente(estado_inicial_walmart):
    """Test: mover pedido que SÍ cabe físicamente"""
    state = estado_inicial_walmart
    
    # Mover PED003 (3 pallets BASE) a cam002 (que tiene espacio)
    pedidos_mover = [state["pedidos_no_incluidos"][0]]
    
    resultado = move_orders(
        state=state,
        pedidos=pedidos_mover,
        target_truck_id="cam002",
        cliente="walmart"
    )
    
    # Verificar que movimiento fue exitoso
    cam002 = next(c for c in resultado["camiones"] if c["id"] == "cam002")
    assert len(cam002["pedidos"]) == 2  # PED002 + PED003
    assert "PED003" in [p["PEDIDO"] for p in cam002["pedidos"]]
    
    # Verificar que métricas físicas fueron actualizadas
    assert "pos_usadas_reales" in cam002
    assert cam002["pos_usadas_reales"] > 0
    assert "altura_maxima" in cam002
    
    # Verificar que pedido ya no está en no_incluidos
    assert len(resultado["pedidos_no_incluidos"]) == 0


def test_move_orders_no_caben_fisicamente(estado_inicial_walmart):
    """Test: rechazar movimiento que NO cabe físicamente"""
    state = estado_inicial_walmart
    state["camiones"][0]["pedidos"] = []
    # Crear pedidos que exceden capacidad física
    pedidos_grandes = [
        {
            "PEDIDO": f"PED_BIG{i}",
            "CD": "6009 Lo Aguirre",
            "CE": "0088",
            "OC": "INV",
            "PALLETS": 1,
            "VOL": 5000,
            "PESO": 2000,
            "VCU_VOL": 0.07,
            "VCU_PESO": 0.08,
            "SKUS": [
                {"sku": f"SKU_BIG{i}", "pallets": 1.0, "tipo_apilabilidad": "NO_APILABLE", "altura_pallet": 200}
            ]
        }
        for i in range(35)  # 35 NO_APILABLE (excede 30 posiciones)
    ]
    
    state["pedidos_no_incluidos"] = pedidos_grandes
    
    # Intentar mover 35 pedidos NO_APILABLE a cam001 (max 30 posiciones)
    with pytest.raises(ValueError, match="No caben todos los pedidos|No se puede realizar el movimiento"):
        move_orders(
            state=state,
            pedidos=pedidos_grandes[:35],
            target_truck_id="cam001",
            cliente="walmart"
        )


def test_move_orders_a_no_incluidos(estado_inicial_walmart):
    """Test: mover pedidos de camión a no_incluidos"""
    state = estado_inicial_walmart
    
    # Mover PED001 de cam001 a no_incluidos
    pedidos_mover = [state["camiones"][0]["pedidos"][0]]
    
    resultado = move_orders(
        state=state,
        pedidos=pedidos_mover,
        target_truck_id=None,  # None = mover a no_incluidos
        cliente="walmart"
    )
    
    # Verificar
    cam001 = next(c for c in resultado["camiones"] if c["id"] == "cam001")
    assert len(cam001["pedidos"]) == 0  # Vacío
    assert len(resultado["pedidos_no_incluidos"]) == 2  # PED003 + PED001


# ============================================================
# TESTS DE apply_truck_type_change
# ============================================================

def test_cambio_tipo_valido(estado_inicial_walmart):
    """Test: cambiar tipo normal → bh (válido)"""
    state = estado_inicial_walmart
    
    # cam002 tiene VCU=0.3 (puede ser BH si VCU < BH_VCU_MAX)
    resultado = apply_truck_type_change(
        state=state,
        truck_id="cam002",
        new_type="bh",
        cliente="walmart"
    )
    
    # Verificar cambio exitoso
    cam002 = next(c for c in resultado["camiones"] if c["id"] == "cam002")
    assert cam002["tipo_camion"] == "bh"
    
    # Verificar métricas recalculadas
    assert "pos_usadas_reales" in cam002
    assert "eficiencia_posiciones_fisica" in cam002


def test_cambio_tipo_invalido_posiciones(estado_inicial_walmart):
    """Test: rechazar cambio si excede posiciones del nuevo tipo"""
    state = estado_inicial_walmart
    print("PEDIDOS")
    print(state["camiones"][0]["pedidos"])
    # Crear camión con muchos NO_APILABLE (ocupan 25 posiciones)
    state["camiones"][0]["pedidos"] = [
        {
            "PEDIDO": f"PED_NA{i}",
            "CD": "6009 Lo Aguirre",
            "CE": "0088",
            "OC": "INV",
            "PALLETS": 1,
            "VOL": 2000,
            "PESO": 800,
            "VCU_VOL": 0.03,
            "VCU_PESO": 0.03,
            "SKUS": [
                {"sku": f"SKU_NA{i}", "pallets": 1.0, "tipo_apilabilidad": "NO_APILABLE", "altura_pallet": 120}
            ]
        }
        for i in range(29)  # 29 NO_APILABLE
    ]
    
    # Intentar cambiar a BH (max_positions=28 en Walmart)
    with pytest.raises(ValueError, match="posiciones ocupadas|No caben todos los pedidos|No se puede cambiar"):
        apply_truck_type_change(
            state=state,
            truck_id="cam001",
            new_type="bh",
            cliente="walmart"
        )


# ============================================================
# TESTS DE add_truck
# ============================================================

def test_add_truck_con_metricas_fisicas(estado_inicial_walmart):
    """Test: agregar camión vacío con métricas físicas inicializadas"""
    state = estado_inicial_walmart
    
    resultado = add_truck(
        state=state,
        cd=["6009 Lo Aguirre"],
        ce=["0088"],
        ruta="normal",
        cliente="walmart"
    )
    
    # Verificar que se agregó
    assert len(resultado["camiones"]) == 3
    
    # Verificar nuevo camión
    nuevo = resultado["camiones"][-1]
    assert nuevo["tipo_camion"] == "normal"
    assert len(nuevo["pedidos"]) == 0
    
    # Verificar métricas físicas inicializadas
    assert nuevo["pos_usadas_reales"] == 0
    assert nuevo["altura_maxima"] == 0.0
    assert nuevo["pallets_fisicos"] == 0
    assert nuevo["eficiencia_posiciones_fisica"] == 0.0
    assert nuevo["eficiencia_altura_fisica"] == 0.0


# ============================================================
# TESTS DE delete_truck
# ============================================================

def test_delete_truck(estado_inicial_walmart):
    """Test: eliminar camión mueve pedidos a no_incluidos"""
    state = estado_inicial_walmart
    
    resultado = delete_truck(
        state=state,
        truck_id="cam001",
        cliente="walmart"
    )
    
    # Verificar que camión fue eliminado
    assert len(resultado["camiones"]) == 1
    assert "cam001" not in [c["id"] for c in resultado["camiones"]]
    
    # Verificar que pedidos fueron movidos a no_incluidos
    assert len(resultado["pedidos_no_incluidos"]) == 2  # PED003 + PED001


# ============================================================
# TESTS DE CASOS EDGE
# ============================================================

def test_consolidacion_multiple_skus(estado_inicial_walmart):
    """Test: validación física con consolidación de SKUs"""
    state = estado_inicial_walmart
    
    # Pedido con múltiples SKUs incompletos (consolidables)
    pedido_consolidable = {
        "PEDIDO": "PED_CONSOL",
        "CD": "6009 Lo Aguirre",
        "CE": "0088",
        "OC": "INV",
        "PALLETS": 1.0,
        "VOL": 10000,
        "PESO": 4000,
        "VCU_VOL": 0.14,
        "VCU_PESO": 0.17,
        "SKUS": [
            {"sku": "SKU_A", "pallets": 0.3, "tipo_apilabilidad": "FLEXIBLE", "altura_pallet": 120},
            {"sku": "SKU_B", "pallets": 0.3, "tipo_apilabilidad": "FLEXIBLE", "altura_pallet": 120},
            {"sku": "SKU_C", "pallets": 0.4, "tipo_apilabilidad": "FLEXIBLE", "altura_pallet": 120},
        ]
    }
    
    state["pedidos_no_incluidos"] = [pedido_consolidable]
    
    # Mover a cam002 (con consolidación permitida en Walmart)
    resultado = move_orders(
        state=state,
        pedidos=[pedido_consolidable],
        target_truck_id="cam002",
        cliente="walmart"
    )
    
    # Verificar éxito
    cam002 = next(c for c in resultado["camiones"] if c["id"] == "cam002")
    assert "PED_CONSOL" in [p["PEDIDO"] for p in cam002["pedidos"]]


def test_cencosud_sin_consolidacion():
    """Test: Cencosud no permite consolidación de SKUs"""
    state = {
        "camiones": [
            {
                "id": "cam001",
                "tipo_camion": "normal",
                "tipo_ruta": "normal",
                "cd": ["N725 Bodega Noviciado"],
                "ce": ["0088"],
                "vcu_vol": 0.0,
                "vcu_peso": 0.0,
                "vcu_max": 0.0,
                "pedidos": []
            }
        ],
        "pedidos_no_incluidos": []
    }
    
    # Pedido con SKUs incompletos
    pedido = {
        "PEDIDO": "PED001",
        "CD": "N725 Bodega Noviciado",
        "CE": "0088",
        "PALLETS": 1.0,
        "VOL": 10000,
        "PESO": 4000,
        "VCU_VOL": 0.14,
        "VCU_PESO": 0.17,
        "SKUS": [
            {"sku": "SKU_A", "pallets": 0.5, "tipo_apilabilidad": "BASE", "altura_pallet": 120},
            {"sku": "SKU_B", "pallets": 0.5, "tipo_apilabilidad": "SUPERIOR", "altura_pallet": 100},
        ]
    }
    
    state["pedidos_no_incluidos"] = [pedido]
    
    # Mover (Cencosud no consolida, pero puede apilar BASE+SUPERIOR verticalmente)
    resultado = move_orders(
        state=state,
        pedidos=[pedido],
        target_truck_id="cam001",
        cliente="cencosud"
    )
    
    # Verificar éxito
    cam001 = next(c for c in resultado["camiones"] if c["id"] == "cam001")
    assert "PED001" in [p["PEDIDO"] for p in cam001["pedidos"]]


# Test adicional para validar restricción de altura con apilamiento forzado
# Agregar este test a test_postprocess_integration.py

def test_altura_maxima_apilamiento_forzado(estado_inicial_walmart):
    """
    Test: Verificar que NO se pueden apilar 3 pallets del mismo SKU 
    si la suma de alturas excede el máximo permitido (240cm).
    
    Este test FUERZA el apilamiento usando un camión con pocas posiciones
    y muchos pallets del mismo SKU tipo SI_MISMO.
    """
    state = estado_inicial_walmart
    
    # Configurar camión con capacidad limitada de posiciones
    # Vamos a forzar que intente apilar usando un camión BH (28 posiciones)
    state["camiones"][0]["tipo_camion"] = "bh"
    
    # Crear exactamente 29 pallets del mismo SKU tipo SI_MISMO con altura 125cm
    # Lógica:
    # - Camión BH tiene 28 posiciones
    # - 29 pallets necesitan al menos 29 posiciones sin apilar
    # - Para caber en 28 posiciones, DEBE apilar al menos 2 pallets
    # - 2 pallets × 125cm = 250cm > 240cm máximo → DEBE FALLAR
    state["camiones"][0]["pedidos"] = [
        {
            "PEDIDO": f"PED_ALTO{i}",
            "CD": "6009 Lo Aguirre",
            "CE": "0088",
            "OC": "INV",
            "PALLETS": 1,
            "VOL": 3000,
            "PESO": 1500,
            "VCU_VOL": 0.04,
            "VCU_PESO": 0.06,
            "SKUS": [
                {
                    "sku": "SKU_ALTO_MISMO",  # Mismo SKU para todos
                    "pallets": 1.0, 
                    "tipo_apilabilidad": "SI_MISMO",  # Permite apilamiento vertical
                    "altura_pallet": 125  # 2 × 125 = 250cm > 240cm
                }
            ]
        }
        for i in range(29)  # 29 pallets del mismo SKU
    ]
    
    # Al intentar cambiar a tipo "normal" (o mantener "bh"), 
    # el validador debe rechazar porque no puede colocar 29 pallets
    # sin exceder la altura máxima
    with pytest.raises(ValueError, match="No caben todos los pedidos|no cabe|altura"):
        apply_truck_type_change(
            state=state,
            truck_id="cam001",
            new_type="bh",
            cliente="walmart"
        )


def test_altura_maxima_con_3_pallets_exactos():
    """
    Test ESPECÍFICO: Validar que 3 pallets de 130cm NO se pueden apilar 
    en una sola posición porque 3×130=390cm > 240cm.
    
    Este test crea un escenario simple y directo usando el StackingValidator.
    """
    from services.stacking_validator import (
        StackingValidator, FragmentoSKU, TipoApilabilidad,
        validar_pedidos_en_camion
    )
    
    # Crear un pedido con exactamente 3 pallets completos del mismo SKU
    pedido_data = [
        {
            "PEDIDO": "PED_3PALLETS",
            "CD": "6009 Lo Aguirre",
            "CE": "0088",
            "OC": "INV",
            "PALLETS": 3,
            "VOL": 15000,
            "PESO": 6000,
            "VCU_VOL": 0.21,
            "VCU_PESO": 0.26,
            "SKUS": [
                {
                    "sku": "SKU_ALTO_3X",
                    "pallets": 3.0,  # 3 pallets completos
                    "tipo_apilabilidad": "SI_MISMO",
                    "altura_pallet": 130  # 3 × 130 = 390cm > 240cm
                }
            ]
        }
    ]
    
    # Validar con un camión que solo tiene 2 posiciones disponibles
    # Esto FUERZA que intente apilar los 3 pallets
    validator = StackingValidator(
        max_positions=2,  # Solo 2 posiciones disponibles
        max_altura=240,   # Altura máxima estándar
        permite_consolidacion=True,
        max_skus_por_pallet=5
    )
    
    # Extraer fragmentos
    from services.stacking_validator import extraer_fragmentos_de_pedidos
    fragmentos = extraer_fragmentos_de_pedidos(pedido_data)
    
    # Validar
    resultado = validator.validar_pedidos(fragmentos)
    
    # Verificación: 3 pallets de 130cm no pueden apilarse todos juntos
    # Opciones de resultado:
    # 1. Si caben: debe usar más de 1 posición (porque 3×130=390 > 240)
    # 2. Si no caben: el pedido debe estar rechazado
    
    if resultado.cabe:
        # Si cabe, debe usar 2 posiciones (2 pallets en una + 1 en otra)
        # porque no puede apilar los 3 juntos
        assert resultado.posiciones_usadas >= 2, \
            f"Con 3 pallets de 130cm, debe usar al menos 2 posiciones. Usó: {resultado.posiciones_usadas}"
        
        # Verificar que ninguna posición tiene altura > 240cm
        for pos in resultado.layout:
            if not pos.esta_vacia():
                assert pos.altura_usada <= 240, \
                    f"Posición {pos.index} excede altura máxima: {pos.altura_usada}cm > 240cm"
    else:
        # Si no cabe, el pedido debe estar rechazado
        assert "PED_3PALLETS" in resultado.pedidos_rechazados, \
            "El pedido con 3 pallets de 130cm debería estar rechazado si no cabe"


def test_altura_maxima_con_multiples_configuraciones():
    """
    Test EXHAUSTIVO: Probar múltiples configuraciones de pallets 
    para validar que la restricción de altura se respeta siempre.
    """
    from services.stacking_validator import (
        StackingValidator, FragmentoSKU, TipoApilabilidad
    )
    
    # Configuraciones de prueba: (num_pallets, altura_cada_uno, debe_caber)
    casos = [
        (2, 120, True),   # 2×120=240 → Justo en el límite, debe caber
        (2, 125, False),  # 2×125=250 > 240 → NO debe poder apilarlos juntos
        (3, 80, True),    # 3×80=240 → Justo en el límite, debe caber
        (3, 85, False),   # 3×85=255 > 240 → NO debe poder apilarlos juntos
        (3, 130, False),  # 3×130=390 > 240 → NO debe poder apilarlos juntos
        (4, 60, True),    # 4×60=240 → Justo en el límite, debe caber
        (4, 65, False),   # 4×65=260 > 240 → NO debe poder apilarlos juntos
    ]
    
    for num_pallets, altura, debe_caber_apilados in casos:
        # Crear fragmentos
        fragmentos_por_pedido = {
            "PED_TEST": [
                FragmentoSKU(
                    sku="SKU_TEST",
                    pedido="PED_TEST",
                    cantidad=1.0,
                    tipo=TipoApilabilidad.SI_MISMO,
                    altura=float(altura)
                )
                for _ in range(num_pallets)
            ]
        }
        
        # Validador con solo 1 posición disponible (fuerza apilamiento)
        validator = StackingValidator(
            max_positions=1,  # Solo 1 posición → DEBE apilar todos
            max_altura=240,
            permite_consolidacion=True,
            max_skus_por_pallet=5
        )
        
        resultado = validator.validar_pedidos(fragmentos_por_pedido)
        
        altura_total = num_pallets * altura
        
        if debe_caber_apilados:
            # Debe caber porque altura_total <= 240
            assert resultado.cabe, \
                f"FALLO: {num_pallets} pallets × {altura}cm = {altura_total}cm <= 240cm → debería CABER"
            assert "PED_TEST" in resultado.pedidos_incluidos
            assert resultado.posiciones_usadas == 1, \
                f"Con 1 posición disponible y pallets que caben, debe usar 1 posición"
        else:
            # NO debe caber porque altura_total > 240
            assert not resultado.cabe or "PED_TEST" in resultado.pedidos_rechazados, \
                f"FALLO: {num_pallets} pallets × {altura}cm = {altura_total}cm > 240cm → NO debería caber en 1 posición"



# Ejecutar: python -m pytest tests/test_postprocess_integration.py -v