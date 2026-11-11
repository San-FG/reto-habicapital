/**
 * Claves de idempotencia: UNA por intención del usuario, no una por clic.
 *
 * POR QUÉ: si una petición falla por red o por un timeout, el navegador no
 * sabe si el backend alcanzó a mover la plata. Si el reintento llevara una
 * clave nueva, el backend lo vería como una operación distinta y podría
 * cobrar dos veces. Con la MISMA clave, el backend reconoce el reintento y
 * devuelve el resultado original sin mover nada otra vez.
 *
 * Por eso la clave solo se renueva en dos casos:
 *  1. El backend respondió bien -> se llama cumplida(): lo siguiente que haga
 *     el usuario ya es otra intención.
 *  2. El usuario cambió los datos (otro monto, otro destinatario...) -> ya no
 *     es la misma operación. Además el backend rechaza una clave repetida con
 *     datos distintos (ConflictoIdempotencia).
 *
 * Cada intención tiene un nombre ('transferir', 'liberar-12'...) para que un
 * componente pueda llevar varias a la vez, por ejemplo una por compromiso.
 */
export class Intenciones {
  private readonly vigentes = new Map<string, { datos: string; clave: string }>();

  /** Clave para enviar estos datos: la misma mientras los datos no cambien. */
  clave(nombre: string, datos: object): string {
    const texto = JSON.stringify(datos);
    const vigente = this.vigentes.get(nombre);
    if (vigente && vigente.datos === texto) {
      return vigente.clave; // reintento de la misma intención
    }
    const clave = crypto.randomUUID();
    this.vigentes.set(nombre, { datos: texto, clave });
    return clave;
  }

  /** El backend confirmó la operación: esa clave ya no se vuelve a usar. */
  cumplida(nombre: string): void {
    this.vigentes.delete(nombre);
  }
}
