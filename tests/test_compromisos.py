"""Evidencia de que la custodia de compromisos tampoco pierde un peso."""
import random
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


@pytest.fixture
def compromiso(con, ana_y_luis):
    """Ana le debe 20.000 a Luis. Todavía PENDIENTE."""
    ana, luis = ana_y_luis
    return servicio.crear_compromiso(con, ana, luis, 20_000, "Arriendo", "2027-01-15")["id"]


def saldo(con, cuenta_id):
    return servicio.consultar_cuenta(con, cuenta_id)["saldo"]


def custodia(con):
    return saldo(con, servicio._id_custodia(con))


def saldos(con, ana, luis):
    return saldo(con, ana), saldo(con, luis), custodia(con)


def estado(con, compromiso_id):
    return servicio.consultar_compromiso(con, compromiso_id)["estado"]


# ---------- Ciclo de vida ----------

def test_crear_un_compromiso_no_mueve_plata(con, ana_y_luis):
    ana, luis = ana_y_luis
    c = servicio.crear_compromiso(con, ana, luis, 20_000, "Arriendo", "2027-01-15")
    assert c["estado"] == "PENDIENTE"
    assert (c["pagador_id"], c["beneficiario_id"], c["monto"]) == (ana, luis, 20_000)
    assert saldos(con, ana, luis) == (50_000, 10_000, 0)
    assert servicio.historial(con, servicio._id_custodia(con)) == []
    assert servicio.auditar(con)["ok"]


def test_respaldar_retiene_la_plata_en_custodia(con, ana_y_luis, compromiso):
    ana, luis = ana_y_luis
    c = servicio.respaldar_compromiso(con, compromiso, ana, clave())
    assert c["estado"] == "RESPALDADO" and c["respaldado_en"]
    # El beneficiario todavía no recibe nada.
    assert saldos(con, ana, luis) == (30_000, 10_000, 20_000)
    mov = servicio.historial(con, ana)[0]
    assert (mov["tipo"], mov["compromiso_id"]) == ("RETENCION", compromiso)
    auditoria = servicio.auditar(con)
    assert auditoria["ok"]
    assert auditoria["saldo_custodia"] == auditoria["total_respaldado"] == 20_000


def test_liberar_entrega_el_monto_exacto_al_beneficiario(con, ana_y_luis, compromiso):
    ana, luis = ana_y_luis
    servicio.respaldar_compromiso(con, compromiso, ana, clave())
    c = servicio.liberar_compromiso(con, compromiso, ana, clave())
    assert c["estado"] == "CUMPLIDO" and c["cerrado_en"]
    assert saldos(con, ana, luis) == (30_000, 30_000, 0)
    mov = servicio.historial(con, luis)[0]
    assert (mov["tipo"], mov["compromiso_id"]) == ("LIBERACION", compromiso)
    assert servicio.auditar(con)["ok"]


def test_cancelar_respaldado_devuelve_el_monto_exacto_al_pagador(con, ana_y_luis, compromiso):
    ana, luis = ana_y_luis
    servicio.respaldar_compromiso(con, compromiso, ana, clave())
    c = servicio.cancelar_compromiso(con, compromiso, luis, clave())
    assert c["estado"] == "CANCELADO" and c["cerrado_en"]
    assert saldos(con, ana, luis) == (50_000, 10_000, 0)
    mov = servicio.historial(con, ana)[0]
    assert (mov["tipo"], mov["compromiso_id"]) == ("DEVOLUCION", compromiso)
    assert servicio.auditar(con)["ok"]


@pytest.mark.parametrize("quien", [0, 1])
def test_cancelar_pendiente_lo_puede_hacer_cualquiera_de_los_dos(con, ana_y_luis, compromiso, quien):
    ana, luis = ana_y_luis
    servicio.cancelar_compromiso(con, compromiso, ana_y_luis[quien], clave())
    assert estado(con, compromiso) == "CANCELADO"
    assert saldos(con, ana, luis) == (50_000, 10_000, 0)
    assert servicio.auditar(con)["ok"]


def test_consultar_y_listar(con, ana_y_luis, compromiso):
    ana, luis = ana_y_luis
    otro = servicio.crear_cuenta(con, "Otro")["id"]
    assert [c["id"] for c in servicio.listar_compromisos(con, ana)] == [compromiso]
    assert [c["id"] for c in servicio.listar_compromisos(con, luis)] == [compromiso]
    assert servicio.listar_compromisos(con, otro) == []
    with pytest.raises(servicio.CompromisoNoExiste):
        servicio.consultar_compromiso(con, 9999)
    with pytest.raises(servicio.CompromisoNoExiste):
        servicio.respaldar_compromiso(con, 9999, ana, clave())


# ---------- Datos inválidos ----------

