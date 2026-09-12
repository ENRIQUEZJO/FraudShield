// DashboardBiometria.jsx — pestaña "VisionSegura" del Dashboard: lista
// el historial de verificaciones de identidad del usuario logueado.
import { useEffect, useState } from "react";
import { obtenerVerificaciones } from "../api";

export default function DashboardBiometria() {
  const [data, setData] = useState([]);  // lista de verificaciones, viene del backend

  // Al montar el componente, se pide el historial UNA vez.
  useEffect(() => {
    const userId = localStorage.getItem("user_id");
    obtenerVerificaciones(userId).then(setData);
  }, []);

  return (
    <div className="dashboard-section">
      <h3>🔐 VisionSegura — Verificaciones de identidad</h3>

      {/* Resumen rápido con contadores calculados a partir de la lista completa */}
      <div className="resumen-fila">
        <p><strong>Total:</strong> {data.length}</p>
        <p style={{ color: "#4ade80" }}>
          <strong>Aprobadas:</strong> {data.filter((x) => x.resultado === "APROBADO").length}
        </p>
        <p style={{ color: "#f87171" }}>
          <strong>Fraude/Deepfake:</strong> {data.filter((x) => x.resultado === "FRAUDE").length}
        </p>
      </div>

      {/* Si no hay datos, se muestra un mensaje en vez de una tabla vacía */}
      {data.length === 0 ? (
        <p className="dashboard-vacio">Sin verificaciones registradas todavía.</p>
      ) : (
        <table width="100%">
          <thead>
            <tr>
              <th>ID</th>
              <th>Resultado</th>
              <th>Coincidencia</th>
              <th>Deepfake</th>
              <th>Fecha</th>
            </tr>
          </thead>
          <tbody>
            {data.map((v, i) => (
              <tr key={i}>
                <td>{v.id}</td>
                {/* Verde si aprobado, rojo en cualquier otro caso (FRAUDE o REVISION_MANUAL) */}
                <td className={v.resultado === "APROBADO" ? "text-ok" : "text-bad"}>
                  {v.resultado}
                </td>
                <td style={{ textAlign: "center" }}>
                  {/* SQL Server puede devolver el booleano como 1/0 o true/false según el driver — se manejan ambos casos */}
                  {v.coincidencia === 1 || v.coincidencia === true ? "✅" : "❌"}
                </td>
                <td>{v.esDeepfake ? "⚠️" : "OK"}</td>
                {/* La fecha viene como texto ISO (ej. "2026-01-15T10:30:00.123") — se recorta a "2026-01-15 10:30:00" para que se lea mejor */}
                <td>{v.fecha ? v.fecha.split(".")[0].replace("T", " ") : "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
