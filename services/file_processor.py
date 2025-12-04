# services/file_processor.py
from __future__ import annotations

import os
import hashlib
import tempfile
from io import BytesIO
from typing import Tuple, List, Dict, Any

import pandas as pd

from models.domain import Pedido, SKU


# ============================================================================
# DETECCIÓN DE MODO (SKU vs LEGACY)
# ============================================================================

def detectar_modo_excel(df: pd.DataFrame) -> str:
    """
    Detecta si el Excel tiene datos de SKU o es formato legacy.
    
    Args:
        df: DataFrame leído del Excel
    
    Returns:
        "SKU_DETALLADO" si tiene columnas de SKU
        "PEDIDO_LEGACY" si es formato antiguo
    """
    columnas_sku_requeridas = {"SKU", "ALTURA_FULL_PALLET"}
    columnas_disponibles = set(df.columns)
    
    if columnas_sku_requeridas.issubset(columnas_disponibles):
        return "SKU_DETALLADO"
    
    return "PEDIDO_LEGACY"


# ============================================================================
# LECTURA DE EXCEL (ACTUALIZADA)
# ============================================================================

def read_file(
    content: bytes, 
    filename: str, 
    client_config, 
    venta: str
) -> pd.DataFrame:
    """
    Lee archivo Excel y devuelve DataFrame crudo.
    
    CAMBIO: Ahora puede leer tanto formato SKU como legacy.
    El DataFrame retornado tiene las columnas originales del Excel.
    
    Args:
        content: Contenido binario del Excel
        filename: Nombre del archivo
        client_config: Configuración del cliente
        venta: Tipo de venta ("Secos", "Purina")
    
    Returns:
        DataFrame con columnas originales del Excel
    """
    sheet_name = venta.upper()
    header_row = client_config.HEADER_ROW

    mapping = build_column_mapping(client_config, venta)
    wanted_cols = list(mapping.values())
    

    try:
        print(f"[FILE] Leyendo Excel: {filename}, hoja: {sheet_name}")
        
        if not filename.endswith((".xlsx", ".xlsm")):
            raise ValueError("Formato de archivo no soportado")

        xls = pd.ExcelFile(BytesIO(content), engine="openpyxl")
        header_only = xls.parse(sheet_name=sheet_name, header=header_row, nrows=0)


        available_cols = [c for c in wanted_cols if c in header_only.columns]
        missing_cols = [c for c in wanted_cols if c not in header_only.columns]
        

        # Cache parquet (sin cambios)
        sig = _make_cache_sig(content, sheet_name, available_cols)
        cpath = _cache_path(sig)
        
        if os.path.exists(cpath) and os.getenv("EXCEL_CACHE_DISABLE", "false").lower() != "true":
            try:
                df = pd.read_parquet(cpath)
                print(f"[FILE] ✓ Leído desde cache: {len(df)} filas")
                return df
            except Exception as e:
                print(f"[WARN] Falló leer cache parquet ({e}); releyendo Excel...")

        # Tipos para evitar inferencia costosa
        text_internals = {"PEDIDO", "CD", "CE", "OC", "SKU"}  # Agregado SKU
        dtype_hint: Dict[str, str] = {}
        for internal in text_internals:
            excel_name = mapping.get(internal)
            if excel_name and excel_name in available_cols:
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
        raise


# ============================================================================
# MAPEO DE COLUMNAS (ACTUALIZADO con columnas de SKU)
# ============================================================================

def build_column_mapping(client_config, venta: str) -> Dict[str, str]:
    """
    Construye mapeo completo: internal_name -> excel_column.
    
    NUEVO: Incluye columnas de SKU si existen en COLUMN_MAPPING.
    """
    
    col_map = client_config.COLUMN_MAPPING.get(venta, {})
    extra_map = getattr(client_config, 'EXTRA_MAPPING', {})
    
    # Mapeo base (existente)
    mapping = {**extra_map, **col_map}
    
    # NUEVO: Agregar columnas de SKU si están definidas
    columnas_sku = {
        "SKU": "SKU",
        "ALTURA_FULL_PALLET": "Altura full Pallet",
        "ALTURA_PICKING": "Altura Picking",
    }
    
    # Agregar solo si no están en el mapping (para permitir override por cliente)
    for internal, excel_col in columnas_sku.items():
        if internal not in mapping:
            mapping[internal] = excel_col
    
    return mapping


