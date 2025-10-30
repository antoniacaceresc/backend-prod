# test_vcu_validation.py
"""Test de validación de VCU máximo (100%)"""

from services.postprocess import move_orders
from services.models import Pedido, Camion, TruckCapacity, TipoCamion, TipoRuta

# Crear estado de test
state = {
    "camiones": [
        {
            "id": "cam001",
            "numero": 1,
            "tipo_ruta": "normal",
            "tipo_camion": "normal",
            "cd": ["6009 Lo Aguirre"],
            "ce": ["0088"],
            "grupo": "test",
            "pedidos": [
                {
                    "PEDIDO": "PED001",
                    "CD": "6009 Lo Aguirre",
                    "CE": "0088",
                    "PO": "PO001",
                    "PESO": 20000,  # 87% de 23000
                    "VOL": 60000,   # 86% de 70000
                    "PALLETS": 50,
                    "VALOR": 1000000,
                    "BASE": 10,
                    "SUPERIOR": 10,
                    "FLEXIBLE": 5,
                    "NO_APILABLE": 0,
                    "SI_MISMO": 0,
                }
            ],
            "opciones_tipo_camion": ["normal"]
        }
    ],
    "pedidos_no_incluidos": [
        {
            "PEDIDO": "PED002",
            "CD": "6009 Lo Aguirre",
            "CE": "0088",
            "PO": "PO002",
            "PESO": 5000,   # Si se suma: 25000 / 23000 = 108% ❌
            "VOL": 15000,   # Si se suma: 75000 / 70000 = 107% ❌
            "PALLETS": 12,
            "VALOR": 1500000,
            "BASE": 5,
            "SUPERIOR": 5,
            "FLEXIBLE": 2,
            "NO_APILABLE": 0,
            "SI_MISMO": 0,
        }
    ]
}

print("Test: Intentar agregar pedido que excede 100% VCU\n")

try:
    result = move_orders(
        state,
        [state["pedidos_no_incluidos"][0]],  # Intentar agregar PED002
        "cam001",
        "walmart"
    )
    
    # Si llegamos aquí, NO debería haber pasado
    print("❌ ERROR: Se permitió agregar pedido que excede 100%")
    print(f"   VCU resultante: {result['camiones'][0].get('vcu_max', 0)*100:.1f}%")
    
except ValueError as e:
    print(f"✅ Validación correcta - Se rechazó el pedido:")
    print(f"   Razón: {e}\n")

print("\nTest: Agregar pedido que SÍ cabe\n")

# Cambiar a un pedido más pequeño
state["pedidos_no_incluidos"][0]["PESO"] = 2000   # 22000 / 23000 = 96% ✓
state["pedidos_no_incluidos"][0]["VOL"] = 8000    # 68000 / 70000 = 97% ✓

try:
    result = move_orders(
        state,
        [state["pedidos_no_incluidos"][0]],
        "cam001",
        "walmart"
    )
    
    vcu_final = result['camiones'][0].get('vcu_max', 0)
    print(f"✅ Pedido agregado correctamente")
    print(f"   VCU final: {vcu_final*100:.1f}%")
    print(f"   Pedidos en camión: {len(result['camiones'][0]['pedidos'])}")
    
    if vcu_final <= 1.0:
        print("✅ VCU dentro del límite (≤100%)\n")
    else:
        print(f"❌ ERROR: VCU excede 100%: {vcu_final*100:.1f}%\n")
        
except ValueError as e:
    print(f"❌ ERROR: Se rechazó pedido que SÍ cabía:")
    print(f"   Razón: {e}\n")