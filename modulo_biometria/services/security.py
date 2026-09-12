import secrets
import hashlib  # para hashear las API keys (SHA-256 — distinto de bcrypt, ver nota abajo)
from passlib.context import CryptContext  # librería para hashear/verificar contraseñas de forma segura

# CryptContext configurado para usar bcrypt — un algoritmo de hasheo
# diseñado específicamente para contraseñas (lento a propósito, para
# dificultar ataques de fuerza bruta). "deprecated='auto'" hace que, si
# en el futuro se cambia de algoritmo, las contraseñas viejas sigan
# reconociéndose y se puedan re-hashear automáticamente.
#
# NOTA: bcrypt está fijado a la versión 4.0.1 en requirements.txt — las
# versiones más nuevas (4.1+) rompen la compatibilidad con esta librería
# passlib (ver README, sección de solución de problemas).
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hashear_password(password: str) -> str:
    """Genera el hash seguro de una contraseña en texto plano.
    Se usa al registrar un usuario — NUNCA se guarda la contraseña tal
    cual en la base de datos, solo este hash (irreversible)."""
    return pwd_context.hash(password)


def verificar_password(password_plano: str, password_hash: str) -> bool:
    """Compara una contraseña en texto plano (la que el usuario escribe
    al hacer login) contra su hash almacenado en la base de datos."""
    return pwd_context.verify(password_plano, password_hash)


def generar_api_key() -> str:
    """Genera una API key nueva: una cadena aleatoria de alta entropía
    (64 caracteres hexadecimales) para que un sistema externo (de un
    banco o institución afiliada) se autentique contra FraudShield sin
    pasar por el login de usuario normal. Ver modulo_biometria/router.py
    (endpoints /admin/api-keys) para dónde se usa."""
    return secrets.token_hex(32)


def hashear_api_key(api_key: str) -> str:
    """Convierte una API key en texto plano a su hash, para guardarlo en
    la base de datos (tabla ApiKeys.KeyHash).

    Se usa SHA-256 en vez de bcrypt (como con las contraseñas) a propósito:
    bcrypt es LENTO adrede, pensado para contraseñas cortas que un humano
    podría adivinar por fuerza bruta. Una API key ya es una cadena
    aleatoria de 64 caracteres — nadie la va a "adivinar" probando
    combinaciones, así que no hace falta ese costo extra; SHA-256 es
    rápido y sigue siendo imposible de revertir (no se puede recuperar
    la key original a partir del hash)."""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def verificar_api_key(api_key_recibida: str, hash_guardado: str) -> bool:
    """Compara una API key recibida (ej. en el header X-API-Key de una
    petición) contra el hash guardado en la base de datos."""
    return hashear_api_key(api_key_recibida) == hash_guardado