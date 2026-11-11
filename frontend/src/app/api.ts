import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import {
  Auditoria,
  Compromiso,
  Cuenta,
  Movimiento,
  NuevaTransferencia,
  NuevoCompromiso,
} from './tipos';

/** Único lugar donde está escrita la dirección del backend. */
export const URL_API = 'http://localhost:8000';

/**
 * Único servicio que habla con el backend. No tiene reglas de plata: solo
 * arma la petición y devuelve lo que respondió el backend.
 *
 * Cada método devuelve una Promise para poder usar async/await con
 * try/catch en los componentes, que es más fácil de leer que un subscribe.
 *
 * Los métodos que mueven plata exigen la clave de idempotencia: quien llama
 * decide cuál es (ver intenciones.ts), aquí solo se pone en el header.
 */
@Injectable({ providedIn: 'root' })
export class Api {
  private readonly http = inject(HttpClient);

  // ---------- Cuentas ----------

  listarCuentas(): Promise<Cuenta[]> {
    return this.get('/cuentas');
  }

  crearCuenta(nombre: string): Promise<Cuenta> {
    return this.post('/cuentas', { nombre });
  }

  consultarCuenta(id: number): Promise<Cuenta> {
    return this.get(`/cuentas/${id}`);
  }

  historial(cuentaId: number): Promise<Movimiento[]> {
    return this.get(`/cuentas/${cuentaId}/movimientos`);
  }

  // ---------- Plata ----------

  cargar(cuentaId: number, monto: number, clave: string): Promise<Movimiento> {
    return this.post(`/cuentas/${cuentaId}/cargas`, { monto }, clave);
  }

  transferir(datos: NuevaTransferencia, clave: string): Promise<Movimiento> {
    return this.post('/transferencias', datos, clave);
  }

  // ---------- Compromisos ----------

  compromisosDe(cuentaId: number): Promise<Compromiso[]> {
    return this.get(`/cuentas/${cuentaId}/compromisos`);
  }

  crearCompromiso(datos: NuevoCompromiso): Promise<Compromiso> {
    return this.post('/compromisos', datos);
  }

  respaldar(compromisoId: number, actorId: number, clave: string): Promise<Compromiso> {
    return this.post(`/compromisos/${compromisoId}/respaldo`, { actor_id: actorId }, clave);
  }

  liberar(compromisoId: number, actorId: number, clave: string): Promise<Compromiso> {
    return this.post(`/compromisos/${compromisoId}/liberacion`, { actor_id: actorId }, clave);
  }

  cancelar(compromisoId: number, actorId: number, clave: string): Promise<Compromiso> {
    return this.post(`/compromisos/${compromisoId}/cancelacion`, { actor_id: actorId }, clave);
  }

  // ---------- Auditoría ----------

  auditoria(): Promise<Auditoria> {
    return this.get('/auditoria');
  }

  // ---------- Detalle HTTP ----------

  private get<T>(ruta: string): Promise<T> {
    return firstValueFrom(this.http.get<T>(URL_API + ruta));
  }

  private post<T>(ruta: string, cuerpo: object, clave?: string): Promise<T> {
    const opciones = clave ? { headers: { 'Idempotency-Key': clave } } : {};
    return firstValueFrom(this.http.post<T>(URL_API + ruta, cuerpo, opciones));
  }
}
