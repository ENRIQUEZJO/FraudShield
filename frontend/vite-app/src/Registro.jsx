// Registro.jsx — formulario de alta de usuario nuevo, con captura
// guiada de 4 ángulos del rostro (centro/izquierda/derecha/arriba) para
// construir un perfil facial más robusto que una sola foto.
//
// Este componente se usa en DOS contextos distintos:
//   1. Auto-registro público (modoAdmin=false): pantalla completa,
//      accesible desde el link "Crear cuenta" del Login.
//   2. Alta por un admin (modoAdmin=true): embebido dentro de
//      AdminPanel.jsx, con un selector de empresa adicional.
import { useCallback, useEffect, useRef, useState } from "react";
import { registrar } from "../api";
import { useDeteccionGestoFacial } from "./useDeteccionGestoFacial";

// Los 4 gestos que se piden, en orden, con el texto de instrucción para
// cada uno. Este orden debe coincidir con GESTOS_REQUERIDOS del backend
// (modulo_biometria/router.py) — aunque técnicamente el backend no
// exige un ORDEN específico, solo que estén los 4 nombres presentes.
const PASOS_GESTOS = [
  { gesto: "centro", instruccion: "Mira directo a la cámara" },
  { gesto: "izquierda", instruccion: "Gira tu cabeza hacia la izquierda" },
  { gesto: "derecha", instruccion: "Gira tu cabeza hacia la derecha" },
  { gesto: "arriba", instruccion: "Levanta un poco la cabeza, mirando hacia arriba" },
];

/**
 * modoAdmin: si es true, se renderiza embebido dentro de una página (sin
 * el overlay de pantalla completa), muestra un selector de empresa, y
 * oculta el enlace "¿Ya tienes cuenta?" (no aplica cuando un admin está
 * registrando a otra persona).
 * empresas: lista [{ empresaId, nombre }] para el selector (solo se usa
 * si modoAdmin es true).
 */
