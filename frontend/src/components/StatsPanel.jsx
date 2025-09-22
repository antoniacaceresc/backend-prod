import React from 'react'

export default function StatsPanel({ mode, title, stats, active, onClick }) {

    const pct = ((stats?.promedio_vcu || 0) * 100).toFixed(1)
    const mainColor = pct > 0 ? '#4caf50' : '#ccc';

    const normalPct = ((stats?.promedio_vcu_normal || 0) * 100).toFixed(1)
    const bhPct = ((stats?.promedio_vcu_bh || 0) * 100).toFixed(1)

    return (
    <div
      className={`stats-panel ${active ? 'active' : ''}`}
      onClick={onClick}
    >
      <h3>{title}</h3>
      <div className="donut" style={{ '--pct': pct, '--main': mainColor }}>
        <span className="donut-text">{pct}%</span>
        <span className="donut-subtext">VCU</span>
      </div>
      <ul className="stats-list">
        <li>{stats?.cantidad_camiones} Camiones</li>
        <li>{stats?.cantidad_pedidos_asignados}/{stats?.total_pedidos} Pedidos asignados</li>
        <li>CLP ${(stats?.valorizado / 1000000).toFixed(1)}M</li>
      </ul>
      <div className="stats-bottom-row">
        <div className="stats-col">
          <h5>Normal</h5>
          <div className="donut small" style={{ '--pct': normalPct, '--main': mainColor }}>
            <span className="donut-text small">{normalPct}%</span>
        <span className="donut-subtext-small">VCU</span>
          </div>
          <div className="label">{stats?.cantidad_camiones_normal} camiones</div>
        </div>
  
        <div className="stats-col">
          <h5>BH</h5>
          <div className="donut small" style={{ '--pct': bhPct, '--main': mainColor }}>
            <span className="donut-text small">{bhPct}%</span>
        <span className="donut-subtext-small">VCU</span>
          </div>
          <div className="label">{stats?.cantidad_camiones_bh} camiones</div>
        </div>
      </div>
    </div>
  )
}
