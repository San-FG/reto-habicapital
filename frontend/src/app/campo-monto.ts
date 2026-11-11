import { Component, input, model } from '@angular/core';

/**
 * Campo de monto: solo deja escribir dígitos.
 *
 * No se usa <input type="number"> porque acepta "10.5", "-3" o "1e3", y la
 * plata aquí son enteros de pesos. El valor viaja como texto; quien lo usa
 * lo convierte con aEnteroPositivo() justo antes de enviarlo.
 *
 * Uso: <app-campo-monto [(valor)]="monto" />
 */
@Component({
  selector: 'app-campo-monto',
  template: `
    <input
      type="text"
      inputmode="numeric"
      autocomplete="off"
      placeholder="Ej.: 20000"
      [value]="valor()"
      [disabled]="deshabilitado()"
      (input)="alEscribir($event)"
    />
  `,
})
export class CampoMonto {
  readonly valor = model('');
  readonly deshabilitado = input(false);

  protected alEscribir(evento: Event): void {
    const campo = evento.target as HTMLInputElement;
    // Se corrige el campo directamente: lo que no sea dígito no alcanza a quedar escrito.
    campo.value = campo.value.replace(/\D/g, '');
    this.valor.set(campo.value);
  }
}
