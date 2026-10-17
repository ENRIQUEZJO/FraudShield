-- database/schema.sql

-- Tabla principal de clientes
CREATE TABLE clientes (
    cliente_id SERIAL PRIMARY KEY,
    nombre VARCHAR(100) NOT NULL,
    estado_cuenta VARCHAR(20) DEFAULT 'ACTIVA', -- ACTIVA, SUSPENDIDA, BLOQUEADA
    fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Perfil financiero histórico (Monitorea el comportamiento de los últimos 90 días)
CREATE TABLE perfiles_financieros (
    cliente_id INT PRIMARY KEY REFERENCES clientes(cliente_id),
    monto_promedio_transaccion NUMERIC(12, 2) DEFAULT 0.00,
    cuenta_dormida BOOLEAN DEFAULT FALSE,
    ultima_actividad TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Registro de telemetría recolectada por el SDK del teléfono móvil
CREATE TABLE telemetria_comportamiento (
    evento_id SERIAL PRIMARY KEY,
    cliente_id INT REFERENCES clientes(cliente_id),
    llamada_activa BOOLEAN DEFAULT FALSE,
    datos_copiados BOOLEAN DEFAULT FALSE,
    fecha_captura TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Registro transaccional del banco
CREATE TABLE transferencias (
    transferencia_id SERIAL PRIMARY KEY,
    cliente_id INT REFERENCES clientes(cliente_id),
    monto NUMERIC(12, 2) NOT NULL,
    cuenta_destino VARCHAR(50) NOT NULL,
    tiempo_desde_deposito_minutos NUMERIC(6, 2) NOT NULL,
    estado_transaccion VARCHAR(20) DEFAULT 'PENDIENTE', -- APROBADA, RECHAZADA_FRAUDE
    fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
