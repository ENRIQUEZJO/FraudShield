// main.jsx — punto de entrada del frontend. Vite carga este archivo
// primero (referenciado desde index.html) y desde aquí se monta toda
// la aplicación React dentro del <div id="root"> del HTML.
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './styles.css'   // estilos globales de toda la app
import App from './App.jsx'  // el componente raíz, que decide qué mostrar (login, dashboard, etc.)

// createRoot conecta React con el <div id="root"> real del HTML.
// <StrictMode> es una ayuda de desarrollo: hace que React ejecute
// ciertas partes del código dos veces a propósito, para detectar
// efectos secundarios mal escritos — no afecta la versión final que
// verá el usuario (solo corre así durante el desarrollo).
createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)