def test_crear_compromiso_valida_todo(con, ana_y_luis):
    ana, luis = ana_y_luis
    cust = servicio._id_custodia(con)
    bueno = dict(pagador_id=ana, beneficiario_id=luis, monto=20_000,
                 concepto="Arriendo", vence_el="2027-01-15")
    malos = [
        {"monto": 0}, {"monto": -5}, {"monto": 10.5}, {"monto": "100"}, {"monto": True},
        {"concepto": ""}, {"concepto": "   "}, {"concepto": None},
        {"vence_el": "15/01/2027"}, {"vence_el": "2027-02-30"}, {"vence_el": "20270115"},
        {"vence_el": "2027-1-5"}, {"vence_el": None},
        {"beneficiario_id": ana},
        {"pagador_id": cust}, {"beneficiario_id": cust},
    ]
    for cambio in malos:
        with pytest.raises(servicio.DatoInvalido):
            servicio.crear_compromiso(con, **{**bueno, **cambio})
    with pytest.raises(servicio.CuentaNoExiste):
        servicio.crear_compromiso(con, **{**bueno, "beneficiario_id": 9999})
    assert servicio.listar_compromisos(con, ana) == []


def test_respaldar_sin_saldo_no_cambia_nada(con, ana_y_luis):
    ana, luis = ana_y_luis
    c = servicio.crear_compromiso(con, ana, luis, 50_001, "Carro", "2027-01-15")["id"]
    with pytest.raises(servicio.SaldoInsuficiente):
        servicio.respaldar_compromiso(con, c, ana, clave())
    assert estado(con, c) == "PENDIENTE"
    assert saldos(con, ana, luis) == (50_000, 10_000, 0)
    assert servicio.auditar(con)["ok"]


# ---------- Autorización ----------

def test_solo_el_pagador_respalda_y_libera(con, ana_y_luis, compromiso):
    ana, luis = ana_y_luis
    with pytest.raises(servicio.NoAutorizado):
        servicio.respaldar_compromiso(con, compromiso, luis, clave())
    assert estado(con, compromiso) == "PENDIENTE"

    servicio.respaldar_compromiso(con, compromiso, ana, clave())
    with pytest.raises(servicio.NoAutorizado):
        servicio.liberar_compromiso(con, compromiso, luis, clave())
    assert estado(con, compromiso) == "RESPALDADO"
    assert saldos(con, ana, luis) == (30_000, 10_000, 20_000)


def test_el_pagador_no_puede_cancelar_un_compromiso_respaldado(con, ana_y_luis, compromiso):
    ana, luis = ana_y_luis
    servicio.respaldar_compromiso(con, compromiso, ana, clave())
    with pytest.raises(servicio.NoAutorizado):
        servicio.cancelar_compromiso(con, compromiso, ana, clave())
    assert estado(con, compromiso) == "RESPALDADO"
    assert saldos(con, ana, luis) == (30_000, 10_000, 20_000)


def test_un_tercero_no_puede_hacer_nada(con, ana_y_luis, compromiso):
    ana, luis = ana_y_luis
    intruso = servicio.crear_cuenta(con, "Intruso")["id"]
    for accion in (servicio.respaldar_compromiso, servicio.cancelar_compromiso):
        with pytest.raises(servicio.NoAutorizado):
            accion(con, compromiso, intruso, clave())
    servicio.respaldar_compromiso(con, compromiso, ana, clave())
    for accion in (servicio.liberar_compromiso, servicio.cancelar_compromiso):
        with pytest.raises(servicio.NoAutorizado):
            accion(con, compromiso, intruso, clave())
    assert saldos(con, ana, luis) == (30_000, 10_000, 20_000)


# ---------- Transiciones inválidas ----------

def test_no_se_libera_un_pendiente_ni_se_respalda_dos_veces(con, ana_y_luis, compromiso):
    ana, luis = ana_y_luis
    with pytest.raises(servicio.EstadoInvalido):
        servicio.liberar_compromiso(con, compromiso, ana, clave())
    assert saldos(con, ana, luis) == (50_000, 10_000, 0)

    servicio.respaldar_compromiso(con, compromiso, ana, clave())
    with pytest.raises(servicio.EstadoInvalido):
        servicio.respaldar_compromiso(con, compromiso, ana, clave())  # clave nueva
    assert saldos(con, ana, luis) == (30_000, 10_000, 20_000)
    assert servicio.auditar(con)["ok"]


