# ai_models/model.py
import os
import time
import threading
import numpy as np
from sklearn.ensemble import IsolationForest  # algoritmo de ML especializado en detectar "anomalías" (datos que no encajan con el patrón normal)
from typing import Dict, Any

from shared.db import obtener_conexion, DB_DISPONIBLE

# Cada cuántos segundos se reentrena el modelo con datos reales.
# Reentrenar es más costoso que refrescar el grafo, así que por defecto
# se hace con menos frecuencia (30 minutos) — configurable si un banco
# necesita que el modelo se actualice más seguido.
INTERVALO_REENTRENO_SEGUNDOS = int(os.getenv("FRAUDSHIELD_ML_RETRAIN_SEGUNDOS", "1800"))

# Cuántas transacciones aprobadas recientes se usan para reentrenar.
LIMITE_TRANSACCIONES_PARA_ENTRENAR = 5000

# Con menos de esta cantidad de transacciones reales aprobadas, no vale
# la pena reentrenar todavía — el modelo aprendería un patrón basado en
# muy pocos ejemplos, poco confiable. Se sigue usando el modelo
# sintético hasta que el banco tenga suficiente historial real.
MINIMO_TRANSACCIONES_PARA_CONFIAR = 30


class AntiFraudMLModel:
    """Modelo de Machine Learning que aprende cómo se ve una transacción
    'normal' y marca como sospechosas las que se desvían mucho de ese
    patrón — a diferencia de ScoringEngine (reglas fijas), este puede
    detectar combinaciones raras de valores que ninguna regla explícita
    contempló.

    El modelo se reentrena periódicamente con transacciones REALES ya
    evaluadas como APROBADAS (tabla Transferencias en SQL Server) —
    esas representan el comportamiento "normal" de los clientes de ese
    banco en particular. Mientras no haya suficiente historial real
    (menos de MINIMO_TRANSACCIONES_PARA_CONFIAR), se sigue usando un
    modelo entrenado con datos sintéticos de ejemplo, para que el
    sistema funcione desde el primer día sin esperar semanas a acumular
    datos."""

    def __init__(self):
        # contamination=0.05: le decimos al algoritmo "asume que el 5% de
        # tus datos de entrenamiento son anomalías" — esto calibra qué
        # tan estricto es el modelo al decidir qué es "raro".
        # random_state=42: fija la semilla aleatoria para que el modelo
        # entrene siempre igual (resultados reproducibles).
        self.model = IsolationForest(contamination=0.05, random_state=42)
        self._ultimo_reentreno = 0.0
        self._lock = threading.Lock()
        self._usando_datos_reales = False
        self._entrenar_modelo_sintetico()

    def _entrenar_modelo_sintetico(self):
        """Genera un dataset sintético para entrenar el cerebro de la IA
        mientras no hay suficientes datos reales — así el sistema
        funciona desde el primer día."""
        np.random.seed(42)  # misma semilla que el modelo, para que estos números aleatorios sean siempre los mismos

        # Generar 200 transacciones "normales" simuladas:
        montos_normales = np.random.uniform(500, 2000, 200)      # montos entre RD$500 y RD$2,000
        tiempos_normales = np.random.uniform(120, 1440, 200)     # entre 2 horas y 24 horas desde el depósito
        llamadas_normales = np.zeros(200)                         # ninguna con llamada activa (0 = sin llamada)

        # Junta las 3 columnas en una sola matriz de 200 filas x 3 columnas
        # (una fila por transacción simulada, una columna por variable).
        X_normal = np.column_stack((montos_normales, tiempos_normales, llamadas_normales))

        # Entrenar el bosque de aislamiento con estos patrones "legítimos" —
        # a partir de ahora, el modelo sabe cómo se ve una transacción normal.
        self.model.fit(X_normal)
        self._usando_datos_reales = False

    def _reentrenar_desde_db_si_corresponde(self):
        """Si ya pasó INTERVALO_REENTRENO_SEGUNDOS desde la última vez,
        intenta reentrenar el modelo con transacciones reales aprobadas.
        Si no hay suficientes datos reales todavía, o la base de datos
        no está disponible, se sigue usando el modelo que ya había
        (real o sintético)."""
        ahora = time.time()
        if ahora - self._ultimo_reentreno < INTERVALO_REENTRENO_SEGUNDOS:
            return

        if not DB_DISPONIBLE:
            return

        with self._lock:
            if time.time() - self._ultimo_reentreno < INTERVALO_REENTRENO_SEGUNDOS:
                return  # otro thread ya reentrenó mientras este esperaba

            try:
                with obtener_conexion() as (conn, cursor):
                    cursor.execute(
                        f"""
                        SELECT TOP ({LIMITE_TRANSACCIONES_PARA_ENTRENAR})
                            Monto, TiempoDesdeDepositoMinutos, LlamadaActiva
                        FROM Transferencias
                        WHERE EstadoTransaccion = 'APROBADA'
                        ORDER BY FechaRegistro DESC
                        """
                    )
                    filas = cursor.fetchall()

                if len(filas) >= MINIMO_TRANSACCIONES_PARA_CONFIAR:
                    montos = np.array([float(f[0]) for f in filas])
                    tiempos = np.array([float(f[1]) for f in filas])
                    llamadas = np.array([1.0 if f[2] else 0.0 for f in filas])
                    X_real = np.column_stack((montos, tiempos, llamadas))

                    nuevo_modelo = IsolationForest(contamination=0.05, random_state=42)
                    nuevo_modelo.fit(X_real)

                    self.model = nuevo_modelo
                    self._usando_datos_reales = True
                    print(f"[model] Modelo de ML reentrenado con {len(filas)} transacciones reales aprobadas")
                else:
                    # Todavía no hay suficiente historial real — se
                    # mantiene el modelo actual (sintético o real
                    # anterior) tal cual, sin tocarlo.
                    print(f"[model] Solo {len(filas)} transacciones aprobadas en la base de datos (mínimo {MINIMO_TRANSACCIONES_PARA_CONFIAR}) — se sigue usando el modelo anterior")

                self._ultimo_reentreno = ahora

            except Exception as e:
                print(f"[model] No se pudo reentrenar el modelo con datos reales: {e}")
                # Un fallo de reentreno nunca debe tumbar la evaluación
                # de transacciones en curso — se sigue usando el modelo anterior.

    def predecir_anomalia(self, datos: Dict[str, Any]) -> Dict[str, Any]:
        """
        Clasifica matemáticamente si la transacción actual rompe los esquemas normales.
        """
        self._reentrenar_desde_db_si_corresponde()

        try:
            # Se extraen los mismos 3 valores con los que se entrenó el
            # modelo, con valores por defecto seguros si faltan.
            monto = float(datos.get("monto", 0.0))
            tiempo = float(datos.get("tiempo_desde_deposito_minutos", 1440.0))
            llamada = 1.0 if datos.get("llamada_activa", False) else 0.0

            # Estructurar vector de entrada para la predicción (una sola
            # fila, en el mismo orden de columnas que en el entrenamiento).
            vector = np.array([[monto, tiempo, llamada]])
            prediccion = self.model.predict(vector)[0] # Retorna 1 (normal) o -1 (anomalía)

            if prediccion == -1:
                return {
                    "ml_score": 25,
                    "alerta_ml": ["ALERTA ML: Desviación matemática severa detectada por Isolation Forest."]
                }
            return {"ml_score": 0, "alerta_ml": []}

        except Exception as e:
            # Mecanismo de seguridad integrada: si falla la IA (por
            # ejemplo, datos con un formato inesperado), el banco no se
            # cae — simplemente este motor no aporta puntaje esta vez.
            return {"ml_score": 0, "alerta_ml": [f"Error de contingencia en IA: {str(e)}"]}
