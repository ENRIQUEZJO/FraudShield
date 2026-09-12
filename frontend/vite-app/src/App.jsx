// App.jsx — componente raíz de toda la aplicación. Decide qué pantalla
// mostrar según si hay sesión iniciada o no, y maneja la navegación
// entre las distintas secciones (Perfil, Verificación, Dashboard, Admin).
import { useState } from "react";
import Camera from "./Camera";
import Dashboard from "./Dashboard";
import Login from "./Login";
import Registro from "./Registro";
import Perfil from "./Perfil";
import AdminPanel from "./AdminPanel";
import { cerrarSesion as cerrarSesionApi } from "../api";
import "./styles.css";

export default function App() {
  // Al cargar la página, se revisa si ya había una sesión guardada en
  // localStorage (de una visita anterior) — así el usuario no tiene que
  // volver a loguearse cada vez que recarga la página.
  const [autenticado, setAutenticado] = useState(
    !!localStorage.getItem("access_token")
  );
  const [pantallaAuth, setPantallaAuth] = useState("login"); // "login" | "registro" — cuál de las dos mostrar cuando NO hay sesión
  const [mensajeAuth, setMensajeAuth] = useState("");         // mensaje de confirmación (ej. "cuenta creada con éxito") para mostrar en el login
  const [vista, setVista] = useState("verificacion");         // qué sección del menú lateral está activa
  const [resultado, setResultado] = useState(null);           // último resultado de una verificación facial, para mostrarlo en pantalla
  // Se relee de localStorage en cada render — así, apenas cambie el rol
  // (por ejemplo, justo después de loguearse), el menú "Administración"
  // aparece o desaparece sin necesidad de lógica extra.
  const esAdmin = localStorage.getItem("rol") === "admin";

  const manejarLogout = () => {
    cerrarSesionApi();           // borra la sesión de localStorage
    setAutenticado(false);       // esto hace que se vuelva a mostrar el Login
    setPantallaAuth("login");
    setVista("verificacion");    // resetea a la pantalla por defecto para la próxima sesión
    setResultado(null);
  };

  // Si NO hay sesión iniciada, se muestra Login o Registro (nunca el
  // resto de la app) — esto actúa como el "guardia" de autenticación.
  if (!autenticado) {
    if (pantallaAuth === "registro") {
      return (
        <Registro
          onRegistroOk={() => {
            // Tras registrarse con éxito, se vuelve al login con un
            // mensaje de confirmación (no se loguea automáticamente).
            setMensajeAuth("Cuenta creada con éxito. Ya puedes iniciar sesión.");
            setPantallaAuth("login");
          }}
          onVolverLogin={() => setPantallaAuth("login")}
        />
      );
    }
    return (
      <Login
        onLoginOk={() => setAutenticado(true)}
        onIrARegistro={() => {
          setMensajeAuth("");  // limpia cualquier mensaje viejo antes de ir a la pantalla de registro
          setPantallaAuth("registro");
        }}
        mensaje={mensajeAuth}
      />
    );
  }

  // A partir de aquí, el usuario SÍ está autenticado — se muestra la
  // app completa: menú lateral + contenido de la sección activa.
  return (
    <div className="container">
      {/* SIDEBAR: menú lateral, siempre visible */}
      <div className="sidebar">
        <h2>🛡️ FraudShield</h2>

        <div
          className={`menu-item ${vista === "perfil" ? "menu-item-activo" : ""}`}
          onClick={() => setVista("perfil")}
        >
          Mi Perfil
        </div>

        <div
          className={`menu-item ${vista === "verificacion" ? "menu-item-activo" : ""}`}
          onClick={() => setVista("verificacion")}
        >
          Verificación
        </div>

        <div
          className={`menu-item ${vista === "dashboard" ? "menu-item-activo" : ""}`}
          onClick={() => setVista("dashboard")}
        >
          Dashboard
        </div>

        {/* Este ítem del menú solo aparece si el usuario logueado tiene rol admin */}
        {esAdmin && (
          <div
            className={`menu-item ${vista === "admin" ? "menu-item-activo" : ""}`}
            onClick={() => setVista("admin")}
          >
            Administración
          </div>
        )}
      </div>

      {/* CONTENIDO PRINCIPAL: cambia según qué opción del menú esté seleccionada */}
      <div className="main">
        {vista === "perfil" && <Perfil onLogout={manejarLogout} />}

        {vista === "verificacion" && (
          <>
            {/* Camera hace la captura+verificación automática y llama a
                setResultado() cuando termina */}
            <Camera setResultado={setResultado} />

            {/* Solo se muestra la tarjeta de resultado si ya se hizo al
                menos una verificación en esta sesión */}
            {resultado && (
              <div className="card">
                <h3>Resultado de Verificación</h3>
                <p><b>Estado:</b> {resultado.resultado}</p>
                <p>
                  <b>Coincidencia facial:</b>{" "}
                  {resultado.coincidencia ? "✔ Sí" : "❌ No"}
                </p>
                <p>
                  <b>Deepfake:</b>{" "}
                  {resultado.deepfake ? "⚠️ Detectado" : "No"}
                </p>
                <p><b>Sistema:</b> {resultado.sistema}</p>
              </div>
            )}
          </>
        )}

        {vista === "dashboard" && <Dashboard />}

        {/* Doble chequeo de esAdmin aquí también (además del menú) —
            así, aunque alguien manipule el estado "vista" a mano desde
            la consola del navegador, igual no ve el panel sin ser admin
            (aunque la protección REAL está en el backend, con
            requerir_admin — esto es solo para la experiencia visual). */}
        {vista === "admin" && esAdmin && <AdminPanel />}
      </div>
    </div>
  );
}
