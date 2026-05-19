class IMSConfig:
    HEADER_ROW = 0
    
    # Mapeo de columnas
    COLUMN_MAPPING = {
        "Secos": {   
            "CD": "CD",
            #"PO": "Número PO",
            #"PEDIDO": "N° Pedido",
            #"OC": "Flujo OC", 
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
            "SKU": "SKU",
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
    
    
    # Configuración por canal de venta
    CHANNEL_CONFIG = {
        "Secos": {
            "USA_OC": False,
            "AGRUPAR_POR_PO": False,
            "MIX_GRUPOS": [],
            "VALIDAR_ALTURA": True,
            "PERMITE_CONSOLIDACION": True,
            "MAX_SKUS_POR_PALLET": 2,
            "TRUCK_TYPES": {
                'HC40':        {'cap_weight': 32500, 'cap_volume': 76200, 'max_positions': 30, 'levels': 2, 'vcu_min': 0.85, 'max_pallets': 42,'altura_cm': 280},
            },

            "RUTAS_POSIBLES":  {
                
                "normal": [
                    # Lo Aguirre - permite backhaul
                    {"cds": ["6009 Lo Aguirre"], "ces": ["0079"], "camiones_permitidos": ["paquetera", "rampla_directa", "backhaul"]},
                    {"cds": ["6009 Lo Aguirre"], "ces": ["0080"], "camiones_permitidos": ["paquetera", "rampla_directa", "backhaul"]},
                    {"cds": ["6009 Lo Aguirre"], "ces": ["0088"], "camiones_permitidos": ["paquetera", "rampla_directa", "backhaul"]},
                    {"cds": ["6009 Lo Aguirre"], "ces": ["0097"], "camiones_permitidos": ["paquetera", "rampla_directa", "backhaul"]},
                    {"cds": ["6009 Lo Aguirre"], "ces": ["0103"], "camiones_permitidos": ["paquetera", "rampla_directa", "backhaul"]},
                    {"cds": ["6009 Lo Aguirre"], "ces": ["3598"], "camiones_permitidos": ["paquetera", "rampla_directa", "backhaul"]},
                    {"cds": ["6009 Lo Aguirre"], "ces": ["8150"], "camiones_permitidos": ["paquetera", "rampla_directa", "backhaul"]},

                ],

            }
                },

    }


    @classmethod
    def get_channel_config(cls, venta: str) -> dict:
        """Retorna configuración específica del canal, con fallback a Secos."""
        return cls.CHANNEL_CONFIG.get(venta, cls.CHANNEL_CONFIG["Secos"])