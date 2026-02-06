# Entrar al enviroment
C:\venvs\backend-prod-env\Scripts\Activate.ps1

# Entrar a la carpeta backend
cd backend-prod

# Ejecutar backend
uvicorn app.main:app --port 8001

# Para levantarlo sin logs:
uvicorn app.main:app --no-access-log --port 8001

# Para ejecutar el frontend, debes encontrarte en la carpeta frontend-prod y es necesario tener un .env en la razís del front con lo siguiente:
VITE_API_BASE_URL=http://127.0.0.1:8001

# ejecutar
npm run dev


let
  Source = Table.Combine({#"OTR OL2"}),
  #"Added Custom" = Table.AddColumn(Source, "Key_EA", each [#"MaterialNumber(MATNR)"] & [SalesUnit]),
  #"Changed Type" = Table.TransformColumnTypes(#"Added Custom", {{"Key_EA", type text}}),
  #"Merged Queries" = Table.NestedJoin(#"Changed Type", {"Key_EA"}, #"Conv EA", {"ID"}, "Conv EA", JoinKind.LeftOuter),
  #"Expanded {0}" = Table.ExpandTableColumn(#"Merged Queries", "Conv EA", {"NumeratorForConversionToBaseUnitsOfMeasure", "DenominatorForConversionToBaseUnitsOfMeasure"}, {"Conv EA.NumeratorForConversionToBaseUnitsOfMeasure", "Conv EA.DenominatorForConversionToBaseUnitsOfMeasure"}),
  #"Added Custom1" = Table.AddColumn(#"Expanded {0}", "Order Quantity", each if [Conv EA.NumeratorForConversionToBaseUnitsOfMeasure] = null then 
    [CumulativeOrderQuantityInSalesUnits] 
else 
    [CumulativeOrderQuantityInSalesUnits] * ([Conv EA.NumeratorForConversionToBaseUnitsOfMeasure] / [Conv EA.DenominatorForConversionToBaseUnitsOfMeasure])),
  #"Added Custom2" = Table.AddColumn(#"Added Custom1", "Confirmed Quantity", each if [Conv EA.NumeratorForConversionToBaseUnitsOfMeasure] = null then 
    [CumulativeOrderQuantityInSalesUnits] 
else 
    [CumulativeConfirmedQuantityInSalesUnit] * ([Conv EA.NumeratorForConversionToBaseUnitsOfMeasure] / [Conv EA.DenominatorForConversionToBaseUnitsOfMeasure])),
  #"Changed Type1" = Table.TransformColumnTypes(#"Added Custom2", {{"Order Quantity", type number}, {"Confirmed Quantity", type number}}),
  #"Renamed Columns" = Table.RenameColumns(#"Changed Type1", {{"Order Quantity", "Order Quantity EA"}, {"Confirmed Quantity", "Confirmed Quantity EA"}}),
  #"Merged Queries1" = Table.NestedJoin(#"Renamed Columns", {"MaterialNumber(MATNR)"}, #"Conv PUM", {"MaterialNumber"}, "Conv PUM", JoinKind.LeftOuter),
  #"Expanded {0}1" = Table.ExpandTableColumn(#"Merged Queries1", "Conv PUM", {"NumeratorForConversionToBaseUnitsOfMeasure", "DenominatorForConversionToBaseUnitsOfMeasure"}, {"Conv PUM.NumeratorForConversionToBaseUnitsOfMeasure", "Conv PUM.DenominatorForConversionToBaseUnitsOfMeasure"}),
  #"Consultas combinadas 1" = Table.NestedJoin(#"Expanded {0}1", {"MaterialNumber(MATNR)"}, #"Conv Cj", {"MaterialNumber"}, "Conv Cj", JoinKind.LeftOuter),
  #"Conv Cj expandido" = Table.ExpandTableColumn(#"Consultas combinadas 1", "Conv Cj", {"NumeratorForConversionToBaseUnitsOfMeasure", "DenominatorForConversionToBaseUnitsOfMeasure"}, {"ConvCj.NumeratorForConversionToBaseUnitsOfMeasure", "ConvCj.DenominatorForConversionToBaseUnitsOfMeasure"}),
  #"Personalizado agregado" = Table.AddColumn(#"Conv Cj expandido", "Order Quantity Cj", each if [ConvCj.NumeratorForConversionToBaseUnitsOfMeasure] = null  then [CumulativeOrderQuantityInSalesUnits] else [Order Quantity EA] / ([ConvCj.NumeratorForConversionToBaseUnitsOfMeasure]/[ConvCj.DenominatorForConversionToBaseUnitsOfMeasure])),
  #"Personalizado agregado 1" = Table.AddColumn(#"Personalizado agregado", "Confirmed Quantity Cj", each if [ConvCj.NumeratorForConversionToBaseUnitsOfMeasure] = null then [CumulativeOrderQuantityInSalesUnits] else [Confirmed Quantity EA] / ([ConvCj.NumeratorForConversionToBaseUnitsOfMeasure]/[ConvCj.DenominatorForConversionToBaseUnitsOfMeasure])),
  #"Added Custom5" = Table.AddColumn(#"Personalizado agregado 1", "Confirmed Quantity1", each if [Conv PUM.NumeratorForConversionToBaseUnitsOfMeasure] = null then [CumulativeConfirmedQuantityInSalesUnit] else [Confirmed Quantity EA] / ([Conv PUM.NumeratorForConversionToBaseUnitsOfMeasure]/[Conv PUM.DenominatorForConversionToBaseUnitsOfMeasure])),
  #"Added Custom4" = Table.AddColumn(#"Added Custom5", "Order Quantity1", each if [Conv PUM.NumeratorForConversionToBaseUnitsOfMeasure] = null  then [CumulativeOrderQuantityInSalesUnits] else [Order Quantity EA] / ([Conv PUM.NumeratorForConversionToBaseUnitsOfMeasure]/[Conv PUM.DenominatorForConversionToBaseUnitsOfMeasure])),
  #"Added Custom7" = Table.AddColumn(#"Added Custom4", "POS", each Text.TrimStart([#"SalesDocumentItem(POSNR)"], "0")),
  #"Changed Type2" = Table.TransformColumnTypes(#"Added Custom7", {{"Order Quantity1", type number}, {"Confirmed Quantity1", type number}}),
  #"Added Custom8" = Table.AddColumn(#"Changed Type2", "Material Entered", each Text.TrimStart([MaterialEntered], "0")),
  #"Added Custom9" = Table.AddColumn(#"Added Custom8", "SKU", each Text.TrimStart([#"MaterialNumber(MATNR)"], "0")),
  
  #"Changed Type3" = Table.TransformColumnTypes(#"Added Custom9", {{"POS", type text}, {"Material Entered", type text}, {"SKU", type text}}),

  // Crear columna sin ceros para el join con Solicitante
  #"Added Sold To Temp" = Table.AddColumn(#"Changed Type3", "SoldTo_Temp", each Text.TrimStart([CustomerNumberSoldTo], "0"), type text),

  // Join con Solicitante usando la columna sin ceros
  #"Merged Solicitante Temp" = Table.NestedJoin(#"Added Sold To Temp", {"SoldTo_Temp"}, Solicitante, {"Solicitante"}, "Solicitante_Temp", JoinKind.LeftOuter),
  #"Expanded Solicitante Temp" = Table.ExpandTableColumn(#"Merged Solicitante Temp", "Solicitante_Temp", {"CD"}, {"CD_Temp"}),
  #"Replace null CD" = Table.ReplaceValue(#"Expanded Solicitante Temp", null, "No encontrado", Replacer.ReplaceValue, {"CD_Temp"}),

  // Eliminar columna temporal
  #"Removed SoldTo Temp" = Table.RemoveColumns(#"Replace null CD", {"SoldTo_Temp"}),

  // Join estándar con Maestra Paletizado (para los demás clientes)
  #"Merged queries 1" = Table.NestedJoin(#"Removed SoldTo Temp", {"SKU"}, #"Maestra Paletizado", {"SKU"}, "Maestra Paletizado", JoinKind.LeftOuter),
  #"Expanded Maestra Paletizado" = Table.ExpandTableColumn(#"Merged queries 1", "Maestra Paletizado", {"CENCO", "SMU", "TOTTUS", "WALMART", "Paletizado Nestle"}, {"CENCO", "SMU", "TOTTUS", "WALMART", "Paletizado Nestle"}),

  // Join específico para SMU por SKU + CD
  #"Merged SMU by CD" = Table.NestedJoin(#"Expanded Maestra Paletizado", {"SKU", "CD_Temp"}, #"Maestra Paletizado SMU", {"SKU", "Bodega"}, "SMU_CD", JoinKind.LeftOuter),
  #"Expanded SMU_CD" = Table.ExpandTableColumn(#"Merged SMU by CD", "SMU_CD", {"SMU"}, {"SMU_por_CD"}),

  // Cálculo de Confirmed Quantity con prioridad SMU por CD
  #"Added custom 1" = Table.AddColumn(#"Expanded SMU_CD", "Confirmed Quantity", each 
    if [CUSTHIERLEVEL4NAME] = "L4 CL Cencosud" then
        if [CENCO] = null then [Confirmed Quantity Cj] / [Paletizado Nestle] 
        else [Confirmed Quantity Cj] / [CENCO] 
    else if [CUSTHIERLEVEL4NAME] = "L4 CL SMU" then
        if [SMU_por_CD] <> null then [Confirmed Quantity Cj] / [SMU_por_CD]
        else if [SMU] <> null then [Confirmed Quantity Cj] / [SMU]
        else [Confirmed Quantity Cj] / [Paletizado Nestle]
    else if [CUSTHIERLEVEL4NAME] = "L4 CL Tottus" then
        if [TOTTUS] = null then [Confirmed Quantity Cj] / [Paletizado Nestle] 
        else [Confirmed Quantity Cj] / [TOTTUS]
    else if [CUSTHIERLEVEL4NAME] = "L4 CL Walmart" then
        if [WALMART] = null then [Confirmed Quantity Cj] / [Paletizado Nestle] 
        else [Confirmed Quantity Cj] / [WALMART]
    else [Confirmed Quantity1]
),

  // Cálculo de Order Quantity con prioridad SMU por CD
  #"Added custom 2" = Table.AddColumn(#"Added custom 1", "Order Quantity", each 
    if [CUSTHIERLEVEL4NAME] = "L4 CL Cencosud" then
        if [CENCO] = null then [Order Quantity Cj] / [Paletizado Nestle] 
        else [Order Quantity Cj] / [CENCO] 
    else if [CUSTHIERLEVEL4NAME] = "L4 CL SMU" then
        if [SMU_por_CD] <> null then [Order Quantity Cj] / [SMU_por_CD]
        else if [SMU] <> null then [Order Quantity Cj] / [SMU]
        else [Order Quantity Cj] / [Paletizado Nestle]
    else if [CUSTHIERLEVEL4NAME] = "L4 CL Tottus" then
        if [TOTTUS] = null then [Order Quantity Cj] / [Paletizado Nestle] 
        else [Order Quantity Cj] / [TOTTUS]
    else if [CUSTHIERLEVEL4NAME] = "L4 CL Walmart" then
        if [WALMART] = null then [Order Quantity Cj] / [Paletizado Nestle] 
        else [Order Quantity Cj] / [WALMART]
    else [Order Quantity1]
),

  #"Removed columns 1" = Table.RemoveColumns(#"Added custom 2", {"CENCO", "SMU", "TOTTUS", "WALMART", "Confirmed Quantity1", "Order Quantity1", "SMU_por_CD"}),
  #"Changed column type" = Table.TransformColumnTypes(#"Removed columns 1", {{"Order Quantity", type number}, {"Confirmed Quantity", type number}}),
  #"Renamed Columns1" = Table.RenameColumns(#"Changed column type", {{"SalesOrganization", "Sales Organization"}}),
  #"Removed Columns" = Table.RemoveColumns(#"Renamed Columns1", {"SalesDocumentItem(POSNR)", "MaterialEntered", "MaterialNumber(MATNR)"}),
  #"Renamed Columns2" = Table.RenameColumns(#"Removed Columns", {{"ShortTextForSalesOrderItem", "Description"}}),
  #"Added Custom10" = Table.AddColumn(#"Renamed Columns2", "SU", each if [Conv PUM.NumeratorForConversionToBaseUnitsOfMeasure] = null then [SalesUnit] else "PUM"),
  #"Changed Type4" = Table.TransformColumnTypes(#"Added Custom10", {{"SU", type text}}),
  #"Removed Columns1" = Table.RemoveColumns(#"Changed Type4", {"CumulativeOrderQuantityInSalesUnits", "CumulativeConfirmedQuantityInSalesUnit", "SalesUnit"}),
  #"Renamed Columns3" = Table.RenameColumns(#"Removed Columns1", {{"PlantName", "Plant Name"}, {"NetValueOfTheOrderItemInDocumentCurrency", "Net Value Of The Order Item In Document Currency"}}),
  #"Added Custom11" = Table.AddColumn(#"Renamed Columns3", "NetValue Of The Order Item In Document Currency", each [Net Value Of The Order Item In Document Currency] * 100),
  #"Changed Type5" = Table.TransformColumnTypes(#"Added Custom11", {{"NetValue Of The Order Item In Document Currency", type number}}),
  #"Removed Columns2" = Table.RemoveColumns(#"Changed Type5", {"Net Value Of The Order Item In Document Currency"}),
  #"Renamed Columns4" = Table.RenameColumns(#"Removed Columns2", {{"NetValue Of The Order Item In Document Currency", "Net Value Of The Order Item In Document Currency"}, {"RequestedDeliveryDate", "Requested Delivery Date"}, {"SalesDocument", "Sales Document"}}),
  #"Renamed Columns8" = Table.RenameColumns(#"Renamed Columns4", {{"CustomerPurchASeOrderNumber", "Customer Purchase Order Number"}}),
  #"Added Custom12" = Table.AddColumn(#"Renamed Columns8", "Customer Number Ship To", each Text.TrimStart([CustomerNumberShipTo], "0")),
  #"Changed Type10" = Table.TransformColumnTypes(#"Added Custom12", {{"Customer Number Ship To", type text}}),
  #"Removed Columns3" = Table.RemoveColumns(#"Changed Type10", {"CustomerNumberShipTo"}),
  #"Added Custom13" = Table.AddColumn(#"Removed Columns3", "Customer Number Sold To", each Text.TrimStart([CustomerNumberSoldTo], "0")),
  #"Changed Type11" = Table.TransformColumnTypes(#"Added Custom13", {{"Customer Number Sold To", type text}}),
  #"Removed Columns5" = Table.RemoveColumns(#"Changed Type11", {"CustomerNumberSoldTo", "Key_EA", "Conv EA.NumeratorForConversionToBaseUnitsOfMeasure", "Conv EA.DenominatorForConversionToBaseUnitsOfMeasure", "Order Quantity EA", "Confirmed Quantity EA", "Conv PUM.NumeratorForConversionToBaseUnitsOfMeasure", "Conv PUM.DenominatorForConversionToBaseUnitsOfMeasure", "ConvCj.NumeratorForConversionToBaseUnitsOfMeasure", "ConvCj.DenominatorForConversionToBaseUnitsOfMeasure"}),
  #"Added Custom14" = Table.AddColumn(#"Removed Columns5", "id", each [Sales Document] & [POS]),
  #"Changed Type12" = Table.TransformColumnTypes(#"Added Custom14", {{"id", type text}}),
  #"Removed Duplicates" = Table.Distinct(#"Changed Type12", {"id"}),
  #"Removed Columns6" = Table.RemoveColumns(#"Removed Duplicates", {"id"}),
  #"Consultas combinadas" = Table.NestedJoin(#"Removed Columns6", {"SKU"}, #"Maestra Apilabilidad", {"Material"}, "Maestra Apilabilidad", JoinKind.LeftOuter),
  #"Se expandió Maestra Apilabilidad" = Table.ExpandTableColumn(#"Consultas combinadas", "Maestra Apilabilidad", {"¿Puede ser base de un pallets? (Sí / No)", "¿Puede montarse sobre otro pallets? (Sí / No)", "¿Apilable por sí mismo? (Sí / No)"}, {"Apilable Base", "Montado", "Apilable por si mismo"}),
  #"Columna No Apilable" = Table.AddColumn(#"Se expandió Maestra Apilabilidad", "No Apilable", each if ([Apilable Base] = "NO" and [Montado] = "NO" and [Apilable por si mismo] = "NO") or ([Apilable Base] = null and [Montado] = null and [Apilable por si mismo] = null)  then [Confirmed Quantity] else 0),
  #"Columna Superior" = Table.AddColumn(#"Columna No Apilable", "Superior", each if [Apilable Base] = "NO" and [Montado] = "SI" and [Apilable por si mismo] = "NO" then [Confirmed Quantity] else 0),
  #"Columna Base" = Table.AddColumn(#"Columna Superior", "Base", each if [Apilable Base] = "SI" and [Montado] = "NO" and [Apilable por si mismo] = "NO" then [Confirmed Quantity] else 0),
  #"Columna Flexible" = Table.AddColumn(#"Columna Base", "Flexible", each if [Apilable Base] = "SI" and [Montado] = "SI" then [Confirmed Quantity] else 0),
  #"Personalizado agregado 5" = Table.AddColumn(#"Columna Flexible", "Apilable si mismo", each if ([Apilable Base] = "SI" and [Montado] = "NO" and [Apilable por si mismo] = "SI") or ([Apilable Base] = "NO" and [Montado] = "SI" and [Apilable por si mismo] = "SI") or ([Apilable Base] = "NO" and [Montado] = "NO" and [Apilable por si mismo] = "SI") then [Confirmed Quantity] else 0),
  #"Personalizado agregado 4" = Table.AddColumn(#"Personalizado agregado 5", "Falta en Maestra", each if [Apilable Base] = null and [Montado] = null then [Confirmed Quantity] else 0),
  #"Consultas combinadas1" = Table.NestedJoin(#"Personalizado agregado 4", {"SKU"}, #"Maestra SKU", {"SKU"}, "Maestra SKU", JoinKind.LeftOuter),
  #"Se expandió Maestra SKU" = Table.ExpandTableColumn(#"Consultas combinadas1", "Maestra SKU", {"Categoría"}, {"Maestra SKU.Categoría"}),
  #"Personalizada agregada" = Table.AddColumn(#"Se expandió Maestra SKU", "Confirmed Quantity $", each [Confirmed Quantity]*([Net Value Of The Order Item In Document Currency]/[Order Quantity])),
  #"Personalizada agregada1" = Table.AddColumn(#"Personalizada agregada", "Chocolate", each if Text.Lower([Maestra SKU.Categoría]) = "chocolates" then 1 else 0),
  #"Personalizada agregada2" = Table.AddColumn(#"Personalizada agregada1", "Valor Cafe", each if Text.Lower([Maestra SKU.Categoría]) = "soluble coffee/nesca" then [#"Confirmed Quantity $"] else 0),
  #"Peso a KG" = Table.AddColumn(#"Personalizada agregada2", "Order Quantity Kg", each if [#"WeightUnit(GEWEI)"] = "KG" then [NetWeightOfTheItem] else [NetWeightOfTheItem] / 1000, type number),
  #"Peso a KG Net" = Table.AddColumn(#"Peso a KG", "Order Quantity Kg Net", each if [#"WeightUnit(GEWEI)"] = "KG" then [GrossWeightOfTheItem] else [GrossWeightOfTheItem] / 1000, type number),
  #"Personalizada agregada3" = Table.AddColumn(#"Peso a KG Net", "Confirmed Quantity Kg", each [Confirmed Quantity]*([Order Quantity Kg]/[Order Quantity])),
  #"Personalizada agregada3 net" = Table.AddColumn(#"Personalizada agregada3", "Confirmed Quantity Kg Net", each [Confirmed Quantity]*([Order Quantity Kg Net]/[Order Quantity])),
  #"Columnas con nombre cambiado" = Table.RenameColumns(#"Personalizada agregada3 net", {{"Net Value Of The Order Item In Document Currency", "Order Quantity $"}}),
  #"Personalizada agregada4" = Table.AddColumn(#"Columnas con nombre cambiado", "PDQ", each if Text.Contains([Description], "PDQ") then [Confirmed Quantity] else 0),
  #"Consultas combinadas2" = Table.NestedJoin(#"Personalizada agregada4", {"SKU"}, #"Maestra Valioso", {"SKU Nestle"}, "Maestra Valioso", JoinKind.LeftOuter),
  #"Se expandió Maestra Valioso1" = Table.ExpandTableColumn(#"Consultas combinadas2", "Maestra Valioso", {"VALIOSO"}, {"Maestra Valioso.VALIOSO"}),
  #"Replaced value 2" = Table.ReplaceValue(#"Se expandió Maestra Valioso1", "VALIOSO", "1", Replacer.ReplaceText, {"Maestra Valioso.VALIOSO"}),
  #"Merged queries 2" = Table.NestedJoin(#"Replaced value 2", {"SKU"}, #"Maestra Flujo WM", {"SKU"}, "Maestra Flujo WM", JoinKind.LeftOuter),
  #"Expanded Maestra Flujo WM" = Table.ExpandTableColumn(#"Merged queries 2", "Maestra Flujo WM", {"LEVANTAMIENTO SALDO PALLET"}, {"LEVANTAMIENTO SALDO PALLET"}),
  #"Renamed columns 1" = Table.RenameColumns(#"Expanded Maestra Flujo WM", {{"LEVANTAMIENTO SALDO PALLET", "Flujo WM"}}),
  #"Replaced value" = Table.ReplaceValue(#"Renamed columns 1", "Camada INV", "1", Replacer.ReplaceText, {"Flujo WM"}),
  #"Replaced value 1" = Table.ReplaceValue(#"Replaced value", null, "0", Replacer.ReplaceValue, {"Flujo WM"}),
  #"Reemplazar ceros" = Table.TransformColumns(#"Replaced value 1", {{"Maestra Valioso.VALIOSO", each if _ = null then "0" else _, type text}}),
  #"Personalizada agregada5" = Table.AddColumn(#"Reemplazar ceros", "Valioso Cencosud", each if Text.Lower([CUSTHIERLEVEL4NAME]) = "l4 cl cencosud" then [Maestra Valioso.VALIOSO] else "0"),
  #"transformacion volumen" = Table.AddColumn(#"Personalizada agregada5", "Order Quantity Vol", each if [#"VolumeUnit(VOLEH)"] = "CDM" then [VolumeOfTheItem]
        else if [#"VolumeUnit(VOLEH)"] = "CCM" then [VolumeOfTheItem] / 1000
        else if [#"VolumeUnit(VOLEH)"] = "M3" then [VolumeOfTheItem] * 1000
        else 0, type number),
  #"Personalizada agregada6" = Table.AddColumn(#"transformacion volumen", "Confirmed Quantity Vol", each [Confirmed Quantity]*([Order Quantity Vol]/[Order Quantity])),
  #"Personalizada agregada7" = Table.AddColumn(#"Personalizada agregada6", "Confirmado Redondeado", each Number.RoundUp([Confirmed Quantity]), Int64.Type),
  #"Renamed columns 3" = Table.RenameColumns(#"Personalizada agregada7", {{"Flujo WM", "Flujo WM1"}}),
  #"Added custom 3" = Table.AddColumn(#"Renamed columns 3", "Flujo WM", each if [Flujo WM1] = "0" then 
    0 
else if Number.Mod([Order Quantity], 1) = 0 then 
    0 
else 
    1),
  #"Removed columns 2" = Table.RemoveColumns(#"Added custom 3", {"Flujo WM1"}),
  #"Changed Type6" = Table.TransformColumnTypes(#"Removed columns 2", {{"Flujo WM", Int64.Type}, {"Valioso Cencosud", Int64.Type}, {"Order Quantity Cj", Int64.Type}, {"Confirmed Quantity Cj", Int64.Type}, {"Superior", type number}, {"Base", type number}, {"Flexible", type number}, {"Apilable si mismo", type number}, {"Falta en Maestra", type number}, {"Confirmed Quantity Kg Net", type number}, {"Confirmed Quantity Kg", type number}, {"Order Quantity Kg Net", type number}}),
  #"Personalizado agregado 2" = Table.AddColumn(#"Changed Type6", "Nivel de Servicio", each if [Order Quantity Cj] = 0 then 0 else try Number.Round([Confirmed Quantity Cj] / [Order Quantity Cj], 3) otherwise null, type number),
  #"Tipo de columna cambiado" = Table.TransformColumnTypes(#"Personalizado agregado 2", {{"Nivel de Servicio", Percentage.Type}}),
  #"Personalizado agregado 3" = Table.AddColumn(#"Tipo de columna cambiado", "Tipo de Flujo", each if 
 [CUSTHIERLEVEL5NAME] = "L5 CL Alvi" and Text.Start([Customer Purchase Order Number],1) = "7" then "CRR"
        else if [CUSTHIERLEVEL4NAME] = "L4 CL SMU" then "INV"
