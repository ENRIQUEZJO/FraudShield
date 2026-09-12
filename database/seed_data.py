# database/seed_data.py
#
# Reescrito para SQL Server (la versión original usaba SQLite como motor
# aparte, solo para pruebas rápidas — ya no aplica ahora que todo corre
# sobre el mismo SQL Server que usa modulo_biometria).
#
# Requiere que database/schema_sqlserver.sql ya se haya ejecutado (crea
# la base de datos FraudShieldDB y sus tablas).
#
# Uso:
#   python database/seed_data.py

import sys
import os

# Trucazo para que "from shared.db import ..." funcione al correr este
# script directamente: se agrega la carpeta raíz del proyecto (un nivel
# arriba de database/) a la lista de lugares donde Python busca módulos.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.db import obtener_conexion, DB_DISPONIBLE

# Datos de ejemplo para probar el motor antifraude sin tener que crear
# clientes a mano. Cada tupla es (Nombre, CuentaDormida, MontoPromedioTransaccion).
CLIENTES_EJEMPLO = [
    ("Juan Pérez (Cuenta Nómina Activa)", 0, 4500.00),
    ("Víctor - Cuenta Inactiva/Popular (Tu Escenario)", 1, 150.00),  # CuentaDormida=1: para probar el trigger de "vaciado rápido"
    ("María Gómez (Cuenta Comercial)", 0, 25000.00),
]


def inicializar_entorno_prueba():
    if not DB_DISPONIBLE:
        print("⚠️  No hay conexión a SQL Server. Revisa FRAUDSHIELD_DB_SERVER / FRAUDSHIELD_DB_NAME.")
        return

    print("🚀 Cargando datos de prueba en FraudShieldDB...")

    with obtener_conexion() as (conn, cursor):
        for nombre, cuenta_dormida, monto_promedio in CLIENTES_EJEMPLO:
            # Primero se busca si el cliente ya existe (por nombre), para
            # poder correr este script varias veces sin crear duplicados.
            cursor.execute(
                "SELECT ClienteId FROM Clientes WHERE Nombre = ?", (nombre,)
            )
            existente = cursor.fetchone()

            if existente:
                cliente_id = existente[0]
            else:
                cursor.execute(
                    "INSERT INTO Clientes (Nombre) OUTPUT INSERTED.ClienteId VALUES (?)",
                    (nombre,),
                )
                cliente_id = cursor.fetchone()[0]

            # Mismo criterio para el perfil financiero: solo se crea si no existe todavía.
            cursor.execute(
                "SELECT 1 FROM PerfilesFinancieros WHERE ClienteId = ?", (cliente_id,)
            )
            if not cursor.fetchone():
                cursor.execute(
                    """
                    INSERT INTO PerfilesFinancieros (ClienteId, MontoPromedioTransaccion, CuentaDormida)
                    VALUES (?, ?, ?)
                    """,
                    (cliente_id, monto_promedio, cuenta_dormida),
                )

        conn.commit()  # guarda todos los inserts/updates de una vez

    print("✅ Datos de prueba cargados con éxito.")
    print("ℹ️  El cliente 'Víctor - Cuenta Inactiva/Popular' quedó con CuentaDormida=1 para replicar el escenario de fraude por vaciado rápido.")


# Este bloque solo corre si ejecutas "python database/seed_data.py"
# directamente (no si otro archivo hace "import seed_data").
if __name__ == "__main__":
    inicializar_entorno_prueba()
