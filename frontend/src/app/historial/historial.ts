import { DatePipe } from '@angular/common';
import { Component, input } from '@angular/core';

import { PesosPipe } from '../pesos-pipe';
import { Cuenta, Movimiento, TipoMovimiento } from '../tipos';
import { nombreDe } from '../utilidades';

const NOMBRE_DEL_TIPO: Record<TipoMovimiento, string> = {
  CARGA: 'Carga',
  TRANSFERENCIA: 'Transferencia',
  RETENCION: 'Retención',
  LIBERACION: 'Liberación',
  DEVOLUCION: 'Devolución',
};

/** Movimientos de la cuenta seleccionada. Solo muestra: no envía nada. */
@Component({
  selector: 'app-historial',
  imports: [DatePipe, PesosPipe],
  templateUrl: './historial.html',
})
export class Historial {
  readonly yo = input.required<Cuenta>();
  readonly cuentas = input.required<Cuenta[]>();
  readonly movimientos = input.required<Movimiento[]>();

  protected tipo(m: Movimiento): string {
    return NOMBRE_DEL_TIPO[m.tipo];
  }

  /** ¿La plata entró a esta cuenta? Decide el signo; no se hace ninguna cuenta. */
  protected entro(m: Movimiento): boolean {
    return m.cuenta_destino === this.yo().id;
  }

  protected contraparte(m: Movimiento): string {
    if (m.tipo === 'CARGA') {
      return 'Fuera del sistema (simulado)';
    }
    if (m.tipo !== 'TRANSFERENCIA') {
      // Retención, liberación y devolución siempre son contra la cuenta de custodia.
      return 'Custodia';
    }
    const otra = this.entro(m) ? m.cuenta_origen : m.cuenta_destino;
    return otra === null ? '—' : nombreDe(this.cuentas(), otra);
  }
}
