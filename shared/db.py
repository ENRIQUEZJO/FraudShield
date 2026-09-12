"""
shared/db.py

Pool de conexiones a SQL Server, compartido por modulo_biometria y
modulo_antifraude — reemplaza la versión anterior que usaba UNA SOLA
conexión global para toda la aplicación (segura solo con un usuario a
la vez, no apta para varios bancos/usuarios concurrentes).

CÓMO FUNCIONA UN "POOL" DE CONEXIONES:
En vez de una única conexión compartida (insegura si dos peticiones la
usan al mismo tiempo), se abren de antemano varias conexiones (por
defecto 20, configurable) y se guardan en una fila de espera (queue.Queue).
Cada petición HTTP que necesita la base de datos:
  1. "Pide prestada" una conexión libre de la fila (get_connection()).
  2. La usa exclusivamente para SU trabajo (nadie más la toca mientras tanto).
  3. La devuelve a la fila al terminar (incluso si hubo un error).
Esto es exactamente el mismo patrón que usan herramientas como
SQLAlchemy o pgbouncer internamente — aquí se implementa a mano, sin
librerías adicionales, para mantener el proyecto simple.

Si el pool se queda sin conexiones libres (muchísimas peticiones a la
vez), una nueva petición espera hasta POOL_TIMEOUT_SEGUNDOS antes de
rendirse con un error claro, en vez de colgarse para siempre.

RECONEXIÓN AUTOMÁTICA: un hilo en segundo plano revisa periódicamente
si SQL Server está disponible. Si el servidor estaba caído cuando
arrancó el backend y luego vuelve, el pool se reconstruye solo — sin
necesidad de reiniciar el proceso. Si el servidor se cae DESPUÉS de
haber arrancado bien, el mismo hilo lo detecta y marca la base de datos
como no disponible (para que los endpoints respondan con un error claro
en vez de colgarse), y la reconecta apenas vuelva."""
import os
import queue
import threading
import time

# ==========================================
# CONFIGURACIÓN
# ==========================================

SQLSERVER_HOST = os.getenv("FRAUDSHIELD_DB_SERVER", os.getenv("VISIONSEGURA_DB_SERVER", "DESKTOP-TKPM2HC"))
SQLSERVER_DB = os.getenv("FRAUDSHIELD_DB_NAME", os.getenv("VISIONSEGURA_DB_NAME", "FraudShieldDB"))

# Cuántas conexiones simultáneas mantener abiertas y listas. Cada banco
# que use este sistema puede ajustar este número según cuántos usuarios
# concurrentes espere — 20 es un punto de partida razonable para un
# banco mediano; se puede subir con la variable de entorno
# FRAUDSHIELD_DB_POOL_SIZE sin tocar código.
POOL_SIZE = int(os.getenv("FRAUDSHIELD_DB_POOL_SIZE", "20"))

# Cuánto esperar (en segundos) por una conexión libre antes de rendirse.
# Si esto se agota seguido en producción, es señal de que hace falta un
# POOL_SIZE más grande (o el servidor de SQL Server está sobrecargado).
POOL_TIMEOUT_SEGUNDOS = float(os.getenv("FRAUDSHIELD_DB_POOL_TIMEOUT", "10"))

# Cada cuántos segundos el hilo de vigilancia revisa si SQL Server
# volvió a estar disponible (o si se cayó). 30 segundos es un buen
# balance: lo bastante seguido para recuperarse rápido, sin generar
# demasiadas conexiones de prueba innecesarias.
RECONEXION_INTERVALO_SEGUNDOS = int(os.getenv("FRAUDSHIELD_DB_RECONNECT_SEGUNDOS", "30"))

# Cuántas veces seguidas debe fallar la prueba de conexión antes de
# marcar la base de datos como "caída" — evita que un solo fallo
# pasajero de red (un timeout suelto) tumbe todo el pool innecesariamente.
FALLAS_CONSECUTIVAS_PARA_MARCAR_CAIDA = 3

