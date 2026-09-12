-- 1. Crear la base de datos
IF NOT EXISTS (SELECT * FROM sys.databases WHERE name = 'VisionSeguraDB')
CREATE DATABASE VisionSeguraDB;
GO

USE VisionSeguraDB;
GO

-- 2. Crear Tabla de Usuarios (Unificada)
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
ß
-- 3. Crear Tabla de Verificaciones (Historial)
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

-- Para crear tu primer usuario administrador manualmente:
-- UPDATE Usuarios SET Rol = 'admin' WHERE Email = 'admin@visionsegura.com';