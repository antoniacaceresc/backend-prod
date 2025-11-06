from __future__ import annotations
from dataclasses import dataclass, field
from .enums import TipoRuta, TipoCamion
from typing import List, Dict, Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from models.stacking import FragmentoSKU

@dataclass
class TruckCapacity:
    """
    Capacidades y límites de un tipo de camión.
    Inmutable durante la optimización.
    """
    cap_weight: float
    cap_volume: float
    max_positions: int
    max_pallets: int
    levels: int = 2
    vcu_min: float = 0.85
    altura_cm: float = 270
    
    @classmethod
    def from_config(cls, config_dict: Dict[str, Any]) -> TruckCapacity:
        """Constructor desde diccionario de configuración del cliente"""
        return cls(
            cap_weight=float(config_dict.get('cap_weight', 23000)),
            cap_volume=float(config_dict.get('cap_volume', 70000)),
            max_positions=int(config_dict.get('max_positions', 30)),
            max_pallets=int(config_dict.get('max_pallets', 60)),
            levels=int(config_dict.get('levels', 2)),
            vcu_min=float(config_dict.get('vcu_min', 0.85)),
            altura_cm=float(config_dict.get('altura_cm', 270))
        )
    
    def calcular_vcu(self, peso: float, volumen: float) -> tuple[float, float, float]:
        """Calcula VCU de peso, volumen y máximo para valores dados"""
        vcu_peso = peso / self.cap_weight if self.cap_weight > 0 else 0.0
        vcu_vol = volumen / self.cap_volume if self.cap_volume > 0 else 0.0
        vcu_max = max(vcu_peso, vcu_vol)
        return vcu_peso, vcu_vol, vcu_max


@dataclass
class SKU:
    """
    Representa un SKU individual dentro de un pedido.
    Mapea a una fila del Excel con datos de SKU.
    """
    # Identificadores
    sku_id: str
    pedido_id: str  # Referencia al pedido padre
    
    # Dimensiones físicas
    cantidad_pallets: float  # Columna: "Pal. Conf." (a nivel SKU)
    altura_full_pallet_cm: float  # Columna: "Altura full pallet"
    altura_picking_cm: Optional[float] = None  # Columna: "Altura picking"
    peso_kg: float = 0.0  # Columna: "Peso neto Conf." (a nivel SKU)
    volumen_m3: float = 0.0  # Columna: "Vol. Conf." (a nivel SKU)
    valor: float = 0.0  # Columna: "$$ Conf." (a nivel SKU)
    
    # Apilabilidad (en pallets, no booleano)
    # Estas columnas indican CUÁNTOS pallets de este SKU tienen esta característica
    base: float = 0.0              # Columna: "Base"
    superior: float = 0.0          # Columna: "Superior"
    flexible: float = 0.0          # Columna: "Flexible"
    no_apilable: float = 0.0       # Columna: "No Apilable"
    si_mismo: float = 0.0          # Columna: "Apilable por si mismo"
    
    # Límites de apilamiento (si aplica)
    max_altura_apilable_cm: Optional[float] = None  # Calculado o configurado
    
    # Metadata
    descripcion: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def altura_efectiva_cm(self) -> float:
        """
        Altura efectiva a usar: picking si existe, sino full pallet.
        """
        if self.altura_picking_cm is not None and self.altura_picking_cm > 0:
            return self.altura_picking_cm
        return self.altura_full_pallet_cm
    
    @property
    def es_picking(self) -> bool:
        """Indica si este SKU usa altura de picking"""
        return (
            self.altura_picking_cm is not None and 
            self.altura_picking_cm > 0 and
            self.altura_picking_cm < self.altura_full_pallet_cm
        )
    
    @property
    def categoria_apilamiento_dominante(self) -> str:
        """
        Determina la categoría de apilamiento dominante del SKU.
        Prioridad: NO_APILABLE > BASE > SUPERIOR > SI_MISMO > FLEXIBLE
        
        Returns:
            Nombre de la categoría ("no_apilable", "base", etc.)
        """
        if self.no_apilable > 0:
            return "no_apilable"
        if self.base > 0:
            return "base"
        if self.superior > 0:
            return "superior"
        if self.si_mismo > 0:
            return "si_mismo"
        if self.flexible > 0:
            return "flexible"
        
        # Default: flexible
        return "flexible"
    
    def to_fragmento(self, fraccion: float = 1.0) -> FragmentoSKU:
        """
        Convierte el SKU a un FragmentoSKU para validación.
        
        Args:
            fraccion: Porción del SKU que representa (default 1.0 = completo)
        
        Returns:
            FragmentoSKU con los datos del SKU
        """
        from models.stacking import FragmentoSKU, CategoriaApilamiento
        
        categoria = CategoriaApilamiento(self.categoria_apilamiento_dominante)
        
        return FragmentoSKU(
            sku_id=self.sku_id,
            pedido_id=self.pedido_id,
            fraccion=fraccion,
            altura_cm=self.altura_efectiva_cm * fraccion,
            peso_kg=self.peso_kg * fraccion,
            volumen_m3=self.volumen_m3 * fraccion,
            categoria=categoria,
            max_altura_apilable_cm=self.max_altura_apilable_cm,
            descripcion=self.descripcion,
            es_picking=self.es_picking
        )
    
    def validar_integridad(self) -> tuple[bool, Optional[str]]:
        """
        Valida que el SKU sea coherente.
        
        REGLA: Al menos UNA altura debe ser > 0 (full pallet O picking)
        """
        if self.cantidad_pallets <= 0:
            return False, f"SKU {self.sku_id}: cantidad_pallets debe ser > 0"
        
        # ✅ VALIDAR: Al menos una altura debe existir
        tiene_full = self.altura_full_pallet_cm > 0
        tiene_picking = self.altura_picking_cm is not None and self.altura_picking_cm > 0
        
        if not tiene_full and not tiene_picking:
            return False, (
                f"SKU {self.sku_id}: debe tener al menos una altura válida "
                f"(full pallet o picking)"
            )
        
        # Validar que alturas no sean negativas
        if self.altura_full_pallet_cm < 0:
            return False, f"SKU {self.sku_id}: altura_full_pallet no puede ser negativa"
        
        if self.altura_picking_cm is not None and self.altura_picking_cm < 0:
            return False, f"SKU {self.sku_id}: altura_picking no puede ser negativa"
        
        # Validar categorías de apilabilidad
        suma_categorias = (
            self.base + self.superior + self.flexible + 
            self.no_apilable + self.si_mismo
        )
        
        if suma_categorias <= 0:
            return False, (
                f"SKU {self.sku_id}: debe tener al menos una categoría de apilabilidad > 0"
            )
        
        # Tolerancia para decimales
        if suma_categorias > self.cantidad_pallets + 0.1:
            return False, (
                f"SKU {self.sku_id}: suma de categorías ({suma_categorias:.2f}) "
                f"excede cantidad de pallets ({self.cantidad_pallets:.2f})"
            )
        
        return True, None


