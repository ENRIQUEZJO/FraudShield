// AdminApiKeys.jsx — pantalla del panel de admin para generar y
// gestionar API keys: credenciales que un banco/institución afiliada
// usa para que SUS sistemas llamen a FraudShield directamente (por
// ejemplo, para evaluar el riesgo de una transacción), sin pasar por
// el login de un usuario humano.
import { useEffect, useState } from "react";
import {
  adminListarApiKeys,
  adminCrearApiKey,
  adminRevocarApiKey,
  adminCambiarLimiteApiKey,
  adminListarEmpresas,
} from "../api";

export default function AdminApiKeys() {
  const [keys, setKeys] = useState([]);
  const [empresas, setEmpresas] = useState([]);
  const [nombreNueva, setNombreNueva] = useState("");
  const [empresaIdNueva, setEmpresaIdNueva] = useState("");
  const [limiteRpsNueva, setLimiteRpsNueva] = useState("10");
  const [creando, setCreando] = useState(false);
  const [error, setError] = useState("");
  // La key recién creada, en texto plano — SOLO existe en este estado
  // temporal del navegador; una vez que el admin recarga o navega a
  // otro lado, se pierde para siempre (el backend nunca la vuelve a mostrar).
  const [keyRecienCreada, setKeyRecienCreada] = useState(null);
  const [copiado, setCopiado] = useState(false);
  // Edición en línea del límite de cada key ya existente
  const [editandoLimiteId, setEditandoLimiteId] = useState(null);
  const [limiteEditado, setLimiteEditado] = useState("");

  const cargar = () => {
    Promise.all([adminListarApiKeys(), adminListarEmpresas()]).then(([k, e]) => {
      setKeys(Array.isArray(k) ? k : []);
      setEmpresas(Array.isArray(e) ? e : []);
    });
  };

  useEffect(() => {
    cargar();
  }, []);

  const crear = async (e) => {
    e.preventDefault();
    if (!nombreNueva.trim()) return;

    setCreando(true);
    setError("");
    setKeyRecienCreada(null);
    setCopiado(false);

    const empresaId = empresaIdNueva ? parseInt(empresaIdNueva, 10) : null;
    const limiteRps = parseInt(limiteRpsNueva, 10) || 10;
    const res = await adminCrearApiKey(nombreNueva.trim(), empresaId, limiteRps);
    setCreando(false);

    if (res.status === "ok") {
      setKeyRecienCreada(res.api_key); // se muestra en el recuadro de advertencia de abajo
      setNombreNueva("");
      setEmpresaIdNueva("");
      setLimiteRpsNueva("10");
      cargar();
    } else {
      setError(res.message || "No se pudo crear la API key");
    }
  };

  const copiarKey = () => {
    navigator.clipboard.writeText(keyRecienCreada);
    setCopiado(true);
  };

  const revocar = async (id) => {
    await adminRevocarApiKey(id);
    cargar();
  };

  const empezarEdicionLimite = (k) => {
    setEditandoLimiteId(k.id);
    setLimiteEditado(String(k.limiteRps));
  };

  const guardarLimite = async (id) => {
    const nuevoLimite = parseInt(limiteEditado, 10);
    if (!nuevoLimite || nuevoLimite <= 0) return;
    await adminCambiarLimiteApiKey(id, nuevoLimite);
    setEditandoLimiteId(null);
    cargar();
  };

  return (
    <div>
      <p className="dashboard-subtitle">
        Credenciales para que sistemas externos (de un banco o
        institución afiliada) llamen a FraudShield directamente, sin
        pasar por el login de un usuario. Cada institución tiene su
        propia cuota de peticiones por segundo, para que ninguna
        integración pueda saturar el sistema a costa de las demás.
      </p>

      <form className="mini-form" onSubmit={crear}>
        <input
          type="text"
          placeholder='Nombre (ej. "App móvil Banco Popular")'
          value={nombreNueva}
          onChange={(e) => setNombreNueva(e.target.value)}
        />
        <select value={empresaIdNueva} onChange={(e) => setEmpresaIdNueva(e.target.value)}>
          <option value="">Sin empresa asociada</option>
          {empresas.map((emp) => (
            <option key={emp.empresaId} value={emp.empresaId}>
              {emp.nombre}
            </option>
          ))}
        </select>
        <input
          type="number"
          min="1"
          placeholder="Límite peticiones/seg"
          value={limiteRpsNueva}
          onChange={(e) => setLimiteRpsNueva(e.target.value)}
          style={{ width: 160 }}
        />
        <button className="button" type="submit" disabled={creando}>
          {creando ? "Generando..." : "Generar API key"}
        </button>
      </form>

      {error && <p className="login-error">{error}</p>}

      {/* Recuadro de advertencia con la key en texto plano — SOLO aparece
          justo después de crearla, nunca más se puede volver a ver. */}
      {keyRecienCreada && (
        <div className="resultado-box resultado-ok" style={{ marginTop: 10 }}>
          <p style={{ margin: "0 0 8px 0" }}>
            <strong>⚠️ Copia esta key ahora — no se volverá a mostrar:</strong>
          </p>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <code style={{ background: "#0f172a", padding: "6px 10px", borderRadius: 6, wordBreak: "break-all" }}>
              {keyRecienCreada}
            </code>
            <button type="button" className="button" style={{ padding: "6px 12px", fontSize: 13 }} onClick={copiarKey}>
              {copiado ? "✔ Copiada" : "Copiar"}
            </button>
          </div>
        </div>
      )}

      {keys.length === 0 ? (
        <p className="dashboard-vacio">Sin API keys generadas todavía.</p>
      ) : (
        <table width="100%">
          <thead>
            <tr>
              <th>Nombre</th>
              <th>Empresa</th>
              <th>Estado</th>
              <th>Límite (peticiones/seg)</th>
              <th>Creada</th>
              <th>Último uso</th>
              <th>Acción</th>
            </tr>
          </thead>
          <tbody>
            {keys.map((k) => (
              <tr key={k.id}>
                <td>{k.nombre}</td>
                <td>{k.empresaNombre || "-"}</td>
                <td className={k.activa ? "text-ok" : "text-bad"}>{k.activa ? "Activa" : "Revocada"}</td>
                <td>
                  {editandoLimiteId === k.id ? (
                    <div style={{ display: "flex", gap: 4 }}>
                      <input
                        type="number"
                        min="1"
                        value={limiteEditado}
                        onChange={(e) => setLimiteEditado(e.target.value)}
                        style={{ width: 70 }}
                      />
                      <button className="button" style={{ padding: "4px 8px", fontSize: 12 }} onClick={() => guardarLimite(k.id)}>
                        ✔
                      </button>
                      <button className="button button-danger" style={{ padding: "4px 8px", fontSize: 12 }} onClick={() => setEditandoLimiteId(null)}>
                        ✘
                      </button>
                    </div>
                  ) : (
                    <span
                      style={{ cursor: k.activa ? "pointer" : "default", textDecoration: k.activa ? "underline dotted" : "none" }}
                      onClick={() => k.activa && empezarEdicionLimite(k)}
                      title={k.activa ? "Click para cambiar el límite" : ""}
                    >
                      {k.limiteRps}/seg
                    </span>
                  )}
                </td>
                <td>{k.fechaCreacion ? k.fechaCreacion.split(".")[0].replace("T", " ") : "-"}</td>
                <td>{k.ultimoUso ? k.ultimoUso.split(".")[0].replace("T", " ") : "Nunca usada"}</td>
                <td>
                  {k.activa && (
                    <button
                      className="button button-danger"
                      style={{ padding: "6px 12px", fontSize: 13 }}
                      onClick={() => revocar(k.id)}
                    >
                      Revocar
                    </button>
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
