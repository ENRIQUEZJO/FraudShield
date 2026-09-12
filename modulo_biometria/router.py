"""
modulo_biometria/router.py

Adaptado del main.py original de VisionSegura.
Antes era una FastAPI() independiente (con su propio CORS y su propio
uvicorn.run); ahora es un APIRouter que se monta dentro del backend
unificado (ver main.py). El middleware de CORS y el arranque de
uvicorn viven ahora solo en el main.py del backend unificado.

Base de datos: SQL Server, a través de un POOL de conexiones
(shared/db.py) compartido con modulo_antifraude — seguro para muchos
usuarios/instituciones usando el sistema al mismo tiempo.
"""
import numpy as np    # para convertir los embeddings faciales (bytes <-> números) al leer/guardar en la base de datos
import base64          # las fotos llegan del frontend codificadas en base64 dentro de un string
import cv2             # para decodificar los bytes de la imagen a una matriz de píxeles que DeepFace pueda leer

from fastapi import APIRouter, Depends

from modulo_biometria.services.face_engine import (
    get_encoding,               # convierte una foto en un embedding facial
    calcular_similitud,         # compara dos embeddings y devuelve qué tan parecidos son
    detectar_liveness_y_spoof,  # detecta si es una persona real o una foto/pantalla
    UMBRAL_SIMILITUD,           # a partir de qué similitud se considera "la misma persona"
)
from modulo_biometria.services.security import hashear_password, verificar_password, generar_api_key, hashear_api_key
from modulo_biometria.auth import crear_token, obtener_usuario_actual, requerir_admin
from modulo_biometria.models.schemas import (
    FrameData, RegistroUsuario, LoginRequest, AccionarRequest,
    EmpresaCreate, CambiarEmpresaRequest, ApiKeyCreate,
)
from shared.db import obtener_conexion, DB_DISPONIBLE

router = APIRouter(tags=["biometria"])

# Gestos que se piden durante el registro, para capturar varios ángulos
# del rostro (como hace Face ID al configurarse). El orden se respeta en
# el frontend para guiar al usuario paso a paso.
GESTOS_REQUERIDOS = ["centro", "izquierda", "derecha", "arriba"]


# ==========================================
# UTILIDADES
# ==========================================

def decode_image(base64_str):
    """Convierte una foto en formato base64 (como la envía el navegador)
    en una imagen que OpenCV/DeepFace puedan procesar."""
    try:
        # El navegador manda algo como "data:image/jpeg;base64,/9j/4AAQ...".
        # Solo nos interesa la parte después de la coma.
        if "," in base64_str:
            base64_str = base64_str.split(",")[1]
        img_bytes = base64.b64decode(base64_str)             # texto base64 -> bytes crudos de la imagen
        np_arr = np.frombuffer(img_bytes, np.uint8)           # bytes -> arreglo de números
        frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)        # arreglo de números -> imagen (matriz de píxeles a color)
        return frame
    except Exception as e:
        print(f"Error imagen: {e}")
        return None  # imagen corrupta o mal formada — quien llama debe manejar este caso


def calcular_score(similitud: float, es_real: bool, confianza_antispoof: float) -> int:
    """Combina la similitud facial y el resultado del anti-spoofing en
    un solo puntaje de confianza de 0 a 100."""
    puntos = 0
    # Hasta 60 puntos según qué tan cerca esté la similitud del umbral
    # de aprobación (si iguala o supera el umbral, da el máximo de 60).
    puntos += min(60, int(similitud * 60 / UMBRAL_SIMILITUD)) if similitud > 0 else 0
    # Hasta 40 puntos si el modelo de anti-spoofing considera que es una
    # persona real (proporcional a qué tan seguro está el modelo).
    puntos += int(40 * confianza_antispoof) if es_real else 0
    return min(100, puntos)  # nunca superar 100


def decidir_resultado(score: int) -> str:
    """Traduce el puntaje numérico a una categoría legible."""
    if score >= 80:
        return "APROBADO"
    if score >= 50:
        return "REVISION_MANUAL"
    return "FRAUDE"


