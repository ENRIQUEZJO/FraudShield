// AdminPanel.jsx — contenedor con pestañas del panel de administración
// (solo visible para usuarios con rol admin, ver App.jsx). Coordina 5
// sub-pantallas: lista de usuarios, lista de empresas, alta de un
// usuario nuevo (reutilizando el mismo componente Registro.jsx del
// registro público, pero en "modoAdmin"), revisión manual de casos
// pendientes, y generación de API keys para integraciones externas.
import { useEffect, useState } from "react";
import AdminUsuarios from "./AdminUsuarios";
import AdminEmpresas from "./AdminEmpresas";
import AdminRevision from "./AdminRevision";
import AdminApiKeys from "./AdminApiKeys";
import Registro from "./Registro";
import { adminListarEmpresas } from "../api";

const TABS = [
  { id: "usuarios", label: "Usuarios" },
  { id: "empresas", label: "Empresas" },
  { id: "registrar", label: "Registrar usuario" },
  { id: "revision", label: "Revisar verificaciones" },
  { id: "apikeys", label: "API Keys" },
];

export default function AdminPanel() {
  const [tab, setTab] = useState("usuarios");
  const [empresas, setEmpresas] = useState([]);       // lista de empresas, para pasársela al selector dentro de Registro
  const [recargarSenal, setRecargarSenal] = useState(0); // truco para forzar que AdminUsuarios recargue su lista (ver más abajo)

  const cargarEmpresas = () => {
    adminListarEmpresas().then((e) => setEmpresas(Array.isArray(e) ? e : []));
  };

  useEffect(() => {
    cargarEmpresas();
  }, []);

  // Cuando se registra un usuario nuevo desde este panel, se vuelve a
  // la pestaña de "Usuarios" y se le avisa a AdminUsuarios que debe
  // recargar su lista (incrementar recargarSenal cambia una prop que
  // ese componente usa como dependencia de un useEffect — es una forma
  // común en React de decir "algo cambió en otro lado, refréscate").
  const alRegistrarOk = () => {
    setTab("usuarios");
    setRecargarSenal((n) => n + 1); // fuerza a AdminUsuarios a recargar la lista
  };

  return (
    <div className="card">
      <h2 style={{ marginTop: 0 }}>Panel de Administración</h2>
      <p className="dashboard-subtitle">
        Usuarios registrados, empresas/grupos, alta de nuevos usuarios,
        revisión manual, e integraciones externas.
      </p>

      <div className="dashboard-tabs">
        {TABS.map((t) => (
          <button
            key={t.id}
            className={`dashboard-tab ${tab === t.id ? "dashboard-tab-activo" : ""}`}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "usuarios" && <AdminUsuarios recargarSenal={recargarSenal} />}
      {tab === "empresas" && <AdminEmpresas onCambio={cargarEmpresas} />}
      {tab === "registrar" && (
        // modoAdmin=true hace que Registro.jsx muestre el selector de
        // empresa y no muestre el enlace "¿Ya tienes cuenta?".
        <Registro modoAdmin={true} empresas={empresas} onRegistroOk={alRegistrarOk} />
      )}
      {tab === "revision" && <AdminRevision />}
      {tab === "apikeys" && <AdminApiKeys />}
    </div>
  );
}
