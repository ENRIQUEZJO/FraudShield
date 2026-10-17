// Dashboard.jsx — contenedor con pestañas para las 3 vistas de datos:
// VisionSegura (biometría), Sistema Antifraude, y Orquestador. Cada
// pestaña es un componente separado (ver los 3 imports de abajo).
import { useState } from "react";
import DashboardBiometria from "./DashboardBiometria";
import DashboardAntifraude from "./DashboardAntifraude";
import DashboardOrquestador from "./DashboardOrquestador";

// Lista de pestañas: id (para comparar cuál está activa) + label (texto visible)
const TABS = [
  { id: "biometria", label: "VisionSegura" },
  { id: "antifraude", label: "Sistema Antifraude" },
  { id: "orquestador", label: "Orquestador" },
];

export default function Dashboard() {
  const [tab, setTab] = useState("biometria");  // cuál pestaña está seleccionada actualmente

  return (
    <div className="card">
      <h2 style={{ marginTop: 0 }}>Dashboard FraudShield</h2>
      <p className="dashboard-subtitle">
        Información combinada de los 3 módulos del sistema.
      </p>

      {/* Botones de pestañas, generados a partir de la lista TABS */}
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

      {/* Solo se renderiza (y se monta/ejecuta) el componente de la
          pestaña activa — las otras dos ni siquiera existen en el DOM
          mientras no estén seleccionadas. */}
      {tab === "biometria" && <DashboardBiometria />}
      {tab === "antifraude" && <DashboardAntifraude />}
      {tab === "orquestador" && <DashboardOrquestador />}
    </div>
  );
}
