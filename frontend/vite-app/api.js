// Este archivo centraliza TODAS las llamadas del frontend al backend.
// Cada función hace un fetch() a un endpoint específico y devuelve los
// datos ya convertidos de JSON — así los componentes de React no tienen
// que preocuparse por URLs, headers, ni manejo de errores repetido.

// URL base del backend — configurable, en vez de fija.
//
// En DESARROLLO (npm run dev): Vite no define VITE_API_BASE_URL por
// defecto, así que se usa "http://127.0.0.1:8000" — el backend
// corriendo en tu máquina en otro puerto.
//
// En PRODUCCIÓN (Docker + nginx, ver nginx/Dockerfile y
// docs/DESPLIEGUE.md): el build de producción usa
// frontend/vite-app/.env.production, que fija VITE_API_BASE_URL a una
// cadena VACÍA — así las peticiones quedan como rutas RELATIVAS
// ("/api/v1/..."), y es nginx quien las recibe y las reparte entre las
// réplicas del backend. Esto evita además cualquier problema de CORS,
// porque el navegador ve todo como el MISMO origen (nginx sirve tanto
// el frontend como el proxy hacia la API).
const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

const API_URL = `${API_BASE}/api/v1/biometria`;
const API_URL_ANTIFRAUDE = `${API_BASE}/api/v1/transacciones`;
const API_URL_ORQUESTADOR = `${API_BASE}/api/v1/transferencia`;

// Arma el header "Authorization: Bearer <token>" a partir del token
// guardado en localStorage tras el login. Si no hay token (usuario no
// logueado), devuelve un objeto vacío — fetch simplemente no manda ese
// header, y el backend responde 401/403 si la ruta lo requiere.
function authHeaders() {
    const token = localStorage.getItem("access_token");
    return token ? { Authorization: `Bearer ${token}` } : {};
}


export const login = async (email, password) => {
    try {
        const res = await fetch(`${API_URL}/login`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email, password }),
        });

        const data = await res.json();

        // Si el login fue exitoso, se guardan los datos de sesión en
        // localStorage — así persisten aunque se recargue la página, y
        // el resto de la app (authHeaders, App.jsx) puede leerlos.
        if (data.status === "ok") {
            localStorage.setItem("access_token", data.access_token);
            localStorage.setItem("user_id", data.user_id);
            localStorage.setItem("rol", data.rol);
            localStorage.setItem("nombre", data.nombre);
            localStorage.setItem("email", email);
        }

        return data;
    } catch (error) {
        console.error(error);
        return { status: "error", message: error.message };
    }
};

export const cerrarSesion = () => {
    // Borra toda la sesión guardada — App.jsx detecta que ya no hay
    // access_token y vuelve a mostrar la pantalla de Login.
    localStorage.removeItem("access_token");
    localStorage.removeItem("user_id");
    localStorage.removeItem("rol");
    localStorage.removeItem("nombre");
    localStorage.removeItem("email");
};

export const registrar = async (nombre, email, password, documento, fotos, empresaId = null) => {
    // fotos: [{ gesto: "centro", frame: "data:image/jpeg;base64,..." }, ...]
    try {
        const res = await fetch(`${API_URL}/register`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ nombre, email, password, documento, fotos, empresa_id: empresaId }),
        });
        return await res.json();
    } catch (error) {
        console.error(error);
        return { status: "error", message: error.message };
    }
};

export const verificar = async (frame) => {
    try {
        // Se compara la foto en vivo contra el usuario ACTUALMENTE
        // logueado (su ID sale de localStorage, no se pide como parámetro).
        const userId = localStorage.getItem("user_id");

        const res = await fetch(`${API_URL}/verificar`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                ...authHeaders(),  // esta ruta SÍ exige estar logueado
            },
            body: JSON.stringify({
                frame: frame,
                user_id: parseInt(userId),
            }),
        });

        if (!res.ok) {
            throw new Error("Error en la verificación");
        }

        return await res.json();
    } catch (error) {
        console.error(error);
        return { resultado: "ERROR", detalle: error.message };
    }
};

export const obtenerVerificaciones = async (userId) => {
    try {
        const res = await fetch(`${API_URL}/verificaciones/${userId}`, {
            headers: { ...authHeaders() },
        });

        if (!res.ok) {
            throw new Error("No se pudo obtener el historial");
        }

        return await res.json();
    } catch (error) {
        console.error(error);
        return [];  // en caso de error, se devuelve una lista vacía en vez de reventar el componente que llama esto
    }
};

// Usada por la pantalla "Revisar verificaciones" del panel de admin —
// trae TODAS las verificaciones de TODOS los usuarios (incluyendo las
// marcadas como REVISION_MANUAL, que son las que necesitan que un
// humano decida).
export const obtenerHistorialAdmin = async () => {
    try {
        const res = await fetch(`${API_URL}/admin/historial`, {
            headers: { ...authHeaders() },
        });
        if (!res.ok) throw new Error("No se pudo obtener el historial de admin");
        return await res.json();
    } catch (error) {
        console.error(error);
        return [];
    }
};

// Usada por la pantalla "Revisar verificaciones": el admin aprueba o
// rechaza a mano un caso marcado como REVISION_MANUAL.
export const accionarRegistro = async (id, nuevoEstado) => {
    try {
        const res = await fetch(`${API_URL}/admin/accionar`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                ...authHeaders(),
            },
            body: JSON.stringify({ id, nuevoEstado }),
        });
        return await res.json();
    } catch (error) {
        console.error(error);
        return { success: false, error: error.message };
    }
};

// ==========================================
// sistema-antifraude (/api/v1/transacciones)
// ==========================================

