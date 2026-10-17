# nginx/Dockerfile
#
# Este Dockerfile tiene DOS etapas ("multi-stage build"):
#   Etapa 1 ("build"): usa una imagen con Node.js para compilar el
#     frontend (npm install + npm run build) — genera los archivos
#     estáticos finales (HTML/CSS/JS) en la carpeta dist/.
#   Etapa 2: usa una imagen liviana de nginx y SOLO copia el resultado
#     de la etapa 1 (los archivos ya compilados) — así la imagen final
#     no carga con Node.js ni con node_modules, que no hacen falta para
#     SERVIR los archivos, solo para construirlos.

# --- Etapa 1: construir el frontend ---
FROM node:20-slim AS build

WORKDIR /app
COPY frontend/vite-app/package.json frontend/vite-app/package-lock.json ./
RUN npm install

COPY frontend/vite-app/ .
RUN npm run build
# En este punto, /app/dist tiene los archivos finales del frontend.

# --- Etapa 2: imagen final, solo con nginx + los archivos ya compilados ---
FROM nginx:1.27-alpine

# Se copian los archivos del frontend generados en la etapa anterior.
COPY --from=build /app/dist /usr/share/nginx/html

# Se copia la configuración de nginx de este proyecto (proxy al
# backend, HTTPS, balanceo de carga) — reemplaza la config por defecto
# que trae la imagen de nginx.
COPY nginx/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80 443
