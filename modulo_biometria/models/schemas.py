# Cada clase aquí es un "schema" de Pydantic: define qué forma debe
# tener el JSON que llega en el body de una petición. FastAPI valida
# automáticamente los datos contra estos schemas antes de que el código
# del endpoint se ejecute — si falta un campo obligatorio o tiene el
# tipo equivocado, FastAPI rechaza la petición con un error 422 solo.
from pydantic import BaseModel
from typing import List, Optional


class FrameData(BaseModel):
    """Datos para verificar una foto contra un usuario ya registrado."""
    frame: str    # la foto en base64 (formato "data:image/jpeg;base64,...")
    user_id: int  # a qué usuario comparar


class FotoAngulo(BaseModel):
    """Una sola foto capturada durante el registro, con el gesto al que corresponde."""
    gesto: str  # "centro", "izquierda", "derecha", "arriba"
    frame: str  # la foto en base64


class RegistroUsuario(BaseModel):
    """Datos completos para crear una cuenta nueva."""
    nombre: str
    email: str
    password: str
    documento: str
    fotos: List[FotoAngulo]           # deben venir los 4 gestos (ver GESTOS_REQUERIDOS en router.py)
    empresa_id: Optional[int] = None  # opcional — a qué empresa/grupo pertenece (panel de admin)


class LoginRequest(BaseModel):
    email: str
    password: str


class AccionarRequest(BaseModel):
    """Usado por el admin para cambiar el estado de una verificación
    (ej. de 'REVISION_MANUAL' a 'APROBADO' tras revisarla a mano)."""
    id: int
    nuevoEstado: str


class EmpresaCreate(BaseModel):
    """Para crear una empresa/grupo nuevo desde el panel de admin."""
    nombre: str


class CambiarEmpresaRequest(BaseModel):
    """Para asignar (o quitar) la empresa de un usuario ya existente."""
    user_id: int
    empresa_id: Optional[int] = None  # None = quitar de cualquier empresa


class ApiKeyCreate(BaseModel):
    """Para generar una API key nueva desde el panel de admin — pensada
    para que un banco/institución afiliada integre sus propios sistemas
    con FraudShield sin usar el login de usuario normal."""
    nombre: str                        # ej. "Integración Banco Popular - App Móvil"
    empresa_id: Optional[int] = None   # opcional — a qué empresa pertenece esta integración