# ai_models/graph_analyzer.py
import time  # para controlar cada cuánto se refresca el grafo desde la base de datos
import threading  # para evitar que dos peticiones refresquen el grafo al mismo tiempo
import networkx as nx  # librería para trabajar con grafos (nodos y conexiones entre ellos)
from typing import Dict, Any

from shared.db import obtener_conexion, DB_DISPONIBLE

# Cada cuántos segundos se vuelve a construir el grafo desde la base de
# datos real. No se hace en CADA evaluación de transacción porque
# reconstruir el grafo completo en cada petición sería lento con miles
# de transacciones históricas — 5 minutos es un buen balance entre
# "datos frescos" y "no sobrecargar la base de datos". Configurable por
# si un banco necesita datos más al día.
import os
INTERVALO_REFRESCO_SEGUNDOS = int(os.getenv("FRAUDSHIELD_GRAPH_REFRESH_SEGUNDOS", "300"))

# Cuántas transacciones históricas recientes se usan para construir el
# grafo — suficiente para detectar patrones sin traer TODA la tabla
# (que en un banco real podría tener millones de filas).
LIMITE_TRANSACCIONES_PARA_GRAFO = 5000


class GraphAnalyzer:
    """Analiza la 'red' de transferencias entre cuentas para detectar
    cuentas que actúan como puntos de recolección de dinero de fraude
    (varias cuentas "mula" enviando a una misma cuenta destino).

    El grafo se construye a partir de transacciones REALES guardadas en
    SQL Server (tabla Transferencias) — cada fila se convierte en una
    conexión "ClienteId envió dinero a CuentaDestino". Se refresca cada
    INTERVALO_REFRESCO_SEGUNDOS en vez de en cada petición, para no
    volver lenta cada evaluación.

    Si no hay conexión a la base de datos (por ejemplo, en un entorno
    de desarrollo sin SQL Server), se usa un grafo de EJEMPLO fijo, para
    que el resto del sistema se pueda seguir probando sin depender de
    tener datos reales cargados."""

    def __init__(self):
        self.G = nx.DiGraph()  # grafo dirigido: A -> B significa "A le envió dinero a B"
        self._ultimo_refresco = 0.0  # 0 fuerza que la primera llamada siempre intente cargar datos reales
        self._lock = threading.Lock()  # evita que dos threads reconstruyan el grafo a la vez
        self._usando_datos_reales = False
        self._cargar_grafo_simulado()  # arranca con datos de ejemplo por si la primera carga real tarda o falla

    def _cargar_grafo_simulado(self):
        """Puebla el grafo con conexiones de ejemplo — se usa como
        respaldo mientras no hay datos reales disponibles."""
        self.G.clear()
        transferencias_previas = [
            ("MULA_01", "CHIPERO_88"),  # MULA_01 le envió dinero a CHIPERO_88
            ("MULA_02", "CHIPERO_88"),
            ("MULA_03", "CHIPERO_88")
        ]
        for origen, destino in transferencias_previas:
            self.G.add_edge(origen, destino)  # agrega la conexión (flecha) al grafo
        self._usando_datos_reales = False

    def _refrescar_desde_db_si_corresponde(self):
        """Si ya pasó INTERVALO_REFRESCO_SEGUNDOS desde la última vez,
        reconstruye el grafo a partir de las transacciones reales en
        SQL Server. Si la base de datos no está disponible, no hace
        nada (se sigue usando lo que ya había cargado — datos reales
        viejos son mejores que ninguno, y si nunca hubo datos reales,
        queda el grafo de ejemplo)."""
        ahora = time.time()
        if ahora - self._ultimo_refresco < INTERVALO_REFRESCO_SEGUNDOS:
            return  # todavía no toca refrescar

        if not DB_DISPONIBLE:
            return  # sin base de datos, no hay de dónde sacar datos reales

        with self._lock:
            # Doble chequeo: si otro thread ya refrescó mientras este
            # esperaba el lock, no hace falta hacerlo de nuevo.
            if time.time() - self._ultimo_refresco < INTERVALO_REFRESCO_SEGUNDOS:
                return

            try:
                nuevo_grafo = nx.DiGraph()
                with obtener_conexion() as (conn, cursor):
                    cursor.execute(
                        f"""
                        SELECT TOP ({LIMITE_TRANSACCIONES_PARA_GRAFO}) ClienteId, CuentaDestino
                        FROM Transferencias
                        ORDER BY FechaRegistro DESC
                        """
                    )
                    filas = cursor.fetchall()

                for cliente_id, cuenta_destino in filas:
                    # El nodo de origen se marca como "CLIENTE_<id>" para
                    # no confundirlo con un número de cuenta destino
                    # literal (son dos "espacios de nombres" distintos).
                    nuevo_grafo.add_edge(f"CLIENTE_{cliente_id}", cuenta_destino)

                if len(nuevo_grafo.nodes) > 0:
                    self.G = nuevo_grafo
                    self._usando_datos_reales = True
                    print(f"[graph_analyzer] Grafo actualizado con {len(filas)} transacciones reales ({len(nuevo_grafo.nodes)} nodos)")
                # Si no hay transacciones reales todavía (banco recién
                # empezando a usar el sistema), se deja el grafo de
                # ejemplo — no tiene sentido reemplazarlo por uno vacío.

                self._ultimo_refresco = ahora

            except Exception as e:
                print(f"[graph_analyzer] No se pudo refrescar el grafo desde SQL Server: {e}")
                # Se mantiene el grafo anterior (real o de ejemplo) — un
                # fallo de refresco nunca debe tumbar la evaluación de
                # transacciones en curso.

    def analizar_riesgo_red(self, cuenta_destino: str) -> Dict[str, Any]:
        """
        Determina si una cuenta destino actúa como sumidero/recolector de fraude.
        """
        self._refrescar_desde_db_si_corresponde()

        try:
            # Si la cuenta destino ni siquiera aparece en el grafo, no
            # hay información de ella todavía — no se puede evaluar riesgo.
            if not self.G.has_node(cuenta_destino):
                return {"graph_score": 0, "alerta_grafo": []}

            # Grado de entrada (in_degree): cuántas cuentas DISTINTAS le
            # han enviado dinero a esta cuenta destino. Muchas cuentas
            # distintas enviando a una sola es la firma típica de una
            # cuenta "recolectora" de fraude.
            in_degree = self.G.in_degree(cuenta_destino)

            if in_degree >= 3:
                # 3 o más orígenes distintos: alerta fuerte
                return {
                    "graph_score": 35,
                    "alerta_grafo": [f"ALERTA TOPOLÓGICA: Cuenta destino es un nodo recolector con {in_degree} orígenes sospechosos."]
                }
            elif in_degree > 0:
                # Al menos una conexión previa, pero no suficientes para ser "recolectora": alerta leve
                return {"graph_score": 10, "alerta_grafo": ["Conexiones previas en la red de transferencias."]}

            # Tiene nodo en el grafo pero nadie le ha enviado dinero (in_degree == 0): sin riesgo
            return {"graph_score": 0, "alerta_grafo": []}

        except Exception:
            # Fallback seguro si falla el análisis de redes: nunca dejar
            # que un error aquí tumbe toda la evaluación de la transacción.
            return {"graph_score": 0, "alerta_grafo": []}