# ============================================================================
# PROCESAMIENTO (ACTUALIZADO para soportar SKUs)
# ============================================================================

def process_dataframe(
    df_full: pd.DataFrame, 
    client_config, 
    cliente: str, 
    venta: str
) -> Tuple[pd.DataFrame, List[Dict[str, Any]]]:
    """
    Procesa DataFrame del Excel.
    
    CAMBIO PRINCIPAL:
    - Si tiene datos de SKU: agrupa SKUs por pedido
    - Si es legacy: mantiene comportamiento original
    
    Returns:
        (df_pedidos_agregados, lista_pedidos_dicts)
    """
    mapping = build_column_mapping(client_config, venta)
    rename_map = {
        excel: internal 
        for internal, excel in mapping.items() 
        if excel in df_full.columns
    }
    
    warn_missing_columns(df_full, mapping)
    df_raw = df_full[list(rename_map.keys())].rename(columns=rename_map).copy()
    
    # Detectar modo
    modo = detectar_modo_excel(df_raw)
    

    if modo == "SKU_DETALLADO":
        return _process_dataframe_con_skus(df_raw, client_config, cliente, venta)
    else:
        return _process_dataframe_legacy(df_raw, client_config, cliente, venta)


# ============================================================================
# PROCESAMIENTO CON SKUs (NUEVO)
# ============================================================================

def _process_dataframe_con_skus(
    df_raw: pd.DataFrame,
    client_config,
    cliente: str,
    venta: str
) -> Tuple[pd.DataFrame, List[Dict[str, Any]]]:
    """
    Procesa Excel con datos de SKU.
    
    Flujo:
    1. Limpiar y normalizar datos a nivel SKU
    2. Agregar SKUs por pedido (suma/max según reglas)
    3. Generar df_pedidos y lista de dicts
    
    Returns:
        (df_pedidos_agregados, lista_pedidos_dicts)
    """
    
    # 1. Limpieza y normalización a nivel SKU
    df_skus = _limpiar_datos_skus(df_raw)

    # 2. Optimizar apilabilidad ANTES de validar
    altura_maxima = 270  # Default, o extraer de client_config
    if hasattr(client_config, 'TRUCK_TYPES'):
        # Usar altura de paquetera como referencia
        truck_types = client_config.TRUCK_TYPES
        if 'paquetera' in truck_types:
            altura_maxima = truck_types['paquetera'].get('altura_cm', 270)
    
    df_skus = _optimizar_apilabilidad_skus(df_skus, altura_maxima)
    
    # 3. Validar datos de SKU
    df_skus = _validar_datos_skus(df_skus)
    
    # 4. Agregar SKUs por pedido
    df_pedidos, df_skus_con_pedido = _agregar_skus_a_pedidos(df_skus, client_config)
    
    # 5. Crear lista de dicts de pedidos (para metadata)
    pedidos_dicts = _crear_pedidos_dicts_con_skus(df_pedidos, df_skus_con_pedido)
    
    return df_pedidos, pedidos_dicts