def mejor_similitud_contra_perfil(user_id: int, encoding_en_vivo) -> tuple[float, int]:
    """Compara el encoding capturado en vivo contra TODOS los ángulos
    guardados en PerfilesFaciales para ese usuario, y devuelve la mejor
    similitud encontrada (más tolerante que comparar contra un solo
    ángulo). Devuelve (similitud, cantidad_de_perfiles_comparados)."""
    if not DB_DISPONIBLE:
        return 0.0, 0  # sin base de datos, no hay con qué comparar

    with obtener_conexion() as (conn, cursor):
        cursor.execute(
            "SELECT Encoding FROM PerfilesFaciales WHERE UsuarioId = ?",
            (user_id,),
        )
        filas = cursor.fetchall()

        if not filas:
            return 0.0, 0  # usuario sin ángulos faciales guardados (registro incompleto)

        mejor = 0.0
        for fila in filas:
            # Los embeddings se guardan como bytes crudos (.tobytes() al
            # registrar) — hay que reconstruirlos de vuelta a un arreglo de
            # números antes de poder compararlos.
            db_encoding = np.frombuffer(fila[0], dtype=np.float64)
            sim = calcular_similitud(encoding_en_vivo, db_encoding)
            if sim > mejor:
                mejor = sim  # nos quedamos con la comparación más favorable de las 4

        return mejor, len(filas)


# ==========================================
# STATUS
# ==========================================

@router.get("/status")
def status():
    """Endpoint simple para confirmar que este módulo está vivo (sin
    necesidad de estar logueado) — útil para pruebas rápidas."""
    return {"mensaje": "VisionSegura (modulo_biometria) operativo"}


# ==========================================
# REGISTRO
# ==========================================

@router.post("/register")
async def register(user: RegistroUsuario):
    # Primero se valida la FORMA de los datos (que vengan los 4 gestos)
    # antes de siquiera tocar la base de datos — así un error de "faltan
    # datos" no depende de si SQL Server está disponible o no.
    gestos_recibidos = {f.gesto for f in user.fotos}
    faltantes = set(GESTOS_REQUERIDOS) - gestos_recibidos
    if faltantes:
        return {"status": "error", "message": f"Faltan gestos por capturar: {', '.join(faltantes)}"}

    if not DB_DISPONIBLE:
        return {"status": "error", "message": "Sin conexión DB"}

    # Se validan TODOS los ángulos antes de insertar nada — si uno solo
    # falla (no se detectó rostro en esa foto), se rechaza el registro
    # completo en vez de guardar un perfil facial a medias. Esto se hace
    # ANTES de pedir una conexión del pool — no tiene sentido ocupar una
    # conexión mientras se procesan las fotos con DeepFace (que no
    # necesita la base de datos para nada).
    encodings_por_gesto = {}
    for foto in user.fotos:
        frame = decode_image(foto.frame)
        if frame is None:
            return {"status": "error", "message": f"Imagen inválida para el gesto '{foto.gesto}'"}

        encoding = get_encoding(frame)
        if encoding is None:
            return {"status": "error", "message": f"No se detectó rostro en la foto de '{foto.gesto}'"}

        encodings_por_gesto[foto.gesto] = encoding

    password_hash = hashear_password(user.password)  # nunca se guarda la contraseña en texto plano

    try:
        with obtener_conexion() as (conn, cursor):
            # OUTPUT INSERTED.Id: le pide a SQL Server que devuelva el ID
            # recién generado del nuevo usuario, para poder usarlo abajo al
            # guardar sus fotos faciales asociadas.
            cursor.execute(
                """
                INSERT INTO Usuarios (Nombre, Email, Password, Documento, EmpresaId)
                OUTPUT INSERTED.Id
                VALUES (?, ?, ?, ?, ?)
                """,
                (user.nombre, user.email, password_hash, user.documento, user.empresa_id),
            )
            usuario_id = cursor.fetchone()[0]

            # Una fila por cada gesto capturado (centro, izquierda, derecha, arriba)
            for gesto, encoding in encodings_por_gesto.items():
                cursor.execute(
                    """
                    INSERT INTO PerfilesFaciales (UsuarioId, Gesto, Encoding)
                    VALUES (?, ?, ?)
                    """,
                    (usuario_id, gesto, encoding.tobytes()),  # el embedding (números) se guarda como bytes crudos
                )

            conn.commit()  # confirma TODOS los inserts de una vez (usuario + 4 fotos)

        return {"status": "ok", "message": f"Usuario registrado con {len(encodings_por_gesto)} ángulos faciales"}

    except Exception as e:
        # El "with obtener_conexion()" ya hace rollback automático si
        # algo falla adentro (ver shared/db.py) — aquí solo se traduce
        # el error a una respuesta legible.
        return {"status": "error", "message": str(e)}


