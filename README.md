# FraudShield

Backend unificado que combina dos sistemas antes independientes, ahora
sobre **un solo motor de base de datos: SQL Server**.

- **`modulo_biometria`** (antes VisionSegura) — verificación de identidad por
  reconocimiento facial + anti-spoofing/deepfake.
- **`modulo_antifraude`** (antes sistema-antifraude) — detección de mulas
  bancarias mediante reglas heurísticas + análisis de grafos + ML
  (IsolationForest).
- **`shared/orquestador.py`** — endpoint que combina ambos módulos en un
  solo flujo de transferencia (identidad → riesgo → veredicto).
- **`shared/db.py`** — conexión única a SQL Server, compartida por los tres.

> `modulo_antifraude` usaba PostgreSQL originalmente (y su `seed_data.py`
> usaba SQLite aparte). Todo eso se migró a SQL Server — los archivos
> originales quedaron archivados en `database/legacy_postgresql/` solo
> como referencia histórica, ya no se usan.

Nota de diseño que sigue pendiente (no bloquea las pruebas del MVP): las
tablas `Usuarios` (biometría) y `Clientes` (antifraude) todavía son dos
identidades de usuario separadas, aunque ahora vivan en la misma base de
datos. Unificarlas en una sola entidad de usuario es una decisión aparte,
pospuesta para después de la validación con el banco.

---

## 1. Requisitos previos

- **Python 3.10, 3.11, 3.12 o 3.13** — NO uses Python 3.14: `tensorflow`
  (requerido por `deepface` para el reconocimiento facial) todavía no
  tiene soporte para esa versión y la instalación fallará a medias sin
  avisar claramente por qué.
- Node.js 18+ (para el frontend Vite)
- **SQL Server** corriendo, con el **ODBC Driver 17 for SQL Server**
  instalado en la máquina
- Sin SQL Server disponible, el backend arranca igual — cada módulo cae a
  un respaldo controlado (ver sección 6) en vez de fallar.

## 2. Base de datos

Ejecuta el schema único contra tu instancia de SQL Server:

```
database/schema_sqlserver.sql
```

Esto crea la base de datos `FraudShieldDB` con las tablas de los tres
módulos:

| Tabla | Módulo |
|---|---|
| `Usuarios`, `PerfilesFaciales`, `Verificaciones`, `Empresas` | Biometría |
| `Clientes`, `PerfilesFinancieros`, `TelemetriaComportamiento`, `Transferencias` | Antifraude |
| `VerificacionesTransferencia` | Orquestador |

**Registro facial multi-ángulo**: el registro ya no guarda una sola foto —
pide 4 gestos (`centro`, `izquierda`, `derecha`, `arriba`) y guarda un
embedding facial por cada uno en `PerfilesFaciales`. En cada verificación
posterior, se compara el rostro en vivo contra los 4 ángulos guardados y
se toma la mejor coincidencia — más tolerante a variaciones de ángulo/luz
que un solo embedding, y más difícil de burlar con una sola foto estática.
La columna `Usuarios.FaceEncoding` queda en la tabla solo por compatibilidad
con filas antiguas; el código ya no escribe ahí.

Incluye el trigger de "vaciado rápido en cuenta dormida" (equivalente al
que tenía la versión PostgreSQL original, convertido a T-SQL).

Para cargar datos de prueba (clientes de ejemplo, incluyendo uno con
cuenta dormida para probar el trigger):

```bash
python database/seed_data.py
```

> Si ya habías corrido `schema_sqlserver.sql` antes de esta actualización
> (sin la tabla `PerfilesFaciales`), puedes volver a correrlo sin
> problema — todas las sentencias usan `IF NOT EXISTS`, así que solo
> agrega lo que falta sin tocar tus tablas existentes.

## 3. Backend

```bash
cd FraudShield
python -m venv venv
source venv/bin/activate        # En Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Por defecto, `shared/db.py` se conecta a `DESKTOP-TKPM2HC` / `FraudShieldDB`
con autenticación de Windows (`Trusted_Connection=yes`). Para apuntar a
otro servidor, define las variables de entorno antes de arrancar:

```bash
export FRAUDSHIELD_DB_SERVER=tu_servidor
export FRAUDSHIELD_DB_NAME=FraudShieldDB
```

Levanta el servidor:

```bash
python main.py
```

Esto arranca **una sola app FastAPI** en `http://127.0.0.1:8000` con los
tres grupos de endpoints:

