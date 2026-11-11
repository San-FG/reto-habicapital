import { Component, computed, inject, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { Api } from '../api';
import { CampoMonto } from '../campo-monto';
import { Intenciones } from '../intenciones';
import { PesosPipe } from '../pesos-pipe';
import { Compromiso, Cuenta, NuevoCompromiso } from '../tipos';
import { aEnteroPositivo, mensajeDeError, nombreDe } from '../utilidades';

const ORDEN_ESTADO: Record<Compromiso['estado'], number> = {
  RESPALDADO: 0,
  PENDIENTE: 1,
  CUMPLIDO: 2,
  CANCELADO: 3,
};

const FORMATO_FECHA = new Intl.DateTimeFormat('es-CO', {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
});

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
  protected readonly ordenados = computed(() =>
    [...this.compromisos()].sort((a, b) => ORDEN_ESTADO[a.estado] - ORDEN_ESTADO[b.estado]),
  );

  // ---------- Formulario: crear un compromiso (yo soy el pagador) ----------
  protected readonly beneficiario = signal<number | null>(null);
  protected readonly monto = signal('');
  protected readonly concepto = signal('');
  protected readonly venceEl = signal('');
  protected readonly creando = signal(false);
  protected readonly errorCrear = signal('');
  protected readonly avisoCrear = signal('');
  protected readonly mostrarFormulario = signal(false);
  private temporizadorAviso: ReturnType<typeof setTimeout> | undefined;

  // ---------- Acciones sobre un compromiso de la lista ----------
  // Una sola acción a la vez: mientras hay una en curso se deshabilitan todos los botones.
  protected readonly ocupado = signal(false);
  protected readonly errorAccion = signal('');
  protected readonly accionEnCurso = signal<string | null>(null);
  // Solo una tarjeta puede pedir confirmación de cancelación a la vez.
  protected readonly confirmandoCancelacionId = signal<number | null>(null);

  protected async crear(): Promise<void> {
    this.limpiarAvisoCrear();
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
    try {
      // Crear no mueve plata, por eso el backend no pide clave de idempotencia aquí.
      await this.api.crearCompromiso(datos);
      this.beneficiario.set(null);
      this.monto.set('');
      this.concepto.set('');
      this.venceEl.set('');
      this.mostrarFormulario.set(false);
      this.mostrarAvisoCrear('Compromiso creado. Ya puedes respaldarlo para apartar la plata.');
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

  // ---------- Textos y fechas de presentación ----------

  /** La fecha YYYY-MM-DD se construye en hora local para no correrla un día. */
  protected fechaVencimiento(texto: string): string {
    const [anio, mes, dia] = texto.split('-').map(Number);
    return this.fechaNatural(new Date(anio, mes - 1, dia));
  }

  protected textoEstado(c: Compromiso): string {
    const pagador = this.nombre(c.pagador_id);
    const beneficiario = this.nombre(c.beneficiario_id);

    if (c.estado === 'PENDIENTE') {
      return this.soyPagador(c)
        ? 'Todavía no has apartado la plata.'
        : `Esperando a que ${pagador} aparte la plata.`;
    }
    if (c.estado === 'RESPALDADO') {
      return this.soyPagador(c)
        ? `Tu plata está en custodia: ya salió de tu saldo y todavía no le llega a ${beneficiario}. Libérala cuando se cumpla el acuerdo.`
        : `La plata ya está apartada para ti. Te llega cuando ${pagador} la libere.`;
    }

    const fecha = c.cerrado_en ? this.fechaNatural(new Date(c.cerrado_en)) : '';
    if (c.estado === 'CUMPLIDO') {
      return fecha ? `Entregado el ${fecha}.` : 'Entregado.';
    }

    const devolucion = c.respaldado_en ? ` La plata volvió a ${pagador}.` : '';
    return `${fecha ? `Cancelado el ${fecha}.` : 'Cancelado.'}${devolucion}`;
  }

  protected etiquetaProgreso(c: Compromiso): string {
    if (c.estado === 'PENDIENTE') {
      return 'Estado: acordado, paso 1 de 3';
    }
    if (c.estado === 'RESPALDADO') {
      return 'Estado: en custodia, paso 2 de 3';
    }
    if (c.estado === 'CUMPLIDO') {
      return 'Estado: entregado, paso 3 de 3';
    }
    return 'Estado: cancelado';
  }

  protected pasoCompleto(c: Compromiso, paso: number): boolean {
    return c.estado === 'CUMPLIDO' || (c.estado === 'RESPALDADO' && paso === 1);
  }

  protected pasoActual(c: Compromiso, paso: number): boolean {
    return (c.estado === 'PENDIENTE' && paso === 1) || (c.estado === 'RESPALDADO' && paso === 2);
  }

  protected procesando(c: Compromiso, accion: string): boolean {
    return this.accionEnCurso() === `${accion}-${c.id}`;
  }

  protected estaConfirmandoCancelacion(c: Compromiso): boolean {
    return this.confirmandoCancelacionId() === c.id;
  }

  /** Primer paso visual: todavía no llama al backend ni crea una clave. */
  protected pedirConfirmacionCancelacion(c: Compromiso): void {
    if (!this.ocupado()) {
      this.confirmandoCancelacionId.set(c.id);
    }
  }

  protected cerrarConfirmacionCancelacion(): void {
    if (!this.ocupado()) {
      this.confirmandoCancelacionId.set(null);
    }
  }

  /** Intl en es-CO agrega "de"; se quita para el formato breve pedido. */
  private fechaNatural(fecha: Date): string {
    return FORMATO_FECHA.format(fecha).replace(/\sde\s/g, ' ');
  }

  private mostrarAvisoCrear(texto: string): void {
    this.limpiarAvisoCrear();
    this.avisoCrear.set(texto);
    this.temporizadorAviso = setTimeout(() => this.avisoCrear.set(''), 4000);
  }

  private limpiarAvisoCrear(): void {
    if (this.temporizadorAviso !== undefined) {
      clearTimeout(this.temporizadorAviso);
      this.temporizadorAviso = undefined;
    }
    this.avisoCrear.set('');
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

  protected async cancelar(c: Compromiso): Promise<void> {
    await this.ejecutar(`cancelar-${c.id}`, (clave) =>
      this.api.cancelar(c.id, this.yo().id, clave),
    );
    // Si salió bien, se sale del modo confirmación. Si falló, la tarjeta sigue
    // confirmando para que el usuario reintente (con la misma clave).
    if (!this.errorAccion()) {
      this.confirmandoCancelacionId.set(null);
    }
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
    this.accionEnCurso.set(intencion);
    this.errorAccion.set('');
    try {
      await enviar(clave);
      this.intenciones.cumplida(intencion);
    } catch (fallo) {
      this.errorAccion.set(mensajeDeError(fallo));
    } finally {
      this.ocupado.set(false);
      this.accionEnCurso.set(null);
      // También si falló: quizá la otra persona ya cambió el estado y la lista está vieja.
      this.cambio.emit();
    }
  }
}
