# core/scoring_engine.py
from typing import Dict, Any, List


class ScoringEngine:
    """Motor de reglas heurísticas fijas: puntúa una transacción según
    patrones de comportamiento conocidos de fraude bancario (velocidad
    de retiro, presión telefónica, montos atípicos, etc). No usa IA —
    son reglas de negocio explícitas, fáciles de auditar y explicar."""

    def __init__(self, umbral_tiempo_minutos: float = 15.0, umbral_monto_anomalo: float = 5000.0):
        self.umbral_tiempo = umbral_tiempo_minutos    # por debajo de esto, un retiro se considera "demasiado rápido"
        self.umbral_monto = umbral_monto_anomalo      # por encima de esto, un monto se considera "atípico"

    def evaluar_reglas_estaticas(self, datos: Dict[str, Any]) -> Dict[str, Any]:
        """
        Calcula un puntaje de riesgo de 0 a 100 basado en reglas heurísticas de negocio.
        """
        score = 0
        detalles: List[str] = []  # aquí se van acumulando los mensajes de cada alerta que se dispare

        # Regla 1: Velocidad de fondos (Moneymule Pass-Through).
        # Si el dinero se retira muy poco tiempo después de haber sido
        # depositado, es un patrón clásico de "cuenta mula" (recibe
        # fondos robados y los reenvía de inmediato antes de que el
        # banco pueda reaccionar).
        tiempo_deposito = datos.get("tiempo_desde_deposito_minutos", 999.0)  # 999 = "hace mucho", valor seguro por defecto
        if tiempo_deposito <= self.umbral_tiempo:
            score += 40
            detalles.append(f"ALERTA: Intento de retiro rápido en menos de {self.umbral_tiempo} min.")

        # Regla 2: Coerción activa por llamada en segundo plano.
        # Si el usuario tiene una llamada telefónica activa MIENTRAS
        # hace la transferencia, es la señal más común de estafas de
        # "ingeniería social" (alguien lo está presionando por teléfono
        # haciéndose pasar por el banco/la policía/etc).
        if datos.get("llamada_activa", False):
            score += 30
            detalles.append("ALERTA: Llamada telefónica activa concurrente con la transferencia (Posible coerción).")

        # Regla 3: Desviación drástica de montos habituales.
        # Un monto inusualmente alto (respecto al comportamiento normal
        # de la cuenta) merece más escrutinio.
        monto = datos.get("monto", 0.0)
        if monto >= self.umbral_monto:
            score += 15
            detalles.append(f"ALERTA: Monto transferido ({monto}) supera el comportamiento base de la cuenta.")

        # Regla 4: Telemetría de Interfaz (Pegado masivo de datos del
        # estafador). Si los datos del destinatario (número de cuenta,
        # etc.) fueron copiados y pegados en bloque en vez de escritos a
        # mano, sugiere que se los pasó un tercero (patrón típico de
        # fraude telefónico donde el estafador dicta los datos).
        if datos.get("datos_copiados", False):
            score += 15
            detalles.append("ALERTA: Datos del destinatario copiados y pegados en bloque (Patrón chipero).")

        return {
            "reglas_score": min(score, 100),  # nunca superar 100, aunque se disparen varias reglas a la vez
            "alertas_reglas": detalles
        }