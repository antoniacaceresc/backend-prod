import React from 'react'
export default function ClientSelector({ label, options, value, onChange }) {
  return (
    <div className="selector">
      
      <label>{label}</label>
      <select value={value} onChange={e => onChange(e.target.value)}>
        <option value="">-- Seleccionar --</option>
        {options.map(opt => <option key={opt} value={opt}>{opt}</option>)}
      </select>
    </div>
  )
}