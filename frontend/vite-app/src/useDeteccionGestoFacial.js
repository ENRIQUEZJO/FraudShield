import { useEffect, useRef, useState } from "react";
import { FaceLandmarker, FilesetResolver } from "@mediapipe/tasks-vision";

// Índices de landmarks de MediaPipe FaceMesh que usamos para estimar
// hacia dónde está girada la cabeza, sin necesitar un cálculo 3D
// completo de pose — suficiente para distinguir centro/izquierda/
// derecha/arriba de forma confiable. FaceMesh numera 468 puntos fijos
// en la cara; estos 5 números son posiciones ESPECÍFICAS y conocidas
// dentro de esa numeración estándar (no hay que adivinarlas).
const PUNTA_NARIZ = 1;
const MEJILLA_IZQ = 234; // borde izquierdo de la cara (en la imagen)
const MEJILLA_DER = 454; // borde derecho de la cara (en la imagen)
const FRENTE = 10;
const BARBILLA = 152;

// Rangos "razonables" para cada gesto. yaw: 0 = pegado al borde
// izquierdo, 1 = pegado al borde derecho, 0.5 = centro. pitch: 0 = nariz
// a la altura de la frente (mirando arriba), 1 = nariz a la altura de
// la barbilla (mirando abajo).
//
// ⚠️ IMPORTANTE sobre "izquierda"/"derecha": el límite superior/inferior
// se bajó de 1.00/0.00 a 0.85/0.15 tras una prueba real — con el rango
// original, el auto-captura disparaba en ángulos de CASI PERFIL
// COMPLETO, que el detector de rostros del backend (DeepFace, más
// estricto que el detector del navegador) no lograba reconocer como un
// rostro válido, causando "No se detectó rostro" justo después de
// haber capturado la foto. Con un giro más moderado (todavía un ángulo
// claramente distinto del centro, pero sin llegar a perfil completo),
// el backend sí lo reconoce. Si sigue fallando, achicar más el rango
// (ej. 0.75 en vez de 0.85).
const RANGOS_GESTOS = {
  centro: { yaw: [0.40, 0.60], pitch: [0.30, 0.55] },
  izquierda: { yaw: [0.60, 0.85], pitch: [0.20, 0.65] },
  derecha: { yaw: [0.15, 0.40], pitch: [0.20, 0.65] },
  arriba: { yaw: [0.35, 0.65], pitch: [0.00, 0.22] },
};

const MS_ESTABLE_REQUERIDO = 700; // cuánto tiempo debe sostenerse la pose antes de capturar (evita capturas por un movimiento accidental de medio segundo)

// Calcula, a partir de los puntos de referencia del rostro, dos números
// que describen la orientación de la cabeza: "yaw" (giro horizontal,
// izquierda/derecha) y "pitch" (giro vertical, arriba/abajo).
function calcularPose(landmarks) {
  const nariz = landmarks[PUNTA_NARIZ];
  const izq = landmarks[MEJILLA_IZQ];
  const der = landmarks[MEJILLA_DER];
  const frente = landmarks[FRENTE];
  const barbilla = landmarks[BARBILLA];

  // Yaw: en qué posición horizontal está la nariz, relativa al ancho
  // de la cara (0 = pegada al borde izquierdo, 1 = pegada al derecho).
  // Cuando giras la cabeza, la nariz se "desplaza" hacia un lado.
  const anchoCara = der.x - izq.x;
  const yaw = anchoCara !== 0 ? (nariz.x - izq.x) / anchoCara : 0.5;

  // Pitch: lo mismo pero en vertical (posición de la nariz entre la
  // frente y la barbilla).
  const altoCara = barbilla.y - frente.y;
  const pitch = altoCara !== 0 ? (nariz.y - frente.y) / altoCara : 0.5;

  return { yaw, pitch };
}

// Compara la pose actual contra el rango esperado para el gesto pedido.
function poseCoincideConGesto(pose, gesto) {
  const rango = RANGOS_GESTOS[gesto];
  if (!rango) return false;
  return (
    pose.yaw >= rango.yaw[0] &&
    pose.yaw <= rango.yaw[1] &&
    pose.pitch >= rango.pitch[0] &&
    pose.pitch <= rango.pitch[1]
  );
}

/**
 * Hook que analiza el video en vivo y detecta cuándo la cabeza está en
 * la posición pedida (gestoObjetivo), sosteniéndola por
 * MS_ESTABLE_REQUERIDO antes de avisar con onGestoDetectado().
 */
