import React from 'react'
import logo from '../assets/logo.png' // Ajusta la ruta según tu estructura

export default function Header() {
  return (
    <header className="header">
      <div className="header-content">
        <img src={logo} alt="Logo OptiLoad" className="header-logo" />
        <div>
        </div>
      </div>
    </header>
  )
}
