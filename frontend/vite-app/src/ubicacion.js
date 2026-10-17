/**
 * Pide la ubicación del navegador (GPS/red) y la devuelve como
 * { latitud, longitud }, o null si el usuario la niega, el navegador no
 * la soporta, o tarda demasiado. Nunca lanza una excepción — el llamador
 * no necesita try/catch, y una transacción nunca debe bloquearse solo
 * porque no se pudo obtener la ubicación.
 */
export function obtenerUbicacion(timeoutMs = 5000) {
  return new Promise((resolve) => {
    // Algunos navegadores viejos o configuraciones muy restrictivas no
    // exponen "navigator.geolocation" en absoluto.
    if (!navigator.geolocation) {
      resolve(null);
      return;
    }

    // getCurrentPosition muestra el popup nativo de permiso la primera
    // vez (o si el usuario aún no decidió). Recibe 2 callbacks: éxito y error.
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        resolve({
          latitud: pos.coords.latitude,
          longitud: pos.coords.longitude,
        });
      },
      () => resolve(null), // permiso denegado u otro error — seguimos sin ubicación
      {
        timeout: timeoutMs,   // si tarda más de esto, se rinde y resuelve null
        maximumAge: 60000,    // acepta una ubicación en caché de hasta 1 minuto (más rápido que pedir una nueva siempre)
      }
    );
  });
}

// Arma un link de Google Maps que, al abrirse, cae directo sobre el
// punto exacto (lat, lon) — usado en las tablas de historial.
export function urlMapa(latitud, longitud) {
  return `https://www.google.com/maps?q=${latitud},${longitud}`;
}
