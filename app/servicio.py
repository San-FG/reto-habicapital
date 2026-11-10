"""Reglas de negocio de la billetera. Aquí vive todo lo que toca plata."""
import sqlite3
from datetime import date, datetime, timezone

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


class CompromisoNoExiste(ErrorBilletera):
    http = 404


class EstadoInvalido(ErrorBilletera):
    http = 409


class NoAutorizado(ErrorBilletera):
    http = 403


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


def _exigir_cuenta_de_usuario(con: sqlite3.Connection, cuenta_id: int) -> sqlite3.Row:
    # La custodia guarda plata ajena: solo los compromisos pueden moverla.
    fila = _exigir_cuenta(con, cuenta_id)
    if fila["es_sistema"]:
        raise DatoInvalido(f"la cuenta {cuenta_id} es del sistema y no se puede operar")
    return fila


def _id_custodia(con: sqlite3.Connection) -> int:
    fila = con.execute(
        "SELECT id FROM cuentas WHERE es_sistema = 1 AND nombre = 'CUSTODIA'"
    ).fetchone()
    if fila is None:
        # Sin custodia no hay dónde retener: mejor fallar que improvisar una cuenta.
        raise RuntimeError("falta la cuenta CUSTODIA; ejecute inicializar()")
    return fila["id"]


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
        _exigir_cuenta_de_usuario(con, cuenta_id)
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
        _exigir_cuenta_de_usuario(con, origen)
        _exigir_cuenta_de_usuario(con, destino)
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


# ---------- Compromisos de pago con custodia ----------
#
# OJO: actor_id es una identidad SIMULADA. En este reto no hay autenticación:
# quien llama dice quién es y le creemos. En producción el actor saldría de
# una sesión o un token verificado, nunca del cuerpo de la petición.

def _validar_fecha(vence_el) -> None:
    # fromisoformat acepta variantes como '20270115'; comparar con isoformat()
    # deja pasar únicamente YYYY-MM-DD.
    try:
        valida = isinstance(vence_el, str) and date.fromisoformat(vence_el).isoformat() == vence_el
    except ValueError:
        valida = False
    if not valida:
        raise DatoInvalido("vence_el debe ser una fecha válida en formato YYYY-MM-DD")


def _publico(fila: sqlite3.Row) -> dict:
    # La clave de idempotencia es de quien canceló; la otra parte no tiene por qué verla.
    compromiso = dict(fila)
    compromiso.pop("clave_cancelacion")
    return compromiso


def _exigir_compromiso(con: sqlite3.Connection, compromiso_id: int) -> sqlite3.Row:
    fila = con.execute("SELECT * FROM compromisos WHERE id = ?", (compromiso_id,)).fetchone()
    if fila is None:
        raise CompromisoNoExiste(f"el compromiso {compromiso_id} no existe")
    return fila


def _exigir_actor(actor_id, permitidos, accion: str) -> None:
    if actor_id not in permitidos:
        raise NoAutorizado(f"la cuenta {actor_id} no puede {accion} este compromiso")


def _exigir_estado(compromiso: sqlite3.Row, esperado: str, accion: str) -> None:
    if compromiso["estado"] != esperado:
        raise EstadoInvalido(
            f"no se puede {accion} un compromiso en estado {compromiso['estado']}"
        )


def _accion_repetida(con, clave, tipo, compromiso_id) -> bool:
    """¿Esta clave ya movió plata para esta misma acción sobre este compromiso?

    Si la clave pertenece a otra operación es un error del cliente; avisamos
    antes de que el UNIQUE de movimientos reviente a mitad de la transacción.
    """
    fila = con.execute(
        "SELECT tipo, compromiso_id FROM movimientos WHERE clave_idempotencia = ?", (clave,)
    ).fetchone()
    if fila is None:
        return False
    if fila["tipo"] != tipo or fila["compromiso_id"] != compromiso_id:
        raise ConflictoIdempotencia("esa clave ya se usó para otra operación")
    return True


def _cambiar_estado(con, compromiso: sqlite3.Row, nuevo: str, columna_fecha: str) -> dict:
    """Cambia el estado. SIEMPRE dentro de la misma transaccion() que mueve la plata."""
    # El WHERE repite el estado de partida: si algún día alguien llama esto
    # sin el turno de escritura, la base no deja saltarse una transición.
    cur = con.execute(
        f"UPDATE compromisos SET estado = ?, {columna_fecha} = ? WHERE id = ? AND estado = ?",
        (nuevo, _ahora(), compromiso["id"], compromiso["estado"]),
    )
    if cur.rowcount != 1:
        raise EstadoInvalido("el compromiso cambió de estado mientras se procesaba")
    return _publico(_exigir_compromiso(con, compromiso["id"]))


