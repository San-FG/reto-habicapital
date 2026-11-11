// Formas exactas de lo que responde el backend (app/servicio.py).
// Los montos y saldos son SIEMPRE enteros de pesos: nunca decimales.

export interface Cuenta {
  id: number;
  nombre: string;
  saldo: number;
  creada_en: string;
  es_sistema: number;
}

export type TipoMovimiento = 'CARGA' | 'TRANSFERENCIA' | 'RETENCION' | 'LIBERACION' | 'DEVOLUCION';

export interface Movimiento {
  id: number;
  tipo: TipoMovimiento;
  cuenta_origen: number | null; // null solo en una CARGA: la plata viene de afuera
  cuenta_destino: number;
  monto: number;
  concepto: string | null;
  clave_idempotencia: string;
  compromiso_id: number | null;
  creado_en: string;
}

export type EstadoCompromiso = 'PENDIENTE' | 'RESPALDADO' | 'CUMPLIDO' | 'CANCELADO';

export interface Compromiso {
  id: number;
  pagador_id: number;
  beneficiario_id: number;
  monto: number;
  concepto: string;
  vence_el: string; // YYYY-MM-DD
  estado: EstadoCompromiso;
  creado_en: string;
  respaldado_en: string | null;
  cerrado_en: string | null;
}

export interface Auditoria {
  ok: boolean;
  total_saldos: number;
  total_cargas: number;
  cuentas_descuadradas: { id: number; saldo_guardado: number; saldo_calculado: number }[];
  saldo_custodia: number;
  total_respaldado: number;
}

/** Lo que se envía para crear un compromiso. */
export interface NuevoCompromiso {
  pagador_id: number;
  beneficiario_id: number;
  monto: number;
  concepto: string;
  vence_el: string;
}

/** Lo que se envía para transferir. */
export interface NuevaTransferencia {
  origen: number;
  destino: number;
  monto: number;
  concepto: string | null;
}
