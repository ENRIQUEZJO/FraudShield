// Perfil.jsx — muestra los datos del usuario logueado (guardados en
// localStorage desde el login) y el botón de cerrar sesión.
export default function Perfil({ onLogout }) {
  // Todos estos datos ya se guardaron en localStorage al hacer login
  // (ver api.js::login) — aquí solo se leen, no se piden de nuevo al backend.
  const nombre = localStorage.getItem("nombre") || "Usuario";
  const email = localStorage.getItem("email") || "-";
  const rol = localStorage.getItem("rol") || "user";
  const userId = localStorage.getItem("user_id") || "-";

  return (
    <div className="card perfil-card">
      <div className="perfil-header">
        {/* Avatar simple: círculo con la primera letra del nombre en mayúscula */}
        <div className="perfil-avatar">{nombre.charAt(0).toUpperCase()}</div>
        <div>
          <h3 style={{ margin: 0 }}>{nombre}</h3>
          <span className="badge-rol">{rol}</span>
        </div>
        <button className="button button-danger" onClick={onLogout}>
          Cerrar sesión
        </button>
      </div>
      <div className="perfil-detalle">
        <p><b>ID de usuario:</b> {userId}</p>
        <p><b>Email:</b> {email}</p>
      </div>
    </div>
  );
}
