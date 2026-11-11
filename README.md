# Cuadre

Plata entre personas, sin perder un peso.

Reto técnico de practicantes 2027, HabiCapital. Hecho por Manuel Santiago Figueroa Gómez.

- Video de la demo: https://drive.google.com/file/d/1M52Of8WPQGRu-XiPhPFUIph33aveUps1/view
- GitHub: https://github.com/San-FG

## Qué es

Una billetera para que personas se muevan plata entre ellas. Tiene el núcleo que pide el reto (crear cuenta, cargar saldo simulado, transferir, consultar saldo y ver historial) y encima una sola cosa mía: **compromisos de pago con custodia**.

Un compromiso es un acuerdo entre dos personas: quién paga, a quién, cuánto, por qué y para cuándo. El que paga puede dejar la plata apartada en custodia. Mientras está ahí ya no es de él, pero todavía no es del otro. Después se libera al que cobra, o se cancela y vuelve al que pagó. La custodia dura 24 horas: si en ese tiempo no se liberó, el que pagó puede recuperar su plata.

## Cómo correrlo

Se necesita Python 3.12 y Node 24.

Linux o Mac:

```bash
git clone https://github.com/San-FG/reto-habicapital.git && cd reto-habicapital
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q                                  # 61 pruebas
.venv/bin/python -m uvicorn app.main:app --reload --port 8000  # backend
# en otra terminal:
cd frontend && npm ci && npx ng serve                          # http://localhost:4200
```

Windows (PowerShell):

```powershell
git clone https://github.com/San-FG/reto-habicapital.git; cd reto-habicapital
py -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
# en otra terminal:
cd frontend; npm ci; npx ng serve
```

El frontend se abre en `http://localhost:4200` (tiene que ser `localhost`, no `127.0.0.1`, porque el backend solo le permite ese origen). La API también se puede probar sola en `http://localhost:8000/docs`.

## Cómo está armado

| Carpeta | Qué hay |
|---|---|
| `app/db.py` | Las tablas y la función `transaccion()`, que es la que garantiza todo o nada |
| `app/servicio.py` | Todas las reglas de la plata |
| `app/main.py` | La API. Solo traduce HTTP a llamadas de `servicio.py`, no decide nada de plata |
| `tests/` | 61 pruebas |
| `frontend/` | La interfaz en Angular |

## 1. Las decisiones clave y por qué las tomé

**Python con FastAPI.** Python es el lenguaje en el que aprendí a programar y es el que mejor manejo. En la entrevista me van a pedir cambiar mi propio código en vivo, entonces preferí lo que domino sobre lo que suena más llamativo. Además es el backend que usa el equipo.

**SQLite, una base relacional.** Lo primero que tuve claro es que esto necesitaba una base relacional con transacciones, para que la persistencia y la confiabilidad de la plata no dependieran de mi código. Escogí SQLite porque no hay que instalar nada para correr el proyecto. Sé que no es lo que se usaría en producción y lo explico en el punto 4.

**Sin ORM, con SQL directo.** Quería que se viera exactamente qué instrucción toca la plata y dónde empieza y termina cada transacción.

**La plata se guarda en pesos enteros.** En Python `0.1 + 0.2` no da `0.3`. Con decimales flotantes se van perdiendo fracciones, y en un sistema de plata eso no puede pasar.

**Una sola función mueve plata entre cuentas.** Se llama `_mover()`. Las transferencias y los tres movimientos de custodia pasan por ahí. Si algo falla con la plata, hay un solo lugar donde buscar.

**Las escrituras van de a una.** En mi materia de infraestructura vi monitores y el problema de lectores y escritores, y mi primera idea fue un monitor por cuenta, para que transferencias entre cuentas distintas corrieran al tiempo. Al final escogí algo más simple: muchos lectores a la vez y un solo escritor para todo el sistema, que es lo que SQLite ya hace. Un monitor por cuenta obliga a cuidar el orden en que se toman para no caer en un deadlock (A le paga a B mientras B le paga a A), y además un monitor vive en la memoria de un proceso, no sirve si hay varios. Para el tamaño de este reto preferí lo simple y seguro.

