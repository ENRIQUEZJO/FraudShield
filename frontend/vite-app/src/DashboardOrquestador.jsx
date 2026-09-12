// DashboardOrquestador.jsx — pestaña "Orquestador" del Dashboard: el
// flujo más completo de prueba, combina captura facial automática +
// datos de una transacción, y llama al endpoint que evalúa AMBAS cosas
// juntas (identidad + riesgo) en un solo veredicto.
import { useEffect, useRef, useState } from "react";
import { procesarTransferencia, historialOrquestador } from "../api";
import { useDeteccionGestoFacial } from "./useDeteccionGestoFacial";
import { obtenerUbicacion } from "./ubicacion";

const FORM_INICIAL = {
  monto: "",
  cuenta_destino: "",
  llamada_activa: false,
  tiempo_desde_deposito_minutos: "",
  datos_copiados: false,
};

const DEBOUNCE_AUTO_ENVIO_MS = 900;  // espera tras completar todo, antes de auto-procesar

export default function DashboardOrquestador() {
  const [data, setData] = useState([]);              // historial de transferencias procesadas
  const [form, setForm] = useState(FORM_INICIAL);
  const [frame, setFrame] = useState(null);            // la foto ya capturada (o null si aún no se ha tomado)
  const [enviando, setEnviando] = useState(false);
  const [ultimoResultado, setUltimoResultado] = useState(null);  // el veredicto de la última transferencia procesada, para mostrarlo destacado
  const [ubicacion, setUbicacion] = useState(null);    // { latitud, longitud } | null
  const videoRef = useRef(null);
  const [camaraLista, setCamaraLista] = useState(false);
  const yaEnviadoAutoRef = useRef(false);
  const debounceRef = useRef(null);

  const cargarHistorial = () => {
    historialOrquestador().then(setData);
  };

  // Se ejecuta una sola vez al montar: carga el historial y pide ubicación.
  useEffect(() => {
    cargarHistorial();
    obtenerUbicacion().then(setUbicacion);
  }, []);

  // Efecto separado para la cámara (se mantiene aparte por claridad —
  // son dos responsabilidades distintas, aunque ambas corran "al montar").
  useEffect(() => {
    navigator.mediaDevices.getUserMedia({ video: true }).then((stream) => {
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        videoRef.current.onloadedmetadata = () => setCamaraLista(true);
      }
    });
  }, []);

  const capturarFoto = () => {
    const canvas = document.createElement("canvas");
    canvas.width = 640;
    canvas.height = 480;
    canvas.getContext("2d").drawImage(videoRef.current, 0, 0, 640, 480);
    setFrame(canvas.toDataURL("image/jpeg"));
  };

  // Detección automática de rostro centrado — igual que en Camera.jsx.
  // Se desactiva sola en cuanto ya hay una foto capturada (!frame se
  // vuelve false), así no sigue analizando video innecesariamente.
  const { cargandoModelo, errorModelo, progreso } = useDeteccionGestoFacial({
    videoRef,
    gestoObjetivo: "centro",
    activo: camaraLista && !frame && !enviando,
    onGestoDetectado: capturarFoto,
  });

  const manejarCambio = (campo, valor) => {
    setForm((prev) => ({ ...prev, [campo]: valor }));
  };

  const formCompleto =
    form.monto !== "" && form.cuenta_destino !== "" && form.tiempo_desde_deposito_minutos !== "";

  const procesar = async () => {
    if (!frame || !formCompleto || enviando) return;  // no se puede procesar sin foto Y datos completos

    setEnviando(true);
    const userId = localStorage.getItem("user_id");  // el backend valida que este ID coincida con el del token (ver shared/orquestador.py)
    const resultado = await procesarTransferencia({
      frame,
      user_id: parseInt(userId, 10),
      monto: parseFloat(form.monto),
      cuenta_destino: form.cuenta_destino,
      llamada_activa: form.llamada_activa,
      tiempo_desde_deposito_minutos: parseFloat(form.tiempo_desde_deposito_minutos),
      datos_copiados: form.datos_copiados,
      latitud: ubicacion?.latitud ?? null,
      longitud: ubicacion?.longitud ?? null,
    });

    setUltimoResultado(resultado);   // se muestra en la tarjeta destacada de arriba
    setEnviando(false);
    setForm(FORM_INICIAL);
    setFrame(null);                  // se borra la foto también, para forzar una nueva captura en el siguiente intento
    yaEnviadoAutoRef.current = false;
    cargarHistorial();
  };

  // Auto-envío: en cuanto hay foto Y los campos requeridos están
  // llenos, espera un momento (por si el usuario sigue escribiendo) y
  // procesa solo — sin necesitar el botón. yaEnviadoAutoRef evita
  // disparar dos veces para el mismo conjunto de datos.
  useEffect(() => {
    if (frame && formCompleto && !enviando && !yaEnviadoAutoRef.current) {
      clearTimeout(debounceRef.current);
      debounceRef.current = setTimeout(() => {
        yaEnviadoAutoRef.current = true;
        procesar();
      }, DEBOUNCE_AUTO_ENVIO_MS);
    }
    return () => clearTimeout(debounceRef.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [frame, formCompleto, form.monto, form.cuenta_destino, form.tiempo_desde_deposito_minutos, form.llamada_activa, form.datos_copiados]);

  const manejarSubmitManual = (e) => {
    e.preventDefault();
    if (!frame) {
      alert("Espera a que se capture la foto (o captúrala manualmente) antes de procesar.");
      return;
    }
    clearTimeout(debounceRef.current);
    yaEnviadoAutoRef.current = true;
    procesar();
  };

  return (
    <div className="dashboard-section">
      <h3>🧩 Orquestador — Identidad + riesgo en un solo flujo</h3>

      <form className="mini-form" onSubmit={manejarSubmitManual}>
        <div className="camara-deteccion-wrap">
          <video ref={videoRef} autoPlay muted width="220" />
          {/* Barra de progreso solo mientras no hay foto capturada todavía */}
          {!errorModelo && !frame && (
            <div className="barra-progreso-gesto">
              <div className="barra-progreso-gesto-relleno" style={{ width: `${progreso * 100}%` }} />
            </div>
          )}
          {frame && <span className="text-ok">✔ Foto capturada</span>}
          {!frame && !errorModelo && !cargandoModelo && (
            <span className="login-subtitle">Mira a la cámara — se captura sola</span>
          )}
          {errorModelo && <span className="login-error">{errorModelo}</span>}
        </div>

        {/* Solo aparece una vez que ya hay foto, por si salió mal y quieres repetirla */}
        {frame && (
          <button type="button" className="button" onClick={capturarFoto}>
            Volver a capturar
          </button>
        )}

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

        {/* Aviso de que el auto-envío está por dispararse (solo si ya hay foto Y formulario completo) */}
        {frame && formCompleto && !enviando && (
          <span className="login-subtitle">Procesando automáticamente en un momento...</span>
        )}

        <span className="login-subtitle">
          {ubicacion
            ? `📍 Ubicación capturada (${ubicacion.latitud.toFixed(4)}, ${ubicacion.longitud.toFixed(4)})`
            : "📍 Sin ubicación (permiso no concedido o no disponible)"}
        </span>

        {/* Respaldo manual: siempre disponible, además del auto-envío */}
        <button className="button" type="submit" disabled={enviando}>
          {enviando ? "Procesando..." : "Procesar manualmente"}
        </button>
      </form>

      {/* Tarjeta destacada con el resultado del último procesamiento, verde/roja según el veredicto */}
      {ultimoResultado && (
        <div className={`resultado-box ${ultimoResultado.veredicto === "APROBADA" ? "resultado-ok" : "resultado-bad"}`}>
          <b>Veredicto:</b> {ultimoResultado.veredicto} — {ultimoResultado.motivo_principal}
        </div>
      )}

      {/* Resumen rápido con contadores calculados a partir del historial */}
      <div className="resumen-fila">
        <p><strong>Total procesadas:</strong> {data.length}</p>
        <p style={{ color: "#4ade80" }}>
          <strong>Aprobadas:</strong> {data.filter((x) => x.veredicto === "APROBADA").length}
        </p>
        <p style={{ color: "#f87171" }}>
          <strong>Rechazadas:</strong> {data.filter((x) => x.veredicto === "RECHAZADA").length}
        </p>
      </div>

      {data.length === 0 ? (
        <p className="dashboard-vacio">Sin transferencias procesadas todavía.</p>
      ) : (
        <table width="100%">
          <thead>
            <tr>
              <th>Usuario</th>
              <th>Monto</th>
              <th>Cuenta destino</th>
              <th>Veredicto</th>
              <th>Motivo</th>
              <th>Ubicación</th>
              <th>Fecha</th>
            </tr>
          </thead>
          <tbody>
            {data.map((v, i) => (
              <tr key={i}>
                <td>{v.user_id}</td>
                <td>${v.monto}</td>
                <td>{v.cuenta_destino}</td>
                <td className={v.veredicto === "APROBADA" ? "text-ok" : "text-bad"}>
                  {v.veredicto}
                </td>
                <td>{v.motivo_principal}</td>
                <td>
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