# ==========================================
# LOGIN
# ==========================================

@router.post("/login")
async def login(data: LoginRequest):
    if not DB_DISPONIBLE:
        return {"status": "error", "message": "Sin conexión DB"}
    try:
        with obtener_conexion() as (conn, cursor):
            cursor.execute(
                "SELECT Id, Nombre, Password, Rol FROM Usuarios WHERE Email = ?",
                (data.email,),
            )
            user = cursor.fetchone()

            if not user:
                # Mensaje genérico a propósito: no se distingue entre "email
                # no existe" y "contraseña incorrecta" en el mensaje de
                # login en sí (ver el otro caso más abajo) — aunque aquí sí
                # se podría afinar para que ambos casos usen el mismo texto
                # ("Credenciales inválidas") y así no revelar si un email
                # está registrado o no.
                return {"status": "error", "message": "Usuario no encontrado"}

            user_id, nombre, password_hash, rol = user[0], user[1], user[2], user[3] or "user"

        # La verificación de contraseña (bcrypt) es lenta A PROPÓSITO
        # (para dificultar fuerza bruta) — se hace FUERA del "with", ya
        # con la conexión devuelta al pool, para no tener una conexión
        # ocupada innecesariamente durante ese cálculo.
        if not password_hash or not verificar_password(data.password, password_hash):
            return {"status": "error", "message": "Credenciales inválidas"}

        # Se genera el JWT con el user_id y el rol adentro — así, en
        # cada petición futura, el backend sabe quién es sin tener que
        # volver a consultar la base de datos solo para eso.
        token = crear_token({"user_id": int(user_id), "rol": rol})

        return {
            "status": "ok",
            "user_id": int(user_id),
            "nombre": nombre,
            "rol": rol,
            "access_token": token,
            "token_type": "bearer",
        }

    except Exception as e:
        return {"status": "error", "message": str(e)}


# ==========================================
# VERIFICACIÓN FACIAL (protegida con JWT)
# ==========================================

@router.post("/verificar")
async def verificar(data: FrameData, usuario=Depends(obtener_usuario_actual)):
    try:
        frame = decode_image(data.frame)
        if frame is None:
            return {"resultado": "ERROR", "detalle": "Imagen inválida"}

        encoding = get_encoding(frame)
        es_real, confianza_antispoof = detectar_liveness_y_spoof(frame)

        if encoding is None:
            # Nota: este caso (no se detectó rostro) NO queda guardado en
            # el historial de Verificaciones más abajo, porque el
            # INSERT solo ocurre después de este punto. Para auditoría
            # de fraude podría interesar registrar también los intentos
            # fallidos por "no se detectó rostro" — queda como mejora
            # futura si se necesita ese nivel de trazabilidad.
            return {"resultado": "FRAUDE", "detalle": "No se detectó rostro"}

        similitud = 0.0
        cantidad_angulos = 0

        if DB_DISPONIBLE:
            similitud, cantidad_angulos = mejor_similitud_contra_perfil(data.user_id, encoding)

        score = calcular_score(similitud, es_real, confianza_antispoof)
        resultado = decidir_resultado(score)
        match = similitud > UMBRAL_SIMILITUD
        es_deepfake = not es_real

        # Guardar en el historial es "best effort": si falla (ej. la
        # base de datos se cae justo aquí), igual se le devuelve el
        # resultado al usuario — no tiene sentido bloquear la respuesta
        # de la verificación solo porque no se pudo loguear el intento.
        if DB_DISPONIBLE:
            try:
                with obtener_conexion() as (conn, cursor):
                    cursor.execute(
                        """
                        INSERT INTO Verificaciones
                        (UsuarioId, Resultado, Coincidencia, EsDeepfake, Score, Fecha)
                        VALUES (?, ?, ?, ?, ?, GETDATE())
                        """,
                        (data.user_id, resultado, int(match), int(es_deepfake), score),
                    )
                    conn.commit()
            except Exception as db_error:
                print(f"Error guardando historial: {db_error}")

        return {
            "resultado": resultado,
            "score": score,
            "coincidencia": match,
            "similitud": round(similitud, 3),
            "deepfake": es_deepfake,
            "confianza_antispoof": round(confianza_antispoof, 3),
            "angulos_comparados": cantidad_angulos,
            "sistema": "VisionSegura",
        }

    except Exception as e:
        print(e)
        return {"resultado": "ERROR", "detalle": str(e)}


