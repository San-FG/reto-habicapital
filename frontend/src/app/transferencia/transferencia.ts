import { Component, computed, inject, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { Api } from '../api';
import { CampoMonto } from '../campo-monto';
import { Intenciones } from '../intenciones';
import { Cuenta, NuevaTransferencia } from '../tipos';
import { aEnteroPositivo, mensajeDeError } from '../utilidades';

/** Formulario para pasarle plata a otra cuenta. */
@Component({
  selector: 'app-transferencia',
  imports: [FormsModule, CampoMonto],
  templateUrl: './transferencia.html',
})
export class Transferencia {
  private readonly api = inject(Api);
  private readonly intenciones = new Intenciones();

  readonly yo = input.required<Cuenta>();
  readonly cuentas = input.required<Cuenta[]>();
  readonly cambio = output<void>();

  /** Todas las cuentas menos la mía: nadie se transfiere a sí mismo. */
  protected readonly otras = computed(() => this.cuentas().filter((c) => c.id !== this.yo().id));

  protected readonly destino = signal<number | null>(null);
  protected readonly monto = signal('');
  protected readonly concepto = signal('');
  protected readonly enviando = signal(false);
  protected readonly error = signal('');
  protected readonly aviso = signal('');
  private temporizadorAviso: ReturnType<typeof setTimeout> | undefined;

  protected async transferir(): Promise<void> {
    this.limpiarAviso();
    const destino = this.destino();
    const monto = aEnteroPositivo(this.monto());
    if (destino === null) {
      this.error.set('Elige a quién le vas a transferir.');
      return;
    }
    if (monto === null) {
      this.error.set('El monto debe ser un número entero de pesos mayor que cero.');
      return;
    }
    if (this.enviando()) {
      return;
    }
    const datos: NuevaTransferencia = {
      origen: this.yo().id,
      destino,
      monto,
      concepto: this.concepto().trim() || null,
    };
    // Si el envío falla y se reintenta sin tocar el formulario, sale la misma
    // clave y el backend no mueve la plata dos veces (ver intenciones.ts).
    const clave = this.intenciones.clave('transferir', datos);

    this.enviando.set(true);
    this.error.set('');
    try {
      await this.api.transferir(datos, clave);
      this.intenciones.cumplida('transferir');
      this.monto.set('');
      this.concepto.set('');
      this.mostrarAviso('Transferencia hecha.');
    } catch (fallo) {
      this.error.set(mensajeDeError(fallo));
    } finally {
      this.enviando.set(false);
      this.cambio.emit();
    }
  }

  /** Los avisos positivos son temporales; los errores no se borran solos. */
  private mostrarAviso(texto: string): void {
    this.limpiarAviso();
    this.aviso.set(texto);
    this.temporizadorAviso = setTimeout(() => this.aviso.set(''), 4000);
  }

  private limpiarAviso(): void {
    if (this.temporizadorAviso !== undefined) {
      clearTimeout(this.temporizadorAviso);
      this.temporizadorAviso = undefined;
    }
    this.aviso.set('');
  }
}
