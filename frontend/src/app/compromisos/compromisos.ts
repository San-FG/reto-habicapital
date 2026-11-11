import { Component, computed, inject, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { Api } from '../api';
import { CampoMonto } from '../campo-monto';
import { Intenciones } from '../intenciones';
import { PesosPipe } from '../pesos-pipe';
import { Compromiso, Cuenta, NuevoCompromiso } from '../tipos';
import { aEnteroPositivo, mensajeDeError, nombreDe } from '../utilidades';

/** Compromisos de pago de la cuenta seleccionada: crear, ver y actuar sobre ellos. */
@Component({
  selector: 'app-compromisos',
  imports: [FormsModule, CampoMonto, PesosPipe],
  templateUrl: './compromisos.html',
})
export class Compromisos {
  private readonly api = inject(Api);
  private readonly intenciones = new Intenciones();

  readonly yo = input.required<Cuenta>();
  readonly cuentas = input.required<Cuenta[]>();
  readonly compromisos = input.required<Compromiso[]>();
  readonly cambio = output<void>();

  protected readonly otras = computed(() => this.cuentas().filter((c) => c.id !== this.yo().id));

  // ---------- Formulario: crear un compromiso (yo soy el pagador) ----------
  protected readonly beneficiario = signal<number | null>(null);
  protected readonly monto = signal('');
  protected readonly concepto = signal('');
  protected readonly venceEl = signal('');
  protected readonly creando = signal(false);
  protected readonly errorCrear = signal('');
  protected readonly avisoCrear = signal('');

  // ---------- Acciones sobre un compromiso de la lista ----------
  // Una sola acción a la vez: mientras hay una en curso se deshabilitan todos los botones.
  protected readonly ocupado = signal(false);
  protected readonly errorAccion = signal('');

  protected async crear(): Promise<void> {
    const beneficiario = this.beneficiario();
    const monto = aEnteroPositivo(this.monto());
    const concepto = this.concepto().trim();
    const venceEl = this.venceEl(); // <input type="date"> ya entrega YYYY-MM-DD
    if (beneficiario === null) {
      this.errorCrear.set('Elige a quién le vas a pagar.');
      return;
    }
    if (monto === null) {
      this.errorCrear.set('El monto debe ser un número entero de pesos mayor que cero.');
      return;
    }
    if (!concepto) {
      this.errorCrear.set('Escribe el concepto del compromiso.');
      return;
    }
    if (!venceEl) {
      this.errorCrear.set('Elige la fecha de vencimiento.');
      return;
    }
    if (this.creando()) {
      return;
    }
    const datos: NuevoCompromiso = {
      pagador_id: this.yo().id,
      beneficiario_id: beneficiario,
      monto,
      concepto,
      vence_el: venceEl,
    };

    this.creando.set(true);
    this.errorCrear.set('');
    this.avisoCrear.set('');
    try {
      // Crear no mueve plata, por eso el backend no pide clave de idempotencia aquí.
      await this.api.crearCompromiso(datos);
      this.monto.set('');
      this.concepto.set('');
      this.venceEl.set('');
      this.avisoCrear.set('Compromiso creado. Queda PENDIENTE hasta que lo respaldes.');
    } catch (fallo) {
      this.errorCrear.set(mensajeDeError(fallo));
    } finally {
      this.creando.set(false);
      this.cambio.emit();
    }
  }

  // ---------- Qué botones mostrar ----------
  // Copian las reglas del backend SOLO para no mostrar botones que van a
  // fallar. Quien valida de verdad sigue siendo el backend.

  protected soyPagador(c: Compromiso): boolean {
    return c.pagador_id === this.yo().id;
  }

  protected puedeRespaldar(c: Compromiso): boolean {
    return c.estado === 'PENDIENTE' && this.soyPagador(c);
  }

  protected puedeLiberar(c: Compromiso): boolean {
    return c.estado === 'RESPALDADO' && this.soyPagador(c);
  }

  protected puedeCancelar(c: Compromiso): boolean {
    // PENDIENTE: cualquiera de los dos. RESPALDADO: solo el beneficiario,
    // porque el pagador no puede arrepentirse solo con la plata ya retenida.
    return c.estado === 'PENDIENTE' || (c.estado === 'RESPALDADO' && !this.soyPagador(c));
  }

  protected nombre(id: number): string {
    return nombreDe(this.cuentas(), id);
  }

  // ---------- Acciones ----------

  protected respaldar(c: Compromiso): Promise<void> {
    return this.ejecutar(`respaldar-${c.id}`, (clave) =>
      this.api.respaldar(c.id, this.yo().id, clave),
    );
  }

  protected liberar(c: Compromiso): Promise<void> {
    return this.ejecutar(`liberar-${c.id}`, (clave) => this.api.liberar(c.id, this.yo().id, clave));
  }

  protected cancelar(c: Compromiso): Promise<void> {
    return this.ejecutar(`cancelar-${c.id}`, (clave) =>
      this.api.cancelar(c.id, this.yo().id, clave),
    );
  }

  /**
   * Parte común de las tres acciones. "intencion" identifica la acción sobre
   * ese compromiso (por ejemplo 'liberar-12'): si falla y el usuario vuelve a
   * oprimir el botón, se envía la MISMA clave y el backend no mueve la plata
   * dos veces. La clave solo se descarta cuando el backend responde bien.
   */
  private async ejecutar(intencion: string, enviar: (clave: string) => Promise<unknown>) {
    if (this.ocupado()) {
      return;
    }
    const clave = this.intenciones.clave(intencion, { actor: this.yo().id });

    this.ocupado.set(true);
    this.errorAccion.set('');
    try {
      await enviar(clave);
      this.intenciones.cumplida(intencion);
    } catch (fallo) {
      this.errorAccion.set(mensajeDeError(fallo));
    } finally {
      this.ocupado.set(false);
      // También si falló: quizá la otra persona ya cambió el estado y la lista está vieja.
      this.cambio.emit();
    }
  }
}
