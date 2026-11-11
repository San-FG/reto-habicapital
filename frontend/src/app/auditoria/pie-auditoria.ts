import { Component, input } from '@angular/core';

import { PesosPipe } from '../pesos-pipe';
import { Auditoria } from '../tipos';

/**
 * Sello de la barra superior con el resultado de GET /auditoria.
 * El veredicto ("ok") lo da el backend; aquí solo se muestra.
 */
@Component({
  selector: 'app-pie-auditoria',
  imports: [PesosPipe],
  templateUrl: './pie-auditoria.html',
})
export class PieAuditoria {
  readonly auditoria = input.required<Auditoria | null>();
}
