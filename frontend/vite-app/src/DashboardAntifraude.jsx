// DashboardAntifraude.jsx — pestaña "Sistema Antifraude" del Dashboard.
// Formulario para simular la evaluación de una transacción (pantalla de
// pruebas, no un flujo real de transferencia) + historial de
// evaluaciones ya hechas. Se auto-envía sola al completar el formulario.
import { useEffect, useRef, useState } from "react";
import { evaluarTransaccion, historialAntifraude } from "../api";
import { obtenerUbicacion } from "./ubicacion";  // mapa_url ya viene calculado desde el backend, por eso no se usa urlMapa() aquí

const FORM_INICIAL = {
  cliente_id: "",
  monto: "",
  cuenta_destino: "",
  llamada_activa: false,
  tiempo_desde_deposito_minutos: "",
  datos_copiados: false,
};

const DEBOUNCE_AUTO_ENVIO_MS = 900;  // cuánto esperar tras el último campo llenado, antes de auto-enviar (evita enviar a mitad de que el usuario sigue corrigiendo)

export default function DashboardAntifraude() {
  const [data, setData] = useState([]);          // historial de evaluaciones, para la tabla de abajo
  const [form, setForm] = useState(FORM_INICIAL);
  const [enviando, setEnviando] = useState(false);
  const [ubicacion, setUbicacion] = useState(null); // { latitud, longitud } | null
  const yaEnviadoAutoRef = useRef(false);   // evita que el auto-envío dispare dos veces para el mismo conjunto de datos
  const debounceRef = useRef(null);         // ID del setTimeout pendiente, para poder cancelarlo

  const cargarHistorial = () => {
    historialAntifraude().then(setData);
  };

  useEffect(() => {
    cargarHistorial();
    // Se pide una sola vez al entrar a esta pantalla — si el usuario
    // niega el permiso, seguimos sin ubicación (nunca bloquea nada).
    obtenerUbicacion().then(setUbicacion);
  }, []);

  const manejarCambio = (campo, valor) => {
    setForm((prev) => ({ ...prev, [campo]: valor }));
  };

  // Se considera "completo" cuando los 4 campos obligatorios tienen
  // algún valor (las casillas booleanas no cuentan, ya arrancan con un
  // valor válido: false).
  const formCompleto =
    form.cliente_id !== "" && form.monto !== "" && form.cuenta_destino !== "" &&
    form.tiempo_desde_deposito_minutos !== "";

  const evaluar = async () => {
    if (!formCompleto || enviando) return;  // doble chequeo de seguridad, por si se llama en un momento inválido

    setEnviando(true);
    await evaluarTransaccion({
      cliente_id: parseInt(form.cliente_id, 10),
      monto: parseFloat(form.monto),
      cuenta_destino: form.cuenta_destino,
      llamada_activa: form.llamada_activa,
      tiempo_desde_deposito_minutos: parseFloat(form.tiempo_desde_deposito_minutos),
      datos_copiados: form.datos_copiados,
      latitud: ubicacion?.latitud ?? null,   // si no hay ubicación, se manda null explícitamente
      longitud: ubicacion?.longitud ?? null,
    });

    setEnviando(false);
    setForm(FORM_INICIAL);           // limpia el formulario para la siguiente prueba
    yaEnviadoAutoRef.current = false;
    cargarHistorial();               // refresca la tabla con la evaluación recién hecha
  };

  // Auto-envío: en cuanto todos los campos requeridos están llenos,
  // espera un momento (por si el usuario sigue escribiendo/corrigiendo)
  // y evalúa sola — sin necesitar el botón.
  useEffect(() => {
    if (formCompleto && !enviando && !yaEnviadoAutoRef.current) {
      clearTimeout(debounceRef.current);  // cancela cualquier envío pendiente anterior antes de programar uno nuevo
      debounceRef.current = setTimeout(() => {
        yaEnviadoAutoRef.current = true;
        evaluar();
      }, DEBOUNCE_AUTO_ENVIO_MS);
    }
    // Limpieza: si el componente se desmonta o las dependencias cambian
    // antes de que se cumpla el tiempo de espera, se cancela el envío pendiente.
    return () => clearTimeout(debounceRef.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [formCompleto, form.cliente_id, form.monto, form.cuenta_destino, form.tiempo_desde_deposito_minutos, form.llamada_activa, form.datos_copiados]);

  // Si el usuario presiona el botón "Evaluar manualmente" antes de que
  // se cumpla el tiempo de espera del auto-envío, se cancela ese
  // temporizador pendiente y se evalúa de inmediato (evita un doble envío).
  const manejarSubmitManual = (e) => {
    e.preventDefault();
    clearTimeout(debounceRef.current);
    yaEnviadoAutoRef.current = true;
    evaluar();
  };

  return (
    <div className="dashboard-section">
      <h3>🛡️ Sistema Antifraude — Evaluación de transacciones</h3>

      <form className="mini-form" onSubmit={manejarSubmitManual}>
        <input
          type="number"
          placeholder="ID cliente"
          value={form.cliente_id}
          onChange={(e) => manejarCambio("cliente_id", e.target.value)}
          required
        />
        <input
          type="number"
          step="0.01"
          placeholder="Monto"
          value={form.monto}
          onChange={(e) => manejarCambio("monto", e.target.value)}
          required
        />
        <input
          type="text"
          placeholder="Cuenta destino"
          value={form.cuenta_destino}
          onChange={(e) => manejarCambio("cuenta_destino", e.target.value)}
          required
        />
        <input
          type="number"
          step="0.1"
          placeholder="Min. desde depósito"
          value={form.tiempo_desde_deposito_minutos}
          onChange={(e) => manejarCambio("tiempo_desde_deposito_minutos", e.target.value)}
          required
        />
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={form.llamada_activa}
            onChange={(e) => manejarCambio("llamada_activa", e.target.checked)}
          />
          Llamada activa
        </label>
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={form.datos_copiados}
            onChange={(e) => manejarCambio("datos_copiados", e.target.checked)}
          />
          Datos copiados
        </label>

        {/* Aviso de que el auto-envío está por dispararse */}
        {formCompleto && !enviando && (
          <span className="login-subtitle">Evaluando automáticamente en un momento...</span>
        )}

        <span className="login-subtitle">
          {ubicacion
            ? `📍 Ubicación capturada (${ubicacion.latitud.toFixed(4)}, ${ubicacion.longitud.toFixed(4)})`
            : "📍 Sin ubicación (permiso no concedido o no disponible)"}
        </span>

        {/* Respaldo manual: siempre disponible, además del auto-envío */}
        <button className="button" type="submit" disabled={enviando}>
          {enviando ? "Evaluando..." : "Evaluar manualmente"}
        </button>
      </form>

      {/* Resumen rápido con contadores calculados a partir del historial */}
      <div className="resumen-fila">
        <p><strong>Total evaluadas:</strong> {data.length}</p>
        <p style={{ color: "#4ade80" }}>
          <strong>Aprobadas:</strong> {data.filter((x) => x.status === "APROBADA").length}
        </p>
        <p style={{ color: "#f87171" }}>
          <strong>Rechazadas:</strong> {data.filter((x) => x.status === "RECHAZADA").length}
        </p>
      </div>

      {data.length === 0 ? (
        <p className="dashboard-vacio">Sin transacciones evaluadas todavía.</p>
      ) : (
        <table width="100%">
          <thead>
            <tr>
              <th>Cliente</th>
              <th>Monto</th>
              <th>Cuenta destino</th>
              <th>Estado</th>
              <th>Risk score</th>
              <th>Ubicación</th>
              <th>Fecha</th>
            </tr>
          </thead>
          <tbody>
            {data.map((v, i) => (
              <tr key={i}>
                <td>{v.cliente_id}</td>
                <td>${v.monto}</td>
                <td>{v.cuenta_destino}</td>
                <td className={v.status === "APROBADA" ? "text-ok" : "text-bad"}>
                  {v.status}
                </td>
                <td>{v.risk_score}</td>
                <td>
                  {/* mapa_url ya viene armado (o null) desde el backend — ver _url_mapa en router.py */}
                  {v.mapa_url ? (
                    <a href={v.mapa_url} target="_blank" rel="noreferrer" className="login-link">
                      Ver mapa
                    </a>
                  ) : (
                    "-"
                  )}
                </td>
                <td>{v.fecha ? v.fecha.split(".")[0].replace("T", " ") : "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
