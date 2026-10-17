"""
shared/rate_limiting.py

Sistema de límite de peticiones (rate limiting) para evitar que una
sola integración (o un ataque) sature el backend o acapare toda la
capacidad de la base de datos, perjudicando a las demás instituciones
que usan el mismo sistema.

CÓMO SE DECIDIÓ EL NÚMERO: Visa (la red de pagos más grande del mundo,
operando en más de 200 países) procesa en promedio 1,700-4,000
transacciones por segundo, con picos históricos documentados de hasta
65,000-83,000 mensajes por segundo en su infraestructura global. Un
banco individual o regional está muy por debajo de esa escala — y
FraudShield no evalúa CADA swipe de tarjeta, solo transferencias
puntuales donde importa verificar identidad+riesgo, un subconjunto
bastante menor del total de operaciones de un banco.

Por eso, en vez de un solo número fijo "para todos", cada institución
(cada API key) tiene su PROPIO límite configurable
(ApiKeys.LimiteRPS), que el admin ajusta según el tamaño real de esa
integración — un banco pequeño y un banco grande no deberían competir
por la misma cuota. Ver docs/GUIA_INTEGRACION.md para cómo se solicita
un límite más alto.

LIMITACIÓN A TENER EN CUENTA SI SE CORREN VARIAS INSTANCIAS DEL BACKEND
(ver docs/DESPLIEGUE.md): este límite se cuenta EN MEMORIA de cada
instancia del backend por separado. Si tienes, por ejemplo, 4 instancias
detrás de un balanceador de carga y una institución tiene un límite de
50/segundo, en la práctica podría alcanzar hasta 4×50=200/segundo en
total (50 en cada instancia) si el balanceador reparte parejo. Para un
límite EXACTO y global entre varias instancias, hace falta un backend
de conteo compartido como Redis (`storage_uri="redis://..."` — slowapi
ya lo soporta, ver comentario en `limiter` más abajo) — se documenta
como el siguiente paso natural cuando el sistema crezca a varias
instancias, sin necesidad de cambiar el resto de este código.
"""
import os
import time
import threading

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from modulo_biometria.auth import verificar_token
from modulo_biometria.services.security import hashear_api_key
from shared.db import obtener_conexion, DB_DISPONIBLE

# Límite por defecto para un usuario normal de la app (una persona
# usando su propio celular) — generoso para un solo dispositivo, pero
# bajo comparado con una integración institucional, porque una sola
# persona nunca necesita hacer decenas de transferencias por segundo.
LIMITE_USUARIO_APP_RPS = int(os.getenv("FRAUDSHIELD_RATE_LIMIT_USUARIO", "10"))

# Límite para peticiones que no se pudieron identificar (sin token ni
# API key válidos) — deliberadamente bajo, ya que legítimamente nadie
# sin autenticarse debería estar haciendo muchas peticiones seguidas.
LIMITE_SIN_IDENTIFICAR_RPS = int(os.getenv("FRAUDSHIELD_RATE_LIMIT_ANONIMO", "3"))

# Límite por defecto para una API key que todavía no tiene uno
# configurado explícitamente en la base de datos.
LIMITE_API_KEY_DEFECTO_RPS = 10

# Cada cuánto se refresca el límite de una API key desde la base de
# datos — evita una consulta a SQL Server en CADA petición; se cachea
# en memoria y se refresca cada cierto tiempo (igual patrón que
# graph_analyzer.py y model.py).
INTERVALO_REFRESCO_SEGUNDOS = 60

_cache_limites: dict[str, tuple[int, float]] = {}  # key_hash -> (limite_rps, momento_en_que_se_cacheo)
_cache_lock = threading.Lock()


def _obtener_limite_api_key(key_hash: str) -> int:
    """Devuelve el LimiteRPS configurado para esta API key, usando una
    caché en memoria para no consultar la base de datos en cada
    petición. Si no se puede consultar (sin DB, o la key no existe),
    devuelve el límite por defecto — nunca bloquea la petición por un
    problema de la caché en sí."""
    ahora = time.time()

    with _cache_lock:
        cacheado = _cache_limites.get(key_hash)
        if cacheado and (ahora - cacheado[1]) < INTERVALO_REFRESCO_SEGUNDOS:
            return cacheado[0]

    if not DB_DISPONIBLE:
        return LIMITE_API_KEY_DEFECTO_RPS

    try:
        with obtener_conexion() as (conn, cursor):
            cursor.execute("SELECT LimiteRPS FROM ApiKeys WHERE KeyHash = ? AND Activa = 1", (key_hash,))
            fila = cursor.fetchone()
        limite = int(fila[0]) if fila and fila[0] is not None else LIMITE_API_KEY_DEFECTO_RPS
    except Exception:
        limite = LIMITE_API_KEY_DEFECTO_RPS

    with _cache_lock:
        _cache_limites[key_hash] = (limite, ahora)

    return limite


def identificar_cliente(request: Request) -> str:
    """Determina QUIÉN está haciendo la petición, para que el límite de
    velocidad se cuente por separado para cada institución/usuario — así
    una integración que hace muchas peticiones no le "quita cuota" a
    otra completamente distinta.

    Se lee directamente de los headers de la petición (sin pasar por
    las dependencias de FastAPI/Depends) porque slowapi necesita esta
    función ANTES de que se resuelvan las dependencias normales de la ruta.
    """
    api_key = request.headers.get("X-API-Key")
    if api_key:
        # Se identifica por el HASH de la key, nunca por la key en texto
        # plano — ni siquiera en la memoria interna del rate limiter.
        return f"apikey:{hashear_api_key(api_key)}"

    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        payload = verificar_token(auth_header[7:])
        if payload:
            return f"usuario:{payload.get('user_id')}"

    # Sin ninguna credencial identificable — se agrupa por IP como
    # último recurso, para al menos limitar peticiones anónimas sueltas.
    return f"ip:{get_remote_address(request)}"


def limite_dinamico(key: str) -> str:
    """Devuelve el límite de peticiones por segundo que le corresponde a
    QUIEN está haciendo esta petición — distinto según sea una API key
    institucional (con su propio LimiteRPS configurado), un usuario
    normal de la app, o una petición sin identificar.

    IMPORTANTE sobre la firma de esta función: slowapi (la librería de
    rate limiting) exige que el parámetro se llame exactamente "key" —
    así detecta automáticamente que debe llamarla con el resultado de
    identificar_cliente(request) en vez de con la petición completa.
    Por eso "key" ya viene como el string "apikey:<hash>",
    "usuario:<id>", o "ip:<ip>" — no hay que volver a leer headers aquí.
    """
    if key.startswith("apikey:"):
        key_hash = key[len("apikey:"):]
        limite = _obtener_limite_api_key(key_hash)
        return f"{limite}/second"

    if key.startswith("usuario:"):
        return f"{LIMITE_USUARIO_APP_RPS}/second"

    return f"{LIMITE_SIN_IDENTIFICAR_RPS}/second"


# El Limiter de slowapi. storage_uri="memory://" guarda los contadores
# en la memoria de ESTE proceso — funciona perfecto para una sola
# instancia del backend. Si más adelante se corren varias instancias
# (ver docs/DESPLIEGUE.md), basta con cambiar esta línea a
# storage_uri="redis://<host-redis>:6379" para que el conteo sea EXACTO
# y compartido entre todas las instancias — el resto del código no
# necesita cambiar.
limiter = Limiter(key_func=identificar_cliente, storage_uri="memory://")
