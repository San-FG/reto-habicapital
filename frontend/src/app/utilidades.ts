import { HttpErrorResponse } from '@angular/common/http';

import { URL_API } from './api';
import { Cuenta } from './tipos';

/**
 * Convierte el texto de un campo de monto en un entero de pesos.
 * Devuelve null si no es un entero mayor que cero. No hace cuentas: solo
 * decide si lo escrito se puede enviar como número entero.
 */
export function aEnteroPositivo(texto: string): number | null {
  if (!/^\d+$/.test(texto)) {
    return null; // vacío, con decimales, con signo, con letras...
  }
  const numero = Number(texto);
  return Number.isSafeInteger(numero) && numero > 0 ? numero : null;
}

/** Nombre de una cuenta a partir de su id, para mostrar contrapartes. */
export function nombreDe(cuentas: Cuenta[], id: number): string {
  return cuentas.find((c) => c.id === id)?.nombre ?? `Cuenta #${id}`;
}

/** Un renglón del "detail" con el que FastAPI explica un 422 de validación. */
interface DetalleValidacion {
  loc?: (string | number)[];
  msg?: string;
}

/**
 * Texto para mostrarle al usuario cuando una petición falla.
 * Los errores de negocio del backend llegan como {"error": "..."} y se
 * muestran tal cual: el backend es quien sabe qué pasó.
 */
export function mensajeDeError(fallo: unknown): string {
  if (!(fallo instanceof HttpErrorResponse)) {
    return 'Ocurrió un error inesperado en la página.';
  }
  if (fallo.status === 0) {
    // status 0 = no hubo respuesta: backend apagado, sin red o CORS.
    return `No se pudo conectar con el backend (${URL_API}). ¿Está encendido?`;
  }
  const cuerpo = fallo.error;
  if (typeof cuerpo?.error === 'string') {
    return cuerpo.error;
  }
  if (fallo.status === 422 && Array.isArray(cuerpo?.detail)) {
    // Validación de FastAPI (por ejemplo, un campo con el tipo equivocado).
    const detalles = (cuerpo.detail as DetalleValidacion[]).map((d) => {
      const campo = d.loc?.slice(1).join('.') || 'dato';
      return `${campo}: ${d.msg ?? 'valor no válido'}`;
    });
    return `El backend no aceptó los datos enviados. Revisa: ${detalles.join('; ')}.`;
  }
  return `El backend respondió con un error inesperado (código ${fallo.status}).`;
}
