# Guía de despliegue en producción — FraudShield

Esta guía explica cómo llevar FraudShield de "corriendo en tu máquina"
a "corriendo en un servidor real, con HTTPS, listo para que varios
bancos lo usen a la vez, sin caerse bajo carga".

> ⚠️ **Aviso de transparencia**: los archivos de Docker (`Dockerfile`,
> `docker-compose.yml`, `nginx/`) se revisaron línea por línea con
> mucho cuidado, pero **no se pudieron construir ni correr de verdad**
> en el entorno donde se escribieron (sin Docker instalado ahí). Antes
> de confiar en esto para producción, sigue esta guía paso a paso en tu
> propia máquina o servidor y confirma que cada paso funciona como se
> describe — avísame si algo no coincide con lo documentado aquí, para corregirlo.

---

## 1. Antes de empezar

Necesitas tener instalado en el servidor donde vas a desplegar:

- **Docker** (versión 24 o superior)
- **Docker Compose** (ya viene incluido con Docker Desktop; en Linux
  puede que necesites instalarlo aparte como `docker-compose-plugin`)

Verifica con:
```bash
docker --version
docker compose version
```

## 2. Despliegue local (para probar que todo funciona antes de ir a la nube)

### 2.1. Configura las variables de entorno

```bash
cp .env.example .env
```

Edita `.env` y completa, como mínimo:
- `VISIONSEGURA_SECRET_KEY` — genera una con `openssl rand -hex 32`
- `MSSQL_SA_PASSWORD` — una contraseña fuerte para el SQL Server de prueba

### 2.2. Genera un certificado HTTPS (autofirmado, solo para probar)

Un certificado autofirmado hace que el navegador muestre una advertencia
de "sitio no seguro" — es normal y esperado en desarrollo. Para
producción real, ve a la sección 4.

```bash
mkdir -p nginx/certs
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout nginx/certs/privkey.pem \
  -out nginx/certs/fullchain.pem \
  -subj "/CN=localhost"
```

### 2.3. Levanta todo el stack

```bash
docker compose up --build
```

Esto construye y arranca 3 contenedores: `backend`, `nginx`, y
`sqlserver` (una base de datos de prueba, sin datos todavía).

### 2.4. Crea las tablas en la base de datos

Con el stack corriendo, en otra terminal:
```bash
docker compose exec backend python database/seed_data.py
```

Antes de esto, necesitas correr `database/schema_sqlserver.sql` contra
el SQL Server del contenedor — conéctate con Azure Data Studio o
`sqlcmd` a `localhost:1433` (usuario `sa`, la contraseña que pusiste en
`.env`) y ejecútalo, igual que hiciste en tu instalación local de Windows.

### 2.5. Pruébalo

Abre `https://localhost` en tu navegador (acepta la advertencia del
certificado autofirmado) — deberías ver la pantalla de login de FraudShield.

---

## 3. Escalar a varias réplicas del backend

Este es el comando clave para tu objetivo de "que no se sature":

```bash
docker compose up --build --scale backend=3
```

Esto levanta **3 contenedores del backend corriendo al mismo tiempo**,
y nginx reparte las peticiones entre los 3 automáticamente (ver
`nginx/nginx.conf`) — ni el código ni la configuración de nginx
necesitan cambiar al ajustar este número, solo el comando.

### 3.1. La matemática de cuántas réplicas necesitas

Cada réplica del backend abre su propio pool de conexiones a SQL
Server (`FRAUDSHIELD_DB_POOL_SIZE`, por defecto 20). Si corres varias
réplicas, el total de conexiones que le llegan a SQL Server es:

```
Conexiones totales a SQL Server = número_de_réplicas × FRAUDSHIELD_DB_POOL_SIZE
```

**Ejemplo:** 3 réplicas × 20 conexiones cada una = 60 conexiones
simultáneas a SQL Server.

Antes de escalar, confirma que tu SQL Server (o tu plan de Azure
SQL/RDS) soporta ese total de conexiones — cada nivel de servicio en la
nube tiene su propio límite (por ejemplo, los niveles más económicos de
Azure SQL Database permiten bastante menos conexiones simultáneas que
los niveles empresariales). Si necesitas muchas réplicas, es mejor
BAJAR `FRAUDSHIELD_DB_POOL_SIZE` por réplica (por ejemplo a 10) en vez
de dejarlo en 20 para cada una — sigues teniendo alta concurrencia
total, sin agotar el límite de conexiones de la base de datos.

### 3.2. Qué NO se comparte automáticamente entre réplicas (para tenerlo presente)

- **El respaldo en memoria del historial** (cuando SQL Server no está
  disponible): cada réplica tiene su PROPIA copia en memoria — si una
  petición cae en la réplica A y otra en la réplica B mientras la base
  de datos está caída, no van a ver el historial de la otra. Esto es
  aceptable porque es solo un respaldo temporal (no la fuente real de
  datos), pero vale la pena saberlo.
- **El límite de peticiones por segundo (rate limiting)**: cada réplica
  cuenta su propio límite por separado (ver `shared/rate_limiting.py`).
  Con 3 réplicas y una institución con cuota de 50/segundo, en la
  práctica podría alcanzar hasta 150/segundo en total si el balanceador
  reparte parejo entre las 3. Para un límite EXACTO y global entre
  varias réplicas, el siguiente paso (cuando el sistema crezca) es usar
  Redis como almacén compartido del contador — ya está soportado por la
  librería que se usa (`slowapi`), sería cambiar una sola línea en
  `shared/rate_limiting.py` (`storage_uri="redis://..."`) sin tocar el
  resto del código.

