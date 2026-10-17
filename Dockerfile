# Dockerfile — backend de FraudShield
#
# IMPORTANTE: se usa Python 3.11, NO la última versión disponible —
# TensorFlow (que usa DeepFace para el reconocimiento facial) todavía
# no soporta Python 3.14+ al momento de escribir esto. Ver
# requirements.txt para más detalle sobre esta restricción.
FROM python:3.11-slim

# Evita que Python guarde archivos .pyc y que el output se quede
# "atrapado" en el buffer sin mostrarse en los logs del contenedor —
# ambas cosas facilitan la depuración cuando algo falla.
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# ============================================================
# DEPENDENCIAS DEL SISTEMA OPERATIVO (no son paquetes de Python —
# son librerías que el sistema operativo del contenedor necesita
# tener instaladas para que ciertos paquetes de Python funcionen)
# ============================================================
#
# - curl, gnupg2: necesarios para agregar el repositorio de Microsoft
#   y descargar el driver ODBC de SQL Server.
# - unixodbc-dev, msodbcsql17: el driver real que pyodbc usa para
#   hablar con SQL Server (el mismo "ODBC Driver 17 for SQL Server"
#   que instalaste en Windows para desarrollo — aquí se instala la
#   versión para Linux, porque el contenedor corre Linux por dentro
#   sin importar en qué sistema operativo esté la máquina que lo ejecuta).
# - libgl1, libglib2.0-0, libsm6, libxext6, libxrender1: librerías
#   gráficas de bajo nivel que OpenCV (usado por DeepFace) necesita
#   para procesar imágenes, aunque el contenedor nunca abra una
#   ventana gráfica real.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gnupg2 \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    && curl https://packages.microsoft.com/keys/microsoft.asc | apt-key add - \
    && curl https://packages.microsoft.com/config/debian/12/prod.list > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql17 unixodbc-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Se copia SOLO requirements.txt primero (antes que el resto del código)
# a propósito: Docker guarda en caché cada paso ("layer"). Mientras no
# cambies las dependencias, este paso pesado (instalar TensorFlow,
# PyTorch, etc.) no se vuelve a ejecutar cada vez que cambias una línea
# de tu código — solo cuando cambia requirements.txt. Esto hace que
# reconstruir la imagen después de un cambio de código sea mucho más rápido.
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Ahora sí se copia el resto del código del backend.
COPY main.py .
COPY modulo_biometria ./modulo_biometria
COPY modulo_antifraude ./modulo_antifraude
COPY shared ./shared
COPY database ./database

# El backend escucha en este puerto DENTRO del contenedor — no significa
# que sea accesible desde afuera automáticamente, eso se controla en
# docker-compose.yml o en el comando "docker run -p".
EXPOSE 8000

# Comando que arranca el servidor cuando el contenedor inicia.
# --host 0.0.0.0 es OBLIGATORIO en Docker: significa "escucha en todas
# las interfaces de red", no solo en localhost — sin esto, nadie podría
# conectarse al backend desde fuera del contenedor, ni siquiera
# docker-compose. --workers 1 porque la escalabilidad de este proyecto
# se maneja corriendo VARIOS CONTENEDORES (ver docker-compose.yml y
# docs/DESPLIEGUE.md), no varios procesos dentro de un mismo contenedor
# — cada contenedor ya tiene su propio pool de conexiones a la base de
# datos (shared/db.py), y complicar eso con múltiples workers por
# contenedor no aporta beneficio real aquí.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
