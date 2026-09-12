"""
modulo_antifraude/router.py

Adaptado del app.py original de sistema-antifraude.
Antes era una FastAPI() independiente; ahora es un APIRouter que
se monta dentro del backend unificado (ver main.py).
"""
import json  # para guardar/leer la lista de "motivos" de alerta como texto en la base de datos
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from modulo_antifraude.core.pipeline import FraudPipeline
from shared.db import obtener_conexion, DB_DISPONIBLE
# obtener_usuario_o_api_key: acepta CUALQUIERA de los dos — un usuario
# logueado en la app (JWT) O una API key de una institución integrada.
# El endpoint de evaluación de riesgo (/evaluar) es exactamente el tipo
# de endpoint que un sistema externo de un banco afiliado necesitaría
# llamar directamente, sin pasar por el login de un usuario humano.
from modulo_biometria.auth import obtener_usuario_actual, obtener_usuario_o_api_key

router = APIRouter(tags=["antifraude"])

# El pipeline se instancia UNA sola vez al importar el módulo.
# Importante: el modelo de ML (IsolationForest) se entrena en el
# constructor, así que si lo instanciáramos dentro del endpoint,
# se reentrenaría en CADA petición. El pipeline internamente reentrena
# el modelo de ML y refresca el grafo con datos REALES de forma
# periódica (ver ai_models/model.py y ai_models/graph_analyzer.py).
pipeline = FraudPipeline()

# Historial en memoria — se usa como RESPALDO cuando SQL Server no está
# disponible (por ejemplo, en este entorno de desarrollo). Si
# DB_DISPONIBLE es True, el historial real se guarda y se lee de la
# tabla Transferencias (database/schema_sqlserver.sql).
_historial_memoria: list[dict] = []
_MAX_HISTORIAL = 200  # tope de cuántas evaluaciones se guardan en memoria, para no crecer sin límite


class TransferenciaRequest(BaseModel):
    """Datos que el frontend envía para evaluar una transacción."""
    cliente_id: int
    monto: float
    cuenta_destino: str
    llamada_activa: bool
    tiempo_desde_deposito_minutos: float
    datos_copiados: bool = False
    # Ubicación del navegador en el momento de la transacción. Opcional
    # a propósito: el usuario puede negar el permiso de geolocalización,
    # y eso NUNCA debe bloquear la transacción — solo queda sin ubicación
    # registrada en el historial.
    latitud: Optional[float] = None
    longitud: Optional[float] = None


def _url_mapa(lat, lon):
    """Arma un link de Google Maps a partir de lat/lon, o None si falta alguno de los dos."""
    return f"https://www.google.com/maps?q={lat},{lon}" if lat is not None and lon is not None else None


