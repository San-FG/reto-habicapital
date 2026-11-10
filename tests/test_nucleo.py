"""Evidencia de que el sistema no pierde un peso."""
import random
import sqlite3
import threading
import uuid

import pytest

from app import servicio
from app.db import conectar, inicializar


def clave() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def ruta(tmp_path):
    r = str(tmp_path / "prueba.db")
    inicializar(r)
    return r


@pytest.fixture
def con(ruta):
    c = conectar(ruta)
    yield c
    c.close()


@pytest.fixture
def ana_y_luis(con):
    ana = servicio.crear_cuenta(con, "Ana")["id"]
    luis = servicio.crear_cuenta(con, "Luis")["id"]
    servicio.cargar(con, ana, 50_000, clave())
    servicio.cargar(con, luis, 10_000, clave())
    return ana, luis


def saldo(con, cuenta_id):
    return servicio.consultar_cuenta(con, cuenta_id)["saldo"]


# ---------- Núcleo ----------

def test_cuenta_nueva_empieza_en_cero(con):
    cuenta = servicio.crear_cuenta(con, "Ana")
    assert cuenta["saldo"] == 0


def test_cargar_suma_saldo_y_queda_en_historial(con):
    ana = servicio.crear_cuenta(con, "Ana")["id"]
    servicio.cargar(con, ana, 50_000, clave(), "Carga inicial")
    assert saldo(con, ana) == 50_000
    mov = servicio.historial(con, ana)[0]
    assert (mov["tipo"], mov["monto"], mov["cuenta_origen"]) == ("CARGA", 50_000, None)


def test_transferir_mueve_la_plata_y_el_total_no_cambia(con, ana_y_luis):
    ana, luis = ana_y_luis
    servicio.transferir(con, ana, luis, 20_000, clave(), "Cena del viernes")
    assert saldo(con, ana) == 30_000
    assert saldo(con, luis) == 30_000
    assert servicio.auditar(con)["ok"]


def test_la_transferencia_aparece_en_el_historial_de_ambos(con, ana_y_luis):
    ana, luis = ana_y_luis
    mov = servicio.transferir(con, ana, luis, 20_000, clave(), "Cena del viernes")
    assert servicio.historial(con, ana)[0]["id"] == mov["id"]
    assert servicio.historial(con, luis)[0]["id"] == mov["id"]
    assert mov["concepto"] == "Cena del viernes"


# ---------- Riesgo 5: datos inválidos ----------

def test_saldo_insuficiente_no_mueve_nada(con, ana_y_luis):
    ana, luis = ana_y_luis
    with pytest.raises(servicio.SaldoInsuficiente):
        servicio.transferir(con, ana, luis, 50_001, clave())
    assert (saldo(con, ana), saldo(con, luis)) == (50_000, 10_000)


@pytest.mark.parametrize("monto", [0, -1, 10.5, "100", True, None])
def test_montos_invalidos_se_rechazan(con, ana_y_luis, monto):
    ana, luis = ana_y_luis
    with pytest.raises(servicio.DatoInvalido):
        servicio.transferir(con, ana, luis, monto, clave())
    with pytest.raises(servicio.DatoInvalido):
        servicio.cargar(con, ana, monto, clave())
    assert (saldo(con, ana), saldo(con, luis)) == (50_000, 10_000)


def test_no_se_puede_transferir_a_uno_mismo(con, ana_y_luis):
    ana, _ = ana_y_luis
    with pytest.raises(servicio.DatoInvalido):
        servicio.transferir(con, ana, ana, 1_000, clave())


def test_cuenta_inexistente(con, ana_y_luis):
    ana, _ = ana_y_luis
    with pytest.raises(servicio.CuentaNoExiste):
        servicio.transferir(con, ana, 9999, 1_000, clave())
    with pytest.raises(servicio.CuentaNoExiste):
        servicio.cargar(con, 9999, 1_000, clave())
    assert saldo(con, ana) == 50_000


# ---------- Riesgo 4: doble clic / reintento ----------