def _limpiar_datos_skus(df: pd.DataFrame) -> pd.DataFrame:
    """
    Limpia y normaliza datos a nivel SKU.
    Similar a limpieza existente pero a nivel SKU.
    """
    df = df.copy()
    
    # CE padding
    if "CE" in df.columns:
        df["CE"] = df["CE"].astype(str).str.zfill(4)
    
    # SKU como string
    if "SKU" in df.columns:
        df["SKU"] = df["SKU"].astype(str).str.strip()
    
    # PEDIDO como string
    if "PEDIDO" in df.columns:
        df["PEDIDO"] = df["PEDIDO"].astype(str).str.strip()
    
    # Numéricos (a nivel SKU)
    numeric_cols = [
        "PESO", "VOL", "PALLETS", "VALOR", "VALOR_CAFE",
        "ALTURA_FULL_PALLET", "ALTURA_PICKING"
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    
    # Apilabilidad (a nivel SKU)
    apilabilidad_cols = ["BASE", "SUPERIOR", "FLEXIBLE", "NO_APILABLE", "SI_MISMO"]
    for col in apilabilidad_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
        else:
            df[col] = 0.0

    # Flags (a nivel SKU, se agregarán con MAX)
    flag_cols = ["VALIOSO", "PDQ", "BAJA_VU", "LOTE_DIR"]
    for col in flag_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int).clip(0, 1)
        else:
            df[col] = 0
    
    # Chocolates (especial: SI/NO -> 1/0 para MAX, luego volver a SI/NO)
    if "CHOCOLATES" in df.columns:
        df["CHOCOLATES_FLAG"] = (df["CHOCOLATES"].astype(str).str.upper() == "SI").astype(int)
    else:
        df["CHOCOLATES_FLAG"] = 0
    
    # Filtros
    df = df[
        (df["PEDIDO"] != "") & 
        (df["PEDIDO"].notnull()) &
        (df["SKU"] != "") &
        (df["SKU"].notnull())
    ].copy()
    
    # Filtrar filas con pallets = 0
    df = df[df["PALLETS"] > 0].copy()

    # Preservar campos extra numéricos
    campos_extra_numericos = ["Cant. Sol.", "CJ Conf.", "%NS", "Suma de Sol (Pallet)", "Suma de Conf (Pallet)"]
    for col in campos_extra_numericos:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    
    return df


def _optimizar_apilabilidad_skus(df: pd.DataFrame, altura_maxima_cm: float = 260) -> pd.DataFrame:
    """
    Optimiza categorías de apilabilidad ANTES de la optimización.
    
    Reglas:
    1. SI_MISMO > 200cm → NO_APILABLE
    2. SI_MISMO × 2 > altura_max → intentar convertir a BASE/SUPERIOR
    3. SI_MISMO con cantidad impar → convertir último a BASE/SUPERIOR
    
    Args:
        df: DataFrame de SKUs con columnas de apilabilidad
        altura_maxima_cm: Altura máxima del camión
    
    Returns:
        DataFrame con apilabilidad optimizada
    """
    df = df.copy()
    
    # Contador de cambios
    cambios = {
        'si_mismo_a_no_apilable': 0,
        'si_mismo_a_base_superior': 0,
        'impares_ajustados': 0
    }
    
    # Iterar sobre SKUs con SI_MISMO > 0
    for idx in df[df['SI_MISMO'] > 0].index:
        altura = df.at[idx, 'ALTURA_FULL_PALLET']
        si_mismo = df.at[idx, 'SI_MISMO']
        
        # REGLA 1: Si altura > 200cm → NO_APILABLE
        if altura > 200:
            df.at[idx, 'NO_APILABLE'] += si_mismo
            df.at[idx, 'SI_MISMO'] = 0
            cambios['si_mismo_a_no_apilable'] += 1
            continue
        
        # REGLA 2: Si 2 × altura > altura_max → intentar BASE/SUPERIOR
        if 2 * altura > altura_maxima_cm:
            puede_ser_base = df.at[idx, 'BASE'] > 0 or _tiene_columna_base(df, idx)
            puede_ser_superior = df.at[idx, 'SUPERIOR'] > 0 or _tiene_columna_superior(df, idx)
            
            if puede_ser_base:
                df.at[idx, 'BASE'] += si_mismo
                df.at[idx, 'SI_MISMO'] = 0
                cambios['si_mismo_a_base_superior'] += 1
            elif puede_ser_superior:
                df.at[idx, 'SUPERIOR'] += si_mismo
                df.at[idx, 'SI_MISMO'] = 0
                cambios['si_mismo_a_base_superior'] += 1
            # Si no puede ser ni BASE ni SUPERIOR, dejar como SI_MISMO
            continue
        
        # REGLA 3: Cantidad impar → convertir 1 pallet a BASE/SUPERIOR
        if si_mismo % 2 != 0:  # Impar
            puede_ser_base = df.at[idx, 'BASE'] > 0 or _tiene_columna_base(df, idx)
            puede_ser_superior = df.at[idx, 'SUPERIOR'] > 0 or _tiene_columna_superior(df, idx)
            
            if puede_ser_base:
                df.at[idx, 'BASE'] += 1
                df.at[idx, 'SI_MISMO'] -= 1
                cambios['impares_ajustados'] += 1
            elif puede_ser_superior:
                df.at[idx, 'SUPERIOR'] += 1
                df.at[idx, 'SI_MISMO'] -= 1
                cambios['impares_ajustados'] += 1
    
    return df