# ==========================================
# HISTORIAL POR USUARIO (protegido)
# ==========================================

@router.get("/verificaciones/{user_id}")
async def historial_usuario(user_id: int, usuario=Depends(obtener_usuario_actual)):
    # Control de acceso: un usuario normal solo puede ver SU PROPIO
    # historial. Sin esta verificación, cualquier persona logueada
    # podría leer el historial de verificaciones de otro usuario
    # cualquiera con solo cambiar el número en la URL. Los admins sí
    # pueden ver el de cualquiera (ya tienen /admin/historial para eso,
    # pero se permite también aquí por si el frontend lo necesita).
    if usuario.get("user_id") != user_id and usuario.get("rol") != "admin":
        return {"error": "No autorizado para ver el historial de otro usuario"}

    if not DB_DISPONIBLE:
        return {"error": "Sin conexión DB"}

    try:
        with obtener_conexion() as (conn, cursor):
            cursor.execute(
                """
                SELECT Id, Resultado, Coincidencia, EsDeepfake, Score, Fecha
                FROM Verificaciones
                WHERE UsuarioId = ?
                ORDER BY Fecha DESC
                """,
                (user_id,),
            )
            rows = cursor.fetchall()
            return [
                {
                    "id": r[0],
                    "resultado": r[1],
                    "coincidencia": r[2],
                    "esDeepfake": r[3],
                    "score": r[4],
                    "fecha": str(r[5]),
                }
                for r in rows
            ]
    except Exception as e:
        return {"error": str(e)}


# ==========================================
# PANEL DE ADMINISTRACIÓN (solo rol admin)
# ==========================================

@router.get("/admin/historial")
async def admin_historial(usuario=Depends(requerir_admin)):
    """Historial de TODAS las verificaciones de TODOS los usuarios —
    solo accesible con rol admin (ver requerir_admin en auth.py). La
    pantalla "Revisar verificaciones" del panel de admin usa este
    endpoint para mostrar, entre otras cosas, los casos marcados como
    REVISION_MANUAL que necesitan que un humano decida."""
    if not DB_DISPONIBLE:
        return {"error": "Sin conexión DB"}
    try:
        with obtener_conexion() as (conn, cursor):
            # LEFT JOIN: si por alguna razón el usuario fue borrado pero la
            # verificación sigue en la tabla, igual se muestra la fila (con
            # nombre "Desconocido") en vez de desaparecer silenciosamente.
            cursor.execute(
                """
                SELECT V.Id, U.Nombre, V.Resultado, V.Score, V.EsDeepfake, V.Fecha
                FROM Verificaciones V
                LEFT JOIN Usuarios U ON U.Id = V.UsuarioId
                ORDER BY V.Fecha DESC
                """
            )
            rows = cursor.fetchall()
            return [
                {
                    "id": r[0],
                    "clienteNombre": r[1] or "Desconocido",
                    "estado": r[2],
                    "score": r[3],
                    "esDeepfake": bool(r[4]),
                    "fecha": str(r[5]),
                }
                for r in rows
            ]
    except Exception as e:
        return {"error": str(e)}


