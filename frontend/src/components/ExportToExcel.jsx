import ExcelJS from 'exceljs'
import { saveAs } from 'file-saver'

export async function exportToExcel(resultado, activeOpt, cliente) {
  if (!resultado || !activeOpt) return
  const actuales = resultado[activeOpt]
  const camiones = Array.isArray(actuales.camiones) ? actuales.camiones : []

  const headers = [
    'Unidad', 'CD', 'Solic.', 'Número PO', 'Nº pedido',
    'Fecha preferente de entrega', 'Clasificación OC', 'Ce.',
    'Cant. Sol.', 'CJ Conf.', 'Suma de Sol (Pallet)',
    'Suma de Conf (Pallet)',
    'Suma de  Volumen CONF', 'Suma de Peso bruto conf',
    'Suma de Valor neto CONF', '%NS'
  ]

  const wb = new ExcelJS.Workbook()
  const ws = wb.addWorksheet('Armado')

  camiones.forEach(cam => {

    // ——————————— Helpers ———————————
    const stripNum = (s) => (s || '').toString().replace(/^\d+\s*/, '')
    const uniq = (arr) => [...new Set(arr)]

    // ——————————— CD para comentarios ———————————
    // Si la ruta es multi_cd, incluimos TODOS los CD (sin prefijo numérico).
    let cdName
    if (cam.tipo_ruta === 'multi_cd') {
      let cds = Array.isArray(cam.cd) && cam.cd.length
        ? cam.cd
        : uniq((cam.pedidos || []).map(p => p?.CD).filter(Boolean))

      const cdNames = uniq(cds.map(stripNum)).filter(Boolean)
      cdName = cdNames.join(' - ')
    } else {
      // Caso normal: solo el primer CD
      const cdFull = cam.pedidos?.[0]?.CD || (Array.isArray(cam.cd) ? cam.cd[0] : '') || ''
      cdName = stripNum(cdFull)
    }
    // Composición de metadatos de encabezado
    const solicitarBh = cam.tipo_ruta === 'bh' 
    const tipoCamion = cam.pos_total > 28 ? 'PAQUETERA' : 'RAMPLA DIRECTA'
    const tieneChocolate = cam.chocolates === 'SI'
    const flujoOc = cam.flujo_oc || ''
    const skuValioso = cam.skus_valiosos
    const pdq = cam.pdq


    let comentarios = []

    if (cliente === 'Cencosud') {
      comentarios = [
        cdName,
        solicitarBh ? 'SOLICITAR BH' : '',
        (!solicitarBh) ? tipoCamion : null,
        tieneChocolate ? 'CHOCOLATES' : null,
        skuValioso ? 'VALIOSOS' : null,
        pdq ? 'PDQ' : null
      ]
    }

    else if (cliente === 'Walmart') {
      comentarios = [
        cdName,
        flujoOc,
        solicitarBh ? 'SOLICITAR BH' : '',
        tipoCamion,
        tieneChocolate ? 'CHOCOLATES' : null,
        pdq ? 'PDQ' : null
      ]
    }

    else if (cliente === 'Disvet') {
      comentarios = [
        cdName,
        solicitarBh ? 'BH' : '',
        cam.baja_vu ? 'Baja VU' : null,
        cam.lote_dir ? 'Lote Dirigido' : null,
        tieneChocolate ? 'CHOCOLATES' : null,
      ]
    }

    else {
      comentarios = [
        cdName,
        solicitarBh ? 'SOLICITAR BH' : '',
        tieneChocolate ? 'CHOCOLATES' : null
      ]
    }

    const ceUnicos = [...new Set((cam.pedidos || []).map(p => String(p.CE).padStart(4, '0')))]
    if (ceUnicos.length > 1) {
      const ceFormateados = ceUnicos.map(ce => parseInt(ce, 10))
      comentarios.push(`MR ${ceFormateados.join(' - ')}`)
    }

    comentarios = comentarios.filter(Boolean).join(' - ')


    const regionalCities = ['Chillán', 'Temuco', 'Antofagasta']
    let tipoViaje
    console.log(cliente)
    if (cliente === 'Disvet') {
      tipoViaje = 'Disvet'
    } else {
      tipoViaje = regionalCities.some(city => cdName.includes(city))
        ? 'Bodega Regional'
        : 'Bodega Central'
    }

    const backHaulFlag = cam.tipo_ruta === 'bh' ? 'SI' : 'NO'

    const metaRows = [
      ['COMENTARIOS', comentarios],
      ['TIPO DE VIAJE', tipoViaje],
      ['BACK HAUL', backHaulFlag]
    ]

    metaRows.forEach(rowArr => {
      const row = ws.addRow(rowArr)
      for (let i = 1; i <= 5; i++) {
        row.getCell(i).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFFFFF00' } }
      }
    })

    ws.addRow([])
    const headerRow = ws.addRow(headers)

    headerRow.font = { bold: true }
    for (let i = 1; i <= headers.length; i++) {
      const cell = headerRow.getCell(i)
      cell.border = { top: { style: 'thin' }, left: { style: 'thin' }, bottom: { style: 'thin' }, right: { style: 'thin' } }
    }

    (cam.pedidos || []).forEach(p => {
      const rowValues = [
        cam.numero,
        p.CD,
        p['Solic.'],
        p.PO || p['Número PO'],
        p.PEDIDO,
        p['Fecha preferente de entrega'],
        p.OC,
        parseInt(p.CE, 10),
        Number(p['Cant. Sol.'] || 0),
        Number(p['CJ Conf.'] || 0),
        Number((p['Suma de Sol (Pallet)'] || 0).toFixed(2)),
        p.PALLETS,
        Number((p.VOL || 0).toFixed(0)),
        Number((p.PESO || 0).toFixed(0)),
        p.VALOR || p['Suma de Valor neto CONF'] || 0,
        `${((p['%NS'] || 0) * 100).toFixed(0)}%`
      ]
      const row = ws.addRow(rowValues)
      row.getCell(15).numFmt = '[$$-es-CL]#,##0'
      row.eachCell(cell => {
        cell.border = { top: { style: 'thin' }, left: { style: 'thin' }, bottom: { style: 'thin' }, right: { style: 'thin' } }
      })
    })
    ws.addRow([])
    ws.addRow([])
  })


  const buf = await wb.xlsx.writeBuffer()
  saveAs(new Blob([buf]), `armado_camiones_${activeOpt}.xlsx`)
}