@pytest.mark.parametrize("final", ["CUMPLIDO", "CANCELADO"])
def test_un_compromiso_cerrado_no_admite_mas_acciones(con, ana_y_luis, compromiso, final):
    ana, luis = ana_y_luis
    servicio.respaldar_compromiso(con, compromiso, ana, clave())
    if final == "CUMPLIDO":
        servicio.liberar_compromiso(con, compromiso, ana, clave())
    else:
        servicio.cancelar_compromiso(con, compromiso, luis, clave())
    antes = saldos(con, ana, luis)

    intentos = [
        (servicio.respaldar_compromiso, ana),
        (servicio.liberar_compromiso, ana),
        (servicio.cancelar_compromiso, ana),
        (servicio.cancelar_compromiso, luis),
    ]
    for accion, actor in intentos:
        with pytest.raises(servicio.EstadoInvalido):
            accion(con, compromiso, actor, clave())
    assert estado(con, compromiso) == final
    assert saldos(con, ana, luis) == antes
    assert servicio.auditar(con)["ok"]


# ---------- Doble clic / reintento ----------

def test_misma_clave_en_respaldar_y_liberar_mueve_la_plata_una_sola_vez(con, ana_y_luis, compromiso):
    ana, luis = ana_y_luis
    k1, k2 = clave(), clave()
    primero = servicio.respaldar_compromiso(con, compromiso, ana, k1)
    segundo = servicio.respaldar_compromiso(con, compromiso, ana, k1)
    assert primero == segundo
    assert saldos(con, ana, luis) == (30_000, 10_000, 20_000)

    primero = servicio.liberar_compromiso(con, compromiso, ana, k2)
    segundo = servicio.liberar_compromiso(con, compromiso, ana, k2)
    assert primero == segundo
    assert saldos(con, ana, luis) == (30_000, 30_000, 0)
    # Un reintento tardío del respaldo tampoco vuelve a retener.
    assert servicio.respaldar_compromiso(con, compromiso, ana, k1)["estado"] == "CUMPLIDO"
    assert saldos(con, ana, luis) == (30_000, 30_000, 0)
    assert len(servicio.historial(con, servicio._id_custodia(con))) == 2
    assert servicio.auditar(con)["ok"]


def test_misma_clave_en_cancelar_devuelve_la_plata_una_sola_vez(con, ana_y_luis, compromiso):
    ana, luis = ana_y_luis
    servicio.respaldar_compromiso(con, compromiso, ana, clave())
    k = clave()
    primero = servicio.cancelar_compromiso(con, compromiso, luis, k)
    segundo = servicio.cancelar_compromiso(con, compromiso, luis, k)
    assert primero == segundo
    assert saldos(con, ana, luis) == (50_000, 10_000, 0)


def test_cancelar_pendiente_con_la_misma_clave_no_da_error(con, ana_y_luis, compromiso):
    ana, _ = ana_y_luis
    k = clave()
    primero = servicio.cancelar_compromiso(con, compromiso, ana, k)
    assert servicio.cancelar_compromiso(con, compromiso, ana, k) == primero
    with pytest.raises(servicio.EstadoInvalido):
        servicio.cancelar_compromiso(con, compromiso, ana, clave())


def test_una_clave_ya_usada_en_otra_operacion_es_conflicto(con, ana_y_luis, compromiso):
    ana, luis = ana_y_luis
    k = clave()
    servicio.transferir(con, ana, luis, 1_000, k)
    with pytest.raises(servicio.ConflictoIdempotencia):
        servicio.respaldar_compromiso(con, compromiso, ana, k)
    assert estado(con, compromiso) == "PENDIENTE"

    k2 = clave()
    servicio.respaldar_compromiso(con, compromiso, ana, k2)
    # La clave del respaldo no sirve para liberar, ni para una transferencia.
    with pytest.raises(servicio.ConflictoIdempotencia):
        servicio.liberar_compromiso(con, compromiso, ana, k2)
    with pytest.raises(servicio.ConflictoIdempotencia):
        servicio.cancelar_compromiso(con, compromiso, luis, k2)
    with pytest.raises(servicio.ConflictoIdempotencia):
        servicio.transferir(con, ana, luis, 20_000, k2)
    assert estado(con, compromiso) == "RESPALDADO"
    assert saldos(con, ana, luis) == (29_000, 11_000, 20_000)
    assert servicio.auditar(con)["ok"]


# ---------- Concurrencia ----------

def test_veinte_liberaciones_simultaneas_solo_una_pasa(ruta, con, ana_y_luis, compromiso):
    ana, luis = ana_y_luis
    servicio.respaldar_compromiso(con, compromiso, ana, clave())

    resultados = []
    salida = threading.Barrier(20)

    def intentar():
        propia = conectar(ruta)  # cada hilo con su conexión, como peticiones reales
        salida.wait()            # todos arrancan al mismo tiempo
        try:
            servicio.liberar_compromiso(propia, compromiso, ana, clave())
            resultados.append("ok")
        except servicio.EstadoInvalido:
            resultados.append("rechazada")
        finally:
            propia.close()

    hilos = [threading.Thread(target=intentar) for _ in range(20)]
    [h.start() for h in hilos]
    [h.join() for h in hilos]

    assert resultados.count("ok") == 1
    assert resultados.count("rechazada") == 19
    assert saldos(con, ana, luis) == (30_000, 30_000, 0)
    assert servicio.auditar(con)["ok"]