| Prefijo | Módulo | Ejemplos |
|---|---|---|
| `/api/v1/biometria` | VisionSegura | `/login`, `/register`, `/verificar`, `/admin/historial` |
| `/api/v1/transacciones` | sistema-antifraude | `/evaluar`, `/historial` |
| `/api/v1/transferencia` | Orquestador | `/procesar`, `/historial` |

Documentación interactiva (Swagger) disponible en:
`http://127.0.0.1:8000/docs`

## 4. Configuración de producción (pool de conexiones, CORS, API keys)

**Pool de conexiones (soporta muchos usuarios/instituciones a la vez):**
`shared/db.py` ya no usa una sola conexión compartida — abre un grupo de
conexiones de antemano (por defecto 20) y las presta a cada petición que
las necesita, devolviéndolas al terminar. Configurable:

```bash
export FRAUDSHIELD_DB_POOL_SIZE=30       # cuántas conexiones mantener abiertas
export FRAUDSHIELD_DB_POOL_TIMEOUT=10    # segundos a esperar por una conexión libre antes de fallar
```

Si ves el error "El pool de conexiones está agotado" seguido en los
logs, es señal de que `FRAUDSHIELD_DB_POOL_SIZE` se quedó corto para el
tráfico real — súbelo. Se probó con 20-30 peticiones HTTP concurrentes
reales contra la app completa, todas exitosas y sin colisiones.

**Reconexión automática:** un hilo en segundo plano revisa cada 30
segundos (configurable) si SQL Server está disponible. Si el servidor
estaba caído cuando arrancó el backend y luego se levanta, el pool se
reconstruye solo — no hace falta reiniciar el proceso. Si el servidor
se cae DESPUÉS de haber arrancado bien, el mismo hilo lo detecta (tras
3 fallos seguidos, para no reaccionar de más a un timeout suelto de
red) y marca la base de datos como no disponible hasta que vuelva a
responder. Configurable:

```bash
export FRAUDSHIELD_DB_RECONNECT_SEGUNDOS=30   # cada cuánto revisa si SQL Server sigue disponible
```

Probado en este entorno con un servidor simulado: caída al arrancar →
recuperación automática, caída en pleno funcionamiento (con peticiones
en curso) → recuperación automática, sin corromper el pool ni perder
ninguna petición que ya estaba usando una conexión al momento de la caída.

**CORS restringido a la URL real del frontend:**

```bash
export FRAUDSHIELD_FRONTEND_URLS=https://app.tubanco.com,https://admin.tubanco.com
```

Sin esta variable, el backend usa `http://localhost:5173` (donde corre
Vite en desarrollo) y muestra una advertencia en los logs — no la dejes
así en un despliegue real.

**API Keys (integraciones de otros bancos/instituciones):**
Desde el panel de admin (pestaña "API Keys") se pueden generar
credenciales para que un sistema externo llame directamente al
endpoint de evaluación de riesgo (`POST /api/v1/transacciones/evaluar`)
sin pasar por el login de un usuario — pensado para que un banco
afiliado integre sus propios sistemas. La key se muestra **una sola
vez** al crearla (solo se guarda su hash, nunca la key en texto plano —
igual que con las contraseñas). Uso desde un sistema externo:

```bash
curl -X POST https://tu-servidor/api/v1/transacciones/evaluar \
  -H "X-API-Key: la_key_generada" \
  -H "Content-Type: application/json" \
  -d '{"cliente_id": 1, "monto": 3000, "cuenta_destino": "ACC1", "llamada_activa": false, "tiempo_desde_deposito_minutos": 120}'
```

Ese mismo endpoint también sigue aceptando el login normal (JWT) — sirve
cualquiera de los dos.

**Motor de grafos y de Machine Learning con datos reales:**
Antes usaban datos de ejemplo fijos. Ahora:
- El análisis de grafos (`graph_analyzer.py`) construye la red de
  transferencias a partir de la tabla `Transferencias` real, y se
  refresca cada 5 minutos (`FRAUDSHIELD_GRAPH_REFRESH_SEGUNDOS`).
- El modelo de ML (`model.py`) se reentrena cada 30 minutos
  (`FRAUDSHIELD_ML_RETRAIN_SEGUNDOS`) con las transacciones reales
  marcadas como `APROBADA` — mientras haya menos de 30 transacciones
  reales en la base de datos, sigue usando el modelo sintético de
  ejemplo, para que el sistema funcione desde el primer día sin esperar
  semanas a acumular historial.