def _guardar_en_db(data: TransferenciaRequest, respuesta: dict) -> bool:
    """Intenta persistir la evaluación en SQL Server. Devuelve True si
    tuvo éxito, False si no hay conexión o falló (para usar el
    respaldo en memoria)."""
    if not DB_DISPONIBLE:
        return False  # sin conexión a la base de datos, ni lo intentamos
    try:
        with obtener_conexion() as (conn, cursor):
            cursor.execute(
                """
                INSERT INTO Transferencias
                (ClienteId, Monto, CuentaDestino, TiempoDesdeDepositoMinutos,
                 LlamadaActiva, DatosCopiados, RiskScore, EstadoTransaccion, Motivos,
                 Latitud, Longitud)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data.cliente_id, data.monto, data.cuenta_destino,
                    data.tiempo_desde_deposito_minutos, int(data.llamada_activa),  # SQL Server usa 0/1, no True/False
                    int(data.datos_copiados), respuesta["risk_score"],
                    respuesta["status"], json.dumps(respuesta["motivos"]),  # la lista de motivos se guarda como texto JSON
                    data.latitud, data.longitud,
                ),
            )
            conn.commit()  # sin esto, el INSERT no queda guardado de verdad
        return True
    except Exception as e:
        # El trigger de "vaciado rápido en cuenta dormida" puede abortar
        # el INSERT a propósito (ver database/schema_sqlserver.sql) — en
        # ese caso el rechazo YA está reflejado en `respuesta`, así que
        # no es un error real, solo no queda esta fila en la tabla. El
        # "with obtener_conexion()" ya hace rollback automático.
        print(f"[modulo_antifraude] No se pudo persistir en SQL Server: {e}")
        return False


@router.post("/evaluar")
def evaluar_transferencia(data: TransferenciaRequest, cliente=Depends(obtener_usuario_o_api_key)):
    """Evalúa el riesgo de fraude de una transacción y guarda el
    resultado. Acepta autenticación por JWT (usuario de la app) o por
    API key (sistema externo de un banco/institución integrada)."""
    try:
        # el pipeline de scoring no necesita lat/lon — se excluyen del dict
        # que se le pasa (esas dos claves solo interesan para el historial)
        datos_pipeline = data.model_dump(exclude={"latitud", "longitud"})
        resultado = pipeline.procesar_evaluacion(datos_pipeline)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error en el motor de decisiones: {str(e)}")

    respuesta = {
        "status": resultado["status"],
        "fraude_detectado": resultado["alertar_usuario"],
        "risk_score": resultado["risk_score"],
        "alertar_usuario": resultado["alertar_usuario"],
        "motivos": resultado["motivos"],
        "mensaje": (
            "Transferencia bloqueada preventivamente por patrones de fraude por triangulación."
            if resultado["alertar_usuario"]
            else "Transferencia procesada con éxito."
        ),
        "metadata": resultado["metadata"]
    }

    # Intenta guardar en SQL Server; si no se puede, usa el respaldo en
    # memoria para que el historial del dashboard siga teniendo datos.
    guardado = _guardar_en_db(data, respuesta)
    if not guardado:
        _historial_memoria.insert(0, {  # insert(0, ...) = lo más nuevo queda primero en la lista
            "cliente_id": data.cliente_id,
            "monto": data.monto,
            "cuenta_destino": data.cuenta_destino,
            "latitud": data.latitud,
            "longitud": data.longitud,
            "mapa_url": _url_mapa(data.latitud, data.longitud),
            **respuesta,  # incorpora todas las claves de "respuesta" (status, risk_score, etc.)
            "fecha": datetime.now(timezone.utc).isoformat(),
        })
        del _historial_memoria[_MAX_HISTORIAL:]  # recorta la lista si ya pasó los 200 elementos

    return respuesta


@router.get("/historial")
def historial(cliente_id: int | None = None, limit: int = 50, usuario=Depends(obtener_usuario_actual)):
    """Historial de evaluaciones para alimentar el dashboard.
    Lee de SQL Server si hay conexión; si no, usa el respaldo en memoria."""
    if DB_DISPONIBLE:
        try:
            with obtener_conexion() as (conn, cursor):
                # El "{where}" se arma dinámicamente: si se pidió un cliente_id
                # específico, se agrega el filtro; si no, se traen todos.
                query = """
                    SELECT TOP (?) ClienteId, Monto, CuentaDestino, RiskScore,
                           EstadoTransaccion, Motivos, FechaRegistro, Latitud, Longitud
                    FROM Transferencias
                    {where}
                    ORDER BY FechaRegistro DESC
                """.format(where="WHERE ClienteId = ?" if cliente_id is not None else "")
                params = (limit, cliente_id) if cliente_id is not None else (limit,)
                cursor.execute(query, params)
                rows = cursor.fetchall()
                return [
                    {
                        "cliente_id": r[0],
                        "monto": float(r[1]),
                        "cuenta_destino": r[2],
                        "risk_score": r[3],
                        "status": r[4],
                        "motivos": json.loads(r[5]) if r[5] else [],  # el texto JSON guardado se vuelve a convertir en lista
                        "fecha": r[6].isoformat() if r[6] else None,
                        "latitud": float(r[7]) if r[7] is not None else None,
                        "longitud": float(r[8]) if r[8] is not None else None,
                        "mapa_url": _url_mapa(r[7], r[8]),
                    }
                    for r in rows
                ]
        except Exception as e:
            print(f"[modulo_antifraude] Error leyendo historial de SQL Server: {e}")
            # cae al respaldo en memoria abajo

    # Si no hay conexión a la base de datos, o la consulta falló: se usa
    # la lista en memoria, filtrando por cliente_id si se pidió.
    datos = _historial_memoria if cliente_id is None else [h for h in _historial_memoria if h["cliente_id"] == cliente_id]
    return datos[:limit]