def test_misma_clave_dos_veces_mueve_la_plata_una_sola_vez(con, ana_y_luis):
    ana, luis = ana_y_luis
    k = clave()
    primero = servicio.transferir(con, ana, luis, 20_000, k)
    segundo = servicio.transferir(con, ana, luis, 20_000, k)
    assert primero["id"] == segundo["id"]
    assert (saldo(con, ana), saldo(con, luis)) == (30_000, 30_000)


def test_carga_repetida_no_duplica(con):
    ana = servicio.crear_cuenta(con, "Ana")["id"]
    k = clave()
    servicio.cargar(con, ana, 50_000, k)
    servicio.cargar(con, ana, 50_000, k)
    assert saldo(con, ana) == 50_000


def test_misma_clave_con_datos_distintos_es_conflicto(con, ana_y_luis):
    ana, luis = ana_y_luis
    k = clave()
    servicio.transferir(con, ana, luis, 20_000, k)
    with pytest.raises(servicio.ConflictoIdempotencia):
        servicio.transferir(con, ana, luis, 5_000, k)
    assert (saldo(con, ana), saldo(con, luis)) == (30_000, 30_000)


# ---------- Riesgo 1: caída a mitad de transferencia ----------

def test_si_falla_a_la_mitad_se_deshace_todo(con, ana_y_luis, monkeypatch):
    ana, luis = ana_y_luis

    def explotar(*args, **kwargs):
        raise RuntimeError("se cayó el servidor")

    # Los saldos ya se actualizaron cuando esto explota; el ROLLBACK debe deshacerlos.
    monkeypatch.setattr(servicio, "_registrar_movimiento", explotar)
    with pytest.raises(RuntimeError):
        servicio.transferir(con, ana, luis, 20_000, clave())
    monkeypatch.undo()

    assert (saldo(con, ana), saldo(con, luis)) == (50_000, 10_000)
    assert servicio.auditar(con)["ok"]


# ---------- Riesgo 2: concurrencia ----------

def test_veinte_transferencias_simultaneas_solo_una_pasa(ruta, con):
    ana = servicio.crear_cuenta(con, "Ana")["id"]
    luis = servicio.crear_cuenta(con, "Luis")["id"]
    servicio.cargar(con, ana, 30_000, clave())

    resultados = []
    salida = threading.Barrier(20)

    def intentar():
        propia = conectar(ruta)  # cada hilo con su conexión, como peticiones reales
        salida.wait()            # todos arrancan al mismo tiempo
        try:
            servicio.transferir(propia, ana, luis, 30_000, clave())
            resultados.append("ok")
        except servicio.SaldoInsuficiente:
            resultados.append("rechazada")
        finally:
            propia.close()

    hilos = [threading.Thread(target=intentar) for _ in range(20)]
    [h.start() for h in hilos]
    [h.join() for h in hilos]

    assert resultados.count("ok") == 1
    assert resultados.count("rechazada") == 19
    assert (saldo(con, ana), saldo(con, luis)) == (0, 30_000)
    assert servicio.auditar(con)["ok"]


# ---------- Riesgo 6 y red de seguridad de la base ----------

def test_los_movimientos_no_se_pueden_editar_ni_borrar(con, ana_y_luis):
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("UPDATE movimientos SET monto = 1")
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("DELETE FROM movimientos")


def test_la_base_rechaza_un_saldo_negativo_aunque_el_codigo_falle(con, ana_y_luis):
    ana, _ = ana_y_luis
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("UPDATE cuentas SET saldo = -1 WHERE id = ?", (ana,))


# ---------- La regla completa ----------

def test_quinientas_operaciones_al_azar_y_la_plata_cuadra(con):
    azar = random.Random(2027)
    cuentas = [servicio.crear_cuenta(con, f"Persona {i}")["id"] for i in range(6)]
    cargado = 0
    for c in cuentas:
        servicio.cargar(con, c, 100_000, clave())
        cargado += 100_000

    for _ in range(500):
        origen, destino = azar.sample(cuentas, 2)
        try:
            servicio.transferir(con, origen, destino, azar.randint(1, 150_000), clave())
        except servicio.SaldoInsuficiente:
            pass

    auditoria = servicio.auditar(con)
    assert auditoria["ok"]
    assert auditoria["total_saldos"] == cargado