@dataclass
class Pedido:
    """
    Representación única de un pedido.
    Contiene TODA la información necesaria en un solo lugar.
    """
    # ========== Identificadores (obligatorios) ==========
    pedido: str
    cd: str
    ce: str
    po: str
    
    # ========== Dimensiones físicas (obligatorias) ==========
    peso: float
    volumen: float
    pallets: float
    valor: float
    
    # ========== Dimensiones opcionales ==========
    pallets_real: Optional[float] = None  # Solo para Cencosud
    valor_cafe: float = 0.0
    
    # ========== Clasificación ==========
    oc: Optional[str] = None
    chocolates: str = "NO"
    
    # ========== Flags booleanos ==========
    valioso: bool = False
    pdq: bool = False
    baja_vu: bool = False
    lote_dir: bool = False
    
    # ========== Apilabilidad ==========
    base: float = 0.0
    superior: float = 0.0
    flexible: float = 0.0
    no_apilable: float = 0.0
    si_mismo: float = 0.0
    
    # ========== Asignación (None si no está asignado) ==========
    camion_id: Optional[str] = None
    numero_camion: Optional[int] = None
    grupo: Optional[str] = None
    tipo_ruta: Optional[str] = None
    tipo_camion: Optional[str] = None
    
    # ========== Metadata extra ==========
    skus: List[SKU] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def tiene_skus(self) -> bool:
        """Indica si el pedido tiene datos de SKU detallados"""
        return len(self.skus) > 0
    
    @property
    def pallets_calculado_desde_skus(self) -> float:
        """
        Pallets calculados desde SKUs.
        Solo usar si tiene_skus == True.
        """
        return sum(sku.cantidad_pallets for sku in self.skus)
    
    @property
    def pallets_capacidad(self) -> float:
        """
        Pallets que cuentan para capacidad del camión.
        - Cencosud usa PALLETS_REAL
        - Otros clientes usan PALLETS (o calculado desde SKUs)
        """
        if self.pallets_real is not None:
            return self.pallets_real
        
        if self.tiene_skus:
            return self.pallets_calculado_desde_skus
        
        return self.pallets
    
    @property
    def esta_asignado(self) -> bool:
        """Indica si el pedido está asignado a un camión"""
        return self.camion_id is not None
    
    def calcular_vcu(self, capacidad: TruckCapacity) -> tuple[float, float, float]:
        """Calcula VCU de peso, volumen y máximo"""
        return capacidad.calcular_vcu(self.peso, self.volumen)
    
    def asignar_a_camion(self, camion_id: str, numero: int, grupo: str, 
                         tipo_ruta: str, tipo_camion: str):
        """Asigna el pedido a un camión"""
        self.camion_id = camion_id
        self.numero_camion = numero
        self.grupo = grupo
        self.tipo_ruta = tipo_ruta
        self.tipo_camion = tipo_camion
    
    def desasignar(self):
        """Remueve la asignación del pedido"""
        self.camion_id = None
        self.numero_camion = None
        self.grupo = None
        self.tipo_ruta = None
        self.tipo_camion = None

    def validar_coherencia_skus(self) -> tuple[bool, List[str]]:
        """
        Valida que los datos agregados del pedido sean coherentes
        con la suma de los SKUs.
        
        Returns:
            (es_valido, lista_errores)
        """
        if not self.tiene_skus:
            return True, []
        
        errores = []
        tolerancia = 0.1  # Tolerancia para redondeo
        
        # Validar pallets
        pallets_skus = self.pallets_calculado_desde_skus
        if abs(pallets_skus - self.pallets) > tolerancia:
            errores.append(
                f"Pedido {self.pedido}: pallets agregado ({self.pallets:.2f}) != "
                f"suma SKUs ({pallets_skus:.2f})"
            )
        
        # Validar peso
        peso_skus = sum(sku.peso_kg for sku in self.skus)
        if abs(peso_skus - self.peso) > tolerancia:
            errores.append(
                f"Pedido {self.pedido}: peso agregado ({self.peso:.2f}) != "
                f"suma SKUs ({peso_skus:.2f})"
            )
        
        # Validar volumen
        vol_skus = sum(sku.volumen_m3 for sku in self.skus)
        if abs(vol_skus - self.volumen) > tolerancia:
            errores.append(
                f"Pedido {self.pedido}: volumen agregado ({self.volumen:.2f}) != "
                f"suma SKUs ({vol_skus:.2f})"
            )
        
        # Validar apilabilidad
        base_skus = sum(sku.base for sku in self.skus)
        if abs(base_skus - self.base) > tolerancia:
            errores.append(
                f"Pedido {self.pedido}: base agregado ({self.base:.2f}) != "
                f"suma SKUs ({base_skus:.2f})"
            )
        
        # Similar para otras categorías...
        
        return len(errores) == 0, errores

    @classmethod
    def from_pandas_row(cls, row: Dict[str, Any]) -> Pedido:
        """
        Constructor desde fila de DataFrame procesado.
        Asume que las columnas ya están normalizadas (CD, CE, PEDIDO, etc.)
        """
        # Manejar pallets_real (puede ser NaN, None, o valor numérico)
        pallets_real_val = None
        if "PALLETS_REAL" in row:
            val = row.get("PALLETS_REAL")
            if val is not None and val != "" and str(val).lower() != "nan":
                try:
                    pallets_real_val = float(val)
                except (ValueError, TypeError):
                    pallets_real_val = None
        
        # Manejar OC (puede ser None, vacío, o string)
        oc_val = None
        if "OC" in row:
            val = row.get("OC")
            if val is not None and val != "" and str(val).lower() not in ("nan", "none"):
                oc_val = str(val)
        
        return cls(
            # Obligatorios
            pedido=str(row.get("PEDIDO", "")),
            cd=str(row.get("CD", "")),
            ce=str(row.get("CE", "")),
            po=str(row.get("PO", "")),
            peso=float(row.get("PESO", 0)),
            volumen=float(row.get("VOL", 0)),
            pallets=float(row.get("PALLETS", 0)),
            valor=float(row.get("VALOR", 0)),
            
            # Opcionales con defaults
            pallets_real=pallets_real_val,
            valor_cafe=float(row.get("VALOR_CAFE", 0)),
            oc=oc_val,
            chocolates=str(row.get("CHOCOLATES", "NO")),
            
            # Flags (convertir a bool de manera segura)
            valioso=bool(int(float(row.get("VALIOSO", 0)))),
            pdq=bool(int(float(row.get("PDQ", 0)))),
            baja_vu=bool(int(float(row.get("BAJA_VU", 0)))),
            lote_dir=bool(int(float(row.get("LOTE_DIR", 0)))),
            
            # Apilabilidad
            base=float(row.get("BASE", 0)),
            superior=float(row.get("SUPERIOR", 0)),
            flexible=float(row.get("FLEXIBLE", 0)),
            no_apilable=float(row.get("NO_APILABLE", 0)),
            si_mismo=float(row.get("SI_MISMO", 0)),
            
            # Metadata (todo lo que no usamos arriba)
            skus = [],
            metadata={
                k: v for k, v in row.items() 
                if k not in {
                    "PEDIDO", "CD", "CE", "PO", "PESO", "VOL", "PALLETS", "PALLETS_REAL",
                    "VALOR", "VALOR_CAFE", "OC", "CHOCOLATES", "VALIOSO", "PDQ",
                    "BAJA_VU", "LOTE_DIR", "BASE", "SUPERIOR", "FLEXIBLE", 
                    "NO_APILABLE", "SI_MISMO"
                }
            }
        )
    
    def to_api_dict(self, capacidad: TruckCapacity) -> Dict[str, Any]:
        """
        Convierte a formato API (diccionario).
        SOLO se usa al devolver datos al frontend.
        """
        vcu_peso, vcu_vol, _ = self.calcular_vcu(capacidad)
        
        result = {
            "PEDIDO": self.pedido,
            "CD": self.cd,
            "CE": self.ce,
            "PO": self.po,
            "PESO": self.peso,
            "VOL": self.volumen,
            "PALLETS": self.pallets,
            "VALOR": self.valor,
            "VALOR_CAFE": self.valor_cafe,
            "VCU_VOL": vcu_vol,
            "VCU_PESO": vcu_peso,
            "CHOCOLATES": self.chocolates,
            "VALIOSO": int(self.valioso),
            "PDQ": int(self.pdq),
            "BAJA_VU": int(self.baja_vu),
            "LOTE_DIR": int(self.lote_dir),
            "BASE": self.base,
            "SUPERIOR": self.superior,
            "FLEXIBLE": self.flexible,
            "NO_APILABLE": self.no_apilable,
            "SI_MISMO": self.si_mismo,
        }
        
        # Campos opcionales
        if self.oc:
            result["OC"] = self.oc
        if self.pallets_real is not None:
            result["PALLETS_REAL"] = self.pallets_real
        if self.camion_id:
            result["CAMION"] = self.numero_camion
            result["GRUPO"] = self.grupo
            result["TIPO_RUTA"] = self.tipo_ruta
            result["TIPO_CAMION"] = self.tipo_camion
        
        # Añadir metadata extra
        result.update(self.metadata)
        
        return result
    
    def to_api_dict_fast(self, vcu_peso: float, vcu_vol: float) -> Dict[str, Any]:
        """
        Versión optimizada: recibe VCU pre-calculado.
        Evita re-calcular en cada llamada.
        """
        result = {
            "PEDIDO": self.pedido,
            "CD": self.cd,
            "CE": self.ce,
            "PO": self.po,
            "PESO": self.peso,
            "VOL": self.volumen,
            "PALLETS": self.pallets,
            "VALOR": self.valor,
            "VALOR_CAFE": self.valor_cafe,
            "VCU_VOL": vcu_vol,
            "VCU_PESO": vcu_peso,
            "CHOCOLATES": self.chocolates,
            "VALIOSO": int(self.valioso),
            "PDQ": int(self.pdq),
            "BAJA_VU": int(self.baja_vu),
            "LOTE_DIR": int(self.lote_dir),
            "BASE": self.base,
            "SUPERIOR": self.superior,
            "FLEXIBLE": self.flexible,
            "NO_APILABLE": self.no_apilable,
            "SI_MISMO": self.si_mismo,
        }
        
        if self.oc:
            result["OC"] = self.oc
        if self.pallets_real is not None:
            result["PALLETS_REAL"] = self.pallets_real
        if self.camion_id:
            result["CAMION"] = self.numero_camion
            result["GRUPO"] = self.grupo
            result["TIPO_RUTA"] = self.tipo_ruta
            result["TIPO_CAMION"] = self.tipo_camion
        
        result.update(self.metadata)
        return result


