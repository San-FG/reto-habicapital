"""Reglas de negocio de la billetera. Aquí vive todo lo que toca plata."""
import sqlite3
from datetime import datetime, timezone

from app.db import transaccion


class ErrorBilletera(Exception):
    http = 400


class CuentaNoExiste(ErrorBilletera):
    http = 404


class SaldoInsuficiente(ErrorBilletera):
    http = 409


class ConflictoIdempotencia(ErrorBilletera):
    http = 409


class DatoInvalido(ErrorBilletera):
    http = 422


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _validar_monto(monto) -> None:
    # type(...) is int descarta float (10.5) y bool (True cuenta como 1 en Python).
    if type(monto) is not int or monto <= 0:
        raise DatoInvalido("el monto debe ser un entero de pesos mayor que cero")


def _validar_clave(clave) -> None:
    if not isinstance(clave, str) or not clave.strip():
        raise DatoInvalido("falta la clave de idempotencia")


def _exigir_cuenta(con: sqlite3.Connection, cuenta_id: int) -> sqlite3.Row:
    fila = con.execute("SELECT * FROM cuentas WHERE id = ?", (cuenta_id,)).fetchone()
    if fila is None:
        raise CuentaNoExiste(f"la cuenta {cuenta_id} no existe")
    return fila


def _buscar_repetido(con, clave, tipo, origen, destino, monto):
    """Si esta clave ya se procesó, devuelve el movimiento original.

    Así un doble clic o un reintento de red no mueve la plata dos veces.
    Si la clave llega con datos distintos, es un error del cliente.
    """
    fila = con.execute(
        "SELECT * FROM movimientos WHERE clave_idempotencia = ?", (clave,)
    ).fetchone()
    if fila is None:
        return None
    mismos_datos = (
        fila["tipo"] == tipo
        and fila["cuenta_origen"] == origen
        and fila["cuenta_destino"] == destino
        and fila["monto"] == monto
    )
    if not mismos_datos:
        raise ConflictoIdempotencia("esa clave ya se usó para otra operación")
    return dict(fila)


def _registrar_movimiento(con, tipo, origen, destino, monto, concepto, clave, compromiso_id):
    cur = con.execute(
        """INSERT INTO movimientos
           (tipo, cuenta_origen, cuenta_destino, monto, concepto,
            clave_idempotencia, compromiso_id, creado_en)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (tipo, origen, destino, monto, concepto, clave, compromiso_id, _ahora()),
    )
    fila = con.execute("SELECT * FROM movimientos WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(fila)


def _mover(con, tipo, origen, destino, monto, concepto, clave, compromiso_id=None):
    """Pasa plata de una cuenta a otra. SIEMPRE se llama dentro de transaccion().

    Es la única función que resta saldo. Todo lo que mueva plata entre
    cuentas (transferencias y, luego, la custodia) pasa por aquí.
    """
    if origen == destino:
        raise DatoInvalido("origen y destino no pueden ser la misma cuenta")
    cuenta_origen = _exigir_cuenta(con, origen)
    _exigir_cuenta(con, destino)
    # El saldo se lee DENTRO de la transacción: nadie más puede cambiarlo ahora.
    if cuenta_origen["saldo"] < monto:
        raise SaldoInsuficiente("saldo insuficiente")
    con.execute("UPDATE cuentas SET saldo = saldo - ? WHERE id = ?", (monto, origen))
    con.execute("UPDATE cuentas SET saldo = saldo + ? WHERE id = ?", (monto, destino))
    return _registrar_movimiento(con, tipo, origen, destino, monto, concepto, clave, compromiso_id)


# ---------- Operaciones públicas ----------

def crear_cuenta(con: sqlite3.Connection, nombre: str) -> dict:
    if not isinstance(nombre, str) or not nombre.strip():
        raise DatoInvalido("el nombre no puede estar vacío")
    with transaccion(con):
        cur = con.execute(
            "INSERT INTO cuentas (nombre, saldo, creada_en) VALUES (?, 0, ?)",
            (nombre.strip(), _ahora()),
        )
        return dict(_exigir_cuenta(con, cur.lastrowid))


def cargar(con, cuenta_id: int, monto: int, clave: str, concepto: str | None = None) -> dict:
    """Entra plata desde afuera del sistema (simulado)."""
    _validar_monto(monto)
    _validar_clave(clave)
    with transaccion(con):
        repetido = _buscar_repetido(con, clave, "CARGA", None, cuenta_id, monto)
        if repetido:
            return repetido
        _exigir_cuenta(con, cuenta_id)
        con.execute("UPDATE cuentas SET saldo = saldo + ? WHERE id = ?", (monto, cuenta_id))
        return _registrar_movimiento(con, "CARGA", None, cuenta_id, monto, concepto, clave, None)


def transferir(con, origen: int, destino: int, monto: int, clave: str,
               concepto: str | None = None) -> dict:
    _validar_monto(monto)
    _validar_clave(clave)
    with transaccion(con):
        repetido = _buscar_repetido(con, clave, "TRANSFERENCIA", origen, destino, monto)
        if repetido:
            return repetido
        return _mover(con, "TRANSFERENCIA", origen, destino, monto, concepto, clave)


def consultar_cuenta(con, cuenta_id: int) -> dict:
    return dict(_exigir_cuenta(con, cuenta_id))


def historial(con, cuenta_id: int) -> list[dict]:
    _exigir_cuenta(con, cuenta_id)
    filas = con.execute(
        """SELECT * FROM movimientos
           WHERE cuenta_origen = ? OR cuenta_destino = ?
           ORDER BY id DESC""",
        (cuenta_id, cuenta_id),
    ).fetchall()
    return [dict(f) for f in filas]


def auditar(con) -> dict:
    """Comprueba que no se ha perdido ni creado un peso.

    1. Global: suma de todos los saldos == suma de todas las cargas.
    2. Por cuenta: saldo guardado == entradas - salidas según el historial.
    """
    total_saldos = con.execute("SELECT COALESCE(SUM(saldo), 0) FROM cuentas").fetchone()[0]
    total_cargas = con.execute(
        "SELECT COALESCE(SUM(monto), 0) FROM movimientos WHERE tipo = 'CARGA'"
    ).fetchone()[0]
    descuadradas = con.execute(
        """SELECT c.id, c.saldo AS saldo_guardado,
                  COALESCE((SELECT SUM(monto) FROM movimientos WHERE cuenta_destino = c.id), 0)
                - COALESCE((SELECT SUM(monto) FROM movimientos WHERE cuenta_origen = c.id), 0)
                  AS saldo_calculado
           FROM cuentas c
           WHERE saldo_guardado <> saldo_calculado"""
    ).fetchall()
    return {
        "ok": total_saldos == total_cargas and not descuadradas,
        "total_saldos": total_saldos,
        "total_cargas": total_cargas,
        "cuentas_descuadradas": [dict(f) for f in descuadradas],
    }
