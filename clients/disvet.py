
class DisvetConfig:
    HEADER_ROW = 0

    # Configuraciones algoritmo
    USA_OC = False
    AGRUPAR_POR_PO = False

    # MIX Flujo
    MIX_GRUPOS = []

    # Configuración de validación altura
    VALIDAR_ALTURA = True
    PERMITE_CONSOLIDACION = True
    MAX_SKUS_POR_PALLET = 5

    # Mapeo de columnas 
    COLUMN_MAPPING = {
        "Secos": {   
            "CD": "CD",
            "PO": "Número PO",
            "PEDIDO": "N° Pedido",
            "CE": "Ce.",
            "PALLETS": "Pal. Conf.",
            "PESO": "Peso neto Conf.",
            "VOL": "Vol. Conf.",
            "VALOR": "$$ Conf.",
            "CHOCOLATES": "Chocolates",
            "VALOR_CAFE": "Valor Cafe",
            "BAJA_VU": "Baja VU Disvet",
            "LOTE_DIR": "Lote Dirigido Disvet",
            "BASE": "Base",
            "SUPERIOR": "Superior",
            "FLEXIBLE": "Flexible",
            "NO_APILABLE": "No Apilable",
            "SI_MISMO": "Apilable si mismo",
        },
    }

    EXTRA_MAPPING = {
        "Solic.":   "Solic.",
        "Cant. Sol.": "Cj. Solic.",
        "CJ Conf.": "Cj. Conf.",
        "Suma de Conf (Pallet)": "Pal. Conf.",
        "Suma de Valor neto CONF": "$$ Conf.",
        "%NS": "%NS",
        "Fecha preferente de entrega": "Fecha prefer/entrega", 
    }

    # Tipos de camiones
    TRUCK_TYPES = {
        'paquetera':        {'cap_weight': 23000, 'cap_volume': 70000, 'max_positions': 30, 'levels': 2, 'vcu_min': 0.5, 'max_pallets': 60,'altura_cm': 260},
        'rampla_directa':   {'cap_weight': 23000, 'cap_volume': 70000, 'max_positions': 28, 'levels': 2, 'vcu_min': 0.5, 'max_pallets': 56,'altura_cm': 250},
        'backhaul':         {'cap_weight': 23000, 'cap_volume': 70000, 'max_positions': 28, 'levels': 2, 'vcu_min': 0.5, 'max_pallets': 56, 'altura_cm': 260}
    }

    # Configuración agrupamiento especial
# Configuración agrupamiento especial
    RUTAS_POSIBLES = {
        "normal": [
            # CDs que NO permiten backhaul - solo Nestlé
            {"cds": ["Bioñuble"], "ces": ["0088"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["Bioñuble"], "ces": ["0097"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["Bioñuble"], "ces": ["0103"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            
            {"cds": ["Comech"], "ces": ["0088"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["Comech"], "ces": ["0097"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["Comech"], "ces": ["0103"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            
            {"cds": ["Ferrbest"], "ces": ["0088"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["Ferrbest"], "ces": ["0097"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["Ferrbest"], "ces": ["0103"], "camiones_permitidos": ["paquetera", "rampla_directa"]},

            {"cds": ["Friex"], "ces": ["0088"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["Friex"], "ces": ["0097"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["Friex"], "ces": ["0103"], "camiones_permitidos": ["paquetera", "rampla_directa"]},

            {"cds": ["HN"], "ces": ["0088"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["HN"], "ces": ["0097"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["HN"], "ces": ["0103"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            
            {"cds": ["Jama"], "ces": ["0088"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["Jama"], "ces": ["0097"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["Jama"], "ces": ["0103"], "camiones_permitidos": ["paquetera", "rampla_directa"]},

            {"cds": ["Maxima"], "ces": ["0088"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["Maxima"], "ces": ["0097"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["Maxima"], "ces": ["0103"], "camiones_permitidos": ["paquetera", "rampla_directa"]},

            {"cds": ["Norkoshe"], "ces": ["0088"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["Norkoshe"], "ces": ["0097"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["Norkoshe"], "ces": ["0103"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            
            {"cds": ["Pan de Azucar"], "ces": ["0088"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["Pan de Azucar"], "ces": ["0097"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["Pan de Azucar"], "ces": ["0103"], "camiones_permitidos": ["paquetera", "rampla_directa"]},

            {"cds": ["Relun"], "ces": ["0088"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["Relun"], "ces": ["0097"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["Relun"], "ces": ["0103"], "camiones_permitidos": ["paquetera", "rampla_directa"]},

            {"cds": ["Vivancos SPA"], "ces": ["0088"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["Vivancos SPA"], "ces": ["0097"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["Vivancos SPA"], "ces": ["0103"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            
            # CDs que SOLO permiten backhaul
            {"cds": ["Cerro Grande"], "ces": ["0088"], "camiones_permitidos": ["backhaul"]},
            {"cds": ["Cerro Grande"], "ces": ["0097"], "camiones_permitidos": ["backhaul"]},
            {"cds": ["Cerro Grande"], "ces": ["0103"], "camiones_permitidos": ["backhaul"]},
            
            {"cds": ["Kameid"], "ces": ["0088"], "camiones_permitidos": ["backhaul"]},
            {"cds": ["Kameid"], "ces": ["0097"], "camiones_permitidos": ["backhaul"]},
            {"cds": ["Kameid"], "ces": ["0103"], "camiones_permitidos": ["backhaul"]},
        ],

        "multi_ce": [
            # Multi-CE SOLO con backhaul
            {"cds": ["Cerro Grande"], "ces": ["0088", "0103"], "camiones_permitidos": ["backhaul"]},
            {"cds": ["Kameid"], "ces": ["0088", "0103"], "camiones_permitidos": [ "backhaul"]},
        ],
        
        "multi_cd": [
            # Desde Quilicura - solo Nestlé
            {"cds": ["Bioñuble","Relun"], "ces": ["0088"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["Norkoshe", "HN"], "ces": ["0088"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["Pan de Azucar", "Jama"], "ces": ["0088"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["Ferrbest", "Comech"], "ces": ["0088"], "camiones_permitidos": ["paquetera", "rampla_directa"]},

            # Desde Maipú - solo Nestlé
            {"cds": ["Bioñuble","Relun"], "ces": ["0103"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["Norkoshe", "HN"], "ces": ["0103"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["Pan de Azucar", "Jama"], "ces": ["0103"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["Ferrbest", "Comech"], "ces": ["0103"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
        ],
    }

