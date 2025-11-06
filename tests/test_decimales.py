# test_decimales_apilabilidad.py
import pandas as pd
from services.file_processor import _limpiar_datos_skus
from clients.walmart import WalmartConfig

# DataFrame de prueba con decimales
df_test = pd.DataFrame({
    "PEDIDO": ["PED001", "PED001"],
    "SKU": ["SKU_A", "SKU_B"],
    "PALLETS": [0.38, 0.62],
    "BASE": [0.38, 0.0],     # ← Valor decimal pequeño
    "SUPERIOR": [0.0, 0.62],
    "FLEXIBLE": [0.0, 0.0],
    "NO_APILABLE": [0.0, 0.0],
    "SI_MISMO": [0.0, 0.0],
    "ALTURA_FULL_PALLET": [150.0, 150.0],
    "ALTURA_PICKING": [57.0, 93.0],  # 0.38×150, 0.62×150
    "PESO": [190.0, 310.0],
    "VOL": [0.95, 1.55],
    "VALOR": [9500, 15500],
    "VALOR_CAFE": [0, 0],
    "CD": ["CD1", "CD1"],
    "CE": ["0088", "0088"],
    "PO": ["PO001", "PO001"],
    "CHOCOLATES_FLAG": [0, 0],
    "PDQ": [0, 0],
    "VALIOSO": [0, 0],
    "BAJA_VU": [0, 0],
    "LOTE_DIR": [0, 0],
})

print("=" * 80)
print("TEST: Preservación de Decimales en Apilabilidad")
print("=" * 80)

print("\n1️⃣ Datos originales:")
print(df_test[['SKU', 'PALLETS', 'BASE', 'SUPERIOR']])

print("\n2️⃣ Después de limpieza:")
df_limpio = _limpiar_datos_skus(df_test)
print(df_limpio[['SKU', 'PALLETS', 'BASE', 'SUPERIOR']])

print("\n3️⃣ Verificación:")
for _, row in df_limpio.iterrows():
    sku = row['SKU']
    base = row['BASE']
    print(f"   {sku}: BASE = {base:.4f} {'✅' if base > 0 else '❌'}")