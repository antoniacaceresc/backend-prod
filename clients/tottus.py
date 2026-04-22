
class TottusConfig:
    HEADER_ROW = 0
    
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
            "SKU": "SKU",
            "ALTURA_PICKING": "Altura Picking",
            "ALTURA_FULL_PALLET": "Altura full Pallet",
            "APILABLE_BASE": "Apilable Base",
            "MONTADO": "Montado",  
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

    # Configuración por canal de venta
    CHANNEL_CONFIG = {
        "Secos": {
            "USA_OC": True,
            "AGRUPAR_POR_PO": False,
            "MIX_GRUPOS": [],
            
            "ADHERENCIA_BACKHAUL": None,
            "MODO_ADHERENCIA": None,
            
            "VALIDAR_ALTURA": True,
            "PERMITE_CONSOLIDACION": True,
            "MAX_SKUS_POR_PALLET": 10,

            "TRUCK_TYPES": {
                'paquetera':        {'cap_weight': 23000, 'cap_volume': 70000, 'max_positions': 30, 'levels': 2, 'vcu_min': 0.7, 'max_pallets': 60, 'altura_cm': 280},
                'rampla_directa':   {'cap_weight': 23000, 'cap_volume': 70000, 'max_positions': 28, 'levels': 2, 'vcu_min': 0.7, 'max_pallets': 56, 'altura_cm': 270},
                'mediano':          {'cap_weight': 10000, 'cap_volume': 18000, 'max_positions': 12, 'levels': 2, 'vcu_min': 0.5, 'max_pallets': 15, 'altura_cm': 230},
            },

            "RUTAS_POSIBLES": {
                "normal": [
                    # todo a la farfana
                    {"cds": ["La Farfana"], "ces": ["0088"], "camiones_permitidos": ["paquetera", "rampla_directa", "mediano"]},
                    {"cds": ["La Farfana"], "ces": ["0103"], "camiones_permitidos": ["paquetera", "rampla_directa", "mediano"]},
                    
                ],

                "multi_ce": [],
                
                "multi_cd": [],
            }
        },
    }

    @classmethod
    def get_channel_config(cls, venta: str) -> dict:
        """Retorna configuración específica del canal, con fallback a Secos."""
        return cls.CHANNEL_CONFIG.get(venta, cls.CHANNEL_CONFIG["Secos"])