Todo lo demás (JWTs, base de datos, lógica de negocio) SÍ es
completamente compartido y consistente entre réplicas, porque vive en
SQL Server o se calcula sin estado (stateless) en cada petición.

---

## 4. HTTPS de verdad (Let's Encrypt) para producción

Un certificado autofirmado no sirve para producción — los navegadores
y las apps móviles lo rechazarán. Para un certificado real y gratuito:

### Opción A: Certbot en tu propio servidor

```bash
# Instala certbot en el servidor (fuera de Docker)
sudo apt install certbot

# Genera el certificado (requiere que tu dominio ya apunte a este servidor)
sudo certbot certonly --standalone -d app.tubanco.com

# Copia los certificados generados a donde nginx los espera
sudo cp /etc/letsencrypt/live/app.tubanco.com/fullchain.pem nginx/certs/
sudo cp /etc/letsencrypt/live/app.tubanco.com/privkey.pem nginx/certs/
```

Los certificados de Let's Encrypt expiran cada 90 días — programa una
tarea (`cron`) que corra `certbot renew` y vuelva a copiar los archivos
periódicamente, o usa un contenedor certbot dedicado que lo automatice.

### Opción B: Certificado gestionado por tu proveedor de nube

Si despliegas en Azure, AWS, o Google Cloud (ver sección 5), sus
balanceadores de carga (Azure Application Gateway, AWS ALB, Google
Cloud Load Balancer) pueden gestionar el certificado HTTPS por ti
automáticamente — en ese caso, nginx dentro de tu red privada puede
seguir hablando en HTTP simple, y es el balanceador de la nube quien
termina el HTTPS de cara a Internet. Suele ser más simple de mantener
que gestionar Let's Encrypt tú mismo.

---

## 5. Desplegar en la nube

Tres caminos razonables, del más simple al más robusto:

### Opción A — Un servidor con Docker (más simple)

Cualquier VPS (DigitalOcean, Linode, una VM de Azure/AWS/GCP) con
Docker instalado puede correr exactamente lo mismo que probaste en la
sección 2 — es el camino más parecido a lo que ya probamos. Bueno para
empezar o para instituciones más pequeñas.

### Opción B — Azure (natural para SQL Server)

Dado que este proyecto ya usa SQL Server, Azure tiene integración
directa:
- **Azure SQL Database** en vez del contenedor `sqlserver` — quita ese
  servicio de `docker-compose.yml` y apunta `FRAUDSHIELD_DB_SERVER` a
  tu instancia de Azure SQL.
- **Azure Container Apps** o **Azure App Service** para correr el
  backend — ambos escalan automáticamente el número de réplicas según
  la carga (escalamiento automático, sin que tengas que correr el
  comando `--scale` a mano).
- **Azure Application Gateway** o **Front Door** en vez de tu propio
  nginx, si prefieres que Azure gestione el balanceo de carga y el
  certificado HTTPS por ti.

### Opción C — AWS

- **Amazon RDS for SQL Server** en vez del contenedor `sqlserver`.
- **Amazon ECS con Fargate** para correr el backend sin gestionar
  servidores directamente, con auto-escalamiento configurable.
- **Application Load Balancer (ALB)** para el HTTPS y el balanceo de carga.

En cualquiera de las tres opciones, la lógica del proyecto (pool de
conexiones, reconexión automática, rate limiting, CORS) funciona igual
— lo único que cambia es QUIÉN gestiona la infraestructura alrededor
(tú manualmente con Docker Compose, o el proveedor de nube de forma administrada).

---

## 6. Checklist antes de ir a producción con un banco real

- [ ] `VISIONSEGURA_SECRET_KEY` cambiada a un valor aleatorio único (no el de desarrollo)
- [ ] `FRAUDSHIELD_FRONTEND_URLS` apunta a la URL REAL del frontend (no `localhost`)
- [ ] Certificado HTTPS real (Let's Encrypt o gestionado por la nube), no autofirmado
- [ ] Contraseña de SQL Server fuerte y única, guardada en un gestor de secretos (no en un archivo `.env` sin cifrar en el servidor)
- [ ] `FRAUDSHIELD_DB_POOL_SIZE` ajustado según cuántas réplicas vas a correr y el límite de conexiones de tu SQL Server
- [ ] Límite de peticiones (`LimiteRPS`) configurado para cada institución que reciba una API key — ver docs/GUIA_INTEGRACION.md
- [ ] Backups automáticos configurados en tu SQL Server (esto lo gestiona el servicio de nube si usas Azure SQL/RDS)
- [ ] Revisar `docs/GUIA_INTEGRACION.md` con el equipo técnico del banco antes de que integren su app

---

## 7. Ver los logs (para depurar problemas)

```bash
docker compose logs -f backend    # logs de todas las réplicas del backend
docker compose logs -f nginx      # logs de nginx
```

Los mensajes que ya conoces del backend (conexión a SQL Server, límites
de rate limiting, reconexión automática) aparecen aquí igual que
cuando lo corrías directamente con `uvicorn`.
