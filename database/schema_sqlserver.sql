-- database/schema_sqlserver.sql
--
-- Schema único de FraudShield en SQL Server. Reemplaza:
--   - database/schema.sql (PostgreSQL, antiguo sistema-antifraude)
--   - database/visionsegura_sqlserver.sql (mismas tablas, sin el bug corregido abajo)
-- Ambos archivos se conservan solo como referencia histórica; ya no se usan.
--
-- Nota de diseño: las tablas de VisionSegura (Usuarios/Verificaciones) y las
-- de sistema-antifraude (Clientes/PerfilesFinancieros/Transferencias) NO
-- están fusionadas en una sola identidad de usuario todavía — siguen siendo
-- dos modelos separados, ahora conviviendo en la misma base de datos. Esa
-- unificación de identidad es una decisión aparte, pendiente para después
-- de la validación con el banco (ver /areas/integracion-proyectos.md).

IF NOT EXISTS (SELECT * FROM sys.databases WHERE name = 'FraudShieldDB')
CREATE DATABASE FraudShieldDB;
GO

USE FraudShieldDB;
GO

-- ============================================================
-- MÓDULO BIOMETRÍA (antes VisionSegura)
-- ============================================================

IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='Usuarios' AND xtype='U')
CREATE TABLE Usuarios (
    Id INT PRIMARY KEY IDENTITY(1,1),
    Nombre NVARCHAR(100),
    Email NVARCHAR(100) UNIQUE,
    Password NVARCHAR(255),
    Documento NVARCHAR(50),
    FaceEncoding VARBINARY(MAX),
    Rol NVARCHAR(20) DEFAULT 'user',
    FechaRegistro DATETIME DEFAULT GETDATE()
);
GO

IF NOT EXISTS (
    SELECT * FROM sys.columns
    WHERE object_id = OBJECT_ID('Usuarios') AND name = 'Rol'
)
ALTER TABLE Usuarios ADD Rol NVARCHAR(20) DEFAULT 'user';
GO

-- Empresas: agrupan usuarios para el panel de administración. Un
-- usuario puede no pertenecer a ninguna (EmpresaId NULL) — por ejemplo
-- los que se auto-registraron antes de que existiera este concepto.
IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='Empresas' AND xtype='U')
CREATE TABLE Empresas (
    EmpresaId INT PRIMARY KEY IDENTITY(1,1),
    Nombre NVARCHAR(150) NOT NULL UNIQUE,
    FechaCreacion DATETIME DEFAULT GETDATE()
);
GO

IF NOT EXISTS (
    SELECT * FROM sys.columns
    WHERE object_id = OBJECT_ID('Usuarios') AND name = 'EmpresaId'
)
ALTER TABLE Usuarios ADD EmpresaId INT NULL REFERENCES Empresas(EmpresaId);
GO

-- Perfil facial multi-ángulo: reemplaza el uso de Usuarios.FaceEncoding
-- (que solo guardaba UNA foto/ángulo). Ahora el registro captura varios
-- gestos (centro, izquierda, derecha, arriba) y cada uno se guarda como
-- una fila separada aquí. En la verificación se compara el rostro en
-- vivo contra TODOS los ángulos guardados y se toma la mejor similitud
-- — más tolerante a variaciones de ángulo/luz que un solo embedding, y
-- de paso más difícil de burlar con una sola foto estática (para
-- registrarse hay que mostrar varios ángulos reales de una cara).
-- Usuarios.FaceEncoding se deja en la tabla por compatibilidad con
-- filas viejas, pero el código ya no escribe ahí — todo lo nuevo va a
-- PerfilesFaciales.
IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='PerfilesFaciales' AND xtype='U')
CREATE TABLE PerfilesFaciales (
    Id INT PRIMARY KEY IDENTITY(1,1),
    UsuarioId INT NOT NULL,
    Gesto NVARCHAR(20) NOT NULL, -- 'centro', 'izquierda', 'derecha', 'arriba'
    Encoding VARBINARY(MAX) NOT NULL,
    FechaCaptura DATETIME DEFAULT GETDATE(),
    CONSTRAINT FK_PerfilFacial_Usuario FOREIGN KEY (UsuarioId) REFERENCES Usuarios(Id)
);
GO

IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='Verificaciones' AND xtype='U')
CREATE TABLE Verificaciones (
    Id INT PRIMARY KEY IDENTITY(1,1),
    UsuarioId INT,
    Resultado NVARCHAR(50),
    Coincidencia BIT,
    EsDeepfake BIT,
    Score INT DEFAULT 0,
    Fecha DATETIME DEFAULT GETDATE(),
    CONSTRAINT FK_Usuario FOREIGN KEY (UsuarioId) REFERENCES Usuarios(Id)
);
GO

