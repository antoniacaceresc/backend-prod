# services/file_processor.py
from __future__ import annotations

import os
import hashlib
import tempfile
from io import BytesIO
from typing import Tuple, List, Dict, Any

import pandas as pd

# === Helpers de caché ===

def _make_cache_sig(content: bytes, sheet_name: str, cols: List[str]) -> str:
    h = hashlib.md5()
    h.update(content)
    h.update(b"|")
    h.update(sheet_name.encode("utf-8"))
    h.update(b"|")
    h.update("|".join(sorted(cols)).encode("utf-8"))
    return h.hexdigest()


def _cache_path(sig: str) -> str:
    base = os.getenv("PARQUET_CACHE_DIR") or tempfile.gettempdir()
    return os.path.join(base, f"excel_cache_{sig}.parquet")


# === Lectura de Excel optimizada ===

def read_file(content: bytes, filename: str, client_config, venta: str) -> pd.DataFrame:
    sheet_name = venta.upper()
    header_row = client_config.HEADER_ROW

    mapping = build_column_mapping(client_config, venta)
    wanted_cols = list(mapping.values())

    try:
        if not filename.endswith((".xlsx", ".xlsm")):
            raise ValueError("Formato de archivo no soportado")

        xls = pd.ExcelFile(BytesIO(content), engine="openpyxl")
        header_only = xls.parse(sheet_name=sheet_name, header=header_row, nrows=0)

        available_cols = [c for c in wanted_cols if c in header_only.columns]
        missing_cols = [c for c in wanted_cols if c not in header_only.columns]
        if missing_cols:
            print(f"[WARN] Columnas ausentes (se omiten): {missing_cols}")

        # Cache parquet por archivo-hoja-columnas
        sig = _make_cache_sig(content, sheet_name, available_cols)
        cpath = _cache_path(sig)
        if os.path.exists(cpath) and os.getenv("EXCEL_CACHE_DISABLE", "false").lower() != "true":
            try:
                return pd.read_parquet(cpath)
            except Exception as e:
                print(f"[WARN] Falló leer cache parquet ({e}); releyendo Excel…")

        # Tipos para evitar inferencia costosa
        text_internals = {"PEDIDO", "CD", "CE", "OC"}
        dtype_hint: Dict[str, str] = {}
        for internal in text_internals:
            excel_name = mapping.get(internal)
            if excel_name in available_cols:
                dtype_hint[excel_name] = "string"

        df = xls.parse(
            sheet_name=sheet_name,
            header=header_row,
            usecols=available_cols,
            dtype=dtype_hint,
        )

        if os.getenv("EXCEL_CACHE_DISABLE", "false").lower() != "true":
            try:
                df.to_parquet(cpath, index=False)
            except Exception as e:
                print(f"[WARN] No se pudo escribir cache parquet ({e}).")

        return df

    except Exception as e:
        print(f"[ERROR] Al leer el Excel: {e}")
        raise


# === Transformaciones ===

def build_column_mapping(client_config, venta: str) -> Dict[str, str]:
    col_map = client_config.COLUMN_MAPPING[venta]
    extra_map = client_config.EXTRA_MAPPING
    return {**extra_map, **col_map}


def warn_missing_columns(df: pd.DataFrame, mapping: Dict[str, str]) -> List[str]:
    missing = [excel_name for excel_name in mapping.values() if excel_name not in df.columns]
    if missing:
        print(f"[WARN] Columnas en Excel no encontradas (se omiten): {missing}")
    return missing


