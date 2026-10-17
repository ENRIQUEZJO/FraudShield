"""
main.py

Punto de entrada único del backend unificado.
Monta los routers de VisionSegura (modulo_biometria) y
sistema-antifraude (modulo_antifraude) bajo una sola app FastAPI.
"""
import os
# FastAPI: el framework web que expone todos los endpoints (/api/v1/...)
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
# CORSMiddleware: permite que el frontend (que corre en otro puerto/origen,
# ej. localhost:5173) pueda llamar a este backend (localhost:8000) sin que
# el navegador lo bloquee por política de "same-origin".
from fastapi.middleware.cors import CORSMiddleware

from slowapi.errors import RateLimitExceeded

# Cada módulo expone su propio "router" (grupo de endpoints). Se importan
# aquí para montarlos todos juntos en una sola app más abajo.
from modulo_biometria.router import router as biometria_router
from modulo_antifraude.router import router as antifraude_router
from shared.orquestador import router as orquestador_router
from shared.rate_limiting import limiter

# Instancia única de la aplicación FastAPI — todo lo demás se cuelga de esta.
app = FastAPI(title="FraudShield")

# Registra el limitador de peticiones (shared/rate_limiting.py) en la
# app. app.state.limiter es dónde slowapi espera encontrarlo.
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def manejador_limite_excedido(request: Request, exc: RateLimitExceeded):
    """Respuesta clara cuando se excede el límite de peticiones — en vez
    del error genérico que da slowapi por defecto. Incluye el header
    "Retry-After" para que quien integra sepa exactamente cuánto esperar
    antes de reintentar."""
    return JSONResponse(
        status_code=429,
        content={
            "error": "Límite de peticiones excedido",
            "detalle": (
                "Esta institución/usuario superó su cuota de peticiones por "
                "segundo. Espera un momento antes de reintentar. Si tu "
                "integración necesita un límite más alto de forma "
                "sostenida, contacta al administrador de FraudShield."
            ),
            "limite": str(exc.detail),
        },
        headers={"Retry-After": "1"},
    )


# Configuración de CORS: qué dominios pueden hacerle peticiones a este
# backend desde un navegador.
#
# Se lee de la variable de entorno FRAUDSHIELD_FRONTEND_URLS — una lista
# separada por comas con la(s) URL(s) real(es) del frontend en
# producción, por ejemplo:
#   FRAUDSHIELD_FRONTEND_URLS=https://app.tubanco.com,https://admin.tubanco.com
#
# Si esa variable NO está definida, se usan valores por defecto pensados
# SOLO para desarrollo local (donde Vite corre en localhost:5173) — con
# un aviso claro en la consola para que no pase desapercibido en un
# despliegue real.
_origenes_configurados = os.getenv("FRAUDSHIELD_FRONTEND_URLS", "").strip()

if _origenes_configurados:
    ALLOWED_ORIGINS = [o.strip() for o in _origenes_configurados.split(",") if o.strip()]
else:
    ALLOWED_ORIGINS = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
    print(
        "⚠️  [CORS] FRAUDSHIELD_FRONTEND_URLS no está configurada — usando "
        f"orígenes de DESARROLLO por defecto: {ALLOWED_ORIGINS}. "
        "Antes de un despliegue real, define esa variable con la URL "
        "verdadera del frontend del banco."
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,  # solo estos dominios pueden llamar a la API — ya no "*"
    allow_credentials=True,         # permite enviar cookies/credenciales (no se usan hoy, pero no estorba dejarlo)
    allow_methods=["*"],            # permite GET, POST, PUT, etc. sin restricción
    allow_headers=["*"],            # permite cualquier header custom (ej. Authorization, X-API-Key)
)

# Monta cada router bajo su propio "prefijo" de URL. Por ejemplo, el
# endpoint /login definido dentro de modulo_biometria/router.py queda
# accesible como POST /api/v1/biometria/login.
app.include_router(biometria_router, prefix="/api/v1/biometria")
app.include_router(antifraude_router, prefix="/api/v1/transacciones")
app.include_router(orquestador_router, prefix="/api/v1/transferencia")


# Endpoint raíz — solo para confirmar rápidamente que el backend está
# vivo y qué módulos tiene montados (útil al abrir http://localhost:8000
# directamente en el navegador).
@app.get("/")
def root():
    return {
        "servicio": "FraudShield",
        "modulos": ["biometria", "antifraude", "transferencia (orquestador)"],
    }


# Este bloque solo se ejecuta si corres "python main.py" directamente
# (no si usas "uvicorn main:app --reload", que es el modo recomendado
# para desarrollo porque recarga solo al detectar cambios en el código).
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
