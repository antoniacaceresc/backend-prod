
class CencosudConfig:
    HEADER_ROW = 0

    # Configuraciones algoritmo
    USA_OC = False
    AGRUPAR_POR_PO = True
    MIX_GRUPOS = []

    # Configuración de validación altura
    VALIDAR_ALTURA = True
    PERMITE_CONSOLIDACION = False
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
        'paquetera':        {'cap_weight': 23000, 'cap_volume': 70000, 'max_positions': 30, 'levels': 2, 'vcu_min': 0.85, 'max_pallets': 60, 'altura_cm': 260},
        'rampla_directa':   {'cap_weight': 23000, 'cap_volume': 70000, 'max_positions': 28, 'levels': 2, 'vcu_min': 0.85, 'max_pallets': 56, 'altura_cm': 250},
        'backhaul':         {'cap_weight': 23000, 'cap_volume': 70000, 'max_positions': 26, 'levels': 2, 'vcu_min': 0.55, 'max_pallets': 52, 'altura_cm': 260}
    }



    # Configuración de rutas posibles con tipos de camiones permitidos
    RUTAS_POSIBLES = {
        "normal": [
            # N725 Bodega Noviciado
            {"cds": ["N725 Bodega Noviciado"], "ces": ["0079"], "camiones_permitidos": ["paquetera", "rampla_directa", "backhaul"]},
            {"cds": ["N725 Bodega Noviciado"], "ces": ["0080"], "camiones_permitidos": ["paquetera", "rampla_directa", "backhaul"]},
            {"cds": ["N725 Bodega Noviciado"], "ces": ["0088"], "camiones_permitidos": ["paquetera", "rampla_directa", "backhaul"]},
            {"cds": ["N725 Bodega Noviciado"], "ces": ["0103"], "camiones_permitidos": ["paquetera", "rampla_directa", "backhaul"]},
            {"cds": ["N725 Bodega Noviciado"], "ces": ["3598"], "camiones_permitidos": ["paquetera", "rampla_directa", "backhaul"]},
            {"cds": ["N725 Bodega Noviciado"], "ces": ["8150"], "camiones_permitidos": ["paquetera", "rampla_directa", "backhaul"]},

            # N641 Bodega Noviciado PYP
            {"cds": ["N641 Bodega Noviciado PYP"], "ces": ["0079"], "camiones_permitidos": ["paquetera", "rampla_directa", "backhaul"]},
            {"cds": ["N641 Bodega Noviciado PYP"], "ces": ["0080"], "camiones_permitidos": ["paquetera", "rampla_directa", "backhaul"]},
            {"cds": ["N641 Bodega Noviciado PYP"], "ces": ["0088"], "camiones_permitidos": ["paquetera", "rampla_directa", "backhaul"]},
            {"cds": ["N641 Bodega Noviciado PYP"], "ces": ["0103"], "camiones_permitidos": ["paquetera", "rampla_directa", "backhaul"]},
            {"cds": ["N641 Bodega Noviciado PYP"], "ces": ["3598"], "camiones_permitidos": ["paquetera", "rampla_directa", "backhaul"]},
            {"cds": ["N641 Bodega Noviciado PYP"], "ces": ["8150"], "camiones_permitidos": ["paquetera", "rampla_directa", "backhaul"]},

            # N794 Bodega Chillan - Solo Nestlé
            {"cds": ["N794 Bodega Chillan"], "ces": ["0079"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["N794 Bodega Chillan"], "ces": ["0080"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["N794 Bodega Chillan"], "ces": ["0088"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["N794 Bodega Chillan"], "ces": ["0103"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["N794 Bodega Chillan"], "ces": ["3598"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["N794 Bodega Chillan"], "ces": ["8150"], "camiones_permitidos": ["paquetera", "rampla_directa"]}
        ],

        "multi_ce": [
            # Solo Nestlé
            {"cds": ["N794 Bodega Chillan"], "ces": ["0088", "0103"], "camiones_permitidos": ["paquetera", "rampla_directa"]}
        ]
    }