_pool: "queue.Queue | None" = None
_pool_lock = threading.Lock()  # evita que dos threads reconstruyan el pool a la vez
DB_DISPONIBLE = False  # True solo si se logró crear al menos una conexión
_fallas_consecutivas = 0  # contador interno del hilo de vigilancia


def _crear_conexion_nueva():
    """Abre UNA conexión física nueva a SQL Server. Puede lanzar una
    excepción si el servidor no está disponible — quien la llama debe
    manejarlo."""
    import pyodbc
    return pyodbc.connect(
        "DRIVER={ODBC Driver 17 for SQL Server};"
        f"SERVER={SQLSERVER_HOST};"
        f"DATABASE={SQLSERVER_DB};"
        "Trusted_Connection=yes;",
        autocommit=False,
    )


def _inicializar_pool():
    """Abre POOL_SIZE conexiones de antemano y las guarda en la fila de
    espera. Se llama al importar el módulo, y también la reutiliza el
    hilo de vigilancia cuando detecta que SQL Server volvió a estar
    disponible después de haber estado caído.

    IMPORTANTE: solo es seguro llamar a esta función cuando NO hay
    conexiones prestadas en circulación — es decir, justo al arrancar,
    o cuando DB_DISPONIBLE ya estaba en False (nadie pudo haber pedido
    prestada una conexión mientras estaba marcada como no disponible)."""
    global _pool, DB_DISPONIBLE

    nueva_fila = queue.Queue(maxsize=POOL_SIZE)
    conexiones_creadas = 0

    for _ in range(POOL_SIZE):
        try:
            nueva_fila.put(_crear_conexion_nueva())
            conexiones_creadas += 1
        except Exception as e:
            # Si falla la PRIMERA conexión, es casi seguro que SQL Server
            # no está disponible en absoluto — no tiene sentido seguir
            # intentando abrir 19 más que fallarán igual. Se corta aquí.
            if conexiones_creadas == 0:
                print(f"⚠️  [shared/db] Sin conexión a SQL Server: {e}")
                break

    _pool = nueva_fila
    DB_DISPONIBLE = conexiones_creadas > 0

    if DB_DISPONIBLE:
        print(f"✅ [shared/db] Pool de conexiones listo: {conexiones_creadas}/{POOL_SIZE} conexiones a SQL Server ({SQLSERVER_HOST}/{SQLSERVER_DB})")


def _probar_conexion() -> bool:
    """Abre y cierra de inmediato una conexión de prueba, solo para
    saber si SQL Server responde en este momento — no toca el pool."""
    try:
        prueba = _crear_conexion_nueva()
        prueba.close()
        return True
    except Exception:
        return False


def _vaciar_pool_actual():
    """Cierra y descarta todo lo que quede en el pool actual, sin
    reemplazar la referencia de la cola (ver nota en _hilo_vigilancia
    sobre por qué esto es más seguro que reasignar `_pool`)."""
    try:
        while True:
            c = _pool.get_nowait()
            try:
                c.close()
            except Exception:
                pass
    except queue.Empty:
        pass


def _hilo_vigilancia():
    """Corre en segundo plano durante toda la vida del proceso,
    revisando cada RECONEXION_INTERVALO_SEGUNDOS si SQL Server está
    disponible, para recuperarse solo sin reiniciar el backend."""
    global DB_DISPONIBLE, _fallas_consecutivas

    while True:
        time.sleep(RECONEXION_INTERVALO_SEGUNDOS)
        conexion_ok = _probar_conexion()

        with _pool_lock:
            if conexion_ok:
                _fallas_consecutivas = 0
                if not DB_DISPONIBLE:
                    # SQL Server volvió a responder después de haber
                    # estado caído — como DB_DISPONIBLE era False, nadie
                    # pudo haber pedido prestada una conexión mientras
                    # tanto, así que es seguro reconstruir el pool
                    # completo desde cero.
                    print("🔄 [shared/db] SQL Server disponible de nuevo — reconstruyendo el pool...")
                    _inicializar_pool()
            else:
                if DB_DISPONIBLE:
                    _fallas_consecutivas += 1
                    if _fallas_consecutivas >= FALLAS_CONSECUTIVAS_PARA_MARCAR_CAIDA:
                        print(
                            f"⚠️  [shared/db] Se perdió la conexión a SQL Server "
                            f"({_fallas_consecutivas} intentos fallidos seguidos) — "
                            "marcando la base de datos como no disponible hasta que vuelva."
                        )
                        DB_DISPONIBLE = False
                        # Se vacía el pool (no se reemplaza la cola) para
                        # que cualquier conexión de una petición en curso
                        # que se devuelva después con _pool.put() siga
                        # yendo a la MISMA cola, sin errores de tamaño.
                        _vaciar_pool_actual()


