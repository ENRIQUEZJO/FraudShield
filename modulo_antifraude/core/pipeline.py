# core/pipeline.py
from typing import Dict, Any
from modulo_antifraude.core.scoring_engine import ScoringEngine
from modulo_antifraude.ai_models.graph_analyzer import GraphAnalyzer

# Nota: Para propósitos de ejecución del MVP importamos directamente
from modulo_antifraude.ai_models.model import AntiFraudMLModel

class FraudPipeline:
    """Orquesta los 3 "motores" de detección de fraude y combina sus
    puntajes en un solo veredicto. Se instancia UNA sola vez (ver
    modulo_antifraude/router.py) porque el modelo de ML se entrena en
    el constructor — instanciar esto en cada petición reentrenaría el
    modelo cada vez, lo cual sería lento e innecesario."""

    def __init__(self):
        self.motor_reglas = ScoringEngine()        # reglas de negocio fijas (ver scoring_engine.py)
        self.analizador_grafos = GraphAnalyzer()    # detecta cuentas "recolectoras" de fraude (ver graph_analyzer.py)
        self.modelo_ml = AntiFraudMLModel()         # detecta anomalías estadísticas (ver ai_models/model.py)
        self.umbral_bloqueo = 70                    # score >= 70 sobre 100 => se rechaza la transacción

    def procesar_evaluacion(self, transaccion: Dict[str, Any]) -> Dict[str, Any]:
        """
        Orquesta la ejecución secuencial de los 3 motores y calcula el score consolidado.
        """
        # Ejecutar motores de forma independiente (Aislamiento de fallos):
        # cada motor tiene su propio try/except interno, así que si uno
        # falla, no tumba a los otros dos ni a toda la evaluación.
        res_reglas = self.motor_reglas.evaluar_reglas_estaticas(transaccion)
        res_grafos = self.analizador_grafos.analizar_riesgo_red(transaccion.get("cuenta_destino", ""))
        res_ml = self.modelo_ml.predecir_anomalia(transaccion)

        # Consolidación matemática del riesgo (Cap-and-Sum): se suman los
        # 3 puntajes parciales, y el total se "capa" (limita) a 100 como
        # máximo, para que nunca se salga de la escala 0-100.
        score_total = res_reglas["reglas_score"] + res_grafos["graph_score"] + res_ml["ml_score"]
        score_final = min(score_total, 100)

        # Se juntan en una sola lista todos los mensajes de alerta de los
        # 3 motores, para mostrarle al analista/usuario POR QUÉ se marcó
        # como riesgosa (o no) la transacción.
        alertas_totales = res_reglas["alertas_reglas"] + res_grafos["alerta_grafo"] + res_ml["alerta_ml"]

        # Si el score llega o supera el umbral de bloqueo, se rechaza;
        # si no, se aprueba. (No hay un estado intermedio "revisión
        # manual" a este nivel — eso lo agrega el orquestador, que
        # combina esto con el resultado de la verificación de identidad).
        dictamen = "RECHAZADA" if score_final >= self.umbral_bloqueo else "APROBADA"

        return {
            "status": dictamen,
            "risk_score": score_final,
            "alertar_usuario": dictamen == "RECHAZADA",
            "motivos": alertas_totales,
            # "metadata" muestra cuánto aportó cada motor al score total —
            # útil para depurar POR QUÉ se llegó a ese número.
            "metadata": {
                "desglose_reglas": res_reglas["reglas_score"],
                "desglose_grafos": res_grafos["graph_score"],
                "desglose_ml": res_ml["ml_score"]
            }
        }
