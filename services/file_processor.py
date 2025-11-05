# services/file_processor.py
from __future__ import annotations

import os
import hashlib
import tempfile
from io import BytesIO
from typing import Tuple, List, Dict, Any

import pandas as pd

# ===== IMPORTAR NUESTROS MODELOS =====
from models.domain import Pedido


# === Helpers de cachÃ© (sin cambios) ===

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


# === Lectura de Excel (sin cambios) ===

def read_file(content: bytes, filename: str, client_config, venta: str) -> pd.DataFrame:
    """Lee archivo Excel y devuelve DataFrame con columnas mapeadas"""
    sheet_name = venta.upper()
    header_row = client_config.HEADER_ROW

    mapping = build_column_mapping(client_config, venta)
    wanted_cols = list(mapping.values())

    try:
        print("Reading file")
        if not filename.endswith((".xlsx", ".xlsm")):
            raise ValueError("Formato de archivo no soportado")

        xls = pd.ExcelFile(BytesIO(content), engine="openpyxl")
        header_only = xls.parse(sheet_name=sheet_name, header=header_row, nrows=0)

        available_cols = [c for c in wanted_cols if c in header_only.columns]
        missing_cols = [c for c in wanted_cols if c not in header_only.columns]
        if missing_cols:
            print(f"[WARN] Columnas ausentes (se omiten): {missing_cols}")

        # Cache parquet
        sig = _make_cache_sig(content, sheet_name, available_cols)
        cpath = _cache_path(sig)
        if os.path.exists(cpath) and os.getenv("EXCEL_CACHE_DISABLE", "false").lower() != "true":
            try:
                return pd.read_parquet(cpath)
            except Exception as e:
                print(f"[WARN] FallÃ³ leer cache parquet ({e}); releyendo Excelâ€¦")

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
        print("Leido")
        return df

    except Exception as e:
        print(f"[ERROR] Al leer el Excel: {e}")
        raise


# === Transformaciones ===

def build_column_mapping(client_config, venta: str) -> Dict[str, str]:
    """Construye mapeo completo: internal_name -> excel_column"""
    print("Transformado nombres columnas")
    col_map = client_config.COLUMN_MAPPING[venta]
    extra_map = client_config.EXTRA_MAPPING
    return {**extra_map, **col_map}


def warn_missing_columns(df: pd.DataFrame, mapping: Dict[str, str]) -> List[str]:
    """Advierte sobre columnas faltantes"""
    missing = [excel_name for excel_name in mapping.values() if excel_name not in df.columns]
    if missing:
        print(f"[WARN] Columnas en Excel no encontradas (se omiten): {missing}")
    return missing


def process_dataframe(
    df_full: pd.DataFrame, 
    client_config, 
    cliente: str, 
    venta: str
) -> Tuple[pd.DataFrame, List[Dict[str, Any]]]:
    """
    VERSIÃ“N OPTIMIZADA: Usa operaciones vectorizadas de pandas.
    """
    mapping = build_column_mapping(client_config, venta)
    rename_map = {excel: internal for internal, excel in mapping.items() if excel in df_full.columns}
    warn_missing_columns(df_full, mapping)
    print("Renombrando columnas")
    # Renombrar columnas
    df_raw = df_full[list(rename_map.keys())].rename(columns=rename_map).copy()
    
    needed_cols = list(rename_map.values())
    missing_internal = [c for c in needed_cols if c not in df_raw.columns]
    if missing_internal:
        raise ValueError(f"[ERROR] Columnas requeridas faltantes: {missing_internal}")

    # ===== LIMPIEZA Y NORMALIZACIÃ“N (VECTORIZADO) =====
    print("Limpieza y normalizacion")
    # CE padding
    if "CE" in df_raw.columns:
        df_raw["CE"] = df_raw["CE"].astype(str).str.zfill(4)
    
    # NumÃ©ricos
    numeric_cols = ["PESO", "VOL", "PALLETS", "VALOR", "VALOR_CAFE"]
    for col in numeric_cols:
        if col in df_raw.columns:
            df_raw[col] = pd.to_numeric(df_raw[col], errors="coerce").fillna(0)
    
    if "PALLETS_REAL" in df_raw.columns:
        df_raw["PALLETS_REAL"] = pd.to_numeric(df_raw["PALLETS_REAL"], errors="coerce")
    
    # Apilabilidad
    apilabilidad_cols = ["BASE", "SUPERIOR", "FLEXIBLE", "NO_APILABLE", "SI_MISMO"]
    for col in apilabilidad_cols:
        if col in df_raw.columns:
            df_raw[col] = pd.to_numeric(df_raw[col], errors="coerce").fillna(0)
        else:
            df_raw[col] = 0.0
    
    # Flags
    flag_cols = ["VALIOSO", "PDQ", "BAJA_VU", "LOTE_DIR"]
    for col in flag_cols:
        if col in df_raw.columns:
            df_raw[col] = pd.to_numeric(df_raw[col], errors="coerce").fillna(0).astype(int).clip(0, 1)
        else:
            df_raw[col] = 0
    
    # Filtros
    df_raw = df_raw[
        (df_raw["PEDIDO"] != "") & 
        (df_raw["PEDIDO"].notnull())
    ].copy()
    
    df_raw = df_raw.drop_duplicates(subset="PEDIDO", keep=False)
    df_raw = df_raw[df_raw["PALLETS"] != 0].copy()
    
    # ===== CONVERSIÃ“N BATCH (NO LOOP) =====
    print("Conversion batch")
    # Convertir OC y PALLETS_REAL a None donde sea necesario
    if "OC" in df_raw.columns:
        df_raw["OC"] = df_raw["OC"].replace({"": None, "nan": None, "NaN": None, "none": None})
    
    if "PALLETS_REAL" in df_raw.columns:
        df_raw.loc[df_raw["PALLETS_REAL"].isna(), "PALLETS_REAL"] = None
    
    # Extraer columnas metadata (todo lo que no es estándar)
    standard_cols = {
        "PEDIDO", "CD", "CE", "PO", "PESO", "VOL", "PALLETS", "PALLETS_REAL",
        "VALOR", "VALOR_CAFE", "OC", "CHOCOLATES", "VALIOSO", "PDQ",
        "BAJA_VU", "LOTE_DIR", "BASE", "SUPERIOR", "FLEXIBLE", 
        "NO_APILABLE", "SI_MISMO"
    }
    metadata_cols = [c for c in df_raw.columns if c not in standard_cols]
    print("Crear pedidos con list comprehension")
    
    # Crear lista de diccionarios para metadata (una sola pasada)
    pedidos_dicts = []
    for _, row in df_raw.iterrows():
        pedido_dict = {"PEDIDO": str(row["PEDIDO"])}
        # Agregar toda la metadata
        for col in metadata_cols:
            if col in row:
                pedido_dict[col] = row[col]
        pedidos_dicts.append(pedido_dict)
    
    print(f"[INFO] Procesados {len(df_raw)} pedidos válidos de {len(df_full)} filas originales")
    print("Fin procesamiento datos")
    return df_raw, pedidos_dicts