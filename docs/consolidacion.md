# 📦 Consolidación de Pickings

## Concepto

La **consolidación** permite agrupar múltiples pickings (pallets parciales) del mismo tipo de apilamiento en un único pallet físico, hasta completar la altura del camión.

## Configuración por Cliente

### `PERMITE_CONSOLIDACION`

- **`False`**: Cada picking va en su propio pallet físico (no se agrupan)
  - Ejemplo: Si tengo 3 pickings de 50cm cada uno, ocupan 3 posiciones en el camión
  - Usado por: **Cencosud**, **Walmart**

- **`True`**: Pickings del mismo tipo de apilamiento pueden consolidarse
  - Ejemplo: Los mismos 3 pickings pueden consolidarse en 1 posición (150cm total)
  - Usado por: **Disvet**

### `MAX_SKUS_POR_PALLET`

Solo aplica si `PERMITE_CONSOLIDACION = True`.

Define cuántos SKUs diferentes pueden compartir un pallet físico.

- **Valor típico**: 3-5 SKUs
- **Ejemplo con MAX=3**:
  - ✅ Válido: SKU_A (picking) + SKU_B (picking) + SKU_C (picking) en 1 pallet
  - ❌ Inválido: 4 SKUs diferentes en 1 pallet

## Reglas de Consolidación

### 1. Solo pickings del mismo tipo de apilamiento
```
✅ VÁLIDO:
- Pallet físico con: BASE (picking SKU_A) + BASE (picking SKU_B)

❌ INVÁLIDO:
- Pallet físico con: BASE (picking SKU_A) + SUPERIOR (picking SKU_B)
```

### 2. Respetar límite de altura
```
Altura camión: 270cm
Pickings disponibles:
- SKU_A (BASE): 80cm
- SKU_B (BASE): 90cm
- SKU_C (BASE): 110cm

✅ VÁLIDO: SKU_A + SKU_B = 170cm < 270cm
❌ INVÁLIDO: SKU_A + SKU_B + SKU_C = 280cm > 270cm
```

### 3. Límite de SKUs diferentes
```
MAX_SKUS_POR_PALLET = 3

✅ VÁLIDO: 3 pickings de SKUs diferentes
❌ INVÁLIDO: 4 pickings de SKUs diferentes
✅ VÁLIDO: 5 pickings pero solo de 3 SKUs diferentes
  (por ejemplo: 2 de SKU_A, 2 de SKU_B, 1 de SKU_C)
```

## Ejemplos por Cliente

### Cencosud (NO permite consolidación)
```
Excel entrada:
SKU001 | PED001 | PALLETS: 2.5 | ALTURA_FULL: 150cm | ALTURA_PICKING: 75cm

Resultado:
- Pallet 1: SKU001 full (150cm)
- Pallet 2: SKU001 full (150cm)
- Pallet 3: SKU001 picking (75cm)  ← Va solo, no se consolida

Total: 3 posiciones en camión
```

### Disvet (SÍ permite consolidación, MAX=4)
```
Excel entrada:
SKU001 | PED001 | PALLETS: 0.5 | ALTURA_PICKING: 75cm  | BASE: 0.5
SKU002 | PED001 | PALLETS: 0.6 | ALTURA_PICKING: 90cm  | BASE: 0.6
SKU003 | PED001 | PALLETS: 0.7 | ALTURA_PICKING: 105cm | BASE: 0.7

Resultado consolidado:
- Pallet físico 1: SKU001 (75cm) + SKU002 (90cm) + SKU003 (105cm) = 270cm
  → Solo 1 posición en camión
  → 3 SKUs diferentes (< MAX=4) ✓

Total: 1 posición en camión (vs 3 sin consolidación)
```

## Beneficios de la Consolidación

### Sin consolidación (Cencosud)
- ✅ Más simple de gestionar en bodega
- ✅ Trazabilidad directa (1 pallet físico = 1 SKU)
- ❌ Usa más posiciones del camión
- ❌ Menos eficiente en espacio

### Con consolidación (Disvet)
- ✅ Usa menos posiciones del camión
- ✅ Más eficiente en espacio (mejor aprovechamiento altura)
- ❌ Más complejo de armar en bodega
- ❌ Trazabilidad requiere etiquetar fragmentos

## Validación en el Sistema

El validador de altura considera la configuración de consolidación:
```python
# Sin consolidación
validator = HeightValidator(
    altura_maxima_cm=capacidad.altura_cm,  # Desde config de camión
    permite_consolidacion=False,
    max_skus_por_pallet=1  # Ignorado si permite=False
)

# Con consolidación
validator = HeightValidator(
    altura_maxima_cm=capacidad.altura_cm,
    permite_consolidacion=True,
    max_skus_por_pallet=4
)
```