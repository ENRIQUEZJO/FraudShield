// Login.jsx — formulario de inicio de sesión con email y contraseña.
import { useState } from "react";
import { login } from "../api";

// onLoginOk: función que avisa a App.jsx que ya se inició sesión
// onIrARegistro: cambia la pantalla a Registro
// mensaje: texto opcional a mostrar arriba (ej. "cuenta creada con éxito")
export default function Login({ onLoginOk, onIrARegistro, mensaje }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");       // mensaje de error a mostrar si el login falla
  const [cargando, setCargando] = useState(false); // deshabilita el botón mientras se espera la respuesta del backend

  const manejarSubmit = async (e) => {
    e.preventDefault();  // evita que el navegador recargue la página (comportamiento normal de un <form>)
    setError("");
    setCargando(true);

    const data = await login(email, password);  // llamada real al backend (ver api.js)

    setCargando(false);

    if (data.status === "ok") {
      onLoginOk();  // avisa al padre (App.jsx) que ya puede mostrar el resto de la app
    } else {
      setError(data.message || "Credenciales inválidas");
    }
  };

  return (
    <div className="login-screen">
      <form className="card login-card" onSubmit={manejarSubmit}>
        <h2>🔐 FraudShield</h2>
        <p className="login-subtitle">Inicia sesión para continuar</p>

        {/* Solo se muestra si el padre pasó un mensaje (ej. tras registrarse) */}
        {mensaje && <p className="text-ok">{mensaje}</p>}

        <label>Email</label>
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
        />

        <label>Contraseña</label>
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />

        {/* Solo se muestra si hubo un error en el último intento de login */}
        {error && <p className="login-error">{error}</p>}

        <button className="button" type="submit" disabled={cargando}>
          {cargando ? "Ingresando..." : "Iniciar sesión"}
        </button>

        <p className="login-subtitle" style={{ textAlign: "center" }}>
          ¿No tienes cuenta?{" "}
          <span className="login-link" onClick={onIrARegistro}>
            Crear cuenta
          </span>
        </p>
      </form>
    </div>
  );
}