@router.post("/admin/accionar")
async def admin_accionar(data: AccionarRequest, usuario=Depends(requerir_admin)):
    """Permite al admin cambiar manualmente el resultado de una
    verificación (ej. pasar de REVISION_MANUAL a APROBADO tras
    revisarla a mano) — usado por la pantalla "Revisar verificaciones"."""
    if not DB_DISPONIBLE:
        return {"success": False, "error": "Sin conexión DB"}
    try:
        with obtener_conexion() as (conn, cursor):
            cursor.execute(
                "UPDATE Verificaciones SET Resultado = ? WHERE Id = ?",
                (data.nuevoEstado, data.id),
            )
            conn.commit()
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ==========================================
# ADMIN — USUARIOS Y EMPRESAS
# ==========================================

@router.get("/admin/usuarios")
async def admin_listar_usuarios(usuario=Depends(requerir_admin)):
    """Lista todos los usuarios registrados, con su empresa (si tiene) y
    cuántos ángulos faciales tiene guardados — útil para ver de un
    vistazo si un usuario completó bien su registro biométrico."""
    if not DB_DISPONIBLE:
        return {"error": "Sin conexión DB"}
    try:
        with obtener_conexion() as (conn, cursor):
            # Subconsulta (SELECT COUNT(*)...) dentro del SELECT principal:
            # por cada usuario, cuenta cuántas filas tiene en PerfilesFaciales
            # sin necesidad de una consulta aparte por cada uno.
            cursor.execute(
                """
                SELECT
                    U.Id, U.Nombre, U.Email, U.Documento, U.Rol, U.FechaRegistro,
                    U.EmpresaId, E.Nombre AS EmpresaNombre,
                    (SELECT COUNT(*) FROM PerfilesFaciales PF WHERE PF.UsuarioId = U.Id) AS AngulosGuardados
                FROM Usuarios U
                LEFT JOIN Empresas E ON E.EmpresaId = U.EmpresaId
                ORDER BY U.FechaRegistro DESC
                """
            )
            rows = cursor.fetchall()
            return [
                {
                    "id": r[0],
                    "nombre": r[1],
                    "email": r[2],
                    "documento": r[3],
                    "rol": r[4],
                    "fechaRegistro": str(r[5]),
                    "empresaId": r[6],
                    "empresaNombre": r[7],
                    "angulosGuardados": r[8],
                }
                for r in rows
            ]
    except Exception as e:
        return {"error": str(e)}


@router.get("/admin/empresas")
async def admin_listar_empresas(usuario=Depends(requerir_admin)):
    """Lista todas las empresas/grupos, con cuántos usuarios tiene cada una."""
    if not DB_DISPONIBLE:
        return {"error": "Sin conexión DB"}
    try:
        with obtener_conexion() as (conn, cursor):
            cursor.execute(
                """
                SELECT
                    E.EmpresaId, E.Nombre, E.FechaCreacion,
                    (SELECT COUNT(*) FROM Usuarios U WHERE U.EmpresaId = E.EmpresaId) AS CantidadUsuarios
                FROM Empresas E
                ORDER BY E.Nombre
                """
            )
            rows = cursor.fetchall()
            return [
                {
                    "empresaId": r[0],
                    "nombre": r[1],
                    "fechaCreacion": str(r[2]),
                    "cantidadUsuarios": r[3],
                }
                for r in rows
            ]
    except Exception as e:
        return {"error": str(e)}


@router.post("/admin/empresas")
async def admin_crear_empresa(data: EmpresaCreate, usuario=Depends(requerir_admin)):
    """Crea una empresa/grupo nueva."""
    if not DB_DISPONIBLE:
        return {"status": "error", "message": "Sin conexión DB"}
    try:
        with obtener_conexion() as (conn, cursor):
            cursor.execute(
                "INSERT INTO Empresas (Nombre) OUTPUT INSERTED.EmpresaId VALUES (?)",
                (data.nombre,),
            )
            nueva_id = cursor.fetchone()[0]
            conn.commit()
        return {"status": "ok", "empresaId": nueva_id, "nombre": data.nombre}
    except Exception as e:
        # Nombre de empresa duplicado (UNIQUE constraint) u otro error de datos
        return {"status": "error", "message": str(e)}


