import React, { useState, useEffect } from 'react'
import TruckCard from './TruckCard'
import OrderItem from './OrderItem'
import { useDrop } from 'react-dnd'

export default function TruckGroup({
  cd,
  ce = [],
  camiones = [],
  unassigned = [],
  selectedPedidos,
  onSelectPedido,
  moveOrders,
  onAddTruck,
  onDeleteTruck,
  ruta
}) {
  const [localTrucks, setLocalTrucks] = useState([])

  useEffect(() => {
    setLocalTrucks(camiones)
  }, [camiones])


  const moveTruck = (fromIndex, toIndex) => {
    setLocalTrucks(prev => {
      const updated = [...prev]
      const [moved] = updated.splice(fromIndex, 1)
      updated.splice(toIndex, 0, moved)
      return updated
    })
  }


  const [{ isOverUnassigned }, dropUnassigned] = useDrop({
    accept: 'ORDER',
    drop: item => moveOrders(item.pedidos, { targetTruckId: null }),
    collect: m => ({ isOverUnassigned: m.isOver() })
  })



  const [{ isOver: isOverTrucks }, dropTrucks] = useDrop({
    accept: 'TRUCK',
    drop: () => { },
    collect: monitor => ({ isOver: monitor.isOver() })
  });


  return (
    <div className="truck-group">
      <div className="truck-group-header">
        <button type="button" onClick={() => onAddTruck(cd, ce, ruta)} className="add-truck-btn">
          + Nuevo Camión
        </button>
      </div>

      <div className="truck-list-horizontal" ref={dropTrucks}>
        {localTrucks.map((camion, i) => (
          <TruckCard
            key={camion.id}
            camion={camion}
            camionIndex={i}
            moveTruck={moveTruck}
            selectedPedidos={selectedPedidos}
            onSelectPedido={onSelectPedido}
            moveOrders={moveOrders}
            onDelete={() => onDeleteTruck(camion.id)}
          />
        ))}
      </div>

      <div
        ref={dropUnassigned}
        className={`unassigned-column ${isOverUnassigned ? 'over' : ''}`}
      >
        <h4>Pedidos no asignados - {cd}</h4>
        <div className="unassigned-orders-grid">
          {unassigned.map(p => (
            <OrderItem
              key={p.PEDIDO}
              pedido={p}
              selected={selectedPedidos.some(x => x.PEDIDO === p.PEDIDO)}
              selectedPedidos={selectedPedidos}
              onSelect={onSelectPedido}
            />
          ))}
        </div>
      </div>


    </div>
  );

}