Se probó todo el flujo (grafo detectando una cuenta recolectora real,
modelo de ML aprendiendo un patrón real y detectando una anomalía) con
una base de datos simulada en este entorno — sin SQL Server real
disponible aquí, pero la lógica quedó verificada de punta a punta.

## 5. Pantalla de administración: revisión manual

Pestaña "Revisar verificaciones" del panel de admin: lista los casos
marcados como `REVISION_MANUAL` (donde ni la biometría ni el antifraude
dieron un veredicto claro) para que un humano decida — con botones
Aprobar/Rechazar que llaman a `POST /admin/accionar`. Por defecto
muestra solo los pendientes; hay un filtro para ver el historial completo.

## 6. Frontend — página única (perfil + dashboard de los 3 módulos)

```bash
cd FraudShield/frontend/vite-app
npm install
npm run dev
```

Ya está configurado (`api.js`) para apuntar al backend en
`http://127.0.0.1:8000`, así que solo necesita que este esté corriendo en
paralelo.

**Captura automática de gestos en el registro:** usa `@mediapipe/tasks-vision`
(FaceLandmarker) para detectar hacia dónde está girada tu cabeza en tiempo
real y capturar sola cuando coincide con el gesto pedido (sostenida ~0.7
segundos, con una barra de progreso visual). El modelo se descarga desde
un CDN de Google la primera vez que abres el registro (tarda unos
segundos, requiere internet). Si el detector no carga o falla por
cualquier razón, queda un botón de "Capturar manualmente" como respaldo
para no bloquear el registro.

> ⚠️ Esta detección automática **no se pudo probar con una cámara real**
> en el entorno donde se desarrolló (sin navegador/webcam disponible) —
> se verificó que el código compila y el modelo se carga, pero los rangos
> de ángulo (`RANGOS_GESTOS` en `useDeteccionGestoFacial.js`) están
> calibrados de forma razonable, no probados con rostros reales. Es
> posible que necesites ajustar esos rangos (más flexibles o más
> estrictos) según cómo se sienta en la práctica — están comentados en el
> archivo para que sea fácil tocarlos.

Es **una sola página** (React SPA) con:

- **Login** — con email y contraseña, usando un usuario ya registrado.
- **Mi Perfil** — nombre, rol e ID del usuario autenticado, con botón de
  cerrar sesión.
- **Registro** — captura guiada de 4 ángulos del rostro (automática, con
  respaldo manual).
- **Verificación** — detecta el rostro y verifica automáticamente en
  cuanto lo tienes centrado frente a la cámara, sin necesidad de dar
  clic; queda un botón "Verificar manualmente" como respaldo.
- **Dashboard** — con tres pestañas internas:
  - *VisionSegura*: historial de verificaciones de identidad.
  - *Sistema Antifraude*: formulario para evaluar una transacción de
    prueba — se evalúa sola en cuanto llenas todos los campos (con un
    pequeño margen de espera por si sigues escribiendo), con botón
    "Evaluar manualmente" como respaldo. Historial de evaluaciones.
  - *Orquestador*: la cámara captura la foto sola (igual que en
    Verificación) y, en cuanto también llenaste los datos de la
    transacción, procesa el flujo completo automáticamente — con botón
    "Procesar manualmente" como respaldo. Historial de veredictos
    combinados.
- **Administración** — solo visible si el usuario tiene rol `admin`
  (guardado en `localStorage.rol` desde el login). Tres pestañas:
  - *Usuarios*: lista todos los usuarios registrados (nombre, email,
    documento, rol, cuántos ángulos faciales tiene guardados) con un
    selector por fila para asignarlo a una empresa.
  - *Empresas*: crear nuevas empresas/grupos y ver cuántos usuarios
    tiene cada una.
  - *Registrar usuario*: el mismo flujo de registro con captura
    automática de 4 ángulos, pero con un selector de empresa adicional
    — para que un admin dé de alta usuarios directamente sin que se
    autorregistren.

> Para tener tu primer usuario admin, regístrate normalmente y luego
> ejecuta en SQL Server: `UPDATE Usuarios SET Rol = 'admin' WHERE Email
> = 'tu@email.com'` (este comando ya está comentado al final de
> `database/schema_sqlserver.sql`).

