import os  # para leer la clave secreta desde una variable de entorno
from jose import JWTError, jwt  # librería para crear y verificar tokens JWT
from datetime import datetime, timedelta
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, APIKeyHeader  # extrae el token/API key de los headers de la petición

from shared.db import obtener_conexion, DB_DISPONIBLE
from modulo_biometria.services.security import verificar_api_key

# Clave secreta usada para "firmar" los tokens — con esto se puede
# verificar que un token no fue falsificado. Se lee de la variable de
# entorno VISIONSEGURA_SECRET_KEY; si no existe, usa un valor por
# defecto SOLO para desarrollo.
#
# En producción, define SECRET_KEY como variable de entorno.
# Nunca dejes una clave fija en el código fuente subido a un repositorio.
SECRET_KEY = os.getenv("VISIONSEGURA_SECRET_KEY", "visionsegura_secret")
ALGORITHM = "HS256"  # algoritmo de firma usado para los tokens JWT

# Objeto de FastAPI que sabe extraer el token del header Authorization
security_scheme = HTTPBearer()

# Objeto de FastAPI que sabe extraer una API key del header "X-API-Key".
# auto_error=False: si el header no viene, NO lanza error automáticamente
# — se necesita para poder ofrecer "JWT o API key, cualquiera de los
# dos sirve" en vez de exigir siempre las dos cosas.
api_key_scheme = APIKeyHeader(name="X-API-Key", auto_error=False)


def crear_token(data: dict):
    """Genera un JWT firmado a partir de un diccionario (ej. {"user_id": 5, "rol": "admin"}).
    El token expira a la hora de haberse creado."""
    to_encode = data.copy()  # copia para no modificar el diccionario original
    expire = datetime.utcnow() + timedelta(minutes=60)  # el token vale por 60 minutos desde ahora
    to_encode.update({"exp": expire})  # "exp" es el campo estándar de JWT para la fecha de expiración
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def verificar_token(token: str):
    """Decodifica y valida un JWT. Devuelve el contenido (payload) si es
    válido, o None si está expirado/corrupto/firmado con otra clave."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None  # token inválido, expirado, o mal formado — no se lanza error aquí, se maneja arriba


def obtener_usuario_actual(
    credentials: HTTPAuthorizationCredentials = Depends(security_scheme),
):
    """Dependencia de FastAPI: protege una ruta exigiendo un JWT válido.
    Uso: async def mi_ruta(usuario = Depends(obtener_usuario_actual))
    """
    payload = verificar_token(credentials.credentials)
    if payload is None:
        # Sin un token válido, se corta la petición aquí mismo con 401 —
        # el código de la ruta protegida ni siquiera llega a ejecutarse.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado",
        )
    return payload  # el contenido del token (user_id, rol) queda disponible en la ruta


def requerir_admin(usuario=Depends(obtener_usuario_actual)):
    """Dependencia adicional: exige además que el usuario tenga rol admin.
    Primero corre obtener_usuario_actual (JWT válido), y luego revisa el rol."""
    if usuario.get("rol") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Requiere permisos de administrador",
        )
    return usuario


def _validar_api_key_contra_db(api_key: str):
    """Busca todas las API keys ACTIVAS y compara el hash — devuelve los
    datos de la key si coincide con alguna, o None si no coincide con
    ninguna o hay algún problema.

    Nota: se recorren todas las keys activas en vez de buscar por el
    hash exacto en el WHERE porque hashear_api_key() (SHA-256) siempre
    da el MISMO resultado para la MISMA key — así que si tuviéramos
    muchísimas API keys activas (miles), sería más eficiente guardar el
    hash indexado y comparar con WHERE KeyHash = ?. Con la cantidad de
    integraciones que se esperan (decenas, no miles, por institución),
    esto es más que suficiente."""
    if not DB_DISPONIBLE:
        return None

    with obtener_conexion() as (conn, cursor):
        cursor.execute(
            "SELECT Id, Nombre, EmpresaId, KeyHash FROM ApiKeys WHERE Activa = 1"
        )
        filas = cursor.fetchall()

        for fila in filas:
            key_id, nombre, empresa_id, key_hash = fila
            if verificar_api_key(api_key, key_hash):
                # Se actualiza cuándo fue la última vez que se usó esta
                # key — útil para que el admin detecte integraciones
                # abandonadas o sospechosamente inactivas.
                cursor.execute(
                    "UPDATE ApiKeys SET UltimoUso = GETDATE() WHERE Id = ?",
                    (key_id,),
                )
                conn.commit()
                return {"api_key_id": key_id, "nombre": nombre, "empresa_id": empresa_id}

    return None


def obtener_usuario_o_api_key(
    credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer(auto_error=False)),
    api_key: str = Depends(api_key_scheme),
):
    """Dependencia flexible: acepta CUALQUIERA de los dos métodos de
    autenticación — un JWT normal (usuario logueado en la app) O una
    API key (sistema externo de un banco/institución integrado).
    Pensada para endpoints que ambos tipos de "cliente" necesitan usar,
    como la evaluación de riesgo de transacciones.

    Devuelve un diccionario con al menos "tipo": "usuario" o "api_key",
    para que el código de la ruta sepa distinguir de dónde vino la
    petición si lo necesita.
    """
    if credentials is not None:
        payload = verificar_token(credentials.credentials)
        if payload is not None:
            return {"tipo": "usuario", **payload}

    if api_key:
        datos = _validar_api_key_contra_db(api_key)
        if datos is not None:
            return {"tipo": "api_key", **datos}

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Se requiere un token de sesión válido o una API key válida (header X-API-Key)",
    )