else if [PurchASeOrderNumberSupplement] = null or Text.Trim(Text.From([PurchASeOrderNumberSupplement])) = "" then null
        else if [PurchASeOrderNumberSupplement] = "20" then "INV"
        else if [PurchASeOrderNumberSupplement] = "03" or [PurchASeOrderNumberSupplement] = "33" then "CRR"
        else if [PurchASeOrderNumberSupplement] = "07" then "DSD"
        else null),
  #"Quitar L4" = Table.TransformColumns(#"Personalizado agregado 3", {{"CUSTHIERLEVEL4NAME", each if Value.Is(_, type text) and Text.StartsWith(_, "L4 CL ") then Text.Range(_, 6) else _, type nullable text}}),
  #"Quitar L5" = Table.TransformColumns(#"Quitar L4", {{"CUSTHIERLEVEL5NAME", each if Value.Is(_, type text) and Text.StartsWith(_, "L5 CL ") then Text.Range(_, 6) else _, type nullable text}}),
  #"Quitar L6" = Table.TransformColumns(#"Quitar L5", {{"CUSTHIERLEVEL6NAME", each if Value.Is(_, type text) and Text.StartsWith(_, "L6 CL ") then Text.Range(_, 6) else _, type nullable text}}),
  #"Tipo de columna cambiado 1" = Table.TransformColumnTypes(#"Quitar L6", {{"Confirmed Quantity Vol", type number}, {"Confirmed Quantity Cj", type number}}),

  // Renombrar CD_Temp a CD (ya no necesitamos el segundo join con Solicitante)
  #"Renamed CD" = Table.RenameColumns(#"Tipo de columna cambiado 1", {{"CD_Temp", "CD"}}),

  Find_VU = Table.AddColumn(#"Renamed CD", "Baja VU Disvet", each if Text.Contains(Text.Lower([Customer Purchase Order Number]),"baja") then "1" else "0"),
  Find_Lote = Table.AddColumn(Find_VU, "Lote Dirigido Disvet", each if Text.Contains(Text.Lower([Customer Purchase Order Number]),"lote") then "1" else "0"),
  #"Changed column type 2" = Table.TransformColumnTypes(Find_Lote, {{"Lote Dirigido Disvet", type text}, {"Baja VU Disvet", type text}}),
  #"Renamed columns 2" = Table.RenameColumns(#"Changed column type 2", {{"Sales Document", "N° Pedido"}, {"Plant(OwnOrExternal)", "Ce."}, {"CUSTHIERLEVEL4NAME", "Cliente"}, {"Requested Delivery Date", "Fecha prefer/entrega"}, {"Customer Number Sold To", "Solic."}, {"Customer Purchase Order Number", "Número PO"}, {"Order Quantity", "Pal. Solic."}, {"Confirmed Quantity", "Pal. Conf."}, {"Confirmado Redondeado", "Pal. Conf. Real"}, {"Order Quantity $", "$$ Solic."}, {"Confirmed Quantity $", "$$ Conf."}, {"Order Quantity Kg", "Peso Solic."}, {"Confirmed Quantity Kg", "Peso Conf."}, {"Confirmed Quantity Kg Net", "Peso neto Conf."}, {"Chocolate", "Chocolates"}, {"Order Quantity Vol", "Vol. Solic."}, {"Confirmed Quantity Vol", "Vol. Conf."}, {"Confirmed Quantity Cj", "Cj. Conf."}, {"Order Quantity Cj", "Cj. Solic."}, {"Nivel de Servicio", "%NS"}, {"Tipo de Flujo", "Flujo OC"}}),
  #"Transform columns" = Table.TransformColumnTypes(#"Renamed columns 2", {{"Flujo OC", type text}}),
  #"Replace errors" = Table.ReplaceErrorValues(#"Transform columns", {{"Flujo OC", null}}),
  #"Transform columns 1" = Table.TransformColumnTypes(#"Replace errors", {{"Cj. Solic.", type text}, {"No Apilable", type text}, {"Superior", type text}, {"Base", type text}, {"Flexible", type text}, {"Apilable si mismo", type text}, {"Falta en Maestra", type text}, {"$$ Conf.", type text}, {"Chocolates", type text}, {"Valor Cafe", type text}, {"Peso Conf.", type text}, {"Peso neto Conf.", type text}, {"PDQ", type text}}),
  #"Replace errors 1" = Table.ReplaceErrorValues(#"Transform columns 1", {{"Cj. Solic.", null}, {"No Apilable", null}, {"Superior", null}, {"Base", null}, {"Flexible", null}, {"Apilable si mismo", null}, {"Falta en Maestra", null}, {"$$ Conf.", null}, {"Chocolates", null}, {"Valor Cafe", null}, {"Peso Conf.", null}, {"Peso neto Conf.", null}, {"PDQ", null}}),
  #"Merged queries 4" = Table.NestedJoin(#"Replace errors 1", {"SKU", "Cliente"}, #"Base Toolkit", {"Codigo SAP", "Cliente"}, "Base Toolkit", JoinKind.LeftOuter),
  #"Expanded Base Toolkit" = Table.ExpandTableColumn(#"Merged queries 4", "Base Toolkit", {"CAJA Alto (mm)", "PALLET Alto (mm)", "Base", "Camas"}, {"CAJA Alto (mm)", "PALLET Alto (mm)", "Base.1", "Camas"}),
  #"Added custom 4" = Table.TransformColumnTypes(Table.AddColumn(#"Expanded Base Toolkit", "Altura Picking", each let
                palConf = if [#"Pal. Conf."] = null then 0 else [#"Pal. Conf."],
                cajaAlto = if [#"CAJA Alto (mm)"] = null then 0 else [#"CAJA Alto (mm)"],
                cjConf   = if [#"Cj. Conf."] = null then 0 else [#"Cj. Conf."],
                base1    = if [Base.1] = null then 1 else [Base.1],
                camas    = if [Camas] = null then 1 else [Camas],
                
                safeModPalConf = try Number.Mod(palConf, 1) otherwise 0,
                safeModCj      = try Number.Mod(cjConf, base1 * camas) otherwise 0,

                resultado =
                    if safeModPalConf <> 0 then
                        162 + cajaAlto * Number.RoundUp( safeModCj / base1 , 0)
                    else
                        0
            in
                resultado), {{"Altura Picking", type number}}),
  #"Added custom 5" = Table.AddColumn(#"Added custom 4", "Altura full Pallet", each if ([#"Cj. Conf."] = null or [Base.1] = null or [Camas] = null ) then 0 else if [#"Cj. Conf."] >=  [Base.1]*[Camas]  then [#"PALLET Alto (mm)"] else 0),
  #"Replaced value 4" = Table.ReplaceValue(#"Added custom 5", null, 0, Replacer.ReplaceValue, {"Altura full Pallet", "Altura Picking"}),
  #"Changed column type 1" = Table.TransformColumnTypes(#"Replaced value 4", {{"Altura full Pallet", type number}, {"Altura Picking", type number}}),
  #"Divided column" = Table.TransformColumns(#"Changed column type 1", {{"Altura full Pallet", each if _ = null then 0 else _ / 10, type number}}),
  #"Divided column 1" = Table.TransformColumns(#"Divided column", {{"Altura Picking", each if _ = null then 0 else _ / 10, type number}}),
  Personalizado = Table.AddColumn(#"Divided column 1", "Altura full Pallet Nueva", each 
    let
        palConf = if [#"Pal. Conf."] = null then 0 else [#"Pal. Conf."],
        alturaFull = if [Altura full Pallet] = null then 0 else [Altura full Pallet],
        palletAlto = if [#"PALLET Alto (mm)"] = null then 0 else [#"PALLET Alto (mm)"],
        esEntero = Number.Mod(palConf, 1) = 0 and palConf > 0
    in
        if esEntero and alturaFull = 0 then
            palletAlto / 10
        else
            alturaFull
, type number),
  #"Personalizado 1" = Table.RemoveColumns(#"Personalizado", {"Altura full Pallet"}),
  #"Personalizado 2" = Table.RenameColumns(#"Personalizado 1", {{"Altura full Pallet Nueva", "Altura full Pallet"}}),
  #"Remove columns" = Table.RemoveColumns(#"Personalizado 2", Table.ColumnsOfType(#"Personalizado 2", {type table, type record, type list, type nullable binary, type binary, type function})),
  #"Columnas quitadas" = Table.RemoveColumns(#"Remove columns",{"PurchASeOrderNumberSupplement", "Material Entered", "Order Quantity Kg Net", "NetWeightOfTheItem", "GrossWeightOfTheItem", "WeightUnit(GEWEI)", "VolumeOfTheItem", "VolumeUnit(VOLEH)", "SU", "Customer Number Ship To"}),
  #"Columnas con nombre cambiado 1" = Table.RenameColumns(#"Columnas quitadas", {{"Description", "Descripción"}, {"Sales Organization", "Canal de venta"}}),
  #"Columnas reordenadas" = Table.ReorderColumns(#"Columnas con nombre cambiado 1", {"Canal de venta", "Cliente", "CUSTHIERLEVEL5NAME", "CUSTHIERLEVEL6NAME", "CD", "Solic.", "Flujo OC", "Número PO", "N° Pedido", "SKU", "Descripción", "Maestra SKU.Categoría", "Ce.", "Plant Name", "Fecha prefer/entrega", "DeliveryStatus", "Cj. Solic.", "Cj. Conf.", "Pal. Solic.", "Pal. Conf.", "Pal. Conf. Real", "Peso Solic.", "Peso Conf.", "Peso neto Conf.", "Vol. Solic.", "Vol. Conf.", "Paletizado Nestle", "$$ Solic.", "$$ Conf.", "%NS", "POS", "Apilable Base", "Montado", "Apilable por si mismo", "No Apilable", "Superior", "Base", "Flexible", "Apilable si mismo", "Falta en Maestra", "Chocolates", "Valor Cafe", "PDQ", "Maestra Valioso.VALIOSO", "Valioso Cencosud", "Flujo WM", "Baja VU Disvet", "Lote Dirigido Disvet", "CAJA Alto (mm)", "PALLET Alto (mm)", "Base.1", "Camas", "Altura Picking", "Altura full Pallet"})
in
    #"Columnas reordenadas"