> ⚠️ El auto-envío de los formularios (Sistema Antifraude y Orquestador)
> usa un pequeño margen de espera (~0.9s) después del último campo
> llenado antes de disparar, para no enviar a mitad de que escribes. No
> se pudo probar en un navegador real qué tan cómodo se siente ese
> tiempo de espera — si se siente muy apurado o muy lento, es el valor
> `DEBOUNCE_AUTO_ENVIO_MS` al inicio de cada archivo.
  - *Sistema Antifraude*: formulario para evaluar una transacción de
    prueba + historial de evaluaciones.
  - *Orquestador*: formulario para probar el flujo completo (foto +
    datos de transacción) + historial de veredictos combinados.

## 7. Frontend — pantalla de transferencia (sistema-antifraude, independiente)

Es un HTML estático, sin build tool. Ábrelo directamente en el navegador:

```
FraudShield/frontend/assets/transfer_screen.html
```

Ya apunta a `http://localhost:8000/api/v1/transacciones/evaluar`, así que
solo necesita el backend corriendo.

## 8. Comportamiento sin SQL Server disponible

Cada módulo maneja la ausencia de base de datos de forma distinta según
qué tan crítica sea para su función:

- **Biometría**: el registro/login/verificación requieren la tabla
  `Usuarios` — sin conexión, esos endpoints devuelven un error controlado
  (`"Sin conexión DB"`), pero el resto de la app sigue funcionando.
- **Antifraude y Orquestador**: el motor de scoring y el flujo de
  identidad+riesgo funcionan igual (no dependen de la base de datos para
  calcular), pero el **historial** cae a una lista en memoria del proceso
  en vez de leer/escribir en SQL Server. Se pierde al reiniciar el
  servidor — suficiente para probar funcionamiento, no para producción.

## 9. Ubicación geográfica de las transacciones

Las pantallas de **Sistema Antifraude** y **Orquestador** piden la
ubicación del navegador (`navigator.geolocation`) al entrar, y la envían
junto con cada evaluación/transferencia. Se guarda en las columnas
`Latitud`/`Longitud` de `Transferencias` y `VerificacionesTransferencia`,
y aparece en el historial como un enlace "Ver mapa" que abre el punto
exacto en Google Maps.

**Importante — esto requiere permiso explícito del navegador**: el
navegador muestra un popup nativo pidiendo permiso de ubicación, que el
usuario puede negar. Si lo niega, no hay forma de saltarse eso (es una
protección de privacidad del navegador, no una limitación de este
código) — la transacción sigue funcionando igual, simplemente queda sin
ubicación registrada (columna en `NULL`, "-" en vez de "Ver mapa" en el
historial).

> ⚠️ No se pudo probar el flujo completo de geolocalización con un
> navegador real en el entorno donde se hizo este cambio (sin
> interfaz gráfica disponible) — se verificó la lógica del backend de
> punta a punta (guardar, leer, generar el link de mapa) y que el
> frontend compila, pero no la experiencia real del popup de permiso ni
> la precisión del GPS/red en un dispositivo real.

## 10. Revisión completa de código (correcciones aplicadas)

Se hizo una revisión de todo el proyecto, archivo por archivo, agregando
comentarios explicativos y corrigiendo varios problemas reales que se
encontraron en el proceso:

**Corregidos:**
- 🔴 **Control de acceso (IDOR)**: `GET /verificaciones/{user_id}` y
  `GET /transferencia/historial` permitían que cualquier usuario
  logueado leyera el historial de OTRO usuario cambiando el ID en la
  URL. Ahora se valida que solo puedas ver el tuyo (o cualquiera, si
  eres admin).
- 🔴 **Suplantación de identidad en el orquestador**: `POST
  /transferencia/procesar` no validaba que el `user_id` del cuerpo de
  la petición coincidiera con el usuario del token — un usuario
  logueado podía intentar procesar una transferencia "como" otra
  persona. Ahora se rechaza con 403 si no coincide.
- 🔴 **Endpoints sin autenticación**: `POST /transacciones/evaluar` y
  `GET /transacciones/historial` no exigían estar logueado (a
  diferencia de todo lo demás en la app). Ahora sí lo exigen.
- 🟡 **Bug de UX en Registro**: al completar los 4 ángulos y luego hacer
  clic en una miniatura para repetir una captura, la pantalla de cámara
  no volvía a aparecer (quedaba "atascado" mostrando "✔ completado").
  Corregido.
