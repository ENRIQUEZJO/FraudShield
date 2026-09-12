"""
shared/orquestador.py

Flujo integrado de transferencia: combina modulo_biometria (¿quién es
esta persona?) y modulo_antifraude (¿esta transacción es riesgosa?)
en una sola operación con un veredicto consolidado.

REGLA DE NEGOCIO (decisión de diseño, revisar con el banco más adelante):
1. Si la biometría da FRAUDE (deepfake o rostro no coincide), se
   rechaza de inmediato — no tiene sentido evaluar el riesgo de una
   transacción si no se pudo confirmar quién la está haciendo.
2. Si la biometría es APROBADO o REVISION_MANUAL, se evalúa también
   el riesgo de la transacción con modulo_antifraude.
3. El veredicto final toma la señal MÁS restrictiva entre ambos
   motores (identidad y riesgo transaccional).
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from modulo_biometria.auth import obtener_usuario_actual
from modulo_biometria.services.face_engine import (
    get_encoding,               # convierte la foto en vivo en un embedding facial
    detectar_liveness_y_spoof,  # detecta si es una persona real o una foto/pantalla
    UMBRAL_SIMILITUD,
)
from shared.db import obtener_conexion, DB_DISPONIBLE
# Se reutilizan estas funciones ya definidas en modulo_biometria/router.py
# en vez de duplicar la lógica aquí — así, si algo cambia (ej. el bug de
# similitud que se corrigió), se corrige en un solo lugar.
from modulo_biometria.router import (
    decode_image,
    calcular_score,
    decidir_resultado,
    mejor_similitud_contra_perfil,
)

from modulo_antifraude.router import pipeline as antifraude_pipeline

router = APIRouter(tags=["transferencia"])

# Historial en memoria — respaldo cuando SQL Server no está disponible.
# Si `conn` existe, el historial real se guarda y se lee de la tabla
# VerificacionesTransferencia (database/schema_sqlserver.sql).
_historial_memoria: list[dict] = []
_MAX_HISTORIAL = 200


class TransferenciaCompletaRequest(BaseModel):
    """Todo lo que el frontend manda en un solo request para procesar
    una transferencia completa (identidad + riesgo)."""
    # --- datos para verificación biométrica ---
    frame: str      # foto en vivo, en base64
    user_id: int    # de quién dice ser la persona (se valida contra el token, ver más abajo)
    # --- datos para evaluación de riesgo ---
    monto: float
    cuenta_destino: str
    llamada_activa: bool
    tiempo_desde_deposito_minutos: float
    datos_copiados: bool = False
    # --- ubicación (opcional — el usuario puede negar el permiso) ---
    latitud: Optional[float] = None
    longitud: Optional[float] = None


def _url_mapa(lat, lon):
    """Arma un link de Google Maps a partir de lat/lon, o None si falta alguno de los dos."""
    return f"https://www.google.com/maps?q={lat},{lon}" if lat is not None and lon is not None else None


def _verificar_identidad(frame_b64: str, user_id: int) -> dict:
    """Reutiliza la misma lógica que modulo_biometria/router.py::verificar,
    pero como función interna (sin depender de la request HTTP)."""
    frame = decode_image(frame_b64)
    if frame is None:
        return {"resultado": "ERROR", "detalle": "Imagen inválida"}

    encoding = get_encoding(frame)
    es_real, confianza_antispoof = detectar_liveness_y_spoof(frame)

    if encoding is None:
        return {"resultado": "FRAUDE", "detalle": "No se detectó rostro"}

    similitud = 0.0
    if DB_DISPONIBLE:
        similitud, _ = mejor_similitud_contra_perfil(user_id, encoding)

    score = calcular_score(similitud, es_real, confianza_antispoof)
    resultado = decidir_resultado(score)

    return {
        "resultado": resultado,
        "score": score,
        "coincidencia": similitud > UMBRAL_SIMILITUD,
        "similitud": round(similitud, 3),
        "deepfake": not es_real,
        "confianza_antispoof": round(confianza_antispoof, 3),
    }


def _combinar_veredictos(identidad: dict, riesgo: dict) -> dict:
    """Aplica la regla de 'la señal más restrictiva gana'."""
    id_resultado = identidad["resultado"]
    riesgo_alerta = riesgo["alertar_usuario"]

    if id_resultado == "FRAUDE":
        # La identidad no se pudo confirmar — no importa qué tan limpia
        # sea la transacción, se rechaza igual.
        veredicto = "RECHAZADA"
        motivo_principal = "Identidad no verificada (posible deepfake o rostro no coincide)"
    elif riesgo_alerta:
        # Identidad OK, pero la transacción en sí es riesgosa.
        veredicto = "RECHAZADA"
        motivo_principal = "Transacción bloqueada por riesgo de fraude"
    elif id_resultado == "REVISION_MANUAL" or riesgo["status"] != "APROBADA":
        # Ninguno de los dos motores dio un "rechazo" claro, pero
        # tampoco los dos dieron luz verde total — se manda a que un
        # humano lo revise, en vez de aprobar o rechazar automáticamente.
        veredicto = "REVISION_MANUAL"
        motivo_principal = "Identidad o transacción requieren revisión manual"
    else:
        # Ambos motores dieron el visto bueno: se aprueba.
        veredicto = "APROBADA"
        motivo_principal = "Identidad verificada y transacción sin señales de riesgo"

    return {"veredicto": veredicto, "motivo_principal": motivo_principal}


def _guardar_en_db(user_id: int, data: TransferenciaCompletaRequest, resultado_final: dict) -> bool:
    """Intenta persistir el veredicto en SQL Server. Devuelve True/False
    según si tuvo éxito, para poder usar el respaldo en memoria."""
    if not DB_DISPONIBLE:
        return False
    try:
        with obtener_conexion() as (conn, cursor):
            cursor.execute(
                """
                INSERT INTO VerificacionesTransferencia
                (UsuarioId, Monto, CuentaDestino, Veredicto, MotivoPrincipal, Latitud, Longitud)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, data.monto, data.cuenta_destino,
                 resultado_final["veredicto"], resultado_final["motivo_principal"],
                 data.latitud, data.longitud),
            )
            conn.commit()
        return True
    except Exception as e:
        # El "with obtener_conexion()" ya hace rollback automático si algo falla.
        print(f"[shared/orquestador] No se pudo persistir en SQL Server: {e}")
        return False