export default function Registro({ onRegistroOk, onVolverLogin, modoAdmin = false, empresas = [] }) {
  const videoRef = useRef(null);
  const [nombre, setNombre] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [documento, setDocumento] = useState("");
  const [empresaId, setEmpresaId] = useState("");
  const [fotos, setFotos] = useState({}); // { centro: "data:...", izquierda: "data:...", ... } — se va llenando conforme se capturan
  const [pasoActual, setPasoActual] = useState(0);  // índice dentro de PASOS_GESTOS del gesto que se está pidiendo ahora
  const [error, setError] = useState("");
  const [cargando, setCargando] = useState(false);   // true mientras se espera la respuesta del backend al enviar el formulario
  const [camaraLista, setCamaraLista] = useState(false);

  // Pide permiso de cámara al montar el componente.
  useEffect(() => {
    navigator.mediaDevices
      .getUserMedia({ video: true })
      .then((stream) => {
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          videoRef.current.onloadedmetadata = () => setCamaraLista(true);
        }
      })
      .catch(() => setError("No se pudo acceder a la cámara. Actívala para poder registrarte."));
  }, []);

  const gestoActual = PASOS_GESTOS[pasoActual];
  const todosCapturados = Object.keys(fotos).length === PASOS_GESTOS.length;

  // Captura el cuadro actual del video como foto para el gesto en
  // curso, y avanza al siguiente paso automáticamente (si no era ya el último).
  const capturarFotoActual = useCallback(() => {
    const canvas = document.createElement("canvas");
    canvas.width = 640;
    canvas.height = 480;
    canvas.getContext("2d").drawImage(videoRef.current, 0, 0, 640, 480);
    const dataUrl = canvas.toDataURL("image/jpeg");

    setFotos((prev) => ({ ...prev, [gestoActual.gesto]: dataUrl }));
    setError("");

    setPasoActual((p) => (p < PASOS_GESTOS.length - 1 ? p + 1 : p));
  }, [gestoActual]);

  // Detecta automáticamente cuándo la cabeza está en la posición
  // pedida y llama a capturarFotoActual() sola (ver el hook para el detalle).
  const { cargandoModelo, errorModelo, progreso } = useDeteccionGestoFacial({
    videoRef,
    gestoObjetivo: gestoActual.gesto,
    activo: camaraLista && !todosCapturados,
    onGestoDetectado: capturarFotoActual,
  });

  // Permite volver a capturar un gesto ya tomado (al hacer clic en su
  // miniatura). IMPORTANTE: además de mover pasoActual, hay que BORRAR
  // la foto vieja de ese gesto — si no, cuando ya se completaron los 4
  // ángulos, "todosCapturados" seguiría siendo true (esa foto vieja
  // sigue contando) y la sección de cámara/captura quedaría oculta,
  // dejando al usuario sin forma de rehacer la foto.
  const repetirCaptura = (gesto) => {
    const index = PASOS_GESTOS.findIndex((p) => p.gesto === gesto);
    setPasoActual(index);
    setFotos((prev) => {
      const nuevo = { ...prev };
      delete nuevo[gesto];
      return nuevo;
    });
  };

  const manejarSubmit = async (e) => {
    e.preventDefault();
    setError("");

    if (!todosCapturados) {
      setError("Captura los 4 ángulos antes de continuar.");
      return;
    }

    setCargando(true);
    // Convierte el objeto { centro: "...", izquierda: "...", ... } en la
    // lista [{ gesto, frame }, ...] que espera el backend.
    const fotosPayload = PASOS_GESTOS.map((p) => ({ gesto: p.gesto, frame: fotos[p.gesto] }));
    const empresaIdFinal = empresaId ? parseInt(empresaId, 10) : null;
    const data = await registrar(nombre, email, password, documento, fotosPayload, empresaIdFinal);
    setCargando(false);

    if (data.status === "ok") {
      onRegistroOk();
    } else {
      setError(data.message || "No se pudo completar el registro");
    }
  };

  // El formulario se arma una sola vez aquí, y luego se decide más
  // abajo si envolverlo en el overlay de pantalla completa o no,
  // según el modo (público vs. admin).
  const contenido = (
    <form className="card login-card" onSubmit={manejarSubmit}>
      <h2>🛡️ Crear cuenta</h2>
      <p className="login-subtitle">
        {modoAdmin
          ? "Registra un nuevo usuario — captura varios ángulos de su rostro"
          : "Regístrate con tu rostro — te pediremos varios ángulos para un perfil facial más seguro"}
      </p>

      <label>Nombre completo</label>
      <input type="text" value={nombre} onChange={(e) => setNombre(e.target.value)} required />

      <label>Email</label>
      <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />

      <label>Contraseña</label>
      <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />

      <label>Documento de identidad</label>
      <input type="text" value={documento} onChange={(e) => setDocumento(e.target.value)} required />

      {/* El selector de empresa solo aparece cuando un admin está dando de alta a alguien */}
      {modoAdmin && (
        <>
          <label>Empresa (opcional)</label>
          <select value={empresaId} onChange={(e) => setEmpresaId(e.target.value)}>
            <option value="">Sin empresa asignada</option>
            {empresas.map((emp) => (
              <option key={emp.empresaId} value={emp.empresaId}>
                {emp.nombre}
              </option>
            ))}
          </select>
        </>
      )}

      <label>Foto para verificación facial ({Object.keys(fotos).length}/{PASOS_GESTOS.length})</label>

      {/* El <video> SIEMPRE está montado (nunca se quita del todo del
          DOM) — solo se oculta con CSS cuando ya no hace falta. Si se
          desmontara condicionalmente (como estaba antes), al volver a
          mostrarlo React crearía un elemento <video> NUEVO, que nunca
          recupera la transmisión de la cámara (eso solo se conecta una
          vez, en el useEffect de arriba) — la pantalla se quedaría en
          blanco justo cuando intentas repetir una foto. */}
      <div
        className="camara-deteccion-wrap"
        style={{ display: todosCapturados ? "none" : "flex" }}
      >
        <video ref={videoRef} autoPlay muted width="260" style={{ borderRadius: 8 }} />
        {!errorModelo && (
          <div className="barra-progreso-gesto">
            <div
              className="barra-progreso-gesto-relleno"
              style={{ width: `${progreso * 100}%` }}
            />
          </div>
        )}
      </div>

      {/* Mientras falten ángulos por capturar: se muestran las
          instrucciones y el botón manual. Una vez completados los 4:
          se oculta todo esto y solo queda el mensaje de confirmación. */}
      {!todosCapturados ? (
        <>
          <p className="gesto-instruccion">👉 {gestoActual.instruccion}</p>

          {cargandoModelo && (
            <p className="login-subtitle">Cargando detector facial...</p>
          )}
          {!cargandoModelo && !errorModelo && (
            <p className="login-subtitle">
              Sostén la posición — se captura sola cuando coincide ✨
            </p>
          )}
          {errorModelo && <p className="login-error">{errorModelo}</p>}

          {/* Respaldo manual: siempre disponible, por si la detección automática falla */}
          <button type="button" className="button" onClick={capturarFotoActual}>
            Capturar "{gestoActual.gesto}" manualmente
          </button>
        </>
      ) : (
        <p className="text-ok">✔ Los 4 ángulos fueron capturados</p>
      )}

      {/* Miniaturas de los 4 gestos — clicar una ya capturada permite
          rehacerla (ver repetirCaptura arriba) */}
      <div className="miniaturas-gestos">
        {PASOS_GESTOS.map((p) => (
          <div key={p.gesto} className="miniatura-gesto">
            {fotos[p.gesto] ? (
              <img
                src={fotos[p.gesto]}
                alt={p.gesto}
                width="60"
                style={{ borderRadius: 6, cursor: "pointer" }}
                onClick={() => repetirCaptura(p.gesto)}
                title="Click para volver a capturar"
              />
            ) : (
              <div className="miniatura-pendiente">?</div>
            )}
            <span>{p.gesto}</span>
          </div>
        ))}
      </div>

      {error && <p className="login-error">{error}</p>}

      <button className="button" type="submit" disabled={cargando || !todosCapturados}>
        {cargando ? "Registrando..." : "Crear cuenta"}
      </button>

      {/* El enlace de "ya tengo cuenta" no aplica cuando un admin está
          registrando a otra persona desde el panel */}
      {!modoAdmin && (
        <p className="login-subtitle" style={{ textAlign: "center" }}>
          ¿Ya tienes cuenta?{" "}
          <span className="login-link" onClick={onVolverLogin}>
            Inicia sesión
          </span>
        </p>
      )}
    </form>
  );

  // modoAdmin: se devuelve el formulario "desnudo", para que
  // AdminPanel.jsx lo posicione dentro de su propio layout.
  if (modoAdmin) return contenido;

  // Modo público: se envuelve en el overlay de pantalla completa.
  return <div className="login-screen">{contenido}</div>;
}