def process_dataframe(
    df_full: pd.DataFrame, 
    client_config, 
    cliente: str, 
    venta: str
) -> Tuple[pd.DataFrame, List[Dict[str, Any]], Dict[str, List[Dict]]]:
    """
    Procesa DataFrame con detalle de SKUs.
    
    Returns:
        (df_proc, raw_pedidos, skus_detalle)
        - df_proc: DataFrame agregado por pedido (para CP-SAT)
        - raw_pedidos: Lista de pedidos agregados
        - skus_detalle: Detalle de SKUs por pedido
    """
    mapping = build_column_mapping(client_config, venta)
    rename_map = {excel: internal for internal, excel in mapping.items() if excel in df_full.columns}
    warn_missing_columns(df_full, mapping)

    df_raw = df_full[list(rename_map.keys())].rename(columns=rename_map).copy().fillna("")
    
    # Guardar versión con detalle de SKUs
    df_skus = df_raw.copy()
    
    needed_cols = list(rename_map.values())
    missing_internal = [c for c in needed_cols if c not in df_raw.columns]
    if missing_internal:
        raise ValueError(f"[ERROR] En df_proc faltan columnas mapeadas: {missing_internal}")

    # Procesar formato de SKUs
    if "CE" in df_skus.columns:
        df_skus["CE"] = df_skus["CE"].astype(str).str.zfill(4)

    for col in ["CD", "CE", "OC"]:
        if col in df_skus.columns:
            df_skus[col] = df_skus[col].astype("category")

    # Numéricos y filtros
    if "PESO" in df_skus.columns:
        df_skus["PESO"] = pd.to_numeric(df_skus["PESO"], errors="coerce")
    if "VOL" in df_skus.columns:
        df_skus["VOL"] = pd.to_numeric(df_skus["VOL"], errors="coerce")
    if "PALLETS" in df_skus.columns:
        df_skus["PALLETS"] = pd.to_numeric(df_skus["PALLETS"], errors="coerce")

    df_skus = df_skus[(df_skus["PEDIDO"] != "") & (df_skus["PEDIDO"].notnull())]
    
    # NO eliminar duplicados por PEDIDO (ahora puede haber múltiples filas por pedido)
    # df_skus = df_skus.drop_duplicates(subset="PEDIDO", keep=False)  # ❌ ELIMINAR

    # Pallets > 0
    if "PALLETS" in df_skus.columns:
        pallets_num = pd.to_numeric(df_skus["PALLETS"], errors="coerce").fillna(0)
        df_skus = df_skus[pallets_num > 0]  # Cambiar != 0 a > 0

    # Flags
    for flag in ["VALIOSO", "PDQ", "BAJA_VU", "LOTE_DIR", "SALDO_INV"]:
        if flag in df_skus.columns:
            df_skus[flag] = pd.to_numeric(df_skus[flag], errors="coerce").fillna(0).astype(int).clip(0, 1)
        else:
            df_skus[flag] = 0

    # ⭐ NUEVO: Agregar SKUs por pedido para CP-SAT
    df_agregado, skus_detalle = agregar_skus_por_pedido(df_skus)
    
    # Convertir a lista de diccionarios (agregados)
    raw_pedidos = df_agregado.to_dict(orient="records")
    
    return df_agregado, raw_pedidos, skus_detalle

