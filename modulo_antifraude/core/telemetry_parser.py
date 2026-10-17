# core/telemetry_parser.py
#
# ⚠️ CÓDIGO NO CONECTADO: este archivo no lo importa ni lo usa ningún
# otro archivo del proyecto (verificado — no aparece en pipeline.py ni
# en router.py). Quedó heredado del sistema-antifraude original. La
# misma lógica de "llamada activa + datos copiados" ya está cubierta
# directamente dentro de scoring_engine.py (reglas 2 y 4). Se deja aquí
# por si en el futuro se quiere separar esa lógica en su propio módulo,
# pero hoy no afecta el funcionamiento del sistema.
from typing import Dict, Any

class TelemetryParser:
    def __init__(self):
        pass

    def procesar_senales_dispositivo(self, payload_crudo: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analiza las variables técnicas del celular para identificar riesgos de coerción psicológica.
        """
        # Extraer variables con valores por defecto seguros (si no vienen
        # en el payload, se asume que NO están activas)
        llamada_activa = bool(payload_crudo.get("llamada_activa", False))
        datos_copiados = bool(payload_crudo.get("datos_copiados", False))

        # Lógica heurística: Si hay llamada activa Y datos copiados a la
        # vez, el nivel de manipulación es CRÍTICO (las dos señales juntas
        # son mucho más fuertes que cualquiera por separado).
        nivel_coercion = "BAJO"
        if llamada_activa and datos_copiados:
            nivel_coercion = "CRÍTICO"
        elif llamada_activa or datos_copiados:
            nivel_coercion = "MEDIO"

        return {
            "llamada_activa_confirmada": llamada_activa,
            "copiar_pegar_detectado": datos_copiados,
            "indicador_coercion_humana": nivel_coercion
        }
