// AdminRevision.jsx — pantalla del panel de admin para revisar a mano
// los casos que el sistema no pudo aprobar ni rechazar automáticamente
// (marcados como REVISION_MANUAL), y decidir si aprobarlos o rechazarlos.
import { useEffect, useState } from "react";
import { obtenerHistorialAdmin, accionarRegistro } from "../api";

// Cuáles estados mostrar por defecto — arranca mostrando solo los
// pendientes de revisión, que es lo que más le interesa al admin.
const FILTROS = [
  { id: "REVISION_MANUAL", label: "Pendientes de revisión" },
  { id: "TODOS", label: "Todos los casos" },
];

export default function AdminRevision() {
  const [verificaciones, setVerificaciones] = useState([]);
  const [cargando, setCargando] = useState(true);
  const [filtro, setFiltro] = useState("REVISION_MANUAL");
  const [procesandoId, setProcesandoId] = useState(null); // evita doble clic mientras se procesa una fila específica

  const cargar = () => {
    setCargando(true);
    obtenerHistorialAdmin().then((data) => {
      setVerificaciones(Array.isArray(data) ? data : []);
      setCargando(false);
    });
  };

  useEffect(() => {
    cargar();
  }, []);

  const decidir = async (id, nuevoEstado) => {
    setProcesandoId(id);
    await accionarRegistro(id, nuevoEstado);
    setProcesandoId(null);
    cargar(); // refresca la lista para que el caso ya no aparezca como pendiente
  };

  const listaFiltrada =
    filtro === "TODOS"
      ? verificaciones
      : verificaciones.filter((v) => v.estado === filtro);

  const cantidadPendientes = verificaciones.filter((v) => v.estado === "REVISION_MANUAL").length;

  return (
    <div>
      <p className="dashboard-subtitle">
        Casos que el sistema no pudo aprobar ni rechazar automáticamente
        — requieren que un humano decida.
      </p>

      <div className="resumen-fila">
        <p style={{ color: cantidadPendientes > 0 ? "#facc15" : "#4ade80" }}>
          <strong>Pendientes de revisión:</strong> {cantidadPendientes}
        </p>
      </div>

      <div className="dashboard-tabs">
        {FILTROS.map((f) => (
          <button
            key={f.id}
            className={`dashboard-tab ${filtro === f.id ? "dashboard-tab-activo" : ""}`}
            onClick={() => setFiltro(f.id)}
          >
            {f.label}
          </button>
        ))}
      </div>

      {cargando ? (
        <p className="dashboard-vacio">Cargando...</p>
      ) : listaFiltrada.length === 0 ? (
        <p className="dashboard-vacio">
          {filtro === "REVISION_MANUAL"
            ? "No hay casos pendientes de revisión. 🎉"
            : "Sin verificaciones registradas todavía."}
        </p>
      ) : (
        <table width="100%">
          <thead>
            <tr>
              <th>Cliente</th>
              <th>Estado</th>
              <th>Score</th>
              <th>Deepfake</th>
              <th>Fecha</th>
              <th>Acción</th>
            </tr>
          </thead>
          <tbody>
            {listaFiltrada.map((v) => (
              <tr key={v.id}>
                <td>{v.clienteNombre}</td>
                <td className={v.estado === "APROBADO" ? "text-ok" : v.estado === "FRAUDE" ? "text-bad" : ""}>
                  {v.estado}
                </td>
                <td>{v.score}</td>
                <td>{v.esDeepfake ? "⚠️" : "OK"}</td>
                <td>{v.fecha ? v.fecha.split(".")[0].replace("T", " ") : "-"}</td>
                <td>
                  {/* Los botones de decisión solo tienen sentido en casos pendientes */}
                  {v.estado === "REVISION_MANUAL" ? (
                    <div style={{ display: "flex", gap: 6 }}>
                      <button
                        className="button"
                        style={{ padding: "6px 12px", fontSize: 13 }}
                        disabled={procesandoId === v.id}
                        onClick={() => decidir(v.id, "APROBADO")}
                      >
                        ✔ Aprobar
                      </button>
                      <button
                        className="button button-danger"
                        style={{ padding: "6px 12px", fontSize: 13 }}
                        disabled={procesandoId === v.id}
                        onClick={() => decidir(v.id, "FRAUDE")}
                      >
                        ✘ Rechazar
                      </button>
                    </div>
                  ) : (
                    <span className="login-subtitle">— ya decidido —</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
