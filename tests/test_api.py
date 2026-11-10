"""Prueba de punta a punta por HTTP."""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    monkeypatch.setenv("BILLETERA_DB", str(tmp_path / "api.db"))
    from app.main import app
    with TestClient(app) as c:
        yield c


def test_flujo_completo(cliente):
    ana = cliente.post("/cuentas", json={"nombre": "Ana"}).json()["id"]
    luis = cliente.post("/cuentas", json={"nombre": "Luis"}).json()["id"]

    r = cliente.post(f"/cuentas/{ana}/cargas", json={"monto": 50000},
                     headers={"Idempotency-Key": "carga-1"})
    assert r.status_code == 201

    cuerpo = {"origen": ana, "destino": luis, "monto": 20000, "concepto": "Cena"}
    for _ in range(2):  # doble clic
        r = cliente.post("/transferencias", json=cuerpo, headers={"Idempotency-Key": "t-1"})
        assert r.status_code == 201

    assert cliente.get(f"/cuentas/{ana}").json()["saldo"] == 30000
    assert cliente.get(f"/cuentas/{luis}").json()["saldo"] == 20000
    assert len(cliente.get(f"/cuentas/{luis}/movimientos").json()) == 1
    assert cliente.get("/auditoria").json()["ok"] is True


def test_errores_http(cliente):
    ana = cliente.post("/cuentas", json={"nombre": "Ana"}).json()["id"]
    luis = cliente.post("/cuentas", json={"nombre": "Luis"}).json()["id"]
    h = {"Idempotency-Key": "x"}
    cuerpo = {"origen": ana, "destino": luis, "monto": 1000}
    assert cliente.post("/transferencias", json=cuerpo, headers=h).status_code == 409
    assert cliente.post("/transferencias", json=cuerpo).status_code == 422  # sin clave
    assert cliente.post("/transferencias", json={**cuerpo, "monto": 10.5},
                        headers=h).status_code == 422
    assert cliente.get("/cuentas/9999").status_code == 404


def test_flujo_de_compromiso(cliente):
    ana = cliente.post("/cuentas", json={"nombre": "Ana"}).json()["id"]
    luis = cliente.post("/cuentas", json={"nombre": "Luis"}).json()["id"]
    cliente.post(f"/cuentas/{ana}/cargas", json={"monto": 50000},
                 headers={"Idempotency-Key": "carga-1"})

    cuerpo = {"pagador_id": ana, "beneficiario_id": luis, "monto": 20000,
              "concepto": "Arriendo", "vence_el": "2027-01-15"}
    r = cliente.post("/compromisos", json=cuerpo)
    assert r.status_code == 201
    assert r.json()["estado"] == "PENDIENTE"
    c = r.json()["id"]
    assert cliente.post("/compromisos", json={**cuerpo, "monto": 10.5}).status_code == 422

    # El beneficiario no puede respaldar, y sin clave no se hace nada.
    assert cliente.post(f"/compromisos/{c}/respaldo", json={"actor_id": luis},
                        headers={"Idempotency-Key": "r-0"}).status_code == 403
    assert cliente.post(f"/compromisos/{c}/respaldo", json={"actor_id": ana}).status_code == 422

    for _ in range(2):  # doble clic
        r = cliente.post(f"/compromisos/{c}/respaldo", json={"actor_id": ana},
                         headers={"Idempotency-Key": "r-1"})
        assert r.status_code == 200
        assert r.json()["estado"] == "RESPALDADO"
    assert cliente.get(f"/cuentas/{ana}").json()["saldo"] == 30000
    assert cliente.get(f"/cuentas/{luis}").json()["saldo"] == 0
    assert cliente.get("/auditoria").json()["saldo_custodia"] == 20000

    r = cliente.post(f"/compromisos/{c}/liberacion", json={"actor_id": ana},
                     headers={"Idempotency-Key": "l-1"})
    assert r.status_code == 200
    assert r.json()["estado"] == "CUMPLIDO"
    assert cliente.post(f"/compromisos/{c}/cancelacion", json={"actor_id": luis},
                        headers={"Idempotency-Key": "c-1"}).status_code == 409

    assert cliente.get(f"/cuentas/{ana}").json()["saldo"] == 30000
    assert cliente.get(f"/cuentas/{luis}").json()["saldo"] == 20000
    assert cliente.get(f"/compromisos/{c}").json()["estado"] == "CUMPLIDO"
    assert [x["id"] for x in cliente.get(f"/cuentas/{luis}/compromisos").json()] == [c]
    assert cliente.get("/compromisos/9999").status_code == 404
    auditoria = cliente.get("/auditoria").json()
    assert auditoria["ok"] is True
    assert auditoria["saldo_custodia"] == auditoria["total_respaldado"] == 0