# ---------- Caída a mitad de camino ----------

def test_si_falla_a_la_mitad_de_respaldar_se_deshace_todo(con, ana_y_luis, compromiso, monkeypatch):
    ana, luis = ana_y_luis

    def explotar(*args, **kwargs):
        raise RuntimeError("se cayó el servidor")

    # Los saldos ya se actualizaron cuando esto explota; el ROLLBACK debe deshacerlos.
    monkeypatch.setattr(servicio, "_registrar_movimiento", explotar)
    with pytest.raises(RuntimeError):
        servicio.respaldar_compromiso(con, compromiso, ana, clave())
    monkeypatch.undo()

    assert estado(con, compromiso) == "PENDIENTE"
    assert saldos(con, ana, luis) == (50_000, 10_000, 0)
    assert servicio.auditar(con)["ok"]


# ---------- La custodia no es de nadie ----------

def test_no_se_puede_cargar_ni_transferir_con_la_custodia(con, ana_y_luis, compromiso):
    ana, luis = ana_y_luis
    cust = servicio._id_custodia(con)
    servicio.respaldar_compromiso(con, compromiso, ana, clave())  # que haya algo que robar

    with pytest.raises(servicio.DatoInvalido):
        servicio.cargar(con, cust, 1_000, clave())
    with pytest.raises(servicio.DatoInvalido):
        servicio.transferir(con, ana, cust, 1_000, clave())
    with pytest.raises(servicio.DatoInvalido):
        servicio.transferir(con, cust, luis, 1_000, clave())

    assert saldos(con, ana, luis) == (30_000, 10_000, 20_000)
    assert servicio.auditar(con)["ok"]


def test_la_custodia_es_unica_aunque_se_inicialice_varias_veces(ruta, con):
    inicializar(ruta)
    inicializar(ruta)
    assert con.execute("SELECT COUNT(*) FROM cuentas WHERE es_sistema = 1").fetchone()[0] == 1


def test_la_auditoria_detecta_custodia_descuadrada(con, ana_y_luis, compromiso):
    ana, _ = ana_y_luis
    servicio.respaldar_compromiso(con, compromiso, ana, clave())
    # Simulamos un error de programación: el estado cambia sin mover la plata.
    con.execute("UPDATE compromisos SET estado = 'CUMPLIDO' WHERE id = ?", (compromiso,))
    auditoria = servicio.auditar(con)
    assert not auditoria["ok"]
    assert (auditoria["saldo_custodia"], auditoria["total_respaldado"]) == (20_000, 0)


# ---------- La regla completa ----------

def test_ochocientas_operaciones_al_azar_y_la_plata_cuadra(con):
    azar = random.Random(2027)
    cuentas = [servicio.crear_cuenta(con, f"Persona {i}")["id"] for i in range(6)]
    cargado = 0
    for c in cuentas:
        servicio.cargar(con, c, 100_000, clave())
        cargado += 100_000

    esperados = (servicio.SaldoInsuficiente, servicio.EstadoInvalido, servicio.NoAutorizado)
    compromisos = []
    for _ in range(800):
        operacion = azar.choice(["transferir", "crear", "respaldar", "liberar", "cancelar"])
        try:
            if operacion == "transferir":
                origen, destino = azar.sample(cuentas, 2)
                servicio.transferir(con, origen, destino, azar.randint(1, 150_000), clave())
            elif operacion == "crear" or not compromisos:
                pagador, beneficiario = azar.sample(cuentas, 2)
                compromisos.append(servicio.crear_compromiso(
                    con, pagador, beneficiario, azar.randint(1, 120_000), "Azar", "2027-01-15"))
            else:
                c = azar.choice(compromisos)
                actor = azar.choice([c["pagador_id"], c["beneficiario_id"]])
                accion = getattr(servicio, f"{operacion}_compromiso")
                accion(con, c["id"], actor, clave())
        except esperados:
            pass

    auditoria = servicio.auditar(con)
    assert auditoria["ok"]
    assert auditoria["total_saldos"] == cargado
    assert auditoria["saldo_custodia"] == auditoria["total_respaldado"]
    # Que la prueba no pase de casualidad: se recorrieron todos los estados.
    estados = {estado(con, c["id"]) for c in compromisos}
    assert estados == {"PENDIENTE", "RESPALDADO", "CUMPLIDO", "CANCELADO"}
    tipos = {f[0] for f in con.execute("SELECT DISTINCT tipo FROM movimientos")}
    assert {"RETENCION", "LIBERACION", "DEVOLUCION", "TRANSFERENCIA"} <= tipos