@router.put("/admin/usuarios/empresa")
async def admin_asignar_empresa(data: CambiarEmpresaRequest, usuario=Depends(requerir_admin)):
    """Asigna (o quita, si empresa_id es null) la empresa de un usuario."""
    if not DB_DISPONIBLE:
        return {"status": "error", "message": "Sin conexión DB"}
    try:
        with obtener_conexion() as (conn, cursor):
            cursor.execute(
                "UPDATE Usuarios SET EmpresaId = ? WHERE Id = ?",
                (data.empresa_id, data.user_id),
            )
            conn.commit()
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ==========================================
# ADMIN — API KEYS (integraciones externas)
# ==========================================

@router.get("/admin/api-keys")
async def admin_listar_api_keys(usuario=Depends(requerir_admin)):
    """Lista las API keys existentes — NUNCA se devuelve la key en sí
    (solo se guarda su hash), solo sus metadatos."""
    if not DB_DISPONIBLE:
        return {"error": "Sin conexión DB"}
    try:
        with obtener_conexion() as (conn, cursor):
            cursor.execute(
                """
                SELECT AK.Id, AK.Nombre, AK.EmpresaId, E.Nombre, AK.Activa, AK.FechaCreacion, AK.UltimoUso
                FROM ApiKeys AK
                LEFT JOIN Empresas E ON E.EmpresaId = AK.EmpresaId
                ORDER BY AK.FechaCreacion DESC
                """
            )
            rows = cursor.fetchall()
            return [
                {
                    "id": r[0],
                    "nombre": r[1],
                    "empresaId": r[2],
                    "empresaNombre": r[3],
                    "activa": bool(r[4]),
                    "fechaCreacion": str(r[5]),
                    "ultimoUso": str(r[6]) if r[6] else None,
                }
                for r in rows
            ]
    except Exception as e:
        return {"error": str(e)}


@router.post("/admin/api-keys")
async def admin_crear_api_key(data: ApiKeyCreate, usuario=Depends(requerir_admin)):
    """Genera una API key nueva. La key en texto plano SOLO se devuelve
    en esta respuesta — después de esto, ni siquiera el propio sistema
    puede volver a mostrarla (solo se guarda su hash). El admin debe
    copiarla y guardarla en un lugar seguro de inmediato."""
    if not DB_DISPONIBLE:
        return {"status": "error", "message": "Sin conexión DB"}
    try:
        api_key_texto_plano = generar_api_key()
        key_hash = hashear_api_key(api_key_texto_plano)

        with obtener_conexion() as (conn, cursor):
            cursor.execute(
                "INSERT INTO ApiKeys (Nombre, KeyHash, EmpresaId) OUTPUT INSERTED.Id VALUES (?, ?, ?)",
                (data.nombre, key_hash, data.empresa_id),
            )
            nueva_id = cursor.fetchone()[0]
            conn.commit()

        return {
            "status": "ok",
            "id": nueva_id,
            "nombre": data.nombre,
            "api_key": api_key_texto_plano,  # ÚNICA vez que se ve esto — el frontend debe mostrarlo con una advertencia clara
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.put("/admin/api-keys/{api_key_id}/revocar")
async def admin_revocar_api_key(api_key_id: int, usuario=Depends(requerir_admin)):
    """Desactiva una API key (no se borra, para conservar el historial
    de auditoría de qué key se usó cuándo antes de ser revocada)."""
    if not DB_DISPONIBLE:
        return {"status": "error", "message": "Sin conexión DB"}
    try:
        with obtener_conexion() as (conn, cursor):
            cursor.execute("UPDATE ApiKeys SET Activa = 0 WHERE Id = ?", (api_key_id,))
            conn.commit()
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
