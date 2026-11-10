"""Conexión a la base de datos y esquema.

Usamos sqlite3 directo (sin ORM) para que cada transacción sea explícita
y se vea exactamente qué SQL toca la plata.
"""
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

ESQUEMA = """
CREATE TABLE IF NOT EXISTS cuentas (
    id         INTEGER PRIMARY KEY,
    nombre     TEXT    NOT NULL,
    saldo      INTEGER NOT NULL DEFAULT 0 CHECK (saldo >= 0),
    creada_en  TEXT    NOT NULL,
    -- 1 = cuenta interna (la custodia). Ningún usuario la opera directamente.
    es_sistema INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS movimientos (
    id                  INTEGER PRIMARY KEY,
    tipo                TEXT    NOT NULL
                        CHECK (tipo IN ('CARGA', 'TRANSFERENCIA', 'RETENCION',
                                        'LIBERACION', 'DEVOLUCION')),
    cuenta_origen       INTEGER REFERENCES cuentas(id),
    cuenta_destino      INTEGER NOT NULL REFERENCES cuentas(id),
    monto               INTEGER NOT NULL CHECK (monto > 0),
    concepto            TEXT,
    clave_idempotencia  TEXT    NOT NULL UNIQUE,
    compromiso_id       INTEGER,
    creado_en           TEXT    NOT NULL,
    -- Solo una CARGA puede no tener origen, y nadie se paga a sí mismo.
    CHECK ((tipo = 'CARGA') = (cuenta_origen IS NULL)),
    CHECK (cuenta_origen IS NULL OR cuenta_origen <> cuenta_destino)
);

CREATE TABLE IF NOT EXISTS compromisos (
    id               INTEGER PRIMARY KEY,
    pagador_id       INTEGER NOT NULL REFERENCES cuentas(id),
    beneficiario_id  INTEGER NOT NULL REFERENCES cuentas(id),
    monto            INTEGER NOT NULL CHECK (monto > 0),
    concepto         TEXT    NOT NULL,
    vence_el         TEXT    NOT NULL,
    estado           TEXT    NOT NULL
                     CHECK (estado IN ('PENDIENTE', 'RESPALDADO', 'CUMPLIDO', 'CANCELADO')),
    creado_en        TEXT    NOT NULL,
    respaldado_en    TEXT,
    cerrado_en       TEXT,
    -- Cancelar un compromiso PENDIENTE no deja movimiento, así que la clave
    -- de idempotencia de esa cancelación no tendría dónde quedar. Va aquí.
    clave_cancelacion TEXT,
    CHECK (pagador_id <> beneficiario_id)
);

-- El historial solo crece: la base rechaza editar o borrar movimientos.
CREATE TRIGGER IF NOT EXISTS movimientos_no_update
BEFORE UPDATE ON movimientos
BEGIN
    SELECT RAISE(ABORT, 'los movimientos no se pueden modificar');
END;

CREATE TRIGGER IF NOT EXISTS movimientos_no_delete
BEFORE DELETE ON movimientos
BEGIN
    SELECT RAISE(ABORT, 'los movimientos no se pueden borrar');
END;
"""


def ruta_bd() -> str:
    return os.environ.get("BILLETERA_DB", "billetera.db")


def conectar(ruta: str | None = None) -> sqlite3.Connection:
    # isolation_level=None: nosotros decidimos cuándo empieza y termina
    # cada transacción (BEGIN / COMMIT / ROLLBACK), Python no lo hace solo.
    # timeout=10: si otro está escribiendo, esperamos el turno hasta 10 s.
    con = sqlite3.connect(ruta or ruta_bd(), timeout=10, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def inicializar(ruta: str | None = None) -> None:
    con = conectar(ruta)
    # WAL: los lectores no bloquean al escritor ni al revés.
    con.execute("PRAGMA journal_mode = WAL")
    con.executescript(ESQUEMA)
    _agregar_es_sistema_si_falta(con)
    _crear_custodia_si_falta(con)
    con.close()


def _agregar_es_sistema_si_falta(con: sqlite3.Connection) -> None:
    # CREATE TABLE IF NOT EXISTS no altera una tabla que ya existía: una base
    # creada antes de la custodia necesita que le agreguemos la columna.
    columnas = [f["name"] for f in con.execute("PRAGMA table_info(cuentas)")]
    if "es_sistema" not in columnas:
        con.execute("ALTER TABLE cuentas ADD COLUMN es_sistema INTEGER NOT NULL DEFAULT 0")


def _crear_custodia_si_falta(con: sqlite3.Connection) -> None:
    # El índice único hace que la base misma impida una segunda cuenta de
    # sistema con el mismo nombre, aunque dos procesos arranquen a la vez.
    con.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS cuentas_sistema_unicas
           ON cuentas(nombre) WHERE es_sistema = 1"""
    )
    with transaccion(con):
        con.execute(
            """INSERT INTO cuentas (nombre, saldo, creada_en, es_sistema)
               SELECT 'CUSTODIA', 0, ?, 1
               WHERE NOT EXISTS (SELECT 1 FROM cuentas WHERE es_sistema = 1)""",
            (datetime.now(timezone.utc).isoformat(timespec="seconds"),),
        )


@contextmanager
def transaccion(con: sqlite3.Connection):
    """Todo o nada, y de a uno.

    BEGIN IMMEDIATE toma el turno de escritura ANTES de leer nada. Así dos
    transferencias simultáneas no pueden leer el mismo saldo viejo: la
    segunda espera a que la primera termine.
    Si algo falla adentro, ROLLBACK deshace todos los cambios.
    """
    con.execute("BEGIN IMMEDIATE")
    try:
        yield
        con.execute("COMMIT")
    except BaseException:
        con.execute("ROLLBACK")
        raise