with _pool_lock:
    _inicializar_pool()

# Hilo daemon: no impide que el proceso termine si el programa principal
# se cierra (a diferencia de un hilo normal, que lo mantendría vivo).
threading.Thread(target=_hilo_vigilancia, daemon=True).start()


class ConexionPrestada:
    """Context manager para pedir prestada una conexión del pool y
    devolverla automáticamente al terminar, incluso si hubo un error.

    Uso:
        with ConexionPrestada() as (conn, cursor):
            cursor.execute("SELECT ...")
            conn.commit()

    Si no hay conexiones disponibles en el pool en menos de
    POOL_TIMEOUT_SEGUNDOS, lanza TimeoutError con un mensaje claro en
    vez de colgar la petición indefinidamente.
    """

    def __enter__(self):
        if not DB_DISPONIBLE:
            raise RuntimeError("Sin conexión a la base de datos")

        try:
            self.conn = _pool.get(timeout=POOL_TIMEOUT_SEGUNDOS)
        except queue.Empty:
            # Todas las conexiones del pool están ocupadas y ninguna se
            # liberó a tiempo — normalmente significa que hay MUCHO más
            # tráfico concurrente del que POOL_SIZE puede sostener.
            raise TimeoutError(
                f"El pool de conexiones está agotado (todas las {POOL_SIZE} en uso). "
                "Sube FRAUDSHIELD_DB_POOL_SIZE si esto pasa seguido."
            )

        # Si una conexión anterior quedó en un estado raro (por ejemplo,
        # el proceso murió a mitad de una transacción), un rollback
        # preventivo la deja limpia antes de usarla de nuevo. Si la
        # conexión física ya se cayó de verdad (servidor reiniciado,
        # red caída), se reemplaza por una nueva en vez de devolver una
        # rota al que la está pidiendo.
        try:
            self.conn.rollback()
        except Exception:
            try:
                self.conn.close()
            except Exception:
                pass
            self.conn = _crear_conexion_nueva()

        self.cursor = self.conn.cursor()
        return self.conn, self.cursor

    def __exit__(self, exc_type, exc_value, traceback):
        if exc_type is not None:
            # Si el código dentro del "with" lanzó una excepción, se
            # deshacen los cambios a medias antes de devolver la
            # conexión al pool — así el siguiente que la use no hereda
            # una transacción abierta con cambios sin confirmar.
            try:
                self.conn.rollback()
            except Exception:
                pass
        # SIEMPRE se devuelve la conexión al pool, haya habido error o
        # no — si no se hiciera esto, cada error iría "vaciando" el pool
        # de a poco hasta que ninguna petición pudiera conseguir una conexión.
        #
        # Nota sobre reconexión automática: si mientras esta conexión
        # estaba prestada, el hilo de vigilancia detectó una caída total
        # y vació el pool (_vaciar_pool_actual), esta sigue siendo LA
        # MISMA cola (_pool nunca se reemplaza en ese caso, ver
        # _hilo_vigilancia) — así que este put() no falla ni se pierde,
        # simplemente vuelve a entrar a una cola que el hilo de
        # vigilancia puede haber dejado con espacio de sobra.
        try:
            _pool.put(self.conn)
        except Exception:
            pass
        return False  # False = no silenciar la excepción; sigue propagándose normalmente


def obtener_conexion():
    """Punto de entrada público: `with obtener_conexion() as (conn, cursor): ...`"""
    return ConexionPrestada()