export const evaluarTransaccion = async (transaccion) => {
    try {
        const res = await fetch(`${API_URL_ANTIFRAUDE}/evaluar`, {
            method: "POST",
            headers: { "Content-Type": "application/json", ...authHeaders() },
            body: JSON.stringify(transaccion),
        });
        return await res.json();
    } catch (error) {
        console.error(error);
        return { status: "error", message: error.message };
    }
};

export const historialAntifraude = async (clienteId) => {
    try {
        // Si se pasa un clienteId, se filtra el historial a ese cliente;
        // si no, se traen todas las evaluaciones (pantalla de pruebas).
        const url = clienteId
            ? `${API_URL_ANTIFRAUDE}/historial?cliente_id=${clienteId}`
            : `${API_URL_ANTIFRAUDE}/historial`;
        const res = await fetch(url, { headers: { ...authHeaders() } });
        if (!res.ok) throw new Error("No se pudo obtener el historial de antifraude");
        return await res.json();
    } catch (error) {
        console.error(error);
        return [];
    }
};

// ==========================================
// Orquestador (/api/v1/transferencia)
// ==========================================

export const procesarTransferencia = async (payload) => {
    try {
        const res = await fetch(`${API_URL_ORQUESTADOR}/procesar`, {
            method: "POST",
            headers: { "Content-Type": "application/json", ...authHeaders() },
            body: JSON.stringify(payload),
        });
        return await res.json();
    } catch (error) {
        console.error(error);
        return { veredicto: "ERROR", motivo_principal: error.message };
    }
};

export const historialOrquestador = async (userId) => {
    try {
        // Nota: si NO se pasa userId, el backend ahora asume "mi propio
        // historial" para usuarios normales (o "todos" si eres admin) —
        // ver shared/orquestador.py::historial.
        const url = userId
            ? `${API_URL_ORQUESTADOR}/historial?user_id=${userId}`
            : `${API_URL_ORQUESTADOR}/historial`;
        const res = await fetch(url, { headers: { ...authHeaders() } });
        if (!res.ok) throw new Error("No se pudo obtener el historial del orquestador");
        return await res.json();
    } catch (error) {
        console.error(error);
        return [];
    }
};

// ==========================================
// Admin — usuarios y empresas (/api/v1/biometria/admin)
// ==========================================

export const adminListarUsuarios = async () => {
    try {
        const res = await fetch(`${API_URL}/admin/usuarios`, { headers: { ...authHeaders() } });
        if (!res.ok) throw new Error("No se pudo obtener la lista de usuarios");
        return await res.json();
    } catch (error) {
        console.error(error);
        return [];
    }
};

export const adminListarEmpresas = async () => {
    try {
        const res = await fetch(`${API_URL}/admin/empresas`, { headers: { ...authHeaders() } });
        if (!res.ok) throw new Error("No se pudo obtener la lista de empresas");
        return await res.json();
    } catch (error) {
        console.error(error);
        return [];
    }
};

export const adminCrearEmpresa = async (nombre) => {
    try {
        const res = await fetch(`${API_URL}/admin/empresas`, {
            method: "POST",
            headers: { "Content-Type": "application/json", ...authHeaders() },
            body: JSON.stringify({ nombre }),
        });
        return await res.json();
    } catch (error) {
        console.error(error);
        return { status: "error", message: error.message };
    }
};

export const adminAsignarEmpresa = async (userId, empresaId) => {
    try {
        const res = await fetch(`${API_URL}/admin/usuarios/empresa`, {
            method: "PUT",
            headers: { "Content-Type": "application/json", ...authHeaders() },
            body: JSON.stringify({ user_id: userId, empresa_id: empresaId }),
        });
        return await res.json();
    } catch (error) {
        console.error(error);
        return { status: "error", message: error.message };
    }
};

// ==========================================
// Admin — API Keys (integraciones externas)
// ==========================================

export const adminListarApiKeys = async () => {
    try {
        const res = await fetch(`${API_URL}/admin/api-keys`, { headers: { ...authHeaders() } });
        if (!res.ok) throw new Error("No se pudo obtener la lista de API keys");
        return await res.json();
    } catch (error) {
        console.error(error);
        return [];
    }
};

export const adminCrearApiKey = async (nombre, empresaId, limiteRps = 10) => {
    try {
        const res = await fetch(`${API_URL}/admin/api-keys`, {
            method: "POST",
            headers: { "Content-Type": "application/json", ...authHeaders() },
            body: JSON.stringify({ nombre, empresa_id: empresaId, limite_rps: limiteRps }),
        });
        // La respuesta incluye "api_key" en texto plano — ÚNICA vez que
        // se puede ver. El componente que llama esto debe mostrarla de
        // inmediato con una advertencia clara.
        return await res.json();
    } catch (error) {
        console.error(error);
        return { status: "error", message: error.message };
    }
};

export const adminRevocarApiKey = async (id) => {
    try {
        const res = await fetch(`${API_URL}/admin/api-keys/${id}/revocar`, {
            method: "PUT",
            headers: { ...authHeaders() },
        });
        return await res.json();
    } catch (error) {
        console.error(error);
        return { status: "error", message: error.message };
    }
};

export const adminCambiarLimiteApiKey = async (id, limiteRps) => {
    try {
        const res = await fetch(`${API_URL}/admin/api-keys/${id}/limite`, {
            method: "PUT",
            headers: { "Content-Type": "application/json", ...authHeaders() },
            body: JSON.stringify({ limite_rps: limiteRps }),
        });
        return await res.json();
    } catch (error) {
        console.error(error);
        return { status: "error", message: error.message };
    }
};