IF NOT EXISTS (
    SELECT * FROM sys.columns
    WHERE object_id = OBJECT_ID('Verificaciones') AND name = 'Score'
)
ALTER TABLE Verificaciones ADD Score INT DEFAULT 0;
GO

-- API Keys: para que sistemas externos (de un banco o institución
-- afiliada) llamen a ciertos endpoints de FraudShield sin pasar por el
-- login de usuario normal — pensado para integraciones sistema-a-sistema.
-- Solo se guarda el HASH de la llave, nunca la llave en texto plano —
-- igual que con las contraseñas, si alguien accede a la base de datos
-- no puede recuperar la llave real, solo confirmar si una llave dada coincide.
IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='ApiKeys' AND xtype='U')
CREATE TABLE ApiKeys (
    Id INT PRIMARY KEY IDENTITY(1,1),
    Nombre NVARCHAR(150) NOT NULL,           -- para qué/quién es esta llave (ej. "Integración Banco Popular - Sucursal Digital")
    KeyHash NVARCHAR(255) NOT NULL,          -- hash SHA-256 de la llave real (nunca se guarda la llave en texto plano)
    EmpresaId INT NULL REFERENCES Empresas(EmpresaId),
    Activa BIT DEFAULT 1,
    -- Límite de peticiones por segundo para ESTA institución en
    -- particular (no todas necesitan el mismo volumen — un banco
    -- pequeño y uno grande no deberían compartir el mismo límite).
    -- Ver database/RATE_LIMITING.md para cómo se decide este número.
    LimiteRPS INT DEFAULT 10,
    FechaCreacion DATETIME DEFAULT GETDATE(),
    UltimoUso DATETIME NULL
);
GO

IF NOT EXISTS (
    SELECT * FROM sys.columns
    WHERE object_id = OBJECT_ID('ApiKeys') AND name = 'LimiteRPS'
)
ALTER TABLE ApiKeys ADD LimiteRPS INT DEFAULT 10;
GO


-- Para crear tu primer usuario administrador manualmente:
-- UPDATE Usuarios SET Rol = 'admin' WHERE Email = 'admin@fraudshield.com';


-- ============================================================
-- MÓDULO ANTIFRAUDE (antes sistema-antifraude — convertido de
-- PostgreSQL a T-SQL; ver database/schema.sql para la versión
-- original)
-- ============================================================

-- Nota: ClienteId aquí NO tiene FK hacia Usuarios.Id todavía (ver nota
-- de diseño arriba) ni hacia Clientes.ClienteId en Transferencias — se
-- deja como INT simple para que las pruebas del MVP no fallen si se
-- evalúa una transacción para un cliente_id que aún no tiene perfil.

IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='Clientes' AND xtype='U')
CREATE TABLE Clientes (
    ClienteId INT PRIMARY KEY IDENTITY(1,1),
    Nombre NVARCHAR(100) NOT NULL,
    EstadoCuenta NVARCHAR(20) DEFAULT 'ACTIVA', -- ACTIVA, SUSPENDIDA, BLOQUEADA
    FechaCreacion DATETIME DEFAULT GETDATE()
);
GO

IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='PerfilesFinancieros' AND xtype='U')
CREATE TABLE PerfilesFinancieros (
    ClienteId INT PRIMARY KEY REFERENCES Clientes(ClienteId),
    MontoPromedioTransaccion DECIMAL(12, 2) DEFAULT 0.00,
    CuentaDormida BIT DEFAULT 0,
    UltimaActividad DATETIME DEFAULT GETDATE()
);
GO

IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='TelemetriaComportamiento' AND xtype='U')
CREATE TABLE TelemetriaComportamiento (
    EventoId INT PRIMARY KEY IDENTITY(1,1),
    ClienteId INT REFERENCES Clientes(ClienteId),
    LlamadaActiva BIT DEFAULT 0,
    DatosCopiados BIT DEFAULT 0,
    FechaCaptura DATETIME DEFAULT GETDATE()
);
GO

IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='Transferencias' AND xtype='U')
CREATE TABLE Transferencias (
    TransferenciaId INT PRIMARY KEY IDENTITY(1,1),
    ClienteId INT NOT NULL,
    Monto DECIMAL(12, 2) NOT NULL,
    CuentaDestino NVARCHAR(50) NOT NULL,
    TiempoDesdeDepositoMinutos DECIMAL(6, 2) NOT NULL,
    LlamadaActiva BIT DEFAULT 0,
    DatosCopiados BIT DEFAULT 0,
    RiskScore INT,
    EstadoTransaccion NVARCHAR(20) DEFAULT 'PENDIENTE', -- APROBADA, RECHAZADA
    Motivos NVARCHAR(MAX), -- JSON serializado con la lista de alertas
    Latitud DECIMAL(9, 6) NULL,  -- punto exacto desde donde se hizo la transacción
    Longitud DECIMAL(9, 6) NULL, -- NULL si el usuario negó el permiso de ubicación del navegador
    FechaRegistro DATETIME DEFAULT GETDATE()
);
GO

IF NOT EXISTS (
    SELECT * FROM sys.columns
    WHERE object_id = OBJECT_ID('Transferencias') AND name = 'Latitud'
)
ALTER TABLE Transferencias ADD Latitud DECIMAL(9, 6) NULL;
GO

IF NOT EXISTS (
    SELECT * FROM sys.columns
    WHERE object_id = OBJECT_ID('Transferencias') AND name = 'Longitud'
)
ALTER TABLE Transferencias ADD Longitud DECIMAL(9, 6) NULL;
GO

-- Trigger equivalente al de PostgreSQL (database/triggers.sql):
-- bloquea transferencias que intentan vaciar una cuenta marcada como
-- dormida en menos de 15 minutos desde el último depósito. En T-SQL,
-- los triggers son AFTER por defecto, así que se revierte con ROLLBACK
-- en vez de RAISE EXCEPTION antes del insert.
--
-- Cómo interactúa esto con el código Python (modulo_antifraude/router.py):
-- cuando este trigger hace ROLLBACK + RAISERROR, el INSERT desde Python
-- lanza una excepción — el código ya está preparado para eso (la
-- captura como "no se pudo persistir" y usa el respaldo en memoria).
-- Es decir, un rechazo del trigger NO es un error real del sistema, es
-- exactamente el comportamiento esperado de seguridad.
IF OBJECT_ID('trigger_velocidad_transferencia', 'TR') IS NOT NULL
DROP TRIGGER trigger_velocidad_transferencia;
GO

CREATE TRIGGER trigger_velocidad_transferencia
ON Transferencias
AFTER INSERT
AS
BEGIN
    SET NOCOUNT ON;  -- evita que SQL Server mande un mensaje extra de "(1 row affected)" que podría confundir al driver

    -- "inserted" es una tabla especial de SQL Server que, dentro de un
    -- trigger AFTER INSERT, contiene las filas que se acaban de insertar.
    IF EXISTS (
        SELECT 1
        FROM inserted i
        JOIN PerfilesFinancieros pf ON pf.ClienteId = i.ClienteId
        WHERE pf.CuentaDormida = 1
          AND i.TiempoDesdeDepositoMinutos < 15.00
    )
    BEGIN
        ROLLBACK TRANSACTION;  -- deshace el INSERT que acaba de pasar
        RAISERROR('BLOQUEO TRANSACCIONAL: Intento de vaciado rápido detectado en cuenta inactiva. Fondos retenidos preventivamente.', 16, 1);
    END
END;
GO


-- ============================================================
-- MÓDULO ORQUESTADOR (nuevo — historial de veredictos combinados)
-- ============================================================

IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='VerificacionesTransferencia' AND xtype='U')
CREATE TABLE VerificacionesTransferencia (
    Id INT PRIMARY KEY IDENTITY(1,1),
    UsuarioId INT NOT NULL,
    Monto DECIMAL(12, 2) NOT NULL,
    CuentaDestino NVARCHAR(50) NOT NULL,
    Veredicto NVARCHAR(20) NOT NULL, -- APROBADA, REVISION_MANUAL, RECHAZADA
    MotivoPrincipal NVARCHAR(255),
    Latitud DECIMAL(9, 6) NULL,
    Longitud DECIMAL(9, 6) NULL,
    FechaRegistro DATETIME DEFAULT GETDATE()
);
GO

IF NOT EXISTS (
    SELECT * FROM sys.columns
    WHERE object_id = OBJECT_ID('VerificacionesTransferencia') AND name = 'Latitud'
)
ALTER TABLE VerificacionesTransferencia ADD Latitud DECIMAL(9, 6) NULL;
GO

IF NOT EXISTS (
    SELECT * FROM sys.columns
    WHERE object_id = OBJECT_ID('VerificacionesTransferencia') AND name = 'Longitud'
)
ALTER TABLE VerificacionesTransferencia ADD Longitud DECIMAL(9, 6) NULL;
GO