**El extra: compromisos con custodia.** La cuenta dividida era lo más obvio, pero es el ejemplo que el mismo reto pone, así que no demostraba que yo hubiera visto algo distinto. Me gustaron dos ideas: dejar plata en custodia y llevar un historial de si la gente cumple sus pagos. Como el reto pide una sola cosa bien hecha, las junté en un solo concepto, el compromiso, y construí completa la parte de custodia.

**La custodia dura 24 horas.** Durante ese tiempo el que paga no puede arrepentirse solo: únicamente el que cobra puede cancelar y devolver la plata. Si el que paga pudiera sacarla cuando quisiera, la custodia no le garantizaría nada al otro. Pasadas las 24 horas, si no se liberó, el que pagó puede recuperarla. Lo decidí así porque dejar plata congelada para siempre me pareció peor que un plazo que los dos conocen desde el principio.

**La devolución no es automática.** Cuando se cumple el plazo, la plata no se mueve sola: la pide el que pagó con un botón. No quise que el sistema moviera plata sin que alguien lo pidiera.

## 2. Cómo sé que mi sistema no pierde un peso

La regla que revisa todo es esta: **la suma de todos los saldos, incluida la custodia, tiene que ser igual a la suma de todo lo que se ha cargado.** Una transferencia solo cambia de dueño la plata, nunca cambia el total.

Esto es lo que puede salir mal, cómo lo protejo y la prueba que lo demuestra:

| Qué puede salir mal | Cómo lo protejo | Prueba |
|---|---|---|
| El servidor se cae después de restarle a uno y antes de sumarle al otro | Los dos pasos van en una transacción: si algo falla, se deshace todo | `test_si_falla_a_la_mitad_se_deshace_todo` |
| Dos transferencias al mismo tiempo leen el mismo saldo y las dos pasan | La transacción toma el turno de escritura antes de leer (`BEGIN IMMEDIATE`) y el saldo se revisa adentro | `test_veinte_transferencias_simultaneas_solo_una_pasa` y la misma por HTTP |
| El código falla y deja un saldo negativo | La base tiene la regla `saldo >= 0` y rechaza el cambio | `test_la_base_rechaza_un_saldo_negativo_aunque_el_codigo_falle` |
| Doble clic o reintento de red cobra dos veces | Cada operación lleva una clave única; si llega repetida, devuelve el resultado original sin mover plata | `test_misma_clave_dos_veces_mueve_la_plata_una_sola_vez` |
| Errores de redondeo | Pesos enteros; la API rechaza `10.5` | `test_montos_invalidos_se_rechazan` |
| Montos en cero o negativos, pagarse a uno mismo, cuentas que no existen | Validaciones en el servicio y reglas en la base | `test_no_se_puede_transferir_a_uno_mismo`, `test_cuenta_inexistente` |
| Alguien edita o borra el historial | Dos triggers en la base lo impiden: los movimientos solo se agregan | `test_los_movimientos_no_se_pueden_editar_ni_borrar` |
| La plata en custodia queda sin dueño | El estado del compromiso y el movimiento de plata cambian en la misma transacción | `test_si_falla_a_la_mitad_de_respaldar_se_deshace_todo` |
| La plata queda congelada en custodia si nadie actúa | Plazo de 24 horas: después, el que pagó puede recuperarla | `test_despues_de_24_horas_el_pagador_recupera_la_plata` |
| Alguien saca plata de la custodia por fuera de un compromiso | Cargar y transferir rechazan la cuenta de custodia | `test_no_se_puede_cargar_ni_transferir_con_la_custodia` |

Además hay una auditoría (`GET /auditoria`, y el sello "La plata cuadra" en la pantalla) que revisa tres cosas: que los saldos sumen lo cargado, que el saldo de cada cuenta coincida con lo que dice su historial, y que la plata en custodia sea igual a la suma de los compromisos respaldados.

La evidencia que tengo:

- 61 pruebas automáticas que pasan. Para probar el plazo de 24 horas sin esperar un día, las pruebas simulan el paso del tiempo.
- Dos pruebas que hacen cientos de operaciones al azar y al final revisan que la plata cuadre.
- Pruebas con 20 hilos al tiempo, tanto llamando las funciones como por HTTP.
- El recorrido a mano en el navegador: cargar, transferir, respaldar, liberar y cancelar, mirando que el total nunca cambiara.