export function useDeteccionGestoFacial({ videoRef, gestoObjetivo, activo, onGestoDetectado }) {
  const [cargandoModelo, setCargandoModelo] = useState(true);
  const [errorModelo, setErrorModelo] = useState("");
  const [progreso, setProgreso] = useState(0); // 0-1, para la barra de "sosteniendo pose"
  const landmarkerRef = useRef(null);      // guarda el modelo ya cargado, sin causar re-renders
  const rafRef = useRef(null);             // ID del requestAnimationFrame actual, para poder cancelarlo
  const inicioEstableRef = useRef(null);   // marca de tiempo de cuándo empezó a sostenerse la pose correcta

  // Cargar el modelo una sola vez, cuando el componente se monta.
  useEffect(() => {
    let cancelado = false;  // evita actualizar el estado si el componente ya se desmontó antes de que termine de cargar

    (async () => {
      try {
        // FilesetResolver: descarga los archivos WASM (código binario
        // que corre en el navegador) necesarios para MediaPipe.
        const fileset = await FilesetResolver.forVisionTasks(
          "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.17/wasm"
        );
        // FaceLandmarker: el modelo de IA en sí, que detecta los 468
        // puntos de referencia de un rostro en cada cuadro de video.
        // delegate: "GPU" intenta usar la tarjeta gráfica para que sea
        // más rápido; si el navegador no lo soporta, esto lanzará un
        // error y caerá al catch de abajo (mostrando el botón manual).
        const landmarker = await FaceLandmarker.createFromOptions(fileset, {
          baseOptions: {
            modelAssetPath:
              "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task",
            delegate: "GPU",
          },
          runningMode: "VIDEO",  // optimizado para procesar un video en vivo cuadro a cuadro (no fotos sueltas)
          numFaces: 1,            // solo nos interesa una cara a la vez
        });
        if (!cancelado) {
          landmarkerRef.current = landmarker;
          setCargandoModelo(false);
        }
      } catch (e) {
        console.error(e);
        if (!cancelado) {
          setErrorModelo("No se pudo cargar el detector facial. Puedes capturar manualmente.");
          setCargandoModelo(false);
        }
      }
    })();

    // Función de limpieza: se ejecuta si el componente se desmonta —
    // libera los recursos del modelo y evita fugas de memoria.
    return () => {
      cancelado = true;
      landmarkerRef.current?.close();
    };
  }, []);  // [] = solo se ejecuta una vez, al montar el componente

  // Bucle de detección por cuadro, mientras esté "activo".
  // Se vuelve a ejecutar cada vez que cambia gestoObjetivo (por ejemplo,
  // al pasar de "centro" a "izquierda" durante el registro).
  useEffect(() => {
    // No hacer nada si: no está activo, el modelo sigue cargando, hubo
    // un error cargándolo, o por algún motivo el modelo no está listo.
    if (!activo || cargandoModelo || errorModelo || !landmarkerRef.current) return;

    inicioEstableRef.current = null;  // reinicia el contador de "tiempo sosteniendo la pose" para el nuevo gesto
    setProgreso(0);

    // Esta función se llama a sí misma en cada cuadro (~60 veces por
    // segundo) usando requestAnimationFrame, que es la forma correcta
    // de animar/analizar video en el navegador (se sincroniza con el
    // refresco de pantalla, y se pausa solo si la pestaña no está visible).
    const analizarCuadro = () => {
      const video = videoRef.current;
      // readyState >= 2 significa "el video ya tiene al menos un cuadro
      // listo para mostrarse" — analizar antes de eso daría basura.
      if (video && video.readyState >= 2) {
        const resultado = landmarkerRef.current.detectForVideo(video, performance.now());

        if (resultado.faceLandmarks && resultado.faceLandmarks.length > 0) {
          const pose = calcularPose(resultado.faceLandmarks[0]);
          const coincide = poseCoincideConGesto(pose, gestoObjetivo);

          if (coincide) {
            // La pose es correcta: si es la primera vez que coincide,
            // se marca el momento de inicio; si ya llevaba un rato,
            // se calcula cuánto tiempo lleva sostenida.
            if (inicioEstableRef.current === null) {
              inicioEstableRef.current = performance.now();
            }
            const transcurrido = performance.now() - inicioEstableRef.current;
            setProgreso(Math.min(1, transcurrido / MS_ESTABLE_REQUERIDO));  // actualiza la barra visual de progreso

            if (transcurrido >= MS_ESTABLE_REQUERIDO) {
              // ¡Lleva suficiente tiempo sostenida! Se avisa al
              // componente padre (que captura la foto) y se detiene
              // este bucle — el padre cambiará "gestoObjetivo" o
              // "activo" para el siguiente paso, lo que reinicia este
              // useEffect automáticamente.
              onGestoDetectado();
              inicioEstableRef.current = null;
              setProgreso(0);
              return; // no programa el siguiente cuadro — el efecto se reinicia solo cuando cambien las dependencias
            }
          } else {
            // La pose dejó de coincidir (el usuario se movió) — se
            // reinicia el contador, tiene que sostenerla de nuevo desde cero.
            inicioEstableRef.current = null;
            setProgreso(0);
          }
        } else {
          // No se detectó ningún rostro en este cuadro (se salió del
          // encuadre, poca luz, etc.)
          inicioEstableRef.current = null;
          setProgreso(0);
        }
      }

      // Programa el análisis del siguiente cuadro — así se repite
      // continuamente mientras el gesto no se haya completado.
      rafRef.current = requestAnimationFrame(analizarCuadro);
    };

    rafRef.current = requestAnimationFrame(analizarCuadro);  // arranca el bucle

    // Limpieza: si el componente se desmonta o las dependencias cambian
    // antes de terminar, se cancela el cuadro pendiente para no seguir
    // analizando video de un componente que ya no está en pantalla.
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [activo, gestoObjetivo, cargandoModelo, errorModelo, videoRef, onGestoDetectado]);

  return { cargandoModelo, errorModelo, progreso };
}