def _tiene_columna_base(df: pd.DataFrame, idx: int) -> bool:
    """Verifica si el SKU puede ser BASE según columna APILABLE_BASE"""
    if 'APILABLE_BASE' in df.columns:
        valor = df.at[idx, 'APILABLE_BASE']
        # Manejar diferentes formatos: SI, si, 1, True
        if pd.notna(valor):
            return str(valor).upper() in ('SI', 'SÍ', '1', 'TRUE')
    return False


def _tiene_columna_superior(df: pd.DataFrame, idx: int) -> bool:
    """Verifica si el SKU puede ser SUPERIOR según columna MONTADO"""
    if 'MONTADO' in df.columns:
        valor = df.at[idx, 'MONTADO']
        # Manejar diferentes formatos: SI, si, 1, True
        if pd.notna(valor):
            return str(valor).upper() in ('SI', 'SÍ', '1', 'TRUE')
    return False


def _validar_datos_skus(df: pd.DataFrame) -> pd.DataFrame:
    """
    Valida que los datos de SKU sean coherentes.
    
    ACTUALIZADO: Permite altura = 0 y categorías decimales < 1
    """
    errores = []
    
    # ✅ CAMBIO: Validar altura - puede ser 0 si es picking vacío
    # Solo validamos que NO sea negativa
    skus_altura_negativa = df[df["ALTURA_FULL_PALLET"] < 0]
    if len(skus_altura_negativa) > 0:
        errores.append(
            f"{len(skus_altura_negativa)} SKUs con altura negativa. "
            f"Ejemplos: {skus_altura_negativa['SKU'].head(3).tolist()}"
        )
    
    # ✅ CAMBIO: Advertir (no error) si altura = 0
    skus_altura_cero = df[df["ALTURA_FULL_PALLET"] == 0]
    
    # Validar que cada SKU tenga al menos una categoría de apilabilidad
    df["SUMA_APILABILIDAD"] = (
        df["BASE"] + df["SUPERIOR"] + df["FLEXIBLE"] + 
        df["NO_APILABLE"] + df["SI_MISMO"]
    )
    
    skus_sin_categoria = df[df["SUMA_APILABILIDAD"] <= 0]
    if len(skus_sin_categoria) > 0:
        errores.append(
            f"{len(skus_sin_categoria)} SKUs sin categoría de apilabilidad. "
            f"Ejemplos: {skus_sin_categoria['SKU'].head(3).tolist()}"
        )
    
    # Validar que suma de categorías no exceda pallets con tolerancia para decimales
    df["EXCEDE_PALLETS"] = df["SUMA_APILABILIDAD"] > df["PALLETS"] + 0.1  # Tolerancia de 0.1
    skus_exceden = df[df["EXCEDE_PALLETS"]]
    
    if len(skus_exceden) > 0:
        
        for idx in skus_exceden.index:
            pallets = df.at[idx, 'PALLETS']
            suma = df.at[idx, 'SUMA_APILABILIDAD']
            factor = pallets / suma
            
            # Escalar todas las categorías proporcionalmente
            df.at[idx, 'BASE'] *= factor
            df.at[idx, 'SUPERIOR'] *= factor
            df.at[idx, 'FLEXIBLE'] *= factor
            df.at[idx, 'NO_APILABLE'] *= factor
            df.at[idx, 'SI_MISMO'] *= factor
            
    
    df = df.drop(columns=["SUMA_APILABILIDAD", "EXCEDE_PALLETS"])
    
    if errores:
        raise ValueError(f"Errores de validación:\n" + "\n".join(errores))
    
    return df


