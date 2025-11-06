"""
Tests para lectura y procesamiento de archivos Excel.
"""

import pytest
import pandas as pd
from services.file_processor import (
    detectar_modo_excel,
    _limpiar_datos_skus,
    _validar_datos_skus,
    _agregar_skus_a_pedidos,
)


class TestDeteccionModo:
    """Tests para detección de modo SKU vs Legacy"""
    
    def test_detectar_modo_sku(self):
        """Detectar Excel con columnas de SKU"""
        df = pd.DataFrame({
            "SKU": ["SKU001"],
            "Altura full pallet": [150],
            "N° Pedido": ["PED001"]
        })
        
        modo = detectar_modo_excel(df)
        assert modo == "SKU_DETALLADO"
    
    def test_detectar_modo_legacy(self):
        """Detectar Excel sin columnas de SKU"""
        df = pd.DataFrame({
            "N° Pedido": ["PED001"],
            "Pal. Conf.": [10]
        })
        
        modo = detectar_modo_excel(df)
        assert modo == "PEDIDO_LEGACY"


class TestAgregacionSKUs:
    """Tests para agregación de SKUs a pedidos"""
    
    def test_agregar_skus_suma_dimensiones(self):
        """Dimensiones físicas se suman correctamente"""
        df_skus = pd.DataFrame({
            "PEDIDO": ["PED001", "PED001", "PED002"],
            "SKU": ["SKU_A", "SKU_B", "SKU_C"],
            "CD": ["CD1", "CD1", "CD2"],
            "CE": ["0088", "0088", "0103"],
            "PO": ["PO001", "PO001", "PO002"],
            "PALLETS": [5.0, 3.0, 10.0],
            "PESO": [1000.0, 600.0, 2000.0],
            "VOL": [5.0, 3.0, 10.0],
            "VALOR": [50000, 30000, 100000],
            "ALTURA_FULL_PALLET": [150, 120, 180],
            "BASE": [5.0, 0.0, 10.0],
            "SUPERIOR": [0.0, 3.0, 0.0],
            "FLEXIBLE": [0.0, 0.0, 0.0],
            "NO_APILABLE": [0.0, 0.0, 0.0],
            "SI_MISMO": [0.0, 0.0, 0.0],
            "CHOCOLATES_FLAG": [0, 1, 0],
            "PDQ": [0, 0, 1],
        })
        
        from clients.walmart import WalmartConfig
        df_pedidos, _ = _agregar_skus_a_pedidos(df_skus, WalmartConfig)
        
        # Verificar PED001 (2 SKUs)
        ped001 = df_pedidos[df_pedidos["PEDIDO"] == "PED001"].iloc[0]
        assert ped001["PALLETS"] == 8.0  # 5 + 3
        assert ped001["PESO"] == 1600.0  # 1000 + 600
        assert ped001["BASE"] == 5.0
        assert ped001["SUPERIOR"] == 3.0
        assert ped001["CHOCOLATES"] == "SI"  # MAX(0, 1) = 1 -> SI
        
        # Verificar PED002 (1 SKU)
        ped002 = df_pedidos[df_pedidos["PEDIDO"] == "PED002"].iloc[0]
        assert ped002["PALLETS"] == 10.0
        assert ped002["PDQ"] == 1
    
    def test_agregar_skus_flags_max(self):
        """Flags booleanas usan MAX (si alguno es 1, resultado es 1)"""
        df_skus = pd.DataFrame({
            "PEDIDO": ["PED001", "PED001"],
            "SKU": ["SKU_A", "SKU_B"],
            "CD": ["CD1", "CD1"],
            "CE": ["0088", "0088"],
            "PO": ["PO001", "PO001"],
            "PALLETS": [5.0, 3.0],
            "PESO": [1000.0, 600.0],
            "VOL": [5.0, 3.0],
            "VALOR": [50000, 30000],
            "ALTURA_FULL_PALLET": [150, 120],
            "BASE": [5.0, 3.0],
            "SUPERIOR": [0.0, 0.0],
            "FLEXIBLE": [0.0, 0.0],
            "NO_APILABLE": [0.0, 0.0],
            "SI_MISMO": [0.0, 0.0],
            "CHOCOLATES_FLAG": [0, 0],
            "PDQ": [0, 1],  # Solo el segundo tiene PDQ
            "VALIOSO": [1, 0],  # Solo el primero es valioso
        })
        
        from clients.walmart import WalmartConfig
        df_pedidos, _ = _agregar_skus_a_pedidos(df_skus, WalmartConfig)
        
        ped = df_pedidos.iloc[0]
        assert ped["PDQ"] == 1  # MAX(0, 1) = 1
        assert ped["VALIOSO"] == 1  # MAX(1, 0) = 1


class TestValidacionDatos:
    """Tests para validación de datos de SKU"""
    
    def test_validar_skus_sin_altura(self):
        """Debe fallar si SKUs no tienen altura"""
        df_skus = pd.DataFrame({
            "SKU": ["SKU001"],
            "PEDIDO": ["PED001"],
            "PALLETS": [5.0],
            "ALTURA_FULL_PALLET": [0.0],  # Inválido
            "BASE": [5.0],
            "SUPERIOR": [0.0],
            "FLEXIBLE": [0.0],
            "NO_APILABLE": [0.0],
            "SI_MISMO": [0.0],
        })
        
        with pytest.raises(ValueError, match="SKUs sin altura válida"):
            _validar_datos_skus(df_skus)
    
    def test_validar_skus_sin_categoria(self):
        """Debe fallar si SKUs no tienen categoría de apilabilidad"""
        df_skus = pd.DataFrame({
            "SKU": ["SKU001"],
            "PEDIDO": ["PED001"],
            "PALLETS": [5.0],
            "ALTURA_FULL_PALLET": [150.0],
            "BASE": [0.0],
            "SUPERIOR": [0.0],
            "FLEXIBLE": [0.0],
            "NO_APILABLE": [0.0],
            "SI_MISMO": [0.0],  # Todas en 0 = inválido
        })
        
        with pytest.raises(ValueError, match="sin categoría de apilabilidad"):
            _validar_datos_skus(df_skus)