@dataclass
class Camion:
    """
    Representación de un camión con sus pedidos asignados.
    Las métricas se calculan on-demand (no se almacenan redundantemente).
    """
    
    id: str
    tipo_ruta: TipoRuta
    tipo_camion: TipoCamion
    cd: List[str]
    ce: List[str]
    grupo: str
    capacidad: TruckCapacity

    numero: int = 0
    
    # Pedidos asignados (objetos Pedido, NO diccionarios)
    pedidos: List[Pedido] = field(default_factory=list)
    
    # Opciones de cambio de tipo (calculadas por validators)
    opciones_tipo_camion: List[str] = field(default_factory=lambda: ["normal"])
    
    # Cache de métricas (private, se invalida al modificar pedidos)
    _vcu_vol: Optional[float] = field(default=None, repr=False)
    _vcu_peso: Optional[float] = field(default=None, repr=False)
    _vcu_max: Optional[float] = field(default=None, repr=False)
    _pos_total: Optional[float] = field(default=None, repr=False)
    
    metadata: Optional[Dict[str, Any]] = field(default=None, repr=False)
    
    def __post_init__(self):
        # Convertir strings a enums si es necesario
        if isinstance(self.tipo_ruta, str):
            self.tipo_ruta = TipoRuta(self.tipo_ruta)
        if isinstance(self.tipo_camion, str):
            self.tipo_camion = TipoCamion(self.tipo_camion)
        
        # Asignar info del camión a los pedidos
        self._actualizar_info_pedidos()
    
    def _actualizar_info_pedidos(self):
        """Actualiza la información de asignación en todos los pedidos"""
        for idx, pedido in enumerate(self.pedidos, 1):
            pedido.asignar_a_camion(
                camion_id=self.id,
                numero=idx,
                grupo=self.grupo,
                tipo_ruta=self.tipo_ruta.value,
                tipo_camion=self.tipo_camion.value
            )
    
    def _invalidar_cache(self):
        """Invalida el cache de métricas calculadas"""
        self._vcu_vol = None
        self._vcu_peso = None
        self._vcu_max = None
        self._pos_total = None
    
    # ============ PROPIEDADES CALCULADAS (NO REDUNDANCIA) ============
    
    @property
    def vcu_vol(self) -> float:
        """VCU de volumen (calculado on-demand, cacheado)"""
        if self._vcu_vol is None:
            total_vol = sum(p.volumen for p in self.pedidos)
            self._vcu_vol = total_vol / self.capacidad.cap_volume if self.capacidad.cap_volume > 0 else 0.0
        return self._vcu_vol
    
    @property
    def vcu_peso(self) -> float:
        """VCU de peso (calculado on-demand, cacheado)"""
        if self._vcu_peso is None:
            total_peso = sum(p.peso for p in self.pedidos)
            self._vcu_peso = total_peso / self.capacidad.cap_weight if self.capacidad.cap_weight > 0 else 0.0
        return self._vcu_peso
    
    @property
    def vcu_max(self) -> float:
        """VCU máximo entre peso y volumen"""
        if self._vcu_max is None:
            self._vcu_max = max(self.vcu_vol, self.vcu_peso)
        return self._vcu_max
    
    @property
    def pallets_conf(self) -> float:
        """Total de pallets configurados"""
        return sum(p.pallets for p in self.pedidos)
    
    @property
    def pallets_capacidad(self) -> float:
        """Pallets que cuentan para capacidad (usa pallets_real en Cencosud)"""
        return sum(p.pallets_capacidad for p in self.pedidos)
    
    @property
    def valor_total(self) -> float:
        """Valor total de pedidos en el camión"""
        return sum(p.valor for p in self.pedidos)
    
    @property
    def valor_cafe(self) -> float:
        """Valor de café en el camión"""
        return sum(p.valor_cafe for p in self.pedidos)
    
    @property
    def tiene_chocolates(self) -> bool:
        """Indica si algún pedido tiene chocolates"""
        return any(p.chocolates == "SI" for p in self.pedidos)
    
    @property
    def tiene_valiosos(self) -> bool:
        """Indica si algún pedido es valioso"""
        return any(p.valioso for p in self.pedidos)
    
    @property
    def tiene_pdq(self) -> bool:
        """Indica si algún pedido es PDQ"""
        return any(p.pdq for p in self.pedidos)
    
    @property
    def tiene_baja_vu(self) -> bool:
        """Indica si algún pedido tiene baja VU"""
        return any(p.baja_vu for p in self.pedidos)
    
    @property
    def tiene_lote_dir(self) -> bool:
        """Indica si algún pedido es lote dirigido"""
        return any(p.lote_dir for p in self.pedidos)
    
    @property
    def flujo_oc(self) -> Optional[str]:
        """
        Determina el flujo OC del camión:
        - None: no hay OCs
        - "MIX": múltiples OCs diferentes
        - <OC>: una sola OC
        """
        ocs = {p.oc for p in self.pedidos if p.oc}
        if not ocs:
            return None
        if len(ocs) == 1:
            return next(iter(ocs))
        return "MIX"
    
    @property
    def can_switch_tipo_camion(self) -> bool:
        """Indica si el camión puede cambiar de tipo"""
        return len(self.opciones_tipo_camion) > 1
    
    @property
    def pos_total(self) -> float:
        """
        Posiciones totales usadas (calculadas según apilabilidad).
        Requiere cálculo externo - se setea después de validar.
        """
        return self._pos_total or 0.0
    
    @pos_total.setter
    def pos_total(self, value: float):
        """Permite setear pos_total después de cálculos de validación"""
        self._pos_total = value
    
    # ============ MÉTODOS DE MANIPULACIÓN ============
    
    def agregar_pedido(self, pedido: Pedido):
        """Agrega un pedido al camión"""
        pedido.asignar_a_camion(
            camion_id=self.id,
            numero=len(self.pedidos) + 1,
            grupo=self.grupo,
            tipo_ruta=self.tipo_ruta.value,
            tipo_camion=self.tipo_camion.value
        )
        self.pedidos.append(pedido)
        self._invalidar_cache()


    def agregar_pedidos(self, pedidos: List[Pedido]):
        """
        Agrega pedidos al camión con validación de capacidad.
        
        Args:
            pedidos: Lista de pedidos a agregar
        
        Raises:
            ValueError: Si agregar los pedidos excede la capacidad
        """
        if not pedidos:
            return
        
        # Calcular totales SI se agregan estos pedidos
        vol_actual = sum(p.volumen for p in self.pedidos)
        peso_actual = sum(p.peso for p in self.pedidos)
        
        vol_nuevos = sum(p.volumen for p in pedidos)
        peso_nuevos = sum(p.peso for p in pedidos)
        
        vol_total = vol_actual + vol_nuevos
        peso_total = peso_actual + peso_nuevos
        
        # VCU no puede superar 100%
        vcu_vol_final = vol_total / self.capacidad.cap_volume
        vcu_peso_final = peso_total / self.capacidad.cap_weight
        
        if vcu_vol_final > 1.0 + 1e-6:  # Tolerancia pequeña para redondeo
            raise ValueError(
                f"Excede capacidad de volumen: "
                f"{vcu_vol_final*100:.1f}% > 100% "
                f"({vol_total:.0f} / {self.capacidad.cap_volume:.0f})"
            )
        
        if vcu_peso_final > 1.0 + 1e-6:
            raise ValueError(
                f"Excede capacidad de peso: "
                f"{vcu_peso_final*100:.1f}% > 100% "
                f"({peso_total:.0f} / {self.capacidad.cap_weight:.0f})"
            )
        
        # Validar pallets
        pallets_actual = sum(p.pallets_capacidad for p in self.pedidos)
        pallets_nuevos = sum(p.pallets_capacidad for p in pedidos)
        pallets_total = pallets_actual + pallets_nuevos
        
        if pallets_total > self.capacidad.max_pallets + 1e-6:
            raise ValueError(
                f"Excede capacidad de pallets: "
                f"{pallets_total:.1f} > {self.capacidad.max_pallets}"
            )
        
        # Validar posiciones de apilabilidad
        from optimization.utils.helpers import calcular_posiciones_apilabilidad
        pedidos_simulados = self.pedidos + pedidos
        pos_necesarias = calcular_posiciones_apilabilidad(
            pedidos_simulados,
            self.capacidad.max_positions
        )
        
        if pos_necesarias > self.capacidad.max_positions + 1e-6:
            raise ValueError(
                f"Excede posiciones de apilabilidad: "
                f"{pos_necesarias:.1f} > {self.capacidad.max_positions}"
            )
        
        # Si pasa todas las validaciones, agregar pedidos
        for pedido in pedidos:
            pedido.camion_id = self.id
            pedido.numero_camion = self.numero
            pedido.grupo = self.grupo
            pedido.tipo_ruta = self.tipo_ruta
            pedido.tipo_camion = self.tipo_camion
        
        self.pedidos.extend(pedidos)
        
        # Invalidar cache de métricas
        self._invalidar_cache()
    
    def remover_pedido(self, pedido_id: str) -> Optional[Pedido]:
        """
        Remueve un pedido del camión y lo retorna.
        Renumera los pedidos restantes.
        """
        for idx, p in enumerate(self.pedidos):
            if p.pedido == pedido_id:
                removed = self.pedidos.pop(idx)
                removed.desasignar()
                
                # Renumerar pedidos restantes
                for i, pedido in enumerate(self.pedidos, 1):
                    pedido.numero_camion = i
                
                self._invalidar_cache()
                return removed
        return None
    
    def remover_todos_pedidos(self) -> List[Pedido]:
        """Remueve todos los pedidos del camión y los retorna"""
        pedidos = self.pedidos.copy()
        for p in pedidos:
            p.desasignar()
        self.pedidos.clear()
        self._invalidar_cache()
        return pedidos
    
    def cambiar_tipo(self, nuevo_tipo: TipoCamion, nueva_capacidad: TruckCapacity):
        """Cambia el tipo de camión y actualiza su capacidad"""
        self.tipo_camion = nuevo_tipo
        self.capacidad = nueva_capacidad
        
        # Actualizar tipo en todos los pedidos
        for pedido in self.pedidos:
            pedido.tipo_camion = nuevo_tipo.value
        
        self._invalidar_cache()

    # services/models.py (actualizar método valida_capacidad_para en clase Camion)

    def valida_capacidad(self, nueva_capacidad: TruckCapacity) -> bool:
        """
        Verifica si el camión cumple con una nueva capacidad sin excederla.
        Valida que NO supere 100% en peso ni volumen.
        
        Args:
            nueva_capacidad: Capacidad a validar
        
        Returns:
            True si el camión cabe en la nueva capacidad, False si no
        """
        if not self.pedidos:
            return True  # Camión vacío siempre cabe
        
        # Calcular totales actuales
        vol_total = sum(p.volumen for p in self.pedidos)
        peso_total = sum(p.peso for p in self.pedidos)
        pallets_total = sum(p.pallets_capacidad for p in self.pedidos)
        
        # Validar VCU (NO puede superar 100%)
        vcu_vol = vol_total / nueva_capacidad.cap_volume if nueva_capacidad.cap_volume > 0 else 0
        vcu_peso = peso_total / nueva_capacidad.cap_weight if nueva_capacidad.cap_weight > 0 else 0
        
        if vcu_vol > 1.0 + 1e-6:  # Tolerancia pequeña para redondeo
            return False
        
        if vcu_peso > 1.0 + 1e-6:
            return False
        
        # Validar pallets
        if pallets_total > nueva_capacidad.max_pallets + 1e-6:
            return False
        
        # Validar posiciones de apilabilidad
        try:
            from optimization.utils.helpers import calcular_posiciones_apilabilidad
            pos_necesarias = calcular_posiciones_apilabilidad(
                self.pedidos,
                nueva_capacidad.max_positions
            )
            
            if pos_necesarias > nueva_capacidad.max_positions + 1e-6:
                return False
        except Exception:
            # Si hay error calculando posiciones, ser conservador
            return False
        
        return True
        
    # ============ EXPORTACIÓN ============    
    def to_api_dict(self) -> Dict[str, Any]:
        """Convierte a formato API (diccionario)."""
        result = {
            "id": self.id,
            "numero": self.numero,
            "grupo": self.grupo,
            "tipo_ruta": self.tipo_ruta.value,
            "tipo_camion": self.tipo_camion.value,
            "cd": self.cd,
            "ce": self.ce,
            "pedidos": [p.to_api_dict(self.capacidad) for p in self.pedidos],
            "vcu_vol": self.vcu_vol,
            "vcu_peso": self.vcu_peso,
            "vcu_max": self.vcu_max,
            "pallets_conf": self.pallets_conf,
            "pos_total": self.pos_total,
            "valor_total": self.valor_total,
            "valor_cafe": self.valor_cafe,
            "chocolates": "SI" if self.tiene_chocolates else "NO",
            "skus_valiosos": self.tiene_valiosos,
            "pdq": self.tiene_pdq,
            "baja_vu": self.tiene_baja_vu,
            "lote_dir": self.tiene_lote_dir,
            "flujo_oc": self.flujo_oc,
            "can_switch_tipo_camion": self.can_switch_tipo_camion,
            "opciones_tipo_camion": self.opciones_tipo_camion,
        }
        
        # ✅ AGREGAR: Incluir información de validación si existe
        if self.metadata:
            if 'altura_validada' in self.metadata:
                result['altura_validada'] = self.metadata['altura_validada']
            
            if 'errores_validacion' in self.metadata:
                result['errores_validacion'] = self.metadata['errores_validacion']
            
            if 'layout_info' in self.metadata:
                result['layout_info'] = self.metadata['layout_info']
        
        return result


    def to_api_dict_fast(self) -> Dict[str, Any]:
        """
        Versión optimizada: usa VCU cacheado.
        """
        # Pre-calcular VCUs una sola vez
        _ = self.vcu_vol  # Fuerza cálculo y cache
        _ = self.vcu_peso
        _ = self.vcu_max
            
        # Convertir pedidos en batch
        pedidos_dicts = [
            p.to_api_dict_fast(
                vcu_peso=p.peso / self.capacidad.cap_weight,
                vcu_vol=p.volumen / self.capacidad.cap_volume
            )
            for p in self.pedidos
        ]
            
        return {
                "id": self.id,
                "grupo": self.grupo,
                "tipo_ruta": self.tipo_ruta.value,
                "tipo_camion": self.tipo_camion.value,
                "cd": self.cd,
                "ce": self.ce,
                "pedidos": pedidos_dicts,
                "vcu_vol": self._vcu_vol,  # Usar cache directo
                "vcu_peso": self._vcu_peso,
                "vcu_max": self._vcu_max,
                "pallets_conf": self.pallets_conf,
                "pos_total": self.pos_total,
                "valor_total": self.valor_total,
                "valor_cafe": self.valor_cafe,
                "chocolates": "SI" if self.tiene_chocolates else "NO",
                "skus_valiosos": self.tiene_valiosos,
                "pdq": self.tiene_pdq,
                "baja_vu": self.tiene_baja_vu,
                "lote_dir": self.tiene_lote_dir,
                "flujo_oc": self.flujo_oc,
                "can_switch_tipo_camion": self.can_switch_tipo_camion,
                "opciones_tipo_camion": self.opciones_tipo_camion,
        }


