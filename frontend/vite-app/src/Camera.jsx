// Camera.jsx — pantalla de "Verificación" del menú. Muestra la cámara
// en vivo, detecta automáticamente cuando el rostro está centrado, y
// verifica la identidad sin necesidad de tocar ningún botón.
import { useEffect, useRef, useState } from "react";
import { verificar } from "../api";
import { useDeteccionGestoFacial } from "./useDeteccionGestoFacial";

export default function Camera({ setResultado }) {
  const videoRef = useRef(null);  // referencia al elemento <video> del HTML, para poder leer sus cuadros
  const [camaraLista, setCamaraLista] = useState(false);   // true una vez que el navegador ya está mostrando el video
  const [verificando, setVerificando] = useState(false);   // true mientras se espera la respuesta del backend
  const [autoActivo, setAutoActivo] = useState(true);      // controla si la auto-detección está corriendo o en pausa

  // Al montar el componente, se pide permiso de cámara al navegador y
  // se conecta el video en vivo al elemento <video>.
  useEffect(() => {
    navigator.mediaDevices.getUserMedia({ video: true }).then((stream) => {
      videoRef.current.srcObject = stream;
      // onloadedmetadata se dispara cuando el video ya tiene datos
      // reales (dimensiones, etc.) — recién ahí tiene sentido empezar a analizarlo.
      videoRef.current.onloadedmetadata = () => setCamaraLista(true);
    });
  }, []);

  // Captura el cuadro actual del video como una foto, y la manda al
  // backend a verificar. Se llama tanto automáticamente (cuando se
  // detecta el rostro centrado) como manualmente (botón de respaldo).
  const capturarYVerificar = async () => {
    if (verificando) return; // evita disparos dobles mientras ya hay una verificación en curso

    setVerificando(true);
    setAutoActivo(false); // pausa la auto-detección mientras se procesa esta verificación

    // Se dibuja el cuadro actual del video sobre un <canvas> invisible,
    // y de ahí se extrae como una imagen JPEG en base64 — es la forma
    // estándar de "tomar una foto" de un elemento <video> en el navegador.
    const canvas = document.createElement("canvas");
    canvas.width = 640;
    canvas.height = 480;
    canvas.getContext("2d").drawImage(videoRef.current, 0, 0, 640, 480);
    const image = canvas.toDataURL("image/jpeg");

    const res = await verificar(image);  // llamada real al backend
    setResultado(res);                    // App.jsx muestra este resultado en una tarjeta
    setVerificando(false);

    // Reactiva la auto-detección para la siguiente verificación, dando
    // un pequeño respiro para que el usuario vea el resultado primero.
    setTimeout(() => setAutoActivo(true), 2000);
  };

  // Hook que analiza el video en tiempo real y llama a
  // capturarYVerificar() automáticamente cuando detecta el rostro
  // centrado y quieto por un momento (gesto "centro" — ver el hook).
  const { cargandoModelo, errorModelo, progreso } = useDeteccionGestoFacial({
    videoRef,
    gestoObjetivo: "centro",
    // Solo corre la detección si: la cámara ya está lista, no está en
    // pausa (autoActivo), y no hay una verificación en curso ahora mismo.
    activo: camaraLista && autoActivo && !verificando,
    onGestoDetectado: capturarYVerificar,
  });

  return (
    <div className="card">
      <h3>Verificación en tiempo real</h3>

      <div className="camara-deteccion-wrap">
        <video ref={videoRef} autoPlay muted width="300" />
        {/* Barra de progreso: se llena mientras se sostiene la pose correcta */}
        {!errorModelo && (
          <div className="barra-progreso-gesto">
            <div className="barra-progreso-gesto-relleno" style={{ width: `${progreso * 100}%` }} />
          </div>
        )}
      </div>

      {/* Mensajes de estado — solo uno se muestra a la vez, según la situación actual */}
      {cargandoModelo && <p className="login-subtitle">Cargando detector facial...</p>}
      {!cargandoModelo && !errorModelo && !verificando && (
        <p className="login-subtitle">Mira a la cámara — se verifica sola ✨</p>
      )}
      {verificando && <p className="login-subtitle">Verificando...</p>}
      {errorModelo && <p className="login-error">{errorModelo}</p>}

      {/* Respaldo manual: siempre disponible, por si la detección automática falla */}
      <button className="button" onClick={capturarYVerificar} disabled={verificando}>
        Verificar manualmente
      </button>
    </div>
  );
}