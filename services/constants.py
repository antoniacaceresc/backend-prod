# services/constants.py
"""Constantes globales del optimizador"""

import os

# ============ Límites del solver ============
MAX_CAMIONES_CP_SAT = int(os.getenv("MAX_CAMIONES_CP_SAT", "20"))
MAX_TIEMPO_POR_GRUPO = int(os.getenv("MAX_TIEMPO_POR_GRUPO", "30"))

# ============ Escalamiento para CP-SAT ============
SCALE_VCU = 1000      # Escala para VCU (convertir float 0-1 a int 0-1000)
SCALE_PALLETS = 10    # Escala para pallets y apilabilidad

# ============ Concurrencia ============
GROUP_MAX_WORKERS = max((os.cpu_count() or 4) - 1, 1)
GROUP_MAX_WORKERS = int(os.getenv("GROUP_MAX_WORKERS", str(GROUP_MAX_WORKERS)))
THREAD_WORKERS_NORMAL = int(os.getenv("THREAD_WORKERS_NORMAL", str(min(8, (os.cpu_count() or 4)))))

# ============ Pesos de función objetivo (modo VCU) ============
PESO_VCU = 1000       # Peso para maximizar VCU
PESO_CAMIONES = 200   # Peso para minimizar número de camiones
PESO_PEDIDOS = 3000   # Peso para maximizar pedidos incluidos

# ============ Identificadores especiales ============
CD_LO_AGUIRRE = "6009 Lo Aguirre"

# ============ Cache de Excel ============
EXCEL_CACHE_DISABLE = os.getenv("EXCEL_CACHE_DISABLE", "false").lower() == "true"
PARQUET_CACHE_DIR = os.getenv("PARQUET_CACHE_DIR") or None