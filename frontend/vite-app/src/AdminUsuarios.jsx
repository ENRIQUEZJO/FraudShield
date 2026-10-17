// AdminUsuarios.jsx — tabla con todos los usuarios registrados, y un
// selector por fila para asignarlos a una empresa/grupo.
import { useEffect, useState } from "react";
import { adminListarUsuarios, adminListarEmpresas, adminAsignarEmpresa } from "../api";

// recargarSenal: cualquier cambio en este número (que le manda
// AdminPanel.jsx) hace que este componente vuelva a pedir la lista de
// usuarios — se usa para refrescar justo después de registrar a alguien nuevo.
export default function AdminUsuarios({ recargarSenal }) {
  const [usuarios, setUsuarios] = useState([]);
  const [empresas, setEmpresas] = useState([]);   // se necesita para llenar las opciones de cada <select>
  const [cargando, setCargando] = useState(true);

  const cargar = () => {
    setCargando(true);
    // Se piden usuarios y empresas EN PARALELO (Promise.all) en vez de
    // uno después del otro — más rápido, ya que no dependen entre sí.
    Promise.all([adminListarUsuarios(), adminListarEmpresas()]).then(([u, e]) => {
      setUsuarios(Array.isArray(u) ? u : []);
      setEmpresas(Array.isArray(e) ? e : []);
      setCargando(false);
    });
  };

  // Se vuelve a cargar cada vez que cambia recargarSenal (además de al
  // montar el componente la primera vez).
  useEffect(() => {
    cargar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recargarSenal]);

  const cambiarEmpresa = async (userId, empresaIdStr) => {
    // El <select> del HTML siempre da un string — "" significa "Sin
    // empresa" (se traduce a null), cualquier otro valor se convierte a número.
    const empresaId = empresaIdStr === "" ? null : parseInt(empresaIdStr, 10);
    await adminAsignarEmpresa(userId, empresaId);
    cargar();  // recarga la tabla para reflejar el cambio recién hecho
  };

  if (cargando) return <p className="dashboard-vacio">Cargando usuarios...</p>;

  if (usuarios.length === 0) {
    return <p className="dashboard-vacio">Sin usuarios registrados todavía.</p>;
  }

  return (
    <table width="100%">
      <thead>
        <tr>
          <th>Nombre</th>
          <th>Email</th>
          <th>Documento</th>
          <th>Rol</th>
          <th>Ángulos faciales</th>
          <th>Empresa</th>
          <th>Registrado</th>
        </tr>
      </thead>
      <tbody>
        {usuarios.map((u) => (
          <tr key={u.id}>
            <td>{u.nombre}</td>
            <td>{u.email}</td>
            <td>{u.documento}</td>
            <td>{u.rol}</td>
            {/* Verde si tiene los 4 ángulos completos, rojo si el registro quedó incompleto */}
            <td className={u.angulosGuardados >= 4 ? "text-ok" : "text-bad"}>
              {u.angulosGuardados}/4
            </td>
            <td>
              {/* Selector de empresa — cambia de inmediato al elegir una opción, sin botón "guardar" aparte */}
              <select
                value={u.empresaId ?? ""}
                onChange={(e) => cambiarEmpresa(u.id, e.target.value)}
              >
                <option value="">Sin empresa</option>
                {empresas.map((emp) => (
                  <option key={emp.empresaId} value={emp.empresaId}>
                    {emp.nombre}
                  </option>
                ))}
              </select>
            </td>
            <td>{u.fechaRegistro ? u.fechaRegistro.split(".")[0].replace("T", " ") : "-"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
