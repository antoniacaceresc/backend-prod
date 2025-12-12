
class SmuConfig:
    HEADER_ROW = 0

    # ========== CONSTANTES DE SUBCLIENTE ==========
    CDS_ALVI = ["Alvi Aeroparque 2", "Alvi Canastas"]
    CDS_RENDIC = ["Bodega Coquimbo 2", "Bodega Puerto Montt", "Bodega Concepción", "Bodega Lo Aguirre", "Bodega Noviciado", "Bodega Antofagasta 2"]

    # ========== RESTRICCIONES COMUNES SMU ==========
    ALTURA_MAX_PICKING_APILADO_CM = 180  # Máximo 1.8m de picking apilado

    # ========== RESTRICCIONES ALVI ==========
    ALVI_ALTURA_MAX_CM = 230
    ALVI_ELIMINAR_SKU_DUPLICADO = True  # Si hay SKU duplicado entre OCs, eliminar menor cantidad
    ALVI_FLUJOS_SEPARADOS = True  # INV y Flujo Continuo en camiones separados
    ALVI_FLUJO_CONTINUO_CAMIONES = ["mediano", "pequeño"]
    ALVI_FLUJO_CONTINUO_MAX_SKUS_PALLET = 5  # Solo flujo continuo puede consolidar
    

    # Configuraciones algoritmo
    USA_OC = True
    MIX_GRUPOS = []

    AGRUPAR_POR_PO = False
    ADHERENCIA_BACKHAUL = None
    MODO_ADHERENCIA = None
    
    # Configuración de validación altura
    VALIDAR_ALTURA = True
    PERMITE_CONSOLIDACION = True
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
            "ALTURA_FULL_PALLET": "Altura full Pallet",
            "APILABLE_BASE": "Apilable Base",
            "MONTADO": "Montado",  

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
        'paquetera':        {'cap_weight': 23000, 'cap_volume': 70000, 'max_positions': 30, 'levels': 2, 'vcu_min': 0.8, 'max_pallets': 60, 'altura_cm': 260},
        'rampla_directa':   {'cap_weight': 23000, 'cap_volume': 70000, 'max_positions': 28, 'levels': 2, 'vcu_min': 0.8, 'max_pallets': 56, 'altura_cm': 250},
        'backhaul':         {'cap_weight': 23000, 'cap_volume': 70000, 'max_positions': 28, 'levels': 2, 'vcu_min': 0.6, 'max_pallets': 56, 'altura_cm': 240},
        'mediano':          {'cap_weight': 10000, 'cap_volume': 18000, 'max_positions': 12, 'levels': 2, 'vcu_min': 0.6, 'max_pallets': 12, 'altura_cm': 230},
        'pequeño':          {'cap_weight':  5000, 'cap_volume': 13000, 'max_positions':  3, 'levels': 2, 'vcu_min': 0.6, 'max_pallets':  3, 'altura_cm': 230},

    }

    # Configuración agrupamiento especial
    RUTAS_POSIBLES = {
        
        "normal": [
            # Rendic - bodega coquimbo
            {"cds": ["Bodega Coquimbo 2"], "ces": ["0080"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["Bodega Coquimbo 2"], "ces": ["0088"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["Bodega Coquimbo 2"], "ces": ["0097"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["Bodega Coquimbo 2"], "ces": ["0103"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["Bodega Coquimbo 2"], "ces": ["3598"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["Bodega Coquimbo 2"], "ces": ["8150"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            
            # Rendic - bodega pto montt
            {"cds": ["Bodega Puerto Montt"], "ces": ["0080"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["Bodega Puerto Montt"], "ces": ["0088"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["Bodega Puerto Montt"], "ces": ["0097"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["Bodega Puerto Montt"], "ces": ["0103"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["Bodega Puerto Montt"], "ces": ["3598"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["Bodega Puerto Montt"], "ces": ["8150"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            
             # Rendic - bodega concepción
            {"cds": ["Bodega Concepción"], "ces": ["0080"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["Bodega Concepción"], "ces": ["0088"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["Bodega Concepción"], "ces": ["0097"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["Bodega Concepción"], "ces": ["0103"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["Bodega Concepción"], "ces": ["3598"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["Bodega Concepción"], "ces": ["8150"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            
            # Rendic - bodega lo aguirre
            {"cds": ["Bodega Lo Aguirre"], "ces": ["0080"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["Bodega Lo Aguirre"], "ces": ["0088"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["Bodega Lo Aguirre"], "ces": ["0097"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["Bodega Lo Aguirre"], "ces": ["0103"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["Bodega Lo Aguirre"], "ces": ["3598"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["Bodega Lo Aguirre"], "ces": ["8150"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            
            # Rendic - bodega noviciado
            {"cds": ["Bodega Noviciado"], "ces": ["0080"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["Bodega Noviciado"], "ces": ["0088"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["Bodega Noviciado"], "ces": ["0097"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["Bodega Noviciado"], "ces": ["0103"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["Bodega Noviciado"], "ces": ["3598"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["Bodega Noviciado"], "ces": ["8150"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            
            # Rendic - bodega antofagasta
            {"cds": ["Bodega Antofagasta 2"], "ces": ["0080"], "camiones_permitidos": ["paquetera", "rampla_directa", "backhaul"]},
            {"cds": ["Bodega Antofagasta 2"], "ces": ["0088"], "camiones_permitidos": ["paquetera", "rampla_directa", "backhaul"]},
            {"cds": ["Bodega Antofagasta 2"], "ces": ["0097"], "camiones_permitidos": ["paquetera", "rampla_directa", "backhaul"]},
            {"cds": ["Bodega Antofagasta 2"], "ces": ["0103"], "camiones_permitidos": ["paquetera", "rampla_directa", "backhaul"]},
            {"cds": ["Bodega Antofagasta 2"], "ces": ["3598"], "camiones_permitidos": ["paquetera", "rampla_directa", "backhaul"]},
            {"cds": ["Bodega Antofagasta 2"], "ces": ["8150"], "camiones_permitidos": ["paquetera", "rampla_directa", "backhaul"]},
            
            # Alvi - aeroparque INV
            {"cds": ["Alvi Aeroparque 2"], "ces": ["0080"], "ocs": ["INV"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["Alvi Aeroparque 2"], "ces": ["0088"], "ocs": ["INV"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["Alvi Aeroparque 2"], "ces": ["0097"], "ocs": ["INV"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["Alvi Aeroparque 2"], "ces": ["0103"], "ocs": ["INV"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["Alvi Aeroparque 2"], "ces": ["3598"], "ocs": ["INV"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["Alvi Aeroparque 2"], "ces": ["8150"], "ocs": ["INV"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            
            # Alvi - aeroparque CRR
            {"cds": ["Alvi Aeroparque 2"], "ces": ["0080"], "ocs": ["CRR"], "camiones_permitidos": ["paquetera", "rampla_directa", "mediano", "pequeño"]},
            {"cds": ["Alvi Aeroparque 2"], "ces": ["0088"], "ocs": ["CRR"], "camiones_permitidos": ["paquetera", "rampla_directa", "mediano", "pequeño"]},
            {"cds": ["Alvi Aeroparque 2"], "ces": ["0097"], "ocs": ["CRR"], "camiones_permitidos": ["paquetera", "rampla_directa", "mediano", "pequeño"]},
            {"cds": ["Alvi Aeroparque 2"], "ces": ["0103"], "ocs": ["CRR"], "camiones_permitidos": ["paquetera", "rampla_directa", "mediano", "pequeño"]},
            {"cds": ["Alvi Aeroparque 2"], "ces": ["3598"], "ocs": ["CRR"], "camiones_permitidos": ["paquetera", "rampla_directa", "mediano", "pequeño"]},
            {"cds": ["Alvi Aeroparque 2"], "ces": ["8150"], "ocs": ["CRR"], "camiones_permitidos": ["paquetera", "rampla_directa", "mediano", "pequeño"]},

            # Alvi - canastas INV
            {"cds": ["Alvi Canastas"], "ces": ["0080"], "ocs": ["INV"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["Alvi Canastas"], "ces": ["0088"], "ocs": ["INV"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["Alvi Canastas"], "ces": ["0097"], "ocs": ["INV"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["Alvi Canastas"], "ces": ["0103"], "ocs": ["INV"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["Alvi Canastas"], "ces": ["3598"], "ocs": ["INV"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["Alvi Canastas"], "ces": ["8150"], "ocs": ["INV"], "camiones_permitidos": ["paquetera", "rampla_directa"]},

            # Alvi - canastas CRR
            {"cds": ["Alvi Canastas"], "ces": ["0080"], "ocs": ["CRR"], "camiones_permitidos": ["paquetera", "rampla_directa", "mediano", "pequeño"]},
            {"cds": ["Alvi Canastas"], "ces": ["0088"], "ocs": ["CRR"], "camiones_permitidos": ["paquetera", "rampla_directa", "mediano", "pequeño"]},
            {"cds": ["Alvi Canastas"], "ces": ["0097"], "ocs": ["CRR"], "camiones_permitidos": ["paquetera", "rampla_directa", "mediano", "pequeño"]},
            {"cds": ["Alvi Canastas"], "ces": ["0103"], "ocs": ["CRR"], "camiones_permitidos": ["paquetera", "rampla_directa", "mediano", "pequeño"]},
            {"cds": ["Alvi Canastas"], "ces": ["3598"], "ocs": ["CRR"], "camiones_permitidos": ["paquetera", "rampla_directa", "mediano", "pequeño"]},
            {"cds": ["Alvi Canastas"], "ces": ["8150"], "ocs": ["CRR"], "camiones_permitidos": ["paquetera", "rampla_directa", "mediano", "pequeño"]},
            
        ],

        "multi_ce": [
            
        ],

        "multi_cd": [
            # Solo Nestlé
            {"cds": ["Bodega Coquimbo 2", "Bodega Antofagasta 2"], "ces": ["0088"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["Bodega Coquimbo 2", "Bodega Antofagasta 2"], "ces": ["0103"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            
            {"cds": ["Bodega Concepción", "Bodega Puerto Montt"], "ces": ["0088"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["Bodega Concepción", "Bodega Puerto Montt"], "ces": ["0103"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            
            {"cds": ["Bodega Lo Aguirre", "Bodega Noviciado"], "ces": ["0088"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            {"cds": ["Bodega Lo Aguirre", "Bodega Noviciado"], "ces": ["0103"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
            
        ],
    }


    @classmethod
    def es_alvi(cls, cd: str) -> bool:
        return cd in cls.CDS_ALVI
    
    @classmethod
    def get_max_skus_pallet(cls, cd: str, oc: str) -> int:
        if cls.es_alvi(cd) and oc and oc.upper() == "CRR":
            return cls.ALVI_CRR_MAX_SKUS_PALLET
        return cls.MAX_SKUS_POR_PALLET