Lo que esa evidencia **no** demuestra: no lo probé con varios procesos del servidor al tiempo, ni apagando la máquina de verdad a mitad de una escritura. Confío en SQLite para eso, pero no lo comprobé yo.

## 3. Qué dejé fuera y por qué

- **Autenticación.** No hay login. En la pantalla hay un selector "Soy:" y la API recibe un `actor_id` y le cree. Lo dejé fuera porque el reto era sobre no perder plata, no sobre identidad. Por eso mismo cualquiera puede ver el historial de cualquier cuenta.
- **Devolución automática y plazo acordado.** El caso de la plata congelada lo resolví con el plazo de 24 horas, pero la devolución la tiene que pedir el que pagó, y el plazo es fijo. Quedó por fuera que se devuelva sola y que cada compromiso pueda acordar su propio plazo.
- **Disputas.** Si el que cobra dice que cumplió y el que paga no libera, a las 24 horas el que paga puede recuperar la plata. Resolver eso bien necesita un tercero que decida, y eso es otro sistema.
- **El resumen de cumplimiento.** La idea era mostrar algo como "12 de 12 pagos a tiempo". Los compromisos ya guardan la fecha de vencimiento y la de cierre, pero no alcancé a construir el resumen.
- **La cuenta dividida.** La descarté a propósito, lo explico en el punto 1.
- **Sacar plata del sistema.** Solo se puede cargar. No hay retiros.
- **Idempotencia al crear cuentas y compromisos.** Un doble clic puede crear dos. No mueve plata, por eso lo dejé.
- **Pruebas automáticas del frontend.** El frontend lo probé a mano.

## 4. Qué haría distinto con más tiempo

- Pasaría a PostgreSQL y bloquearía solo las cuentas que participan en cada transferencia, tomándolas siempre en el mismo orden para evitar deadlock. Así dos transferencias que no tienen nada que ver no se hacen esperar.
- Pondría autenticación de verdad, para que el actor salga de una sesión y no del cuerpo de la petición.
- Haría que la auditoría revise la custodia compromiso por compromiso, no solo el total.
- Haría que el plazo de custodia se acuerde en cada compromiso y que la devolución sea automática, con un proceso bien probado. Y pensaría cómo resolver las disputas.
- Construiría el resumen de cumplimiento.
- Arreglaría una advertencia que sale al correr las pruebas, de una librería de pruebas que va a cambiar de dependencia. No afecta el sistema, pero es deuda.
- Habría empezado antes. El primer día no avancé y eso me dejó sin espacio para estudiar el código con calma antes de entregar.

## 5. Qué NO sé

- No sé cómo resuelven las disputas los sistemas de custodia reales cuando las dos partes no se ponen de acuerdo.
- No sé cómo se comporta esto con mucha carga. Nunca medí cuántas transferencias por segundo aguanta con un solo escritor.
- Sé qué hace `BEGIN IMMEDIATE` y por qué lo uso, pero no sé cómo implementa SQLite sus bloqueos por dentro ni cómo funciona el modo WAL en detalle.
- No sé cómo se maneja la plata en un sistema repartido en varios servicios, donde ya no hay una sola base de datos que haga la transacción.
- No conozco la regulación que aplica en Colombia para un producto que guarda plata de otras personas.
- Todavía no puedo explicar de memoria cada función del backend. El núcleo lo generó la IA y lo estoy estudiando para poder defenderlo y cambiarlo en vivo.
- No sé si 24 horas es el plazo correcto. Lo escogí por simple, no porque lo haya validado con usuarios.

## 6. Los supuestos que hice

- La plata es en pesos colombianos y no se manejan centavos.
- Cargar saldo es simulado: la plata aparece, no viene de una pasarela.
- Quien usa el sistema dice quién es y se le cree.
- Corre un solo servidor con una sola base de datos.
- Un compromiso es entre dos personas y por un solo pago.
- La fecha de vencimiento es informativa: no pasa nada automático cuando llega, y se pueden poner fechas pasadas.
- El plazo de custodia es fijo, 24 horas, y la hora que cuenta es la del servidor.
- El que cobra confía en que el que paga va a liberar cuando se cumpla el acuerdo.

## 7. Cómo usé IA

Usé IA en todo el proyecto. No escribí la mayor parte del código a mano.

**Qué herramientas y para qué**

