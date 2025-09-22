// TruckCard.jsx
import React, { useState, useRef } from 'react'
import { useDrop, useDrag } from 'react-dnd'
import OrderItem from './OrderItem'

export default function TruckCard({
  camion,
  camionIndex,
  moveTruck,
  selectedPedidos,
  onSelectPedido,
  moveOrders,
  onDelete
}) {
  const [expanded, setExpanded] = useState(false)
  const ref = useRef(null)
  const aprobacionTransporte = camion.valor_total > 120_000_000
  const aprobacionSeguridad = camion.valor_total > 150_000_000
  const aprobacionCafe = camion.valor_cafe > 76_000_000

  const aprobaciones = [
    aprobacionTransporte && { icon: '⚠️', label: 'Requiere aprobación de transporte' },
    aprobacionSeguridad && { icon: '🛡️', label: 'Requiere aprobación de seguridad' },
    aprobacionCafe && { icon: '🚨', label: 'Incluye >$76 M café' }].filter(Boolean)

  const [{ isOver }, drop] = useDrop({
    accept: ['ORDER', 'TRUCK'],
    drop: (item, monitor) => {
      const type = monitor.getItemType()
      if (type === 'ORDER') {
        const pedidos = item.pedidos
        moveOrders(pedidos, { targetTruckId: camion.id })
      } else if (type === 'TRUCK') {
        const fromIndex = item.index
        const toIndex = camionIndex
        if (fromIndex !== toIndex) {
          moveTruck(fromIndex, toIndex)
          item.index = toIndex
        }
      }
    },
    collect: m => ({ isOver: m.isOver() })
  })

  const [{ isDragging }, drag] = useDrag({
    type: 'TRUCK',
    item: { id: camion.id, index: camionIndex },
    collect: monitor => ({ isDragging: monitor.isDragging() })
  })

  drag(drop(ref))

  const vcu = Math.max(camion.vcu_vol, camion.vcu_peso) * 100
  let vcuClass = vcu < 70 ? 't-low' : vcu <= 80 ? 't-mid' : 't-high'

  return (
    <div
      ref={ref}
      className={`truck-card ${expanded ? '' : 'collapsed'} ${isOver ? 'over' : ''} ${isDragging ? 'dragging' : ''} ${vcuClass}`}
    >

      <div className="truck-card__header" onClick={() => setExpanded(exp => !exp)}>
        <h4 className="truck-title">
          Camión #{camion.numero}
          {aprobaciones.length > 0 && (
            <span className="aprobacion-icons">
              {aprobaciones.map((ap, idx) => (
                <span key={idx} className="aprobacion-icon" title={ap.label}>
                  {ap.icon}
                </span>
              ))}
            </span>
          )}
        </h4>
        <button type="button" className="delete-truck-btn" onClick={onDelete}>×</button>
        <div className="truck-stats">
          <p> VCU Vol: {(camion.vcu_vol * 100).toFixed(1)}% | VCU Peso: {(camion.vcu_peso * 100).toFixed(1)}% |
          {camion.flujo_oc && (<> Flujo: {camion.flujo_oc}</>)}
          {!camion.flujo_oc && (<> Ruta: {camion.tipo_ruta}</>)}</p>
          <p>Camión tipo: {camion.tipo_camion} |
          Órdenes: {camion.pedidos.length} |
          Pallets: {(camion.pallets_conf).toFixed(1)} | Valor: ${Math.round(camion.valor_total / 1000000)} M</p>
          Pos: {Number(camion.pos_total || 0).toFixed(1)}
        </div>
      </div>
      {expanded && camion.pedidos.length > 0 && (
        <div className="orders-column">
          {camion.pedidos.map(p => (
            <OrderItem
              key={p.PEDIDO}
              pedido={p}
              selected={selectedPedidos.some(x => x.PEDIDO === p.PEDIDO)}
              selectedPedidos={selectedPedidos}
              onSelect={onSelectPedido}
            />
          ))}
        </div>
      )}

    </div>
  )
}