import { Component, input } from '@angular/core';

import { PesosPipe } from '../pesos-pipe';
import { Cuenta, Movimiento } from '../tipos';
import { nombreDe } from '../utilidades';

const FORMATO_MOVIMIENTO = new Intl.DateTimeFormat('es-CO', {
  day: 'numeric',
  month: 'short',
  hour: 'numeric',
  minute: '2-digit',
});

/** Movimientos de la cuenta seleccionada. Solo muestra: no envía nada. */
@Component({
  selector: 'app-historial',
  imports: [PesosPipe],
  templateUrl: './historial.html',
})
export class Historial {
  readonly yo = input.required<Cuenta>();
  readonly cuentas = input.required<Cuenta[]>();
  readonly movimientos = input.required<Movimiento[]>();

  /** ¿La plata entró a esta cuenta? Decide el signo; no se hace ninguna cuenta. */
  protected entro(m: Movimiento): boolean {
    return m.cuenta_destino === this.yo().id;
  }

  protected textoMovimiento(m: Movimiento): string {
    if (m.tipo === 'CARGA') {
      return 'Cargaste saldo';
    }
    if (m.tipo === 'RETENCION') {
      return 'Apartaste plata en custodia';
    }
    if (m.tipo === 'LIBERACION') {
      return 'Recibiste plata de custodia';
    }
    if (m.tipo === 'DEVOLUCION') {
      return 'Custodia te devolvió la plata';
    }

    const nombre = this.nombreContraparte(m);
    return this.entro(m) ? `${nombre} te envió` : `Le enviaste a ${nombre}`;
  }

  protected nombreContraparte(m: Movimiento): string {
    const otra = this.entro(m) ? m.cuenta_origen : m.cuenta_destino;
    return otra === null ? 'Otra cuenta' : nombreDe(this.cuentas(), otra);
  }

  protected iniciales(m: Movimiento): string {
    return this.nombreContraparte(m)
      .trim()
      .split(/\s+/)
      .slice(0, 2)
      .map((parte) => parte.charAt(0))
      .join('')
      .toUpperCase();
  }

  protected fecha(m: Movimiento): string {
    return FORMATO_MOVIMIENTO.format(new Date(m.creado_en)).replace(/\sde\s/g, ' ');
  }
}
