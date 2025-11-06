
class CencosudConfig:
    HEADER_ROW = 0

    # Configuraciones algoritmo
    USA_OC = False
    AGRUPAR_POR_PO = True
    MIX_GRUPOS = []

    # Parámetros de Optimización

    # BH
    PERMITE_BH = True
    CD_CON_BH = ['N725 Bodega Noviciado', 'N641 Bodega Noviciado PYP']
    BH_VCU_MAX = 1
    BH_TRUCK_TARGET_RATIO = 0.60

    # Configuración de validación altura
    VALIDAR_ALTURA = True
    PERMITE_CONSOLIDACION = True
    MAX_SKUS_POR_PALLET = 5 # Verificar

    # Mapeo de columnas
    COLUMN_MAPPING = {
        "Secos": {   
            "CD": "CD",
            "PO": "Número PO",
            "PEDIDO": "N° Pedido",
            "CE": "Ce.",
            "PALLETS": "Pal. Conf.",
            "PALLETS_REAL": "Pal. Conf. Real",
            "PESO": "Peso neto Conf.",
            "VOL": "Vol. Conf.",
            "VALOR": "$$ Conf.",
            "CHOCOLATES": "Chocolates",
            "VALOR_CAFE": "Valor Cafe",
            "BASE": "Base",
            "SUPERIOR": "Superior",
            "FLEXIBLE": "Flexible",
            "NO_APILABLE": "No Apilable",
            "SI_MISMO": "Apilable si mismo",
            "VALIOSO": "Valioso Cencosud",
            "PDQ": "PDQ"
        },
        "Purina": {
            "CD": "CD",
            "PO": "Número PO",
            "PEDIDO": "N° Pedido",
            "CE": "Ce.",
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
        'normal': {'cap_weight': 23000, 'cap_volume': 70000, 'max_positions': 30, 'levels': 2, 'vcu_min': 0.85, 'max_pallets': 60, 'altura_cm': 270},
        'bh':     {'cap_weight': 23000, 'cap_volume': 70000, 'max_positions': 26, 'levels': 2, 'vcu_min': 0.55, 'max_pallets': 52, 'altura_cm': 270}
    }



    # Configuración agrupamiento especial

    RUTAS_POSIBLES = {
        "normal": [
            (["N725 Bodega Noviciado"],["0079"]),
            (["N725 Bodega Noviciado"],["0080"]),
            (["N725 Bodega Noviciado"],["0088"]),
            (["N725 Bodega Noviciado"],["0103"]),
            (["N725 Bodega Noviciado"],["3598"]),
            (["N725 Bodega Noviciado"],["8150"]),

            (["N641 Bodega Noviciado PYP"],["0079"]),
            (["N641 Bodega Noviciado PYP"],["0080"]),
            (["N641 Bodega Noviciado PYP"],["0088"]),
            (["N641 Bodega Noviciado PYP"],["0103"]),
            (["N641 Bodega Noviciado PYP"],["3598"]),
            (["N641 Bodega Noviciado PYP"],["8150"]),

            (["N794 Bodega Chillan"],["0079"]),
            (["N794 Bodega Chillan"],["0080"]),
            (["N794 Bodega Chillan"],["0088"]),
            (["N794 Bodega Chillan"],["0103"]),
            (["N794 Bodega Chillan"],["3598"]),
            (["N794 Bodega Chillan"],["8150"])
        ],

        "multi_ce": [

            (["N794 Bodega Chillan"],["0088", "0103"]),

        ],

        "bh": [
            (["N725 Bodega Noviciado"],["0079"]),
            (["N725 Bodega Noviciado"],["0080"]),
            (["N725 Bodega Noviciado"],["0088"]),
            (["N725 Bodega Noviciado"],["0103"]),
            (["N725 Bodega Noviciado"],["3598"]),
            (["N725 Bodega Noviciado"],["8150"]),

            (["N641 Bodega Noviciado PYP"],["0079"]),
            (["N641 Bodega Noviciado PYP"],["0080"]),
            (["N641 Bodega Noviciado PYP"],["0088"]),
            (["N641 Bodega Noviciado PYP"],["0103"]),
            (["N641 Bodega Noviciado PYP"],["3598"]),
            (["N641 Bodega Noviciado PYP"],["8150"]),
        ]

    }