def agregar_skus_por_pedido(df_skus: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, List[Dict]]]:
    """
    Agrega SKUs por pedido para el optimizador CP-SAT.
    Preserva el detalle de SKUs en un diccionario separado.
    
    Args:
        df_skus: DataFrame con una fila por SKU-Pedido
        
    Returns:
        (df_agregado, skus_detalle)
        - df_agregado: DataFrame con una fila por pedido (para CP-SAT)
        - skus_detalle: {pedido_id: [lista de SKUs con sus atributos]}
    """
    # Verificar que tenemos las columnas de SKU
    required = ['PEDIDO', 'SKU']
    missing = [c for c in required if c not in df_skus.columns]
    if missing:
        raise ValueError(f"Faltan columnas requeridas para SKUs: {missing}")
    
    # Guardar detalle de SKUs por pedido
    skus_detalle = {}
    for pedido, grupo in df_skus.groupby('PEDIDO'):
        skus_detalle[str(pedido)] = [
            {
                'sku': row['SKU'],
                'pallets': float(row.get('PALLETS', 0)),
                'tipo_apilabilidad': str(row.get('TIPO_APILABILIDAD', 'FLEXIBLE')),
                'altura_pallet': float(row.get('ALTURA_PALLET', 120)),
                # Preservar otros campos del SKU si existen
                'peso': float(row.get('PESO', 0)) if 'PESO' in row else None,
                'volumen': float(row.get('VOL', 0)) if 'VOL' in row else None,
            }
            for _, row in grupo.iterrows()
        ]
    
    # Agregar por pedido para CP-SAT
    agg_dict = {
        'CD': 'first',
        'CE': 'first',
        'OC': 'first' if 'OC' in df_skus.columns else lambda x: '',
        'PALLETS': 'sum',  # Suma de pallets de todos los SKUs
        'PESO': 'sum' if 'PESO' in df_skus.columns else lambda x: 0,
        'VOL': 'sum' if 'VOL' in df_skus.columns else lambda x: 0,
        'VALOR': 'sum' if 'VALOR' in df_skus.columns else lambda x: 0,
    }
    
    # Agregar columnas de apilabilidad (suma de cada tipo)
    for tipo in ['BASE', 'SUPERIOR', 'FLEXIBLE', 'NO_APILABLE', 'SI_MISMO']:
        if tipo in df_skus.columns:
            agg_dict[tipo] = 'sum'
        else:
            # Calcular desde TIPO_APILABILIDAD si existe
            if 'TIPO_APILABILIDAD' in df_skus.columns:
                agg_dict[tipo] = lambda x, tipo=tipo: (
                    df_skus.loc[x.index, 'PALLETS'][
                        df_skus.loc[x.index, 'TIPO_APILABILIDAD'].str.upper() == tipo
                    ].sum() if 'PALLETS' in df_skus.columns else 0
                )
    
    # Flags booleanos (any)
    for flag in ['VALIOSO', 'PDQ', 'BAJA_VU', 'LOTE_DIR', 'SALDO_INV', 'CHOCOLATES']:
        if flag in df_skus.columns:
            agg_dict[flag] = 'max'  # 1 si cualquier SKU tiene el flag
    
    # Agregar
    df_agregado = df_skus.groupby('PEDIDO', as_index=False).agg(agg_dict)
    
    # Calcular tipos de apilabilidad desde TIPO_APILABILIDAD si no existían las columnas
    if 'TIPO_APILABILIDAD' in df_skus.columns:
        for tipo in ['BASE', 'SUPERIOR', 'FLEXIBLE', 'NO_APILABLE', 'SI_MISMO']:
            if tipo not in df_agregado.columns:
                df_agregado[tipo] = 0
        
        for pedido, grupo in df_skus.groupby('PEDIDO'):
            idx = df_agregado[df_agregado['PEDIDO'] == pedido].index[0]
            for tipo in ['BASE', 'SUPERIOR', 'FLEXIBLE', 'NO_APILABLE', 'SI_MISMO']:
                cantidad = grupo[grupo['TIPO_APILABILIDAD'].str.upper() == tipo]['PALLETS'].sum()
                df_agregado.at[idx, tipo] = cantidad
    
    return df_agregado, skus_detalle


def expandir_pedidos_con_skus(
    pedidos_agregados: List[Dict], 
    skus_detalle: Dict[str, List[Dict]]
) -> List[Dict]:
    """
    Expande pedidos agregados de vuelta a formato con detalle de SKUs.
    
    Args:
        pedidos_agregados: Lista de pedidos del optimizador (agregados)
        skus_detalle: Diccionario con detalle de SKUs por pedido
        
    Returns:
        Lista de pedidos con campo 'SKUS' agregado
    """
    pedidos_expandidos = []
    
    for pedido in pedidos_agregados:
        pedido_id = str(pedido.get('PEDIDO', ''))
        pedido_expanded = pedido.copy()
        
        # Agregar detalle de SKUs si existe
        if pedido_id in skus_detalle:
            pedido_expanded['SKUS'] = skus_detalle[pedido_id]
        else:
            # Fallback: crear SKUs genéricos desde columnas agregadas
            pedido_expanded['SKUS'] = _crear_skus_desde_agregados(pedido)
        
        pedidos_expandidos.append(pedido_expanded)
    
    return pedidos_expandidos


def _crear_skus_desde_agregados(pedido: Dict) -> List[Dict]:
    """
    Crea SKUs genéricos desde columnas de apilabilidad agregadas.
    Usado como fallback cuando no hay detalle de SKUs.
    """
    skus = []
    pedido_id = pedido.get('PEDIDO', '')
    
    for tipo in ['BASE', 'SUPERIOR', 'FLEXIBLE', 'NO_APILABLE', 'SI_MISMO']:
        cantidad = float(pedido.get(tipo, 0))
        if cantidad > 0:
            skus.append({
                'sku': f"{pedido_id}_GEN_{tipo}",
                'pallets': cantidad,
                'tipo_apilabilidad': tipo,
                'altura_pallet': 120  # Default
            })
    
    # Si no hay ningún tipo, crear uno FLEXIBLE genérico
    if not skus:
        pallets_total = float(pedido.get('PALLETS', 0))
        if pallets_total > 0:
            skus.append({
                'sku': f"{pedido_id}_GEN_FLEXIBLE",
                'pallets': pallets_total,
                'tipo_apilabilidad': 'FLEXIBLE',
                'altura_pallet': 120
            })
    
    return skus