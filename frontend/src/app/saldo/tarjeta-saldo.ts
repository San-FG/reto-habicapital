import { Component, inject, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { Api } from '../api';
import { CampoMonto } from '../campo-monto';
import { Intenciones } from '../intenciones';
import { PesosPipe } from '../pesos-pipe';
import { Cuenta } from '../tipos';
import { aEnteroPositivo, mensajeDeError } from '../utilidades';

/** Saldo de la cuenta seleccionada y formulario para cargarle plata (simulado). */
@Component({
  selector: 'app-tarjeta-saldo',
  imports: [FormsModule, CampoMonto, PesosPipe],
  templateUrl: './tarjeta-saldo.html',
})
export class TarjetaSaldo {
  private readonly api = inject(Api);
  private readonly intenciones = new Intenciones();

  readonly yo = input.required<Cuenta>();
  /** Avisa al padre que debe volver a pedir todo al backend. */
  readonly cambio = output<void>();

  protected readonly monto = signal('');
  protected readonly enviando = signal(false);
  protected readonly error = signal('');
  protected readonly aviso = signal('');

  protected async cargar(): Promise<void> {
    const monto = aEnteroPositivo(this.monto());
    if (monto === null) {
      this.error.set('El monto debe ser un número entero de pesos mayor que cero.');
      return;
    }
    if (this.enviando()) {
      return;
    }
    const cuentaId = this.yo().id;
    // Misma cuenta y mismo monto = misma intención = misma clave (ver intenciones.ts).
    const clave = this.intenciones.clave('cargar', { cuentaId, monto });

    this.enviando.set(true);
    this.error.set('');
    this.aviso.set('');
    try {
      await this.api.cargar(cuentaId, monto, clave);
      this.intenciones.cumplida('cargar');
      this.monto.set('');
      this.aviso.set('Carga registrada.');
    } catch (fallo) {
      this.error.set(mensajeDeError(fallo));
    } finally {
      this.enviando.set(false);
      // Con éxito o con error se vuelve a preguntar: el saldo que vale es el del backend.
      this.cambio.emit();
    }
  }
}