- Comentario desactualizado en `modulo_biometria/router.py` que seguía
  mencionando PostgreSQL (ya migrado a SQL Server hace varias iteraciones).
- Varios endpoints sin el chequeo de "sin conexión DB" (dejaban un
  error genérico feo en vez de un mensaje claro).

**Documentados como limitaciones conocidas (no se tocó el
comportamiento, solo se dejó explícito en comentarios):**
- El análisis de grafos (`graph_analyzer.py`) y el modelo de ML
  (`model.py`) usan datos de ejemplo fijos/sintéticos, no aprenden de
  transacciones reales todavía — normal para un MVP, pero hay que
  reemplazarlos con datos reales antes de producción.
- `core/telemetry_parser.py` y `services/security.py::generar_api_key`
  existen pero no los usa ningún otro archivo — código huérfano,
  heredado de versiones anteriores.
- `obtenerHistorialAdmin`/`accionarRegistro` en `api.js` tienen su
  endpoint funcionando en el backend, pero ninguna pantalla del
  frontend los usa — falta construir una vista de "revisar
  verificaciones en REVISION_MANUAL" para que el admin las apruebe/
  rechace a mano.
- La conexión a SQL Server (`shared/db.py`) es una sola, compartida por
  toda la app — funciona bien con un usuario a la vez (como en las
  pruebas actuales), pero antes de producción con usuarios concurrentes
  reales, necesita convertirse en un pool de conexiones.
- CORS está configurado para aceptar cualquier origen (`*`) — bien para
  el MVP, pero debe restringirse a la URL real del frontend antes de
  un despliegue con el banco.

**Probado de punta a punta en este entorno** (con foto real, TensorFlow/
DeepFace/PyTorch funcionando): registro con validaciones, evaluación de
riesgo con y sin autenticación, verificación facial con anti-spoofing
real, control de acceso del orquestador (bloqueo de suplantación),
y panel de administración. Todo el frontend compila sin errores.

## 11. Pendientes conocidos (no bloquean las pruebas del MVP)

- Unificar la identidad de usuario entre `Usuarios` (biometría) y
  `Clientes` (antifraude) — hoy son dos tablas separadas en la misma base
  de datos.
- Persistencia real de `TelemetriaComportamiento` y `PerfilesFinancieros`
  desde el frontend (hoy solo se cargan vía `seed_data.py`).
- `core/telemetry_parser.py` sigue sin usarse en ningún otro archivo
  (código huérfano heredado, no afecta el funcionamiento).

## 12. Solución de problemas comunes

**`ModuleNotFoundError: No module named 'tensorflow'` al arrancar el backend**
Casi siempre significa que estás usando **Python 3.14**, que `tensorflow`
todavía no soporta. Solución:
1. Instala Python 3.11 (o 3.12/3.13) desde python.org, sin desinstalar el
   3.14 que ya tienes — pueden convivir.
2. Crea el entorno virtual con esa versión específica, por ejemplo:
   ```bash
   py -3.11 -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt
   ```
3. Verifica qué Python estás usando dentro del venv con `python --version`
   antes de instalar — debe decir 3.11.x (o 3.10/3.12/3.13), no 3.14.

**Sigue apareciendo `ModuleNotFoundError: No module named 'tensorflow'` después de crear el entorno virtual**
Casi siempre significa que el entorno virtual **no se activó de verdad** antes de instalar o correr algo — sigues usando el Python global. Cómo confirmarlo:
1. Después de "activar", corre `python --version`. Si sigue mostrando 3.14.x, la activación falló.
2. En **PowerShell** (no CMD), el comando de activación es distinto al que aparece en la mayoría de tutoriales:
   ```powershell
   .\venv\Scripts\Activate.ps1
   ```
   `venv\Scripts\activate` (sin el `.ps1`) es la sintaxis de CMD y puede no funcionar en PowerShell.
3. Si PowerShell bloquea el script con un error de "execution policy":
   ```powershell
   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
   ```
   y vuelve a activar.
4. Con el entorno activado deberías ver `(venv)` al inicio de la línea de comandos. Instala y corre todo dentro de esa misma terminal — si la cierras o abres una nueva, tienes que activar de nuevo.

