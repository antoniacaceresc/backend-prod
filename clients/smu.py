
class SmuConfig:
    HEADER_ROW = 0

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
            "SUBCLIENTE": "CUSTHIERLEVEL5NAME",

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


    # Configuración por canal de venta
    CHANNEL_CONFIG = {
        "Secos": {
            "USA_OC": True,
            "AGRUPAR_POR_PO": False,
            "MIX_GRUPOS": [],
            
            "ADHERENCIA_BACKHAUL": None,
            "MODO_ADHERENCIA": None,
            
            "VALIDAR_ALTURA": True,
            "PERMITE_CONSOLIDACION": False,
            "MAX_SKUS_POR_PALLET": 1,

            # Restricciones comunes Picking
            "PROHIBIR_PICKING_DUPLICADO": True,
            "ALTURA_MAX_PICKING_APILADO_CM": 180,  # Máximo 1.8m de picking apilado

            # Restricciones ALVI
            "ALVI_ALTURA_MAX_CM": 230,

            # Restricciones RENDIC
            "RENDIC_ALTURA_MAX_CM": 240,

            # CDs sin apilamiento permitido
            "CDS_SIN_APILAMIENTO": ["Bodega Noviciado"],

            # Configuración por subcliente/flujo
            "SUBCLIENTE_CONFIG": {
                "Alvi": {
                    "INV": {
                        "PERMITE_CONSOLIDACION": False,
                        "MAX_SKUS_POR_PALLET": 1,
                    },
                    "CRR": {
                        "PERMITE_CONSOLIDACION": True,
                        "MAX_SKUS_POR_PALLET": 5,
                        "PASADAS_CAMIONES": ["pequeño", "mediano"],  # Primero pequeños, luego medianos
                    },
                },
                "Rendic": {
                    "PERMITE_CONSOLIDACION": False,
                    "MAX_SKUS_POR_PALLET": 1,
                },
            },

            "TRUCK_TYPES": {
                'paquetera':        {'cap_weight': 23000, 'cap_volume': 70000, 'max_positions': 30, 'levels': 2, 'vcu_min': 0.2, 'max_pallets': 60, 'altura_cm': 280},
                'rampla_directa':   {'cap_weight': 23000, 'cap_volume': 70000, 'max_positions': 28, 'levels': 2, 'vcu_min': 0.8, 'max_pallets': 56, 'altura_cm': 270},
                'backhaul':         {'cap_weight': 23000, 'cap_volume': 70000, 'max_positions': 28, 'levels': 2, 'vcu_min': 0.6, 'max_pallets': 56, 'altura_cm': 240},
                'mediano':          {'cap_weight': 10000, 'cap_volume': 18000, 'max_positions': 12, 'levels': 2, 'vcu_min': 0.1, 'max_pallets': 12, 'altura_cm': 230},
                'pequeño':          {'cap_weight':  5000, 'cap_volume': 13000, 'max_positions':  3, 'levels': 2, 'vcu_min': 0.1, 'max_pallets':  3, 'altura_cm': 230},
            },

            "RUTAS_POSIBLES": {
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
                    {"cds": ["Alvi Aeroparque 2"], "ces": ["0080"], "ocs": ["CRR"], "camiones_permitidos": ["pequeño", "mediano", "rampla_directa", "paquetera"]},
                    {"cds": ["Alvi Aeroparque 2"], "ces": ["0088"], "ocs": ["CRR"], "camiones_permitidos": ["pequeño", "mediano", "rampla_directa", "paquetera"]},
                    {"cds": ["Alvi Aeroparque 2"], "ces": ["0097"], "ocs": ["CRR"], "camiones_permitidos": ["pequeño", "mediano", "rampla_directa", "paquetera"]},
                    {"cds": ["Alvi Aeroparque 2"], "ces": ["0103"], "ocs": ["CRR"], "camiones_permitidos": ["pequeño", "mediano", "rampla_directa", "paquetera"]},
                    {"cds": ["Alvi Aeroparque 2"], "ces": ["3598"], "ocs": ["CRR"], "camiones_permitidos": ["pequeño", "mediano", "rampla_directa", "paquetera"]},
                    {"cds": ["Alvi Aeroparque 2"], "ces": ["8150"], "ocs": ["CRR"], "camiones_permitidos": ["pequeño", "mediano", "rampla_directa", "paquetera"]},

                    # Alvi - canastas INV
                    {"cds": ["Alvi Canastas"], "ces": ["0080"], "ocs": ["INV"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
                    {"cds": ["Alvi Canastas"], "ces": ["0088"], "ocs": ["INV"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
                    {"cds": ["Alvi Canastas"], "ces": ["0097"], "ocs": ["INV"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
                    {"cds": ["Alvi Canastas"], "ces": ["0103"], "ocs": ["INV"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
                    {"cds": ["Alvi Canastas"], "ces": ["3598"], "ocs": ["INV"], "camiones_permitidos": ["paquetera", "rampla_directa"]},
                    {"cds": ["Alvi Canastas"], "ces": ["8150"], "ocs": ["INV"], "camiones_permitidos": ["paquetera", "rampla_directa"]},

                    # Alvi - canastas CRR
                    {"cds": ["Alvi Canastas"], "ces": ["0080"], "ocs": ["CRR"], "camiones_permitidos": ["pequeño", "mediano", "rampla_directa", "paquetera"]},
                    {"cds": ["Alvi Canastas"], "ces": ["0088"], "ocs": ["CRR"], "camiones_permitidos": ["pequeño", "mediano", "rampla_directa", "paquetera"]},
                    {"cds": ["Alvi Canastas"], "ces": ["0097"], "ocs": ["CRR"], "camiones_permitidos": ["pequeño", "mediano", "rampla_directa", "paquetera"]},
                    {"cds": ["Alvi Canastas"], "ces": ["0103"], "ocs": ["CRR"], "camiones_permitidos": ["pequeño", "mediano", "rampla_directa", "paquetera"]},
                    {"cds": ["Alvi Canastas"], "ces": ["3598"], "ocs": ["CRR"], "camiones_permitidos": ["pequeño", "mediano", "rampla_directa", "paquetera"]},
                    {"cds": ["Alvi Canastas"], "ces": ["8150"], "ocs": ["CRR"], "camiones_permitidos": ["pequeño", "mediano", "rampla_directa", "paquetera"]},
                ],

                "multi_ce": [],

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
        },
    }

    @classmethod
    def get_channel_config(cls, venta: str) -> dict:
        """Retorna configuración específica del canal, con fallback a Secos."""
        return cls.CHANNEL_CONFIG.get(venta, cls.CHANNEL_CONFIG["Secos"])

    
    @classmethod
    def get_max_skus_pallet(cls, cd: str, oc: str) -> int:
        if cls.es_alvi(cd) and oc and oc.upper() == "CRR":
            return cls.ALVI_CRR_MAX_SKUS_PALLET
        return cls.MAX_SKUS_POR_PALLET

    @classmethod
    def es_alvi(cls, subcliente: str) -> bool:
        """Verifica si el subcliente es Alvi"""
        return subcliente == "Alvi"

    @classmethod
    def es_rendic(cls, cd: str) -> bool:
        """Verifica si el CD es de Rendic"""
        return cd.startswith("Bodega")

    @classmethod
    def permite_apilamiento(cls, cd: str, venta: str = None) -> bool:
        """Verifica si el CD permite apilamiento"""
        channel = cls.get_channel_config(venta) if venta else cls.CHANNEL_CONFIG.get("Secos", {})
        cds_sin_apilamiento = channel.get("CDS_SIN_APILAMIENTO", [])
        return cd not in cds_sin_apilamiento
    
    @classmethod
    def get_altura_maxima(cls, subcliente: str, altura_default: float, venta: str = "Secos") -> float:
        """Retorna altura máxima según subcliente (Alvi=230cm, Rendic=240cm)"""
        channel = cls.get_channel_config(venta)
        if cls.es_alvi(subcliente):
            return channel.get("ALVI_ALTURA_MAX_CM", 230)
        # Rendic u otros subclientes SMU
        return channel.get("RENDIC_ALTURA_MAX_CM", 240)

    @classmethod
    def get_config_por_subcliente(cls, subcliente: str, oc: str = None, venta: str = "Secos") -> dict:
        """
        Retorna configuración específica por subcliente y flujo.
        
        Args:
            subcliente: "Alvi" o "Rendic"
            oc: "INV" o "CRR" (solo aplica a Alvi)
            venta: Canal de venta
        
        Returns:
            Dict con PERMITE_CONSOLIDACION, MAX_SKUS_POR_PALLET
        """
        channel = cls.get_channel_config(venta)
        subcliente_configs = channel.get("SUBCLIENTE_CONFIG", {})
        
        # Valores por defecto
        config = {
            "PERMITE_CONSOLIDACION": False,
            "MAX_SKUS_POR_PALLET": 1,
        }
        
        if subcliente in subcliente_configs:
            sub_config = subcliente_configs[subcliente]
            
            # Si es Alvi y tiene flujo específico
            if subcliente == "Alvi" and oc and oc.upper() in sub_config:
                flujo_config = sub_config[oc.upper()]
                config["PERMITE_CONSOLIDACION"] = flujo_config.get("PERMITE_CONSOLIDACION", False)
                config["MAX_SKUS_POR_PALLET"] = flujo_config.get("MAX_SKUS_POR_PALLET", 1)
            else:
                # Config general del subcliente
                config["PERMITE_CONSOLIDACION"] = sub_config.get("PERMITE_CONSOLIDACION", False)
                config["MAX_SKUS_POR_PALLET"] = sub_config.get("MAX_SKUS_POR_PALLET", 1)
        
        return config

    @classmethod
    def get_pasadas_camiones(cls, subcliente: str, oc: str = None, venta: str = "Secos") -> list:
        """
        Retorna lista de tipos de camión para pasadas secuenciales.
        Solo aplica a Alvi CRR por ahora.
        
        Returns:
            Lista de tipos ["pequeño", "mediano"] o None si no hay pasadas especiales
        """
        channel = cls.get_channel_config(venta)
        subcliente_configs = channel.get("SUBCLIENTE_CONFIG", {})
        
        if subcliente == "Alvi" and oc and oc.upper() == "CRR":
            alvi_config = subcliente_configs.get("Alvi", {})
            crr_config = alvi_config.get("CRR", {})
            return crr_config.get("PASADAS_CAMIONES", None)
        
        return None