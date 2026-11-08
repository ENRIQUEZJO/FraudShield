import numpy as np
from deepface import DeepFace  # librería que trae los modelos de reconocimiento facial y anti-spoofing ya entrenados

# ==========================================
# CONFIGURACIÓN
# ==========================================

# Modelo de embeddings faciales. Facenet es rápido y preciso; también
# puedes usar "VGG-Face", "ArcFace" o "SFace" si quieres comparar.
# Un "embedding" es una lista de números (un vector) que representa la
# cara de forma que dos caras parecidas dan vectores parecidos.
MODELO_EMBEDDING = "Facenet"

UMBRAL_SIMILITUD = 0.60  # por encima de esto, se considera "la misma persona" (ver explicación en calcular_similitud)

# Nota: se probó forzar detector_backend="mediapipe" pensando que ayudaría
# con fotos de baja resolución, pero la versión de mediapipe instalada
# (0.10.x) es incompatible con el wrapper que usa DeepFace internamente
# (error "module 'mediapipe' has no attribute 'solutions'"). La causa
# real del "No se detectó rostro" era la RESOLUCIÓN de captura (300x200,
# corregida a 640x480 en el frontend) — con eso, el detector por defecto
# de DeepFace ("opencv") ya detecta el rostro sin problema. Se deja
# documentado por si en el futuro se actualiza deepface/mediapipe y se
# quiere reintentar.


# ==========================================
# RECONOCIMIENTO FACIAL (reemplaza Haar + correlación de píxeles)
# ==========================================
DETECTORES = ["opencv", "retinaface", "mtcnn"]


def get_encoding(frame):
    """Extrae un embedding facial real (vector de 128 dimensiones con
    Facenet) usando un modelo entrenado.

    Devuelve None si ningún detector logra encontrar un rostro.
    """
    ultimo_error = None
    for detector in DETECTORES:
        try:
            resultados = DeepFace.represent(
                img_path=frame,
                model_name=MODELO_EMBEDDING,
                detector_backend=detector,
                enforce_detection=True,
            )
            if not resultados:
                continue
            if detector != DETECTORES[0]:
                print(f"[face_engine] Rostro detectado con el detector de respaldo '{detector}'")
            return np.array(resultados[0]["embedding"], dtype=np.float64)
        except Exception as e:
            ultimo_error = e

    print(f"[face_engine] No se detectó rostro con ningún detector ({', '.join(DETECTORES)}): {ultimo_error}")
    return None


def calcular_similitud(encoding, db_encoding) -> float:
    """Similitud coseno entre dos embeddings faciales.

    IMPORTANTE: se devuelve el valor CRUDO de similitud coseno, sin
    remapear a un rango 0-1 con fórmulas tipo (coseno+1)/2. Ese remapeo
    (que tenía este código antes) es matemáticamente incorrecto para
    embeddings faciales: dos rostros de personas DISTINTAS ya dan una
    similitud coseno baja pero POSITIVA (típicamente 0.15-0.35, nunca
    cercana a -1, porque todos los rostros humanos comparten estructura
    como vectores). Remapear con (x+1)/2 empuja esos valores de
    impostores por encima del umbral de aprobación — eso causaba que
    CUALQUIER persona frente a la cámara fuera aprobada.

    UMBRAL_SIMILITUD = 0.60 está calibrado para compararse contra esta
    similitud coseno CRUDA, siguiendo la convención oficial de DeepFace
    (su threshold de "distancia coseno" para Facenet es ~0.40, y
    distancia = 1 - similitud, así que el punto de corte equivalente en
    similitud es 0.60). No volver a "normalizar" este valor.
    """
    a = np.array(encoding, dtype=np.float64)
    b = np.array(db_encoding, dtype=np.float64)
    # Fórmula de similitud coseno: (A · B) / (|A| * |B|).
    # El "+ 1e-9" evita una división por cero si algún vector fuera todo ceros.
    norm = (np.linalg.norm(a) * np.linalg.norm(b)) + 1e-9
    return float(np.dot(a, b) / norm)


# ⚠️ CÓDIGO NO CONECTADO: ningún otro archivo del proyecto llama a esta
# función — todo el código actual usa calcular_similitud() directamente
# y compara el resultado contra UMBRAL_SIMILITUD él mismo (ver
# mejor_similitud_contra_perfil en modulo_biometria/router.py). Se deja
# por si en algún punto se quiere una función de "sí/no" más simple.
def compare_faces(encoding, db_encoding) -> bool:
    """Se mantiene por compatibilidad con código existente."""
    return calcular_similitud(encoding, db_encoding) > UMBRAL_SIMILITUD


# ==========================================
# ANTI-SPOOFING REAL: ¿es una persona real o una foto/pantalla/máscara?
# ==========================================

def detectar_liveness_y_spoof(frame):
    """Usa el modelo de anti-spoofing (FasNet) que trae DeepFace
    integrado para distinguir un rostro real de un ataque de
    presentación: foto impresa, reproducción en pantalla, o máscara.

    Esto SÍ es un modelo entrenado real (no una simulación ni una
    heurística de movimiento entre frames como antes).

    Devuelve (es_real: bool, confianza: float 0-1).
    """
    try:
        # extract_faces con anti_spoofing=True: además de encontrar la
        # cara, corre el modelo FasNet para juzgar si es una persona
        # real o un "ataque de presentación" (foto/pantalla/máscara).
        caras = DeepFace.extract_faces(
            img_path=frame,
            anti_spoofing=True,
            enforce_detection=True,
        )
        if not caras:
            return False, 0.0
        cara = caras[0]  # se asume una sola persona en el cuadro
        es_real = bool(cara.get("is_real", False))
        confianza = float(cara.get("antispoof_score", 0.0))
        return es_real, confianza
    except Exception as e:
        # Si algo falla (por ejemplo, falta el paquete "torch", que este
        # modelo necesita — ver requirements.txt), se asume "no es real"
        # por seguridad, en vez de dejar pasar sin verificar.
        print(f"[face_engine] Error en anti-spoofing: {e}")
        return False, 0.0