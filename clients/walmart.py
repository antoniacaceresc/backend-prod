
class WalmartConfig:
    HEADER_ROW = 0

    # Configuraciones algoritmo
    USA_OC = True
    AGRUPAR_POR_PO = False

    # Parámetros de Optimización
    MAX_ORDENES = 10

    # CRR
    MAX_PALLETS_REAL_CRR = 90

    # BH
    PERMITE_BH = True
    CD_CON_BH = ['6009 Lo Aguirre', '6020 Peñón']
    BH_VCU_MAX = 1

    # MIX Flujo
    MIX_GRUPOS = [
        ['INV', 'CRR'],
        ['CRR', 'XDOCK'],]
    
    # Configuración de validación altura
    VALIDAR_ALTURA = True
    PERMITE_CONSOLIDACION = False
    MAX_SKUS_POR_PALLET = 1

    # Mapeo de columnas
    COLUMN_MAPPING = {
        "Secos": {   
            "CD": "CD",
            "PO": "Número PO",
            "PEDIDO": "N° Pedido",
            "OC": "Flujo OC", 
            "CE": "Ce.",
            "PALLETS": "Pal. Conf.",
            "PESO": "Peso neto Conf.",
            "VOL": "Vol. Conf.",
            "VALOR": "$$ Conf.",
            "VALOR_CAFE": "Valor Cafe",
            "CHOCOLATES": "Chocolates",
            "BASE": "Base",
            "SUPERIOR": "Superior",
            "FLEXIBLE": "Flexible",
            "NO_APILABLE": "No Apilable",
            "SI_MISMO": "Apilable si mismo",
            "PDQ": "PDQ",
            "SKU": "SKU",
            "ALTURA_PICKING": "Altura Picking",
            "ALTURA_FULL_PALLET": "Altura full Pallet"

        },
        "Purina": {
            "CD": "CD",
            "PO": "Número PO",
            "PEDIDO": "Nº Pedido",
            "OC": "Flujo OC", 
            "CE": "Ce.",
            "PALLETS": "Pal. Conf.",
            "PESO": "Peso Conf.",
            "VOL": "Vol. Conf.",
            "VALOR": "$$ Conf."
        }
    }

    EXTRA_MAPPING = {
        "Solic.":   "Solic.",
        "Cant. Sol.": "Cj. Solic.",
        "CJ Conf.": "Cj. Conf.",
        "Suma de Sol (Pallet)": "Pal. Solic.",
        "Suma de Conf (Pallet)": "Pal. Conf.",
        "Suma de Valor neto CONF": "$$ Conf.",
        "%NS": "%NS",
        "Fecha preferente de entrega": "Fecha prefer/entrega",
    }

    # Tipos de camiones
    TRUCK_TYPES = {
        'normal': {'cap_weight': 23000, 'cap_volume': 70000, 'max_positions': 30, 'levels': 2, 'vcu_min': 0.90, 'max_pallets': 60,'altura_cm': 270},
        'bh':     {'cap_weight': 23000, 'cap_volume': 70000, 'max_positions': 28, 'levels': 2, 'vcu_min': 0.55, 'max_pallets': 56, 'altura_cm': 270}
    }

    # Configuración agrupamiento especial

    RUTAS_POSIBLES = {
        "multi_ce_prioridad": [
            (["6009 Lo Aguirre"],["0088", "3598"]),
            (["6020 Peñón"],["0088", "3598"]),
            (["6003 Antofagasta"],["0088", "3598"]),
            (["6010 Chillán"],["0088", "3598"]),
            (["6024 Temuco"],["0088", "3598"]),
        ],
        
        "normal": [
            (["6009 Lo Aguirre"],["0079"]),
            (["6009 Lo Aguirre"],["0080"]),
            (["6009 Lo Aguirre"],["0088"]),
            (["6009 Lo Aguirre"],["0097"]),
            (["6009 Lo Aguirre"],["0103"]),
            (["6009 Lo Aguirre"],["3598"]),
            (["6009 Lo Aguirre"],["8150"]),
            (["6020 Peñón"],["0079"]),
            (["6020 Peñón"],["0080"]),
            (["6020 Peñón"],["0088"]),
            (["6020 Peñón"],["0097"]),
            (["6020 Peñón"],["0103"]),
            (["6020 Peñón"],["3598"]),
            (["6020 Peñón"],["8150"]),
            (["6010 Chillán"],["0079"]),
            (["6010 Chillán"],["0080"]),
            (["6010 Chillán"],["0088"]),
            (["6010 Chillán"],["0097"]),
            (["6010 Chillán"],["0103"]),
            (["6010 Chillán"],["3598"]),
            (["6010 Chillán"],["8150"]),
            (["6024 Temuco"],["0079"]),
            (["6024 Temuco"],["0080"]),
            (["6024 Temuco"],["0088"]),
            (["6024 Temuco"],["0097"]),
            (["6024 Temuco"],["0103"]),
            (["6024 Temuco"],["3598"]),
            (["6024 Temuco"],["8150"]),
            (["6003 Antofagasta"],["0079"]),
            (["6003 Antofagasta"],["0080"]),
            (["6003 Antofagasta"],["0088"]),
            (["6003 Antofagasta"],["0097"]),
            (["6003 Antofagasta"],["0103"]),
            (["6003 Antofagasta"],["3598"]),
            (["6003 Antofagasta"],["8150"]),
            (["6011 LTS Fríos"],["0076"])
        ],

        "multi_ce": [
            
            (["6009 Lo Aguirre"],["0088", "0097"]),
            (["6020 Peñón"],["0088", "0097"]),
            (["6003 Antofagasta"],["0088", "0097"]),
            (["6010 Chillán"],["0088", "0097"]),
            (["6024 Temuco"],["0088", "0097"]),

            # Ces: Quilicura
            (["6009 Lo Aguirre"],["0088", "3598"]),
            (["6020 Peñón"],["0088", "3598"]),
            (["6003 Antofagasta"],["0088", "3598"]),
            (["6010 Chillán"],["0088", "3598"]),
            (["6024 Temuco"],["0088", "3598"]),

            # Ces: Quilicura y Maipú
            (["6003 Antofagasta"],["0088", "0103"]),
            (["6010 Chillán"],["0088", "0103"]),
            (["6024 Temuco"],["0088", "0103"]),

            # Ces: Quilicura y Teno
            (["6003 Antofagasta"],["0088", "8151"]),
            (["6010 Chillán"],["0088", "8151"]),
            (["6024 Temuco"],["0088", "8151"]),

            # Ces: Maipú y Teno
            (["6003 Antofagasta"],["0103", "8151"]),
            (["6010 Chillán"],["0103", "8151"]),
            (["6024 Temuco"],["0103", "8151"]),

            # Ces: Quilicura y San Fernando
            (["6010 Chillán"],["0088", "0079"]),
            (["6024 Temuco"],["0088", "0079"]),

            # Ces: Maipú y San Fernando
            (["6010 Chillán"],["0103", "0079"]),
            (["6024 Temuco"],["0103", "0079"]),

            # Ces: Maipú y Teno
            (["6003 Antofagasta"],["0103", "8151"]),

            # Ces: San Fernando y Teno
            (["6003 Antofagasta"],["0079", "8151"]),

        ],

        "multi_cd": [
            # Desde Quilicura
            (["6010 Chillán","6024 Temuco"],["0088"]),

            # Desde Maipú
            (["6010 Chillán","6024 Temuco"],["0103"]),

        ],

        "bh": [
            (["6009 Lo Aguirre"],["0079"]),
            (["6009 Lo Aguirre"],["0080"]),
            (["6009 Lo Aguirre"],["0088"]),
            (["6009 Lo Aguirre"],["0097"]),
            (["6009 Lo Aguirre"],["0103"]),
            (["6009 Lo Aguirre"],["3598"]),
            (["6009 Lo Aguirre"],["8150"]),
            (["6020 Peñón"],["0079"]),
            (["6020 Peñón"],["0080"]),
            (["6020 Peñón"],["0088"]),
            (["6020 Peñón"],["0097"]),
            (["6020 Peñón"],["0103"]),
            (["6020 Peñón"],["3598"]),
            (["6020 Peñón"],["8150"]),
        ]

    }

