import React, { useState } from 'react'
import { useDrag } from 'react-dnd'
import { FiCopy, FiCheck } from 'react-icons/fi'

export default function OrderItem({ pedido, selected, onSelect, selectedPedidos }) {
    const [copied, setCopied] = useState(false)
    const dragItem = selected ? selectedPedidos : [pedido]
    const [{ isDragging }, drag] = useDrag({
        type: 'ORDER',
        item: { pedidos: dragItem },
        collect: monitor => ({ isDragging: monitor.isDragging() })
    })

    const copyToClipboard = () => {
        navigator.clipboard.writeText(pedido.PEDIDO)
            .then(() => {
                setCopied(true)
                setTimeout(() => setCopied(false), 1500)
            })
            .catch(() => alert('Error al copiar'))
    }

    return (
        <div
            ref={drag}
            className={`order-item ${selected ? 'selected' : ''}`}
            onClick={e => e.ctrlKey && onSelect(pedido)}
            style={{ opacity: isDragging ? 0.5 : 1 }}
        >
            <div className="order-header">
                <strong>#{pedido.PEDIDO} </strong>

                <button
                    onClick={e => { e.stopPropagation(); copyToClipboard() }}
                    className="clipboard"
                    title={copied ? 'Copiado ✓' : 'Copiar pedido'}
                >
                    {copied
                        ? <FiCheck size={14} />
                        : <FiCopy size={14} />
                    }
                </button>

            </div>
            <p className='order-text'>
                Vol: {(pedido.VCU_VOL * 100).toFixed(1)}% |
                Pes: {(pedido.VCU_PESO * 100).toFixed(1)}% |
                Pall: {pedido.PALLETS.toFixed(1)} |
                Valor: CLP ${(pedido.VALOR / 1000000).toFixed(1)} M |
                {pedido.OC && <> Flujo: {pedido.OC}</>}
            </p>
        </div>
    )
}