**`ERROR: Could not find a version that satisfies the requirement scikit-learn==1.4.1` (o numpy/pandas)**
Esas versiones específicas son de principios de 2024, antes de que existiera Python 3.13, y no tienen instalador (wheel) compilado para esa versión de Python. El `requirements.txt` ya no fija esas versiones a propósito — si ves este error, asegúrate de tener la versión más reciente del archivo (vuelve a descargar el zip si es necesario).

**`Defaulting to user installation because normal site-packages is not writeable` al correr `pip install`**
Es la señal de que el entorno virtual no estaba activado en ese momento — revisa el punto anterior sobre activación en PowerShell antes de instalar de nuevo.

**`"No se detectó rostro"` al registrarte o verificar, aunque la foto se vea bien**
Puede tener dos causas distintas:
1. Resolución de captura muy baja (ya corregida a 640x480 en el frontend).
2. **Bug conocido de `opencv-python==5.0.0.93`**: esa versión viene con la
   carpeta `cv2/data` vacía (sin los archivos `.xml` de detección facial),
   así que aunque todo esté instalado "sin errores", el detector nunca
   encuentra un rostro. El `requirements.txt` ya fija la versión
   `4.10.0.84`, que no tiene este problema — si ves este error, confirma
   con `pip show opencv-python` que tienes la 4.10.0.84 y no la 5.x.

Si sigues viendo el error con la versión correcta de opencv-python:
- Asegúrate de tener buena iluminación y el rostro centrado, ocupando buena
  parte del cuadro.
- Revisa la consola del backend (donde corriste `uvicorn`) — imprime el
  motivo exacto por el que DeepFace no pudo detectar el rostro.

**`ModuleNotFoundError` o error de `torch` en `/verificar` o el orquestador**
El módulo de anti-spoofing de DeepFace (detecta si es una persona real o una
foto/pantalla) requiere `torch`, ya incluido en `requirements.txt`. Si lo
agregaste después de tu primer `pip install`, corre `pip install -r
requirements.txt` de nuevo dentro del entorno activado — es una instalación
pesada (varios cientos de MB), así que puede tardar unos minutos.

**`AttributeError: module 'bcrypt' has no attribute '__about__'` / `password cannot be longer than 72 bytes` al registrarte**
`passlib` (no se actualiza desde 2020) espera un atributo interno que
`bcrypt` 4.1+ eliminó. El `requirements.txt` ya fija `bcrypt==4.0.1` para
evitarlo — si ves este error, corre `pip show bcrypt` y confirma que
dice `4.0.1`, no una versión más nueva. Si tienes una más nueva instalada:
```bash
pip install "bcrypt==4.0.1" --force-reinstall
```

**🔴 CRÍTICO — la verificación aprobaba a cualquier persona, no solo a la registrada**
Bug real encontrado y corregido: `calcular_similitud()` en `face_engine.py`
remapeaba la similitud coseno con la fórmula `(coseno+1)/2`, pensando que
así se normalizaba a un rango 0-1. Ese remapeo es matemáticamente
incorrecto para embeddings faciales — dos rostros de personas DISTINTAS
ya dan similitud coseno baja pero positiva (típicamente 0.15-0.35, nunca
cercana a -1), y el remapeo empujaba esos valores por encima del umbral
de aprobación (0.60), aprobando impostores.

**Corregido**: ahora se compara la similitud coseno cruda, siguiendo la
convención de calibración oficial de DeepFace (confirmada en su código
fuente). Se verificó que una misma persona sigue dando similitud ~1.0,
pero **no se pudo probar el caso de una persona distinta siendo
rechazada** en el entorno donde se hizo esta corrección — no había una
segunda foto de rostro real disponible para comparar. Antes de dar esto
por resuelto del todo:
1. Registra un usuario.
2. Intenta verificar con una persona DISTINTA — debe salir "FRAUDE" o
   similitud claramente por debajo de 0.60, no "APROBADO".
3. Si sigue aprobando a personas distintas, avísame con los números
   exactos de `similitud` que te muestre la respuesta — eso me dice si
   hace falta ajustar el umbral (`UMBRAL_SIMILITUD` en `face_engine.py`)
   en vez de la fórmula.

**`npm error Missing script: "dev"`**
El proyecto Vite real está en `FraudShield/frontend/vite-app`, no en
`FraudShield/frontend` (esa carpeta solo contiene la pantalla HTML de
`transfer_screen.html`, que no usa npm). Asegúrate de entrar a la
subcarpeta correcta:
```bash
cd FraudShield/frontend/vite-app
npm install
npm run dev
```