def crear_compromiso(con, pagador_id: int, beneficiario_id: int, monto: int,
                     concepto: str, vence_el: str) -> dict:
    """Registra el acuerdo. Queda PENDIENTE y no mueve plata."""
    _validar_monto(monto)
    _validar_fecha(vence_el)
    if not isinstance(concepto, str) or not concepto.strip():
        raise DatoInvalido("el concepto no puede estar vacío")
    if pagador_id == beneficiario_id:
        raise DatoInvalido("pagador y beneficiario no pueden ser la misma cuenta")
    with transaccion(con):
        _exigir_cuenta_de_usuario(con, pagador_id)
        _exigir_cuenta_de_usuario(con, beneficiario_id)
        cur = con.execute(
            """INSERT INTO compromisos
               (pagador_id, beneficiario_id, monto, concepto, vence_el, estado, creado_en)
               VALUES (?, ?, ?, ?, ?, 'PENDIENTE', ?)""",
            (pagador_id, beneficiario_id, monto, concepto.strip(), vence_el, _ahora()),
        )
        return _publico(_exigir_compromiso(con, cur.lastrowid))


def respaldar_compromiso(con, compromiso_id: int, actor_id: int, clave: str) -> dict:
    """El pagador deja la plata retenida: pagador -> CUSTODIA."""
    _validar_clave(clave)
    with transaccion(con):
        c = _exigir_compromiso(con, compromiso_id)
        _exigir_actor(actor_id, [c["pagador_id"]], "respaldar")
        if _accion_repetida(con, clave, "RETENCION", compromiso_id):
            return _publico(c)
        _exigir_estado(c, "PENDIENTE", "respaldar")
        # Si no hay saldo, _mover lanza SaldoInsuficiente y el estado no se toca.
        _mover(con, "RETENCION", c["pagador_id"], _id_custodia(con), c["monto"],
               c["concepto"], clave, compromiso_id)
        return _cambiar_estado(con, c, "RESPALDADO", "respaldado_en")


def liberar_compromiso(con, compromiso_id: int, actor_id: int, clave: str) -> dict:
    """El pagador da por cumplido el acuerdo: CUSTODIA -> beneficiario."""
    _validar_clave(clave)
    with transaccion(con):
        c = _exigir_compromiso(con, compromiso_id)
        _exigir_actor(actor_id, [c["pagador_id"]], "liberar")
        if _accion_repetida(con, clave, "LIBERACION", compromiso_id):
            return _publico(c)
        _exigir_estado(c, "RESPALDADO", "liberar")
        _mover(con, "LIBERACION", _id_custodia(con), c["beneficiario_id"], c["monto"],
               c["concepto"], clave, compromiso_id)
        return _cambiar_estado(con, c, "CUMPLIDO", "cerrado_en")


def cancelar_compromiso(con, compromiso_id: int, actor_id: int, clave: str) -> dict:
    """Deshace el acuerdo. Si había plata retenida, vuelve al pagador."""
    _validar_clave(clave)
    with transaccion(con):
        c = _exigir_compromiso(con, compromiso_id)
        _exigir_actor(actor_id, [c["pagador_id"], c["beneficiario_id"]], "cancelar")
        if c["estado"] == "CANCELADO" and c["clave_cancelacion"] == clave:
            return _publico(c)
        _accion_repetida(con, clave, "DEVOLUCION", compromiso_id)  # clave de otra operación
        if c["estado"] == "RESPALDADO":
            # Con la plata ya retenida, el pagador no puede arrepentirse solo:
            # únicamente el beneficiario renuncia a ella.
            _exigir_actor(actor_id, [c["beneficiario_id"]], "cancelar")
            _mover(con, "DEVOLUCION", _id_custodia(con), c["pagador_id"], c["monto"],
                   c["concepto"], clave, compromiso_id)
        else:
            _exigir_estado(c, "PENDIENTE", "cancelar")
        con.execute("UPDATE compromisos SET clave_cancelacion = ? WHERE id = ?",
                    (clave, compromiso_id))
        return _cambiar_estado(con, c, "CANCELADO", "cerrado_en")


def consultar_compromiso(con, compromiso_id: int) -> dict:
    return _publico(_exigir_compromiso(con, compromiso_id))


def listar_compromisos(con, cuenta_id: int) -> list[dict]:
    _exigir_cuenta(con, cuenta_id)
    filas = con.execute(
        """SELECT * FROM compromisos
           WHERE pagador_id = ? OR beneficiario_id = ?
           ORDER BY id DESC""",
        (cuenta_id, cuenta_id),
    ).fetchall()
    return [_publico(f) for f in filas]


def auditar(con) -> dict:
    """Comprueba que no se ha perdido ni creado un peso.

    1. Global: suma de todos los saldos (custodia incluida) == suma de todas las cargas.
    2. Por cuenta: saldo guardado == entradas - salidas según el historial.
    3. Custodia: su saldo == suma de los compromisos RESPALDADO. Si no cuadra,
       hay plata retenida sin dueño o un compromiso respaldado sin plata.
    """
    saldo_custodia = con.execute(
        "SELECT COALESCE(SUM(saldo), 0) FROM cuentas WHERE es_sistema = 1"
    ).fetchone()[0]
    total_respaldado = con.execute(
        "SELECT COALESCE(SUM(monto), 0) FROM compromisos WHERE estado = 'RESPALDADO'"
    ).fetchone()[0]
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
        "ok": (total_saldos == total_cargas and not descuadradas
               and saldo_custodia == total_respaldado),
        "total_saldos": total_saldos,
        "total_cargas": total_cargas,
        "cuentas_descuadradas": [dict(f) for f in descuadradas],
        "saldo_custodia": saldo_custodia,
        "total_respaldado": total_respaldado,
    }
