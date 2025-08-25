import os
import hashlib
import tempfile
import pandas as pd
from io import BytesIO
from typing import Tuple, List, Dict, Any

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
    base = os.getenv("PARQUET_CACHE_DIR") or tempfile.gettempdir()  # /tmp en Linux/Railway
    return os.path.join(base, f"excel_cache_{sig}.parquet")


def read_file(content: bytes, filename: str, client_config, venta: str) -> pd.DataFrame:
    sheet_name = venta.upper()
    header_row = client_config.HEADER_ROW
    print("Leyendo excel (optimizado)")

    # 1) Mapeo de columnas necesarias
    mapping = build_column_mapping(client_config, venta)
    wanted_cols = list(mapping.values())

    try:
        if filename.endswith((".xlsx", ".xlsm")):
            bio = BytesIO(content)

            # 2) Lee SOLO el encabezado (rápido) para saber qué columnas existen
            xls = pd.ExcelFile(bio, engine="openpyxl")
            header_only = xls.parse(sheet_name=sheet_name, header=header_row, nrows=0)

            # 3) Intersección: columnas pedidas vs disponibles
            available_cols = [c for c in wanted_cols if c in header_only.columns]
            missing_cols   = [c for c in wanted_cols if c not in header_only.columns]
            if missing_cols:
                print(f"[WARN] Columnas en Excel no encontradas (se omiten): {missing_cols}")

            # 3.1) INTENTO DE CACHE (clave: contenido + hoja + columnas disponibles)
            sig = _make_cache_sig(content, sheet_name, available_cols)
            cpath = _cache_path(sig)
            if os.path.exists(cpath) and os.getenv("EXCEL_CACHE_DISABLE", "false").lower() != "true":
                try:
                    print(f"[read_file] Usando cache parquet: {cpath}")
                    return pd.read_parquet(cpath)
                except Exception as e:
                    print(f"[WARN] Falló leer cache parquet ({e}); leo Excel.")

            # 4) Tipos hint para evitar inferencia pesada en IDs/códigos
            text_internals = {"PEDIDO", "CD", "CE", "OC"}
            dtype_hint = {}
            for internal in text_internals:
                excel_name = mapping.get(internal)
                if excel_name in available_cols:
                    dtype_hint[excel_name] = "string"

            # 5) Leer SOLO las columnas necesarias
            df = xls.parse(
                sheet_name=sheet_name,
                header=header_row,
                usecols=available_cols,
                dtype=dtype_hint
            )
            print("Excel leído (columnas filtradas)")

            # 6) Guardar cache parquet para próximas lecturas del MISMO archivo
            if os.getenv("EXCEL_CACHE_DISABLE", "false").lower() != "true":
                try:
                    df.to_parquet(cpath, index=False)  # usa pyarrow instalado
                    print(f"[read_file] Cache parquet escrito: {cpath}")
                except Exception as e:
                    print(f"[WARN] No se pudo escribir cache parquet ({e}).")

            return df
        else:
            raise ValueError("Formato de archivo no soportado")
    except Exception as e:
        print(f"[ERROR] Al leer el Excel: {e}")
        raise

 
def build_column_mapping(client_config, venta: str) -> Dict[str, str]:
    # Prioriza col_map sobre extra_map
    col_map = client_config.COLUMN_MAPPING[venta]
    extra_map = client_config.EXTRA_MAPPING
    combined_map = {**extra_map, **col_map}
    return combined_map
 
def warn_missing_columns(df: pd.DataFrame, mapping: Dict[str, str]) -> List[str]:
    missing = [excel_name for excel_name in mapping.values() if excel_name not in df.columns]
    if missing:
        print(f"[WARN] Columnas en Excel no encontradas (se omiten): {missing}")
    return missing
 
def process_dataframe(df_full: pd.DataFrame, client_config, cliente:str, venta: str) -> Tuple[pd.DataFrame, List[Dict[str, Any]]]:
    mapping = build_column_mapping(client_config, venta)
    rename_map = {excel_name: internal_name for internal_name, excel_name in mapping.items() if excel_name in df_full.columns}
    warn_missing_columns(df_full, mapping)
   
    df_raw = df_full[list(rename_map.keys())].rename(columns=rename_map).copy()
    df_raw = df_raw.fillna("")
 
    raw_pedidos = df_raw.to_dict(orient="records")
    needed_cols = list(rename_map.values())
    missing_internal = [c for c in needed_cols if c not in df_raw.columns]
    if missing_internal:
        raise ValueError(f"[ERROR] En df_proc faltan columnas mapeadas: {missing_internal}")

    df_proc = df_raw[needed_cols].copy()
    if "CE" in df_proc.columns:
        df_proc["CE"] = df_proc["CE"].astype(str).str.zfill(4)
    # Cast categorical columns
    for col in ["CD", "CE", "OC"]:
        if col in df_proc.columns:
            df_proc[col] = df_proc[col].astype('category')
 
    # Validación y filtrado final
    df_proc["PESO"] = pd.to_numeric(df_proc["PESO"], errors="coerce")

 
    # Filtrar PEDIDO no vacío ni nulo ni duplicado
    df_proc = df_proc[(df_proc["PEDIDO"] != "") & (df_proc["PEDIDO"].notnull())]
    df_proc = df_proc.drop_duplicates(subset="PEDIDO", keep=False)
 
    # Pallet Conf. = 0
    df_proc = df_proc[pd.to_numeric(df_proc["PALLETS"], errors="coerce").fillna(0) != 0]

    # Pallet Conf. = 0
    df_proc = df_proc[pd.to_numeric(df_proc["PALLETS"], errors="coerce").fillna(0) != 0]

    # Pasar a numérico
    df_proc["BASE"]         = pd.to_numeric(df_proc["BASE"], errors="coerce")
    df_proc["SUPERIOR"]     = pd.to_numeric(df_proc["SUPERIOR"], errors="coerce")
    df_proc["FLEXIBLE"]     = pd.to_numeric(df_proc["FLEXIBLE"], errors="coerce")
    df_proc["NO_APILABLE"]  = pd.to_numeric(df_proc["NO_APILABLE"], errors="coerce")
    df_proc["SI_MISMO"]     = pd.to_numeric(df_proc["SI_MISMO"], errors="coerce")

    # Nueva columna para Cencosud: Pal. Conf. Real
    if "PALLETS_REAL" in df_proc.columns:
        df_proc["PALLETS_REAL"] = pd.to_numeric(df_proc["PALLETS_REAL"], errors="coerce").fillna(0)


    for flag in ["VALIOSO", "PDQ", "BAJA_VU", "LOTE_DIR"]:
        if flag in df_proc.columns:
            df_proc[flag] = (pd.to_numeric(df_proc[flag], errors="coerce").fillna(0).astype(int).clip(0, 1))
        else:
            df_proc[flag] = 0
            
    return df_proc, raw_pedidos
