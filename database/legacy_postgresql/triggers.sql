-- database/triggers.sql

CREATE OR REPLACE FUNCTION verificar_velocidad_fondos()
RETURNS TRIGGER AS $$
DECLARE
    es_dormida BOOLEAN;
BEGIN
    -- 1. Consultar si la cuenta del cliente está marcada como dormida/inactiva
    SELECT cuenta_dormida INTO es_dormida 
    FROM perfiles_financieros 
    WHERE cliente_id = NEW.cliente_id;

    -- 2. Si la cuenta está dormida Y el dinero busca salir en menos de 15 minutos, abortar
    IF es_dormida = TRUE AND NEW.tiempo_desde_deposito_minutos < 15.00 THEN
        -- Cambiar estado para auditoría
        NEW.estado_transaccion := 'RECHAZADA_FRAUDE';
        
        -- Lanzar una excepción de SQL para romper la transacción atómicamente
        RAISE EXCEPTION 'BLOQUEO TRANSACCIONAL: Intento de vaciado rápido detectado en cuenta inactiva. Fondos retenidos preventivamente.';
    END IF;

    -- Si pasa las reglas duras, permitir que continúe su curso hacia la aprobación
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Asociar el trigger a la tabla de transferencias para que actúe ANTES de insertar el registro
CREATE TRIGGER trigger_velocidad_transferencia
BEFORE INSERT ON transferencias
FOR EACH ROW
EXECUTE FUNCTION verificar_velocidad_fondos();
