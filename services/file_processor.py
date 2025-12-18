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

        # Cache parquet por archivo-hoja-columnas
        sig = _make_cache_sig(content, sheet_name, available_cols)
        cpath = _cache_path(sig)
        if os.path.exists(cpath) and os.getenv("EXCEL_CACHE_DISABLE", "false").lower() != "true":
            try:
                return pd.read_parquet(cpath)
            except Exception as e:
                raise ValueError(f"[WARN] Falló leer caché ({e}); releyendo Excel…")

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
                raise ValueError(f"[WARN] No se pudo escribir cache ({e}).")

        return df

    except Exception as e:
        raise ValueError(f"[ERROR] Al leer el Excel: {e}")


# === Transformaciones ===

def build_column_mapping(client_config, venta: str) -> Dict[str, str]:
    col_map = client_config.COLUMN_MAPPING[venta]
    extra_map = client_config.EXTRA_MAPPING
    return {**extra_map, **col_map}


def warn_missing_columns(df: pd.DataFrame, mapping: Dict[str, str]) -> List[str]:
    missing = [excel_name for excel_name in mapping.values() if excel_name not in df.columns]
    if missing:
        raise ValueError(f"[WARN] Columnas en Excel no encontradas (se omiten): {missing}")
    return missing


def process_dataframe(df_full: pd.DataFrame, client_config, cliente: str, venta: str) -> Tuple[pd.DataFrame, List[Dict[str, Any]]]:
    mapping = build_column_mapping(client_config, venta)
    rename_map = {excel: internal for internal, excel in mapping.items() if excel in df_full.columns}
    warn_missing_columns(df_full, mapping)

    df_raw = df_full[list(rename_map.keys())].rename(columns=rename_map).copy().fillna("")
    raw_pedidos = df_raw.to_dict(orient="records")

    needed_cols = list(rename_map.values())
    missing_internal = [c for c in needed_cols if c not in df_raw.columns]
    if missing_internal:
        raise ValueError(f"[ERROR] En df_proc faltan columnas mapeadas: {missing_internal}")

    df_proc = df_raw[needed_cols].copy()

    if "CE" in df_proc.columns:
        df_proc["CE"] = df_proc["CE"].astype(str).str.zfill(4)

    for col in ["CD", "CE", "OC"]:
        if col in df_proc.columns:
            df_proc[col] = df_proc[col].astype("category")

    # Numéricos y filtros
    df_proc["PESO"] = pd.to_numeric(df_proc["PESO"], errors="coerce")

    df_proc = df_proc[(df_proc["PEDIDO"] != "") & (df_proc["PEDIDO"].notnull())]
    df_proc = df_proc.drop_duplicates(subset="PEDIDO", keep=False)

    # Pallets > 0
    pallets_num = pd.to_numeric(df_proc["PALLETS"], errors="coerce").fillna(0)
    df_proc = df_proc[pallets_num != 0]

    # Apilabilidad a numérico
    for col in ["BASE", "SUPERIOR", "FLEXIBLE", "NO_APILABLE", "SI_MISMO"]:
        if col in df_proc.columns:
            df_proc[col] = pd.to_numeric(df_proc[col], errors="coerce")
        else:
            df_proc[col] = 0

    if "PALLETS_REAL" in df_proc.columns:
        df_proc["PALLETS_REAL"] = pd.to_numeric(df_proc["PALLETS_REAL"], errors="coerce").fillna(0)

    for flag in ["VALIOSO", "PDQ", "BAJA_VU", "LOTE_DIR"]:
        if flag in df_proc.columns:
            df_proc[flag] = pd.to_numeric(df_proc[flag], errors="coerce").fillna(0).astype(int).clip(0, 1)
        else:
            df_proc[flag] = 0

    return df_proc, raw_pedidos