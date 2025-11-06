"""
Tests unitarios para modelos de apilamiento.
"""

import pytest
from models.stacking import (
    CategoriaApilamiento,
    FragmentoSKU,
    PalletFisico,
    PosicionCamion,
    LayoutCamion
)


class TestFragmentoSKU:
    """Tests para FragmentoSKU"""
    
    def test_crear_fragmento_valido(self):
        """Crear fragmento con datos válidos"""
        frag = FragmentoSKU(
            sku_id="SKU001",
            pedido_id="PED001",
            fraccion=1.0,
            altura_cm=150.0,
            peso_kg=500.0,
            volumen_m3=1.5,
            categoria=CategoriaApilamiento.BASE
        )
        
        assert frag.sku_id == "SKU001"
        assert frag.altura_cm == 150.0
        assert frag.categoria == CategoriaApilamiento.BASE
    
    def test_fraccion_invalida(self):
        """Fracción debe estar entre 0 y 1"""
        with pytest.raises(ValueError, match="Fracción debe estar entre 0 y 1"):
            FragmentoSKU(
                sku_id="SKU001",
                pedido_id="PED001",
                fraccion=1.5,  # Inválido
                altura_cm=150.0,
                peso_kg=500.0,
                volumen_m3=1.5,
                categoria=CategoriaApilamiento.BASE
            )
    
    def test_altura_invalida(self):
        """Altura debe ser positiva"""
        with pytest.raises(ValueError, match="Altura debe ser positiva"):
            FragmentoSKU(
                sku_id="SKU001",
                pedido_id="PED001",
                fraccion=1.0,
                altura_cm=-10.0,  # Inválido
                peso_kg=500.0,
                volumen_m3=1.5,
                categoria=CategoriaApilamiento.BASE
            )


class TestPosicionCamion:
    """Tests para PosicionCamion y reglas de apilamiento"""
    
    def test_posicion_vacia(self):
        """Posición vacía acepta cualquier pallet"""
        pos = PosicionCamion(id=0, altura_maxima_cm=270)
        
        pallet = self._crear_pallet_base(altura=150)
        
        puede, razon = pos.puede_apilar(pallet)
        assert puede is True
        assert razon is None
    
    def test_base_superior_valido(self):
        """BASE + SUPERIOR es válido"""
        pos = PosicionCamion(id=0, altura_maxima_cm=270)
        
        pallet_base = self._crear_pallet_base(altura=150)
        pos.apilar(pallet_base)
        
        pallet_superior = self._crear_pallet_superior(altura=100)
        puede, razon = pos.puede_apilar(pallet_superior)
        
        assert puede is True
    
    def test_base_base_invalido(self):
        """BASE + BASE no es válido"""
        pos = PosicionCamion(id=0, altura_maxima_cm=270)
        
        pallet_base_1 = self._crear_pallet_base(altura=150)
        pos.apilar(pallet_base_1)
        
        pallet_base_2 = self._crear_pallet_base(altura=100)
        puede, razon = pos.puede_apilar(pallet_base_2)
        
        assert puede is False
        assert "BASE no acepta base encima" in razon
    
    def test_no_apilable_rechaza_todo(self):
        """NO_APILABLE no acepta nada encima"""
        pos = PosicionCamion(id=0, altura_maxima_cm=270)
        
        pallet_no_apil = self._crear_pallet_no_apilable(altura=200)
        pos.apilar(pallet_no_apil)
        
        pallet_superior = self._crear_pallet_superior(altura=50)
        puede, razon = pos.puede_apilar(pallet_superior)
        
        assert puede is False
        assert "NO_APILABLE" in razon
    
    def test_si_mismo_mismo_sku_valido(self):
        """SI_MISMO + mismo SKU es válido"""
        pos = PosicionCamion(id=0, altura_maxima_cm=270)
        
        pallet_1 = self._crear_pallet_si_mismo(sku="SKU001", altura=100)
        pos.apilar(pallet_1)
        
        pallet_2 = self._crear_pallet_si_mismo(sku="SKU001", altura=100)
        puede, razon = pos.puede_apilar(pallet_2)
        
        assert puede is True
    
    def test_si_mismo_diferente_sku_invalido(self):
        """SI_MISMO + diferente SKU no es válido"""
        pos = PosicionCamion(id=0, altura_maxima_cm=270)
        
        pallet_1 = self._crear_pallet_si_mismo(sku="SKU001", altura=100)
        pos.apilar(pallet_1)
        
        pallet_2 = self._crear_pallet_si_mismo(sku="SKU002", altura=100)
        puede, razon = pos.puede_apilar(pallet_2)
        
        assert puede is False
        assert "mismo SKU" in razon
    
    def test_excede_altura_maxima(self):
        """No puede apilar si excede altura máxima"""
        pos = PosicionCamion(id=0, altura_maxima_cm=270)
        
        pallet_1 = self._crear_pallet_base(altura=200)
        pos.apilar(pallet_1)
        
        pallet_2 = self._crear_pallet_superior(altura=100)  # 200 + 100 = 300 > 270
        puede, razon = pos.puede_apilar(pallet_2)
        
        assert puede is False
        assert "Excede altura" in razon
    
    # Helpers
    def _crear_pallet_base(self, altura: float) -> PalletFisico:
        pallet = PalletFisico(id="test", posicion_id=0, nivel=0)
        frag = FragmentoSKU(
            sku_id="TEST",
            pedido_id="PED",
            fraccion=1.0,
            altura_cm=altura,
            peso_kg=500,
            volumen_m3=1.0,
            categoria=CategoriaApilamiento.BASE
        )
        pallet.agregar_fragmento(frag)
        return pallet
    
    def _crear_pallet_superior(self, altura: float) -> PalletFisico:
        pallet = PalletFisico(id="test", posicion_id=0, nivel=0)
        frag = FragmentoSKU(
            sku_id="TEST",
            pedido_id="PED",
            fraccion=1.0,
            altura_cm=altura,
            peso_kg=500,
            volumen_m3=1.0,
            categoria=CategoriaApilamiento.SUPERIOR
        )
        pallet.agregar_fragmento(frag)
        return pallet
    
    def _crear_pallet_no_apilable(self, altura: float) -> PalletFisico:
        pallet = PalletFisico(id="test", posicion_id=0, nivel=0)
        frag = FragmentoSKU(
            sku_id="TEST",
            pedido_id="PED",
            fraccion=1.0,
            altura_cm=altura,
            peso_kg=500,
            volumen_m3=1.0,
            categoria=CategoriaApilamiento.NO_APILABLE
        )
        pallet.agregar_fragmento(frag)
        return pallet
    
    def _crear_pallet_si_mismo(self, sku: str, altura: float) -> PalletFisico:
        pallet = PalletFisico(id="test", posicion_id=0, nivel=0)
        frag = FragmentoSKU(
            sku_id=sku,
            pedido_id="PED",
            fraccion=1.0,
            altura_cm=altura,
            peso_kg=500,
            volumen_m3=1.0,
            categoria=CategoriaApilamiento.SI_MISMO
        )
        pallet.agregar_fragmento(frag)
        return pallet