"""Test de validación integrada con optimización"""











"""

Este test nunca funcionó pero lo dejo de backup



"""
import os
import tempfile
import glob
import pandas as pd
from io import BytesIO
from services.file_processor import read_file, process_dataframe
from clients.walmart import WalmartConfig
from models.domain import TruckCapacity
from optimization.validation.height_validator import HeightValidator


def limpiar_cache_excel():
    """Limpia cache de Excel para forzar nueva lectura"""
    cache_dir = os.getenv("PARQUET_CACHE_DIR") or tempfile.gettempdir()
    cache_files = glob.glob(os.path.join(cache_dir, "excel_cache_*.parquet"))
    
    eliminados = 0
    for f in cache_files:
        try:
            os.remove(f)
            eliminados += 1
        except Exception as e:
            print(f"⚠️  No se pudo eliminar {os.path.basename(f)}: {e}")
    
    if eliminados > 0:
        print(f"🗑️  Cache limpiado: {eliminados} archivo(s) eliminado(s)\n")


def test_validacion_con_excel_real():
    """Test con Excel real del proyecto"""
    
    # ✅ Limpiar cache al inicio
    limpiar_cache_excel()
    
    print("=" * 80)
    print("TEST: Validación con Excel Real")
    print("=" * 80)
    
    # Configuración
    archivo = "ejemplo.xlsx"
    hoja = "SECOS"
    cliente_config = WalmartConfig
    
    # 1. Verificar archivo
    print(f"\n1️⃣ Verificando archivo...")
    print(f"   Archivo: {archivo}")
    
    with open(archivo, "rb") as f:
        content = f.read()
    
    xls = pd.ExcelFile(BytesIO(content), engine="openpyxl")
    print(f"   Hojas disponibles: {xls.sheet_names}")
    
    if hoja not in xls.sheet_names:
        hoja_upper = hoja.upper()
        if hoja_upper in xls.sheet_names:
            print(f"   📝 Usando '{hoja_upper}' en vez de '{hoja}'")
            hoja = hoja_upper
    
    print(f"   ✅ Usando hoja: {hoja}")
    
    # 2. Leer Excel
    print(f"\n2️⃣ Leyendo datos...")
    df_raw = read_file(content, archivo, cliente_config, hoja)
    
    print(f"   ✅ DataFrame leído: {len(df_raw)} filas")
    print(f"   ✅ Columnas leídas: {len(df_raw.columns)}")
    
    df_proc, pedidos_dicts = process_dataframe(df_raw, cliente_config, "walmart", hoja)
    
    print(f"   ✅ Pedidos procesados: {len(df_proc)}")
    
    total_skus = sum(len(p.get('_skus', [])) for p in pedidos_dicts)
    print(f"   ✅ Total SKUs: {total_skus}")
    
    if total_skus == 0:
        print(f"   ⚠️  No se encontraron SKUs (archivo legacy)")
    
    # 3. Convertir a objetos Pedido
    print(f"\n3️⃣ Construyendo objetos Pedido...")
    from optimization.orchestrator import _dataframe_a_pedidos
    pedidos = _dataframe_a_pedidos(df_proc, pedidos_dicts)
    
    pedidos_con_skus = [p for p in pedidos if p.tiene_skus]
    pedidos_legacy = [p for p in pedidos if not p.tiene_skus]
    
    print(f"   ✅ Pedidos con SKUs: {len(pedidos_con_skus)}")
    print(f"   ✅ Pedidos legacy: {len(pedidos_legacy)}")
    
    if len(pedidos_con_skus) == 0:
        print(f"\n   ⚠️  Usando pedidos legacy para el test...")
        pedidos_prueba = pedidos_legacy[:5]
    else:
        pedidos_prueba = pedidos_con_skus[:5]
    
    # 4. Crear camión
    print(f"\n4️⃣ Creando camión de prueba...")
    from models.domain import Camion
    from models.enums import TipoRuta, TipoCamion
    
    capacidad = TruckCapacity.from_config(cliente_config.TRUCK_TYPES['normal'])
    
    camion = Camion(
        id="CAM_TEST",
        tipo_ruta=TipoRuta.NORMAL,
        tipo_camion=TipoCamion.NORMAL,
        cd=[pedidos_prueba[0].cd],
        ce=[pedidos_prueba[0].ce],
        grupo="test",
        capacidad=capacidad,
        pedidos=pedidos_prueba
    )
    
    print(f"   ✅ Camión creado con {len(camion.pedidos)} pedidos")
    total_skus_camion = sum(len(p.skus) for p in camion.pedidos)
    print(f"   ✅ Total SKUs en camión: {total_skus_camion}")
    
    # 5. VALIDAR
    print(f"\n5️⃣ Validando altura...")
    validator = HeightValidator(
        altura_maxima_cm=capacidad.altura_cm,
        permite_consolidacion=cliente_config.PERMITE_CONSOLIDACION,
        max_skus_por_pallet=cliente_config.MAX_SKUS_POR_PALLET
    )
    
    valido, errores, layout = validator.validar_camion_rapido(camion)
    
    print(f"\n🔍 Resultado de Validación:")
    print(f"   Válido: {'✅ SÍ' if valido else '❌ NO'}")
    
    if errores:
        print(f"\n   Errores ({len(errores)}):")
        for error in errores:
            print(f"      - {error}")
    
    if layout:
        print(f"\n📊 Layout del Camión:")
        print(f"   Posiciones usadas: {layout.posiciones_usadas} / {layout.max_posiciones}")
        print(f"   Altura máxima: {layout.altura_maxima_cm}cm")
        
        posiciones_ocupadas = [p for p in layout.posiciones if not p.esta_vacia][:5]
        if posiciones_ocupadas:
            print(f"\n   Primeras posiciones ocupadas:")
            for pos in posiciones_ocupadas:
                print(f"      Pos {pos.id}: {pos.num_pallets} pallets, {pos.altura_usada_cm:.1f}cm")
    
    print("\n" + "=" * 80)
    return valido, errores, layout


if __name__ == "__main__":
    try:
        valido, errores, layout = test_validacion_con_excel_real()
        
        if valido:
            print("\n✅ VALIDACIÓN EXITOSA")
        else:
            print("\n⚠️  VALIDACIÓN FALLÓ")
    
    except FileNotFoundError as e:
        print(f"\n❌ Archivo no encontrado: {e}")
    except Exception as e:
        print(f"\n💥 ERROR: {e}")
        import traceback
        traceback.print_exc()