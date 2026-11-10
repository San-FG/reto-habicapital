"""API HTTP. Solo traduce peticiones a llamadas de servicio.py; no tiene reglas de plata."""
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, StrictInt

from app import servicio
from app.db import conectar, inicializar


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    inicializar()
    yield


app = FastAPI(title="Billetera entre personas", lifespan=ciclo_de_vida)


def obtener_conexion():
    # Una conexión por petición; se cierra al terminar.
    con = conectar()
    try:
        yield con
    finally:
        con.close()


@app.exception_handler(servicio.ErrorBilletera)
def manejar_error(request: Request, error: servicio.ErrorBilletera):
    return JSONResponse(status_code=error.http, content={"error": str(error)})


class NuevaCuenta(BaseModel):
    nombre: str


class Carga(BaseModel):
    monto: StrictInt  # StrictInt rechaza 10.5 y "100": solo enteros de verdad
    concepto: str | None = None


class Transferencia(BaseModel):
    origen: int
    destino: int
    monto: StrictInt
    concepto: str | None = None


class NuevoCompromiso(BaseModel):
    pagador_id: int
    beneficiario_id: int
    monto: StrictInt
    concepto: str
    vence_el: str


class Actor(BaseModel):
    # Identidad simulada: en este reto no hay autenticación (ver servicio.py).
    actor_id: int


@app.post("/cuentas", status_code=201)
def crear_cuenta(datos: NuevaCuenta, con=Depends(obtener_conexion)):
    return servicio.crear_cuenta(con, datos.nombre)


@app.get("/cuentas/{cuenta_id}")
def consultar_cuenta(cuenta_id: int, con=Depends(obtener_conexion)):
    return servicio.consultar_cuenta(con, cuenta_id)


@app.post("/cuentas/{cuenta_id}/cargas", status_code=201)
def cargar(cuenta_id: int, datos: Carga, idempotency_key: str = Header(),
           con=Depends(obtener_conexion)):
    return servicio.cargar(con, cuenta_id, datos.monto, idempotency_key, datos.concepto)


@app.post("/transferencias", status_code=201)
def transferir(datos: Transferencia, idempotency_key: str = Header(),
               con=Depends(obtener_conexion)):
    return servicio.transferir(con, datos.origen, datos.destino, datos.monto,
                               idempotency_key, datos.concepto)


@app.get("/cuentas/{cuenta_id}/movimientos")
def historial(cuenta_id: int, con=Depends(obtener_conexion)):
    return servicio.historial(con, cuenta_id)


@app.get("/auditoria")
def auditoria(con=Depends(obtener_conexion)):
    return servicio.auditar(con)


@app.post("/compromisos", status_code=201)
def crear_compromiso(datos: NuevoCompromiso, con=Depends(obtener_conexion)):
    return servicio.crear_compromiso(con, datos.pagador_id, datos.beneficiario_id,
                                     datos.monto, datos.concepto, datos.vence_el)


@app.get("/compromisos/{compromiso_id}")
def consultar_compromiso(compromiso_id: int, con=Depends(obtener_conexion)):
    return servicio.consultar_compromiso(con, compromiso_id)


@app.get("/cuentas/{cuenta_id}/compromisos")
def listar_compromisos(cuenta_id: int, con=Depends(obtener_conexion)):
    return servicio.listar_compromisos(con, cuenta_id)


@app.post("/compromisos/{compromiso_id}/respaldo")
def respaldar_compromiso(compromiso_id: int, datos: Actor, idempotency_key: str = Header(),
                         con=Depends(obtener_conexion)):
    return servicio.respaldar_compromiso(con, compromiso_id, datos.actor_id, idempotency_key)


@app.post("/compromisos/{compromiso_id}/liberacion")
def liberar_compromiso(compromiso_id: int, datos: Actor, idempotency_key: str = Header(),
                       con=Depends(obtener_conexion)):
    return servicio.liberar_compromiso(con, compromiso_id, datos.actor_id, idempotency_key)


@app.post("/compromisos/{compromiso_id}/cancelacion")
def cancelar_compromiso(compromiso_id: int, datos: Actor, idempotency_key: str = Header(),
                        con=Depends(obtener_conexion)):
    return servicio.cancelar_compromiso(con, compromiso_id, datos.actor_id, idempotency_key)
