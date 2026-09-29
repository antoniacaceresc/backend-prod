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
        "DESCRIPCION": "Descripción",
    }
    
    # Agregar solo si no están en el mapping (para permitir override por cliente)
    for internal, excel_col in columnas_sku.items():
        if internal not in mapping:
            mapping[internal] = excel_col
    
    return mapping


# PROCESAMIENTO
def process_dataframe(
    df_full: pd.DataFrame, 
    client_config, 
    cliente: str, 
    venta: str
) -> Tuple[pd.DataFrame, List[Dict[str, Any]]]:
    """
    Procesa DataFrame del Excel.
    
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

    return _process_dataframe_con_skus(df_raw, client_config, cliente, venta)


# PROCESAMIENTO CON SKU
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
    from utils.config_helpers import get_effective_config
    effective = get_effective_config(client_config, venta)
    truck_types = effective.get("TRUCK_TYPES", {})
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
        "ALTURA_FULL_PALLET", "ALTURA_PICKING", "PALLETS_ESTIMADO", "PALLETS_SOLIC", "PESO_SOLIC", "VOL_SOLIC"
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(
                df[col].astype(str).str.replace(",", ".", regex=False),
                errors="coerce"
            ).fillna(0)
    
    # Apilabilidad: inicializar todas las columnas internas
    for col in ["BASE", "SUPERIOR", "FLEXIBLE", "NO_APILABLE", "SI_MISMO",
                "BASE_SIMISMO", "SUPERIOR_SIMISMO"]:
        df[col] = 0.0

    if "APILABILIDAD" in df.columns:
        # Nuevo formato: columna unificada con valores como "base", "superior, si mismo"
        df = _parsear_apilabilidad_unificada(df)
    else:
        # Retrocompatibilidad: columnas separadas
        for col in ["BASE", "SUPERIOR", "FLEXIBLE", "NO_APILABLE", "SI_MISMO"]:
            if col in df.columns:
                df[col] = pd.to_numeric(
                    df[col].astype(str).str.replace(",", ".", regex=False),
                    errors="coerce"
                ).fillna(0)

    # Flags (a nivel SKU, se agregarán con MAX)
    flag_cols = ["VALIOSO", "PDQ", "BAJA_VU", "LOTE_DIR"]
    for col in flag_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int).clip(0, 1)
        else:
            df[col] = 0
        
    # Chocolates (especial: SI/NO -> 1/0 para MAX, luego volver a SI/NO)
    if "CHOCOLATES" in df.columns:
        chocolates_str = df["CHOCOLATES"].astype(str).str.upper().str.strip()
        df["CHOCOLATES_FLAG"] = chocolates_str.isin(["SI", "SÍ", "1", "X", "TRUE", "YES"]).astype(int)
    else:
        df["CHOCOLATES_FLAG"] = 0

    
    pedidos_antes = set(df["PEDIDO"].unique()) if "PEDIDO" in df.columns else set()
    
    # Filtros
    df = df[
        (df["PEDIDO"] != "") & 
        (df["PEDIDO"].notnull()) &
        (df["SKU"] != "") &
        (df["SKU"].notnull())
    ].copy()
    
    # Antes de filtrar, acumular Cant. Sol. de líneas sin stock por pedido
    # para que el %NS final considere todas las unidades solicitadas
    if "Cant. Sol." in df.columns and "PEDIDO" in df.columns:
        cant_sol_sin_stock = (
            df[df["PALLETS"] <= 0]
            .groupby("PEDIDO")["Cant. Sol."]
            .sum()
            .rename("_CANT_SOL_SIN_STOCK")
        )
        df = df.join(cant_sol_sin_stock, on="PEDIDO")
        # Propagar el total sin stock a todas las filas del pedido (para que al agrupar se tome bien)
        df["_CANT_SOL_SIN_STOCK"] = df["_CANT_SOL_SIN_STOCK"].fillna(0)
    else:
        df["_CANT_SOL_SIN_STOCK"] = 0.0

    # Filtrar filas con pallets = 0
    df = df[df["PALLETS"] > 0].copy()

    # Preservar campos extra numéricos
    campos_extra_numericos = ["Cant. Sol.", "CJ Conf.", "%NS", "Suma de Sol (Pallet)", "Suma de Conf (Pallet)"]
    for col in campos_extra_numericos:
        if col in df.columns:
            df[col] = pd.to_numeric(
                df[col].astype(str).str.replace(",", ".", regex=False),
                errors="coerce"
            ).fillna(0)

    # Asegurar que _CANT_SOL_SIN_STOCK sea numérico
    if "_CANT_SOL_SIN_STOCK" in df.columns:
        df["_CANT_SOL_SIN_STOCK"] = pd.to_numeric(df["_CANT_SOL_SIN_STOCK"], errors="coerce").fillna(0)

    return df

def _parsear_apilabilidad_unificada(df: pd.DataFrame) -> pd.DataFrame:
    """
    Parsea columna 'APILABILIDAD' con valores como 'base', 'superior, si mismo'.
    Asigna los pallets del SKU a las categorías correspondientes.

    Para compuestos (ej: 'base, si mismo'):
    - Los pallets se asignan a la categoría primaria (BASE)
    - Se marca la columna compuesta (BASE_SIMISMO) con el mismo valor
    """
    CATEGORIAS_MAP = {
        "base": "BASE",
        "superior": "SUPERIOR",
        "flexible": "FLEXIBLE",
        "no apilable": "NO_APILABLE",
        "no_apilable": "NO_APILABLE",
        "si mismo": "SI_MISMO",
        "si_mismo": "SI_MISMO",
        "apilable si mismo": "SI_MISMO",
    }

    for idx in df.index:
        raw = str(df.at[idx, "APILABILIDAD"]).strip().lower()
        pallets = df.at[idx, "PALLETS"]

        if not raw or raw == "nan":
            df.at[idx, "NO_APILABLE"] = pallets
            continue

        cats_raw = [c.strip() for c in raw.split(",") if c.strip()]
        cats = set()
        for c in cats_raw:
            mapped = CATEGORIAS_MAP.get(c)
            if mapped:
                cats.add(mapped)

        if not cats:
            df.at[idx, "NO_APILABLE"] = pallets
            continue

        # Detectar compuestos
        if "BASE" in cats and "SI_MISMO" in cats:
            df.at[idx, "BASE"] = pallets
            df.at[idx, "BASE_SIMISMO"] = pallets
        elif "SUPERIOR" in cats and "SI_MISMO" in cats:
            df.at[idx, "SUPERIOR"] = pallets
            df.at[idx, "SUPERIOR_SIMISMO"] = pallets
        elif len(cats) == 1:
            df.at[idx, cats.pop()] = pallets
        else:
            # Combinación no contemplada → usar primera por prioridad
            prioridad = ["NO_APILABLE", "BASE", "SUPERIOR", "FLEXIBLE", "SI_MISMO"]
            for cat in prioridad:
                if cat in cats:
                    df.at[idx, cat] = pallets
                    break

    return df

def _optimizar_apilabilidad_skus(df: pd.DataFrame, altura_maxima_cm: float = 260) -> pd.DataFrame:
    """
    Optimiza categorías de apilabilidad ANTES de la optimización.

    Reglas:
    1. Altura > 200cm → NO_APILABLE (aplica a puros y compuestos)
    2. 2 × altura > altura_max → no puede apilarse consigo mismo:
       - SI_MISMO puro → intentar convertir a BASE/SUPERIOR
       - Compuesto → se queda como BASE/SUPERIOR puro (se limpia el flag)
    3. Cantidad impar o con picking → solo para SI_MISMO puro.
       Los compuestos NO se tocan: conservan su doble rol y el validador
       decide en el layout si aparean entre sí o se montan sobre una base.

    Args:
        df: DataFrame de SKUs con columnas de apilabilidad
        altura_maxima_cm: Altura máxima del camión

    Returns:
        DataFrame con apilabilidad optimizada
    """
    df = df.copy()

    cambios = {
        'si_mismo_a_no_apilable': 0,
        'si_mismo_a_base_superior': 0,
        'impares_ajustados': 0,
        'compuestos_degradados': 0,
    }

    cols_apil = ['BASE', 'SUPERIOR', 'FLEXIBLE', 'NO_APILABLE', 'SI_MISMO',
                 'BASE_SIMISMO', 'SUPERIOR_SIMISMO']
    for col in cols_apil:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0).astype(float)
        else:
            df[col] = 0.0

    # SKUs que pueden apilarse consigo mismos: puros o compuestos
    mask = (df['SI_MISMO'] > 0) | (df['BASE_SIMISMO'] > 0) | (df['SUPERIOR_SIMISMO'] > 0)

    for idx in df[mask].index:

        altura = float(df.at[idx, 'ALTURA_FULL_PALLET'] or 0)

        es_base_sim = float(df.at[idx, 'BASE_SIMISMO']) > 0
        es_sup_sim = float(df.at[idx, 'SUPERIOR_SIMISMO']) > 0
        es_compuesto = es_base_sim or es_sup_sim

        if es_base_sim:
            col_sim = 'BASE_SIMISMO'
            col_primaria = 'BASE'
        elif es_sup_sim:
            col_sim = 'SUPERIOR_SIMISMO'
            col_primaria = 'SUPERIOR'
        else:
            col_sim = 'SI_MISMO'
            col_primaria = None

        si_mismo = float(df.at[idx, col_sim])

        pallets_completos = int(si_mismo)
        picking = si_mismo - pallets_completos
        es_solo_picking = pallets_completos == 0

        # ── REGLAS 1 y 2: solo con pallets completos ──
        if not es_solo_picking:

            # REGLA 1: altura > 200cm → NO_APILABLE
            if altura > 200:
                df.at[idx, 'NO_APILABLE'] = float(df.at[idx, 'NO_APILABLE']) + si_mismo
                df.at[idx, col_sim] = 0.0
                if col_primaria:
                    df.at[idx, col_primaria] = float(df.at[idx, col_primaria]) - si_mismo
                cambios['si_mismo_a_no_apilable'] += 1
                continue

            # REGLA 2: 2 × altura > altura_max → no puede auto-apilarse
            if 2 * altura > altura_maxima_cm:
                if es_compuesto:
                    # Ya está contabilizado en BASE/SUPERIOR: solo pierde el rol si_mismo
                    df.at[idx, col_sim] = 0.0
                    cambios['compuestos_degradados'] += 1
                else:
                    puede_ser_base = float(df.at[idx, 'BASE']) > 0 or _tiene_columna_base(df, idx)
                    puede_ser_superior = float(df.at[idx, 'SUPERIOR']) > 0 or _tiene_columna_superior(df, idx)

                    if puede_ser_base:
                        df.at[idx, 'BASE'] = float(df.at[idx, 'BASE']) + si_mismo
                        df.at[idx, 'SI_MISMO'] = 0.0
                        cambios['si_mismo_a_base_superior'] += 1
                    elif puede_ser_superior:
                        df.at[idx, 'SUPERIOR'] = float(df.at[idx, 'SUPERIOR']) + si_mismo
                        df.at[idx, 'SI_MISMO'] = 0.0
                        cambios['si_mismo_a_base_superior'] += 1
                continue

        # ── REGLA 3: sobrantes impares ──
        if es_solo_picking:
            a_convertir = picking
        elif pallets_completos % 2 != 0:
            a_convertir = 1 + picking
        elif picking > 0.001:
            a_convertir = picking
        else:
            a_convertir = 0.0

        if a_convertir > 0.001:
            puede_ser_base = float(df.at[idx, 'BASE']) > 0 or _tiene_columna_base(df, idx)
            puede_ser_superior = float(df.at[idx, 'SUPERIOR']) > 0 or _tiene_columna_superior(df, idx)

            if puede_ser_base:
                df.at[idx, 'BASE'] = float(df.at[idx, 'BASE']) + a_convertir
                df.at[idx, 'SI_MISMO'] = float(df.at[idx, 'SI_MISMO']) - a_convertir
                cambios['impares_ajustados'] += 1
            elif puede_ser_superior:
                df.at[idx, 'SUPERIOR'] = float(df.at[idx, 'SUPERIOR']) + a_convertir
                df.at[idx, 'SI_MISMO'] = float(df.at[idx, 'SI_MISMO']) - a_convertir
                cambios['impares_ajustados'] += 1

    for col in cols_apil:
        df[col] = df[col].clip(lower=0)

    # Invariante: un compuesto nunca puede exceder su categoría primaria
    df['BASE_SIMISMO'] = df[['BASE_SIMISMO', 'BASE']].min(axis=1)
    df['SUPERIOR_SIMISMO'] = df[['SUPERIOR_SIMISMO', 'SUPERIOR']].min(axis=1)

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
    
    #  Validar altura - puede ser 0 si es picking vacío
    # Solo validamos que NO sea negativa
    skus_altura_negativa = df[df["ALTURA_FULL_PALLET"] < 0]
    if len(skus_altura_negativa) > 0:
        errores.append(
            f"{len(skus_altura_negativa)} SKUs con altura negativa. "
            f"Ejemplos: {skus_altura_negativa['SKU'].head(3).tolist()}"
        )
    
    #  Advertir si altura = 0
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
            df.at[idx, 'BASE_SIMISMO'] *= factor
            df.at[idx, 'SUPERIOR_SIMISMO'] *= factor
            
    
    df = df.drop(columns=["SUMA_APILABILIDAD", "EXCEDE_PALLETS"])
    
    # Separar apilabilidad por valor (valioso / no valioso) a nivel SKU.
    # Solo se poblarán de forma útil cuando el cliente use SEPARAR_APILABILIDAD_POR_VALOR, para el resto quedan en 0 y no afectan nada.
    apilabilidad_cols = ["BASE", "SUPERIOR", "FLEXIBLE", "NO_APILABLE", "SI_MISMO", "BASE_SIMISMO", "SUPERIOR_SIMISMO"]
    es_val = df["VALIOSO"] == 1
    for col in apilabilidad_cols:
        df[f"{col}_VAL"] = df[col].where(es_val, 0.0)
        df[f"{col}_NOVAL"] = df[col].where(~es_val, 0.0)
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
        "BASE", "SUPERIOR", "FLEXIBLE", "NO_APILABLE", "SI_MISMO",
        "BASE_SIMISMO", "SUPERIOR_SIMISMO",
        "PALLETS_ESTIMADO",
        "BASE_VAL", "SUPERIOR_VAL", "FLEXIBLE_VAL", "NO_APILABLE_VAL", "SI_MISMO_VAL",
        "BASE_NOVAL", "SUPERIOR_NOVAL", "FLEXIBLE_NOVAL", "NO_APILABLE_NOVAL", "SI_MISMO_NOVAL",
        "BASE_SIMISMO_VAL", "SUPERIOR_SIMISMO_VAL",
        "BASE_SIMISMO_NOVAL", "SUPERIOR_SIMISMO_NOVAL",
    ]
    
    # Campos que se toman con MAX (flags)
    campos_max = [
        "VALIOSO", "PDQ", "BAJA_VU", "LOTE_DIR", "CHOCOLATES_FLAG"
    ]
    
    # Campos de identidad (deben ser iguales, tomar el primero)
    campos_identidad = ["CD", "CE", "PO", "SUBCLIENTE"]
    
    # Agregar OC si existe
    if "OC" in df_skus.columns:
        campos_identidad.append("OC")

    # Campos extra - identidad (primer valor)
    campos_extra_first = ["Solic.", "Fecha preferente de entrega", "Fecha documento"]
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

    # _CANT_SOL_SIN_STOCK: sumar por pedido (solo necesitamos el total una vez)
    if "_CANT_SOL_SIN_STOCK" in df_skus.columns:
        agg_rules["_CANT_SOL_SIN_STOCK"] = "sum"
    
    for col in campos_suma:
        if col in df_skus.columns:
            agg_rules[col] = "sum"
    
    for col in campos_max:
        if col in df_skus.columns:
            agg_rules[col] = "max"
    
    for col in campos_identidad:
        if col in df_skus.columns:
            agg_rules[col] = "first"

    # Derivar ES_PURINA desde canal de venta
    if "CANAL_VENTA" in df_skus.columns:
        df_skus["ES_PURINA"] = (df_skus["CANAL_VENTA"].astype(str).str.strip().str.upper() == "CL25").astype(int)
    else:
        df_skus["ES_PURINA"] = 0

    if "ES_PURINA" in df_skus.columns:
        agg_rules["ES_PURINA"] = "first"

    # Agrupar por PEDIDO
    df_pedidos = df_skus.groupby("PEDIDO", as_index=False).agg(agg_rules)

    # Recalcular %NS correctamente:
    # denominador = Cant. Sol. confirmadas + Cant. Sol. de líneas sin stock
    if "Cant. Sol." in df_pedidos.columns and "CJ Conf." in df_pedidos.columns:
        cant_sol_sin_stock = df_pedidos.get("_CANT_SOL_SIN_STOCK", 0)
        cant_sol_total = df_pedidos["Cant. Sol."] + cant_sol_sin_stock
        df_pedidos["%NS"] = (
            df_pedidos["CJ Conf."] / cant_sol_total.replace(0, float("nan"))
        ).fillna(0).clip(0, 1)
        df_pedidos = df_pedidos.drop(columns=["_CANT_SOL_SIN_STOCK"], errors="ignore")

    # Normalizar SUBCLIENTE a "Alvi" o "Rendic"
    if "SUBCLIENTE" in df_pedidos.columns:
        df_pedidos["SUBCLIENTE"] = df_pedidos["SUBCLIENTE"].apply(
            lambda x: "Alvi" if str(x).strip() == "Alvi" else "Rendic"
        )
    
    # Convertir CHOCOLATES_FLAG de vuelta a SI/NO
    if "CHOCOLATES_FLAG" in df_pedidos.columns:
        df_pedidos["CHOCOLATES"] = df_pedidos["CHOCOLATES_FLAG"].apply(
            lambda x: "SI" if x == 1 else "NO"
        )
        df_pedidos = df_pedidos.drop(columns=["CHOCOLATES_FLAG"])

    if "ES_PURINA" in df_skus.columns:
        agg_rules["ES_PURINA"] = "first"
    
    if "Fecha preferente de entrega" in df_pedidos.columns:
        df_pedidos['Fecha preferente de entrega'] = pd.to_datetime(df_pedidos['Fecha preferente de entrega']).dt.strftime('%d-%m-%Y')

    
    if "Fecha documento" in df_pedidos.columns:
        df_pedidos['Fecha documento'] = pd.to_datetime(df_pedidos['Fecha documento']).dt.strftime('%d-%m-%Y')
    
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
            "_skus": skus_pedido.to_dict("records"),
            "_pallets_estimado": row_pedido.get("PALLETS_ESTIMADO", row_pedido.get("PALLETS", 0))
        }
        
        pedidos_dicts.append(pedido_dict)
    
    return pedidos_dicts

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
