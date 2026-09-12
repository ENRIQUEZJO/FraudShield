// AdminEmpresas.jsx — formulario para crear empresas/grupos nuevos, y
// tabla con las que ya existen (y cuántos usuarios tiene cada una).
import { useEffect, useState } from "react";
import { adminListarEmpresas, adminCrearEmpresa } from "../api";

// onCambio: se llama después de crear una empresa con éxito, para que
// el componente padre (AdminPanel) también refresque su copia de la
// lista (la necesita para pasársela al selector dentro de Registro).
export default function AdminEmpresas({ onCambio }) {
  const [empresas, setEmpresas] = useState([]);
  const [nombreNueva, setNombreNueva] = useState("");
  const [creando, setCreando] = useState(false);
  const [error, setError] = useState("");

  const cargar = () => {
    adminListarEmpresas().then((e) => setEmpresas(Array.isArray(e) ? e : []));
  };

  useEffect(() => {
    cargar();
  }, []);

  const crear = async (e) => {
    e.preventDefault();
    if (!nombreNueva.trim()) return;  // evita crear una empresa con nombre vacío o solo espacios

    setCreando(true);
    setError("");
    const res = await adminCrearEmpresa(nombreNueva.trim());
    setCreando(false);

    if (res.status === "ok") {
      setNombreNueva("");   // limpia el campo para la siguiente empresa
      cargar();              // refresca esta tabla
      onCambio?.();          // avisa al padre, si le interesa saberlo (el "?." evita un error si no se pasó esta prop)
    } else {
      // El backend responde con este mensaje, por ejemplo, si el
      // nombre ya existe (restricción UNIQUE en la base de datos).
      setError(res.message || "No se pudo crear la empresa");
    }
  };

  return (
    <div>
      <form className="mini-form" onSubmit={crear}>
        <input
          type="text"
          placeholder="Nombre de la nueva empresa"
          value={nombreNueva}
          onChange={(e) => setNombreNueva(e.target.value)}
        />
        <button className="button" type="submit" disabled={creando}>
          {creando ? "Creando..." : "Crear empresa"}
        </button>
      </form>

      {error && <p className="login-error">{error}</p>}

      {empresas.length === 0 ? (
        <p className="dashboard-vacio">Sin empresas creadas todavía.</p>
      ) : (
        <table width="100%">
          <thead>
            <tr>
              <th>Nombre</th>
              <th>Usuarios</th>
              <th>Creada</th>
            </tr>
          </thead>
          <tbody>
            {empresas.map((emp) => (
              <tr key={emp.empresaId}>
                <td>{emp.nombre}</td>
                <td>{emp.cantidadUsuarios}</td>
                <td>{emp.fechaCreacion ? emp.fechaCreacion.split(".")[0].replace("T", " ") : "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
