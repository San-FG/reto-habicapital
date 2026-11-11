import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { Api } from './api';
import { PieAuditoria } from './auditoria/pie-auditoria';
import { Compromisos } from './compromisos/compromisos';
import { Historial } from './historial/historial';
import { TarjetaSaldo } from './saldo/tarjeta-saldo';
import { Auditoria, Compromiso, Cuenta, Movimiento } from './tipos';
import { Transferencia } from './transferencia/transferencia';
import { mensajeDeError } from './utilidades';

/**
 * Página única de la billetera.
 *
 * Este componente guarda lo que se muestra y sabe volver a pedirlo todo al
 * backend (recargar). Los componentes hijos reciben esos datos, muestran un
 * formulario o una lista y avisan con (cambio) cuando hay que recargar.
 *
 * REGLA: aquí no se calcula plata. Ningún saldo se suma ni se resta en el
 * navegador; todo número que se ve es una respuesta del backend.
 */
@Component({
  selector: 'app-root',
  imports: [FormsModule, TarjetaSaldo, Transferencia, Compromisos, Historial, PieAuditoria],
  templateUrl: './app.html',
})
export class App {
  private readonly api = inject(Api);

  // ---------- Lo último que respondió el backend ----------
  protected readonly cuentas = signal<Cuenta[]>([]);
  protected readonly yo = signal<Cuenta | null>(null);
  protected readonly movimientos = signal<Movimiento[]>([]);
  protected readonly compromisos = signal<Compromiso[]>([]);
  protected readonly auditoria = signal<Auditoria | null>(null);
  protected readonly cargado = signal(false); // ya llegó la primera respuesta
  protected readonly error = signal('');

  // IDENTIDAD SIMULADA: no hay login. El selector "Soy:" decide a nombre de
  // quién se hacen las operaciones, igual que actor_id en el backend: quien
  // usa la página dice quién es y se le cree. En un sistema real esto saldría
  // de una sesión verificada, nunca de un selector.
  protected readonly yoId = signal<number | null>(null);

  // ---------- Formulario de cuenta nueva ----------
  protected readonly nombreNuevo = signal('');
  protected readonly creando = signal(false);
  protected readonly errorCrear = signal('');

  // Número de la última recarga pedida, para descartar respuestas viejas.
  private turno = 0;

  constructor() {
    void this.recargar();
  }

  /** Cambia de identidad. */
  protected elegir(id: number | null): void {
    this.yoId.set(id);
    // Se borra lo de la cuenta anterior de una vez: mientras llega la respuesta
    // no debe verse el saldo de otra persona, y los formularios se crean de
    // nuevo, sin datos ni mensajes a medio llenar.
    this.yo.set(null);
    this.movimientos.set([]);
    this.compromisos.set([]);
    void this.recargar();
  }

  /** Vuelve a pedir TODO al backend. Se llama después de cada operación. */
  protected async recargar(): Promise<void> {
    const turno = ++this.turno;
    try {
      const [cuentas, auditoria] = await Promise.all([
        this.api.listarCuentas(),
        this.api.auditoria(),
      ]);
      // Al abrir la página se entra como la primera cuenta que exista.
      const id = this.yoId() ?? cuentas[0]?.id ?? null;

      let yo: Cuenta | null = null;
      let movimientos: Movimiento[] = [];
      let compromisos: Compromiso[] = [];
      if (id !== null) {
        [yo, movimientos, compromisos] = await Promise.all([
          this.api.consultarCuenta(id),
          this.api.historial(id),
          this.api.compromisosDe(id),
        ]);
      }

      if (turno !== this.turno) {
        return; // ya se pidió una recarga más nueva: esta respuesta está vieja
      }
      this.cuentas.set(cuentas);
      this.auditoria.set(auditoria);
      this.yoId.set(id);
      this.yo.set(yo);
      this.movimientos.set(movimientos);
      this.compromisos.set(compromisos);
      this.error.set('');
    } catch (fallo) {
      if (turno === this.turno) {
        this.error.set(mensajeDeError(fallo));
      }
    } finally {
      this.cargado.set(true);
    }
  }

  protected async crearCuenta(): Promise<void> {
    const nombre = this.nombreNuevo().trim();
    if (!nombre) {
      this.errorCrear.set('Escribe el nombre de la cuenta.');
      return;
    }
    if (this.creando()) {
      return;
    }
    this.creando.set(true);
    this.errorCrear.set('');
    try {
      const nueva = await this.api.crearCuenta(nombre);
      this.nombreNuevo.set('');
      this.elegir(nueva.id); // se entra de una vez como la cuenta recién creada
    } catch (fallo) {
      this.errorCrear.set(mensajeDeError(fallo));
    } finally {
      this.creando.set(false);
    }
  }
}
