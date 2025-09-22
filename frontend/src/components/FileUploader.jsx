import React from 'react'
export default function FileUploader({ file, onChange }) {
  return (
    <div className="upload">
      <input type="file" accept=".xlsx,.xls,.xlsm" onChange={e=>onChange(e.target.files[0])} />
    </div>
  )
}