def _agregar_skus_a_pedidos(
    df_skus: pd.DataFrame,
    client_config
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Agrupa SKUs por pedido según reglas de agregación.
    
    Reglas:
    - SUMA: dimensiones físicas y apilabilidad
    - MAX: flags booleanas
    - FIRST: campos de identidad (deben ser iguales)
    
    Returns:
        (df_pedidos_agregados, df_skus_con_info_pedido)
    """

    # Campos que se suman
    campos_suma = [
        "PALLETS", "PESO", "VOL", "VALOR", "VALOR_CAFE",
        "BASE", "SUPERIOR", "FLEXIBLE", "NO_APILABLE", "SI_MISMO"
    ]
    
    # Campos que se toman con MAX (flags)
    campos_max = [
        "VALIOSO", "PDQ", "BAJA_VU", "LOTE_DIR", "CHOCOLATES_FLAG"
    ]
    
    # Campos de identidad (deben ser iguales, tomar el primero)
    campos_identidad = ["CD", "CE", "PO"]
    
    # Agregar OC si existe
    if "OC" in df_skus.columns:
        campos_identidad.append("OC")

    # Campos extra - identidad (primer valor)
    campos_extra_first = ["Solic.", "Fecha preferente de entrega"]
    for col in campos_extra_first:
        if col in df_skus.columns:
            campos_identidad.append(col)
    
    # Construir diccionario de agregación
    agg_rules = {}

    # Campos extra - suma
    campos_extra_suma = [
        "Cant. Sol.", "CJ Conf.", "Suma de Sol (Pallet)", 
        "Suma de Conf (Pallet)", "Suma de Valor neto CONF"
    ]
    for col in campos_extra_suma:
        if col in df_skus.columns:
            agg_rules[col] = "sum"
    
    # Campos extra - promedio
    if "%NS" in df_skus.columns:
        agg_rules["%NS"] = "mean"
    
    for col in campos_suma:
        if col in df_skus.columns:
            agg_rules[col] = "sum"
    
    for col in campos_max:
        if col in df_skus.columns:
            agg_rules[col] = "max"
    
    for col in campos_identidad:
        if col in df_skus.columns:
            agg_rules[col] = "first"
    
    # Agrupar por PEDIDO
    df_pedidos = df_skus.groupby("PEDIDO", as_index=False).agg(agg_rules)

    # ✅ CRÍTICO: Verificar que no se perdieron pedidos
    pedidos_originales = set(df_skus["PEDIDO"].unique())
    pedidos_resultantes = set(df_pedidos["PEDIDO"].unique())
    pedidos_perdidos = pedidos_originales - pedidos_resultantes
    
    if pedidos_perdidos:
        print(f"[ERROR] ❌ Se perdieron {len(pedidos_perdidos)} pedidos en agregación:")
        print(f"        Ejemplos: {list(pedidos_perdidos)[:5]}")
    
    # Convertir CHOCOLATES_FLAG de vuelta a SI/NO
    if "CHOCOLATES_FLAG" in df_pedidos.columns:
        df_pedidos["CHOCOLATES"] = df_pedidos["CHOCOLATES_FLAG"].apply(
            lambda x: "SI" if x == 1 else "NO"
        )
        df_pedidos = df_pedidos.drop(columns=["CHOCOLATES_FLAG"])
    
    # Validar coherencia de campos de identidad
    _validar_coherencia_identidad(df_skus, campos_identidad)
    
    # Guardar df_skus con info del pedido agregado para referencia
    df_skus_enriquecido = df_skus.copy()
    
    return df_pedidos, df_skus_enriquecido


def _validar_coherencia_identidad(df: pd.DataFrame, campos: List[str]):
    """
    Valida que los campos de identidad sean consistentes dentro de cada pedido.
    """
    
    for campo in campos:
        if campo not in df.columns:
            continue
        
        # Contar valores únicos por pedido
        inconsistencias = df.groupby("PEDIDO")[campo].nunique()
        pedidos_inconsistentes = inconsistencias[inconsistencias > 1]
        
        if len(pedidos_inconsistentes) > 0:
            ejemplos = pedidos_inconsistentes.head(3)
            raise ValueError(
                f"Campo '{campo}' tiene valores inconsistentes dentro de pedidos. "
                f"Ejemplos de pedidos afectados: {ejemplos.index.tolist()}"
            )


def _crear_pedidos_dicts_con_skus(
    df_pedidos: pd.DataFrame,
    df_skus: pd.DataFrame
) -> List[Dict[str, Any]]:
    """
    Crea lista de diccionarios de pedidos con metadata completa.
    Incluye referencia a los SKUs que componen cada pedido.
    """
    
    pedidos_dicts = []
    
    for _, row_pedido in df_pedidos.iterrows():
        pedido_id = row_pedido["PEDIDO"]
        
        # Obtener SKUs de este pedido
        skus_pedido = df_skus[df_skus["PEDIDO"] == pedido_id]
        
        # Construir dict del pedido
        pedido_dict = {
            "PEDIDO": pedido_id,
            **row_pedido.to_dict(),
            "_skus": skus_pedido.to_dict("records")  # Guardar SKUs como metadata
        }
        
        pedidos_dicts.append(pedido_dict)
    
    return pedidos_dicts


# ============================================================================
# PROCESAMIENTO LEGACY (EXISTENTE, sin cambios mayores)
# ============================================================================

def _process_dataframe_legacy(
    df_raw: pd.DataFrame,
    client_config,
    cliente: str,
    venta: str
) -> Tuple[pd.DataFrame, List[Dict[str, Any]]]:
    """
    Procesa Excel en formato legacy (sin SKUs).
    Mantiene comportamiento original.
    """
    
    # Limpieza existente (mantener código actual)
    df = df_raw.copy()
    
    # CE padding
    if "CE" in df.columns:
        df["CE"] = df["CE"].astype(str).str.zfill(4)
    
    # Numéricos
    numeric_cols = ["PESO", "VOL", "PALLETS", "VALOR", "VALOR_CAFE"]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    
    if "PALLETS_REAL" in df.columns:
        df["PALLETS_REAL"] = pd.to_numeric(df["PALLETS_REAL"], errors="coerce")
    
    # Apilabilidad
    apilabilidad_cols = ["BASE", "SUPERIOR", "FLEXIBLE", "NO_APILABLE", "SI_MISMO"]
    for col in apilabilidad_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
        else:
            df[col] = 0.0
    
    # Flags
    flag_cols = ["VALIOSO", "PDQ", "BAJA_VU", "LOTE_DIR"]
    for col in flag_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int).clip(0, 1)
        else:
            df[col] = 0
    
    # Filtros
    df = df[
        (df["PEDIDO"] != "") & 
        (df["PEDIDO"].notnull())
    ].copy()
    
    df = df.drop_duplicates(subset="PEDIDO", keep=False)
    df = df[df["PALLETS"] != 0].copy()
    
    # OC y PALLETS_REAL
    if "OC" in df.columns:
        df["OC"] = df["OC"].replace({"": None, "nan": None, "NaN": None, "none": None})
    
    if "PALLETS_REAL" in df.columns:
        df.loc[df["PALLETS_REAL"].isna(), "PALLETS_REAL"] = None
    
    # Crear pedidos dicts (metadata)
    standard_cols = {
        "PEDIDO", "CD", "CE", "PO", "PESO", "VOL", "PALLETS", "PALLETS_REAL",
        "VALOR", "VALOR_CAFE", "OC", "CHOCOLATES", "VALIOSO", "PDQ",
        "BAJA_VU", "LOTE_DIR", "BASE", "SUPERIOR", "FLEXIBLE", 
        "NO_APILABLE", "SI_MISMO"
    }
    metadata_cols = [c for c in df.columns if c not in standard_cols]
    
    pedidos_dicts = []
    for _, row in df.iterrows():
        pedido_dict = {"PEDIDO": str(row["PEDIDO"])}
        for col in metadata_cols:
            if col in row:
                pedido_dict[col] = row[col]
        pedidos_dicts.append(pedido_dict)
    
    return df, pedidos_dicts


# ============================================================================
# HELPERS DE CACHE (sin cambios)
# ============================================================================

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


def warn_missing_columns(df: pd.DataFrame, mapping: Dict[str, str]) -> List[str]:
    """Advierte sobre columnas faltantes"""
    missing = [excel_name for excel_name in mapping.values() if excel_name not in df.columns]
    return missing