- **Claude, en chat.** Para entender el reto, discutir el diseño antes de escribir código y sacar la lista de qué podía hacer perder plata. También generó el núcleo (cuentas, cargas, transferencias, historial y auditoría) con sus pruebas, y probó la aplicación en mi navegador.
- **Claude Code, en VS Code.** Para construir el extra y la primera versión del frontend, a partir de instrucciones detalladas que definíamos antes en el chat.
- **Codex.** Para el rediseño visual del frontend.

**Cuál fue la dinámica**

Primero diseño y después código. Antes de generar nada, la IA me hacía preguntas y yo tenía que responder: qué pasa si el servidor se cae a mitad de una transferencia, qué pasa si llegan dos al tiempo. En varias me equivoqué o me faltó precisión. Por ejemplo, dije que las propiedades que necesitaba eran las del CRUD cuando eran las ACID, y propuse controlar la concurrencia por dispositivo cuando el control va sobre la cuenta, dentro de la base de datos.

**Qué decidía yo**

- El lenguaje y que la base fuera relacional.
- El extra. Rechacé la primera propuesta (la cuenta dividida) y pedí algo que mostrara más valor.
- Que el frontend no se quedara como estaba. La primera versión funcionaba pero no me gustó, y pedí rehacer la parte visual.
- Qué aceptar y qué no de lo que la IA proponía.

**Veces en que la IA se equivocó**

*El error que casi se va en la entrega.* El núcleo que generó la IA tenía una prueba de 20 transferencias simultáneas y pasaba. Pero esa prueba llamaba las funciones directamente, no pasaba por HTTP. Cuando se conectó el frontend y se probó con peticiones reales al mismo tiempo, 39 de 40 respondían error 500. La causa: el servidor abría la conexión a la base en un hilo y la usaba en otro, y SQLite por defecto no lo permite. No se perdía plata, las peticiones fallaban antes de mover nada, pero el sistema no servía con más de una persona. Se corrigió con un parámetro en la conexión y se agregó una prueba de concurrencia por HTTP, que era la que faltaba. Lo que me llevo: que las pruebas pasen no significa que el sistema funcione, hay que mirar qué es lo que están probando.

Me enteré porque Claude Code, al probar el frontend contra el backend, me mostró que sin ese cambio fallaban 39 de 40 peticiones y me pidió aprobar la modificación en la conexión antes de hacerla.

*Una solución que primero rechacé.* Claude Code encontró el hueco de la plata congelada: si el que paga no libera y el que cobra no cancela, la plata se queda en custodia para siempre. Propuso devolverla al vencer un plazo. Al principio la rechacé, porque al que paga le bastaría con esperar para recuperar su plata. El último día la retomé por decisión mía, con cambios: un plazo fijo de 24 horas que los dos ven en la tarjeta, y la devolución no es automática. Sé que 24 horas es poco para algunos acuerdos y que le quita algo de protección al que cobra. Me pareció mejor eso que plata que nadie puede usar.

*Un error más pequeño.* Probando a mano, la IA asumió que la cuenta de custodia era la número 1 y le transfirió plata de prueba a otra cuenta. No pasó nada grave, pero muestra que también asume cosas sin revisar.

**Lo que tengo que decir con honestidad**

Entregar rápido con IA tuvo un costo: hay partes del código que todavía estoy estudiando para poder defenderlas. Este README también lo armé con ayuda de IA, a partir de las decisiones que tomé durante el proyecto, y lo revisé y corregí yo.

## 8. Qué aprendí

- La diferencia entre un sistema que anota plata y uno que la guarda. Al principio pensé que el reto era un registro de gastos; no lo era, y por eso la regla de no perder un peso pesa tanto.
- Atomicidad: que varios pasos se traten como uno solo, todo o nada.
- Que la atomicidad no resuelve la concurrencia. Son dos problemas distintos y cada uno tiene su protección.
- Idempotencia. No conocía el concepto y ahora me parece obligatorio en cualquier cosa que cobre.
- Que lo que vi en clase sobre monitores y lectores y escritores sí aplica a un problema real.
- Poner reglas en la base de datos como segunda barrera, por si el código falla.
- Que una prueba que pasa puede no estar probando lo que uno cree.
- A darle instrucciones precisas a la IA y a pedirle que reporte en vez de arreglar por su cuenta cuando falta poco para entregar.