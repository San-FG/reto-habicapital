import { Pipe, PipeTransform } from '@angular/core';

// Se crea una sola vez: formato colombiano, con signo $ y sin decimales
// porque el sistema solo maneja pesos enteros.
const FORMATO = new Intl.NumberFormat('es-CO', {
  style: 'currency',
  currency: 'COP',
  minimumFractionDigits: 0,
  maximumFractionDigits: 0,
});

/** Muestra un entero de pesos como plata: 20000 -> "$ 20.000". Solo presentación. */
@Pipe({ name: 'pesos' })
export class PesosPipe implements PipeTransform {
  transform(monto: number): string {
    return FORMATO.format(monto);
  }
}