@dataclass
class EstadoOptimizacion:
    """
    Estado completo de una optimización.
    Contiene todos los camiones y pedidos no incluidos.
    """
    camiones: List[Camion]
    pedidos_no_incluidos: List[Pedido]
    cliente: str
    
    # Capacidades por tipo (para cálculos)
    capacidad_normal: TruckCapacity
    capacidad_bh: Optional[TruckCapacity] = None
    
    # ============ PROPIEDADES AGREGADAS ============
    
    @property
    def total_camiones(self) -> int:
        """Total de camiones en la solución"""
        return len(self.camiones)
    
    @property
    def camiones_normal(self) -> List[Camion]:
        """Lista de camiones tipo normal"""
        return [c for c in self.camiones if c.tipo_camion == TipoCamion.NORMAL]
    
    @property
    def camiones_bh(self) -> List[Camion]:
        """Lista de camiones tipo BH"""
        return [c for c in self.camiones if c.tipo_camion == TipoCamion.BH]
    
    @property
    def total_pedidos_asignados(self) -> int:
        """Total de pedidos asignados a camiones"""
        return sum(len(c.pedidos) for c in self.camiones)
    
    @property
    def total_pedidos(self) -> int:
        """Total de pedidos (asignados + no incluidos)"""
        return self.total_pedidos_asignados + len(self.pedidos_no_incluidos)
    
    @property
    def promedio_vcu(self) -> float:
        """VCU promedio de todos los camiones"""
        if not self.camiones:
            return 0.0
        return sum(c.vcu_max for c in self.camiones) / len(self.camiones)
    
    @property
    def promedio_vcu_normal(self) -> float:
        """VCU promedio de camiones normales"""
        normales = self.camiones_normal
        if not normales:
            return 0.0
        return sum(c.vcu_max for c in normales) / len(normales)
    
    @property
    def promedio_vcu_bh(self) -> float:
        """VCU promedio de camiones BH"""
        bhs = self.camiones_bh
        if not bhs:
            return 0.0
        return sum(c.vcu_max for c in bhs) / len(bhs)
    
    @property
    def valorizado(self) -> float:
        """Valor total de todos los pedidos asignados"""
        return sum(c.valor_total for c in self.camiones)
    
    @property
    def camiones_validos(self) -> List[Camion]:
        """Camiones que pasaron validación de altura"""
        return [
            c for c in self.camiones
            if c.metadata and c.metadata.get('altura_validada') == True
        ]
    
    @property
    def camiones_invalidos(self) -> List[Camion]:
        """Camiones que NO pasaron validación de altura"""
        return [
            c for c in self.camiones
            if c.metadata and c.metadata.get('altura_validada') == False
        ]
    
    @property
    def camiones_no_validados(self) -> List[Camion]:
        """Camiones sin validación (legacy sin SKUs)"""
        return [
            c for c in self.camiones
            if not c.metadata or c.metadata.get('altura_validada') is None
        ]
    
    @property
    def tasa_validacion(self) -> float:
        """Porcentaje de camiones válidos (sobre los que fueron validados)"""
        validados = self.camiones_validos + self.camiones_invalidos
        if not validados:
            return 0.0
        return (len(self.camiones_validos) / len(validados)) * 100
    

    # ============ MÉTODOS ============
    
    def get_capacidad_para_tipo(self, tipo_camion: TipoCamion) -> TruckCapacity:
        """Obtiene la capacidad correspondiente al tipo de camión"""
        if tipo_camion == TipoCamion.BH and self.capacidad_bh:
            return self.capacidad_bh
        return self.capacidad_normal
    
    def to_api_dict(self) -> Dict[str, Any]:
        base_result = {
            "camiones": [c.to_api_dict() for c in self.camiones],
            "pedidos_no_incluidos": [
                p.to_api_dict(self.capacidad_normal)
                for p in self.pedidos_no_incluidos
            ],
            "estadisticas": {
                "cantidad_camiones": self.total_camiones,
                "cantidad_camiones_normal": len(self.camiones_normal),
                "cantidad_camiones_bh": len(self.camiones_bh),
                "cantidad_pedidos_asignados": self.total_pedidos_asignados,
                "total_pedidos": self.total_pedidos,
                "promedio_vcu": self.promedio_vcu,
                "promedio_vcu_normal": self.promedio_vcu_normal,
                "promedio_vcu_bh": self.promedio_vcu_bh,
                "valorizado": self.valorizado,
            }
        }
        
        # Estadísticas de validación
        total_validos = len(self.camiones_validos)
        total_invalidos = len(self.camiones_invalidos)
        total_no_validados = len(self.camiones_no_validados)
        
        if total_validos > 0 or total_invalidos > 0:
            base_result["estadisticas"]["validacion"] = {
                "camiones_validos": total_validos,
                "camiones_invalidos": total_invalidos,
                "camiones_no_validados": total_no_validados,
                "tasa_validacion": round(self.tasa_validacion, 2),
            }
        
        return base_result
    

@dataclass
class ConfiguracionGrupo:
    """Configuración de un grupo de optimización (ruta específica)"""
    id: str
    tipo: TipoRuta
    ce: List[str]
    cd: List[str]
    oc: Optional[Any] = None
    
    def __post_init__(self):
        if isinstance(self.tipo, str):
            self.tipo = TipoRuta(self.tipo)

