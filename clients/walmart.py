
class WalmartConfig:
    HEADER_ROW = 0

    # Configuraciones algoritmo
    USA_OC = True
    AGRUPAR_POR_PO = False

    # Parámetros de Optimización
    MAX_ORDENES = 10

    # CRR
    MAX_PALLETS_REAL_CRR = 90

    # MIX Flujo
    MIX_GRUPOS = [
        ['INV', 'CRR'],
        ['CRR', 'XDOCK'],]
    
    ADHERENCIA_BACKHAUL = None
    MODO_ADHERENCIA = None
    
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
            "ALTURA_FULL_PALLET": "Altura full Pallet",
            "APILABLE_BASE": "Apilable Base",
            "MONTADO": "Montado",  

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
        'paquetera':        {'cap_weight': 23000, 'cap_volume': 70000, 'max_positions': 30, 'levels': 2, 'vcu_min': 0.8, 'max_pallets': 60,'altura_cm': 260},
        'rampla_directa':   {'cap_weight': 23000, 'cap_volume': 70000, 'max_positions': 28, 'levels': 2, 'vcu_min': 0.8, 'max_pallets': 56,'altura_cm': 250},
        'backhaul':         {'cap_weight': 23000, 'cap_volume': 70000, 'max_positions': 28, 'levels': 2, 'vcu_min': 0.5, 'max_pallets': 56, 'altura_cm': 240}
    }

    # Configuración agrupamiento especial
    RUTAS_POSIBLES = {
        "multi_ce_prioridad": [
            {"cds": ["6009 Lo Aguirre"], "ces": ["0088", "3598"], "camiones_permitidos": ["paquetera", "rampla_directa", "backhaul"]},
            {"cds": ["6020 Peñón"], "ces": ["0088", "3598"], "camiones_permitidos": ["paquetera", "rampla_directa", "backhaul"]},
            {"cds": ["6003 Antofagasta"], "ces": ["0088", "3598"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["6010 Chillán"], "ces": ["0088", "3598"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["6024 Temuco"], "ces": ["0088", "3598"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
        ],
        
        "normal": [
            # Lo Aguirre - permite backhaul
            {"cds": ["6009 Lo Aguirre"], "ces": ["0079"], "camiones_permitidos": ["paquetera", "rampla_directa", "backhaul"]},
            {"cds": ["6009 Lo Aguirre"], "ces": ["0080"], "camiones_permitidos": ["paquetera", "rampla_directa", "backhaul"]},
            {"cds": ["6009 Lo Aguirre"], "ces": ["0088"], "camiones_permitidos": ["paquetera", "rampla_directa", "backhaul"]},
            {"cds": ["6009 Lo Aguirre"], "ces": ["0097"], "camiones_permitidos": ["paquetera", "rampla_directa", "backhaul"]},
            {"cds": ["6009 Lo Aguirre"], "ces": ["0103"], "camiones_permitidos": ["paquetera", "rampla_directa", "backhaul"]},
            {"cds": ["6009 Lo Aguirre"], "ces": ["3598"], "camiones_permitidos": ["paquetera", "rampla_directa", "backhaul"]},
            {"cds": ["6009 Lo Aguirre"], "ces": ["8150"], "camiones_permitidos": ["paquetera", "rampla_directa", "backhaul"]},
            
            # Peñón - permite backhaul
            {"cds": ["6020 Peñón"], "ces": ["0079"], "camiones_permitidos": ["paquetera", "rampla_directa", "backhaul"]},
            {"cds": ["6020 Peñón"], "ces": ["0080"], "camiones_permitidos": ["paquetera", "rampla_directa", "backhaul"]},
            {"cds": ["6020 Peñón"], "ces": ["0088"], "camiones_permitidos": ["paquetera", "rampla_directa", "backhaul"]},
            {"cds": ["6020 Peñón"], "ces": ["0097"], "camiones_permitidos": ["paquetera", "rampla_directa", "backhaul"]},
            {"cds": ["6020 Peñón"], "ces": ["0103"], "camiones_permitidos": ["paquetera", "rampla_directa", "backhaul"]},
            {"cds": ["6020 Peñón"], "ces": ["3598"], "camiones_permitidos": ["paquetera", "rampla_directa", "backhaul"]},
            {"cds": ["6020 Peñón"], "ces": ["8150"], "camiones_permitidos": ["paquetera", "rampla_directa", "backhaul"]},
            
            # Chillán - solo Nestlé
            {"cds": ["6010 Chillán"], "ces": ["0079"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["6010 Chillán"], "ces": ["0080"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["6010 Chillán"], "ces": ["0088"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["6010 Chillán"], "ces": ["0097"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["6010 Chillán"], "ces": ["0103"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["6010 Chillán"], "ces": ["3598"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["6010 Chillán"], "ces": ["8150"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            
            # Temuco - solo Nestlé
            {"cds": ["6024 Temuco"], "ces": ["0079"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["6024 Temuco"], "ces": ["0080"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["6024 Temuco"], "ces": ["0088"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["6024 Temuco"], "ces": ["0097"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["6024 Temuco"], "ces": ["0103"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["6024 Temuco"], "ces": ["3598"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["6024 Temuco"], "ces": ["8150"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            
            # Antofagasta - solo Nestlé
            {"cds": ["6003 Antofagasta"], "ces": ["0079"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["6003 Antofagasta"], "ces": ["0080"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["6003 Antofagasta"], "ces": ["0088"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["6003 Antofagasta"], "ces": ["0097"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["6003 Antofagasta"], "ces": ["0103"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["6003 Antofagasta"], "ces": ["3598"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["6003 Antofagasta"], "ces": ["8150"], "camiones_permitidos": ["paquetera", "rampla_directa"]},

        ],

        "multi_ce": [
            # Lo Aguirre
            {"cds": ["6009 Lo Aguirre"], "ces": ["0088", "0097"], "camiones_permitidos": ["paquetera", "rampla_directa", "backhaul"]},
            {"cds": ["6009 Lo Aguirre"], "ces": ["0088", "3598"], "camiones_permitidos": ["paquetera", "rampla_directa", "backhaul"]},
            
            # Peñón
            {"cds": ["6020 Peñón"], "ces": ["0088", "0097"], "camiones_permitidos": ["paquetera", "rampla_directa", "backhaul"]},
            {"cds": ["6020 Peñón"], "ces": ["0088", "3598"], "camiones_permitidos": ["paquetera", "rampla_directa", "backhaul"]},
            
            # Antofagasta - solo Nestlé
            {"cds": ["6003 Antofagasta"], "ces": ["0088", "0097"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["6003 Antofagasta"], "ces": ["0088", "3598"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["6003 Antofagasta"], "ces": ["0088", "0103"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["6003 Antofagasta"], "ces": ["0088", "8151"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["6003 Antofagasta"], "ces": ["0103", "8151"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["6003 Antofagasta"], "ces": ["0079", "8151"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            
            # Chillán - solo Nestlé
            {"cds": ["6010 Chillán"], "ces": ["0088", "0097"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["6010 Chillán"], "ces": ["0088", "3598"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["6010 Chillán"], "ces": ["0088", "0103"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["6010 Chillán"], "ces": ["0088", "8151"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["6010 Chillán"], "ces": ["0103", "8151"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["6010 Chillán"], "ces": ["0088", "0079"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["6010 Chillán"], "ces": ["0103", "0079"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            
            # Temuco - solo Nestlé
            {"cds": ["6024 Temuco"], "ces": ["0088", "0097"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["6024 Temuco"], "ces": ["0088", "3598"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["6024 Temuco"], "ces": ["0088", "0103"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["6024 Temuco"], "ces": ["0088", "8151"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["6024 Temuco"], "ces": ["0103", "8151"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["6024 Temuco"], "ces": ["0088", "0079"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["6024 Temuco"], "ces": ["0103", "0079"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
        ],

        "multi_cd": [
            # Solo Nestlé
            {"cds": ["6010 Chillán","6024 Temuco"], "ces": ["0088"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["6010 Chillán","6024 Temuco"], "ces": ["0103"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
        ],
    }