@router.post("/procesar")
async def procesar_transferencia(
    data: TransferenciaCompletaRequest,
    usuario=Depends(obtener_usuario_actual),
):
    """Punto de entrada único: recibe foto + datos de la transferencia,
    verifica identidad, evalúa riesgo, y devuelve un veredicto único."""

    # Control de acceso: el "user_id" que viene en el body debe ser el
    # MISMO que el dueño del token (o un admin actuando en su nombre).
    # Sin esto, cualquier usuario logueado podría mandar el user_id de
    # OTRA persona junto con su propia foto, intentando procesar una
    # transferencia atribuida a otra cuenta.
    if usuario.get("user_id") != data.user_id and usuario.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="No autorizado para procesar una transferencia de otro usuario")

    identidad = _verificar_identidad(data.frame, data.user_id)

    if identidad["resultado"] == "ERROR":
        raise HTTPException(status_code=400, detail=identidad["detalle"])

    riesgo = None
    if identidad["resultado"] != "FRAUDE":
        try:
            riesgo = antifraude_pipeline.procesar_evaluacion({
                "cliente_id": data.user_id,
                "monto": data.monto,
                "cuenta_destino": data.cuenta_destino,
                "llamada_activa": data.llamada_activa,
                "tiempo_desde_deposito_minutos": data.tiempo_desde_deposito_minutos,
                "datos_copiados": data.datos_copiados,
            })
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error en motor antifraude: {str(e)}")
    else:
        # Identidad ya rechazada: no se gasta cómputo evaluando la
        # transacción — se marca directamente como no evaluada.
        riesgo = {"status": "NO_EVALUADO", "alertar_usuario": True, "risk_score": None, "motivos": []}

    combinado = _combinar_veredictos(identidad, riesgo)

    resultado_final = {
        "veredicto": combinado["veredicto"],
        "motivo_principal": combinado["motivo_principal"],
        "identidad": identidad,
        "riesgo_transaccion": riesgo,
    }

    # Intenta guardar en SQL Server; si no se puede, se usa el respaldo
    # en memoria para que el historial del dashboard siga funcionando.
    guardado = _guardar_en_db(data.user_id, data, resultado_final)
    if not guardado:
        _historial_memoria.insert(0, {
            "user_id": data.user_id,
            "monto": data.monto,
            "cuenta_destino": data.cuenta_destino,
            "latitud": data.latitud,
            "longitud": data.longitud,
            "mapa_url": _url_mapa(data.latitud, data.longitud),
            **resultado_final,
            "fecha": datetime.now(timezone.utc).isoformat(),
        })
        del _historial_memoria[_MAX_HISTORIAL:]

    return resultado_final


@router.get("/historial")
async def historial(usuario=Depends(obtener_usuario_actual), user_id: int | None = None, limit: int = 50):
    """Historial de veredictos combinados, para el dashboard.
    Lee de SQL Server si hay conexión; si no, usa el respaldo en memoria."""

    # Control de acceso: si se pide el historial de un user_id específico
    # que no es el propio, solo un admin puede verlo. Si no se pasa
    # user_id (se pide "todo"), también se restringe a admins — un
    # usuario normal solo debería ver lo suyo.
    es_admin = usuario.get("rol") == "admin"
    if not es_admin:
        if user_id is not None and user_id != usuario.get("user_id"):
            raise HTTPException(status_code=403, detail="No autorizado para ver el historial de otro usuario")
        if user_id is None:
            user_id = usuario.get("user_id")  # un usuario normal sin filtro explícito solo ve lo suyo

    if DB_DISPONIBLE:
        try:
            with obtener_conexion() as (conn, cursor):
                # El "{where}" se arma dinámicamente: con filtro de usuario o sin él.
                query = """
                    SELECT TOP (?) UsuarioId, Monto, CuentaDestino, Veredicto,
                           MotivoPrincipal, FechaRegistro, Latitud, Longitud
                    FROM VerificacionesTransferencia
                    {where}
                    ORDER BY FechaRegistro DESC
                """.format(where="WHERE UsuarioId = ?" if user_id is not None else "")
                params = (limit, user_id) if user_id is not None else (limit,)
                cursor.execute(query, params)
                rows = cursor.fetchall()
                return [
                    {
                        "user_id": r[0],
                        "monto": float(r[1]),
                        "cuenta_destino": r[2],
                        "veredicto": r[3],
                        "motivo_principal": r[4],
                        "fecha": r[5].isoformat() if r[5] else None,
                        "latitud": float(r[6]) if r[6] is not None else None,
                        "longitud": float(r[7]) if r[7] is not None else None,
                        "mapa_url": _url_mapa(r[6], r[7]),
                    }
                    for r in rows
                ]
        except Exception as e:
            print(f"[shared/orquestador] Error leyendo historial de SQL Server: {e}")
            # cae al respaldo en memoria abajo

    datos = _historial_memoria if user_id is None else [h for h in _historial_memoria if h["user_id"] == user_id]
    return datos[:limit]
