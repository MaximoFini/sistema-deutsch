# Prueba interna completa, punta a punta (DDEV-57)

Guion para que las personas de Deutsch prueben el sistema nuevo **antes de abrir la tienda mayorista**. Se prueba con datos de ensayo: nada de lo que hagas acá toca clientes, pedidos ni stock reales, no sale ningún email de verdad y no se escribe nada en Mercado Libre ni en Tiendanube.

Cada persona tiene su bloque. Tildás cada paso con ✔ (salió como decía) o ✘ (no salió) y, en «Qué vi», anotás lo que viste en pantalla. Si algo sale mal, mirá el apartado **Cómo anotar un error**.

## Antes de empezar (lo hace Kei, una sola vez)

La prueba se hace en una base **de ensayo**, nunca en la de producción. Para armar los datos:

```bash
cd sistema-deutsch
uv run python manage.py seed_demo_launch --yes
```

El comando:

- **se niega a correr en producción** (si `ENVIRONMENT_NAME` es `prod` o `production`) y siempre pide `--yes`;
- crea productos que empiezan con **ENSAYO** (SKU `ENS-…`) con 60 unidades de stock cada uno, 3 clientes mayoristas de ensayo, 1 vendedor de ensayo y pedidos de Mercado Libre, Tiendanube y mayoristas en distintos estados;
- **imprime en la consola, una sola vez, las contraseñas de prueba** (se generan al azar y no se guardan en ningún archivo): anotalas y pasáselas a cada persona por un medio privado, nunca por un chat de grupo ni por Plane;
- se puede correr de nuevo sin duplicar nada (si ya existen, conservan su contraseña; con `--nuevas-claves` se generan otras);
- no manda emails ni toca los canales (los pedidos de ML y Tiendanube del ensayo son solo filas del sistema, sin vínculo con las cuentas reales).

Para que tampoco salga ningún email de invitación por error: dejá `STORE_EMAILS_ENABLED` apagado (sin SMTP configurado) y, para probar el envío de invitaciones, prendé `STORE_EMAIL_DRY_RUN=true` (modo ensayo: el sistema anota qué mandaría y no manda nada). Los emails de ensayo terminan en `@ensayo.invalid`, un dominio que no existe.

Al terminar toda la prueba se borra todo lo de ensayo (y solo eso) con:

```bash
uv run python manage.py seed_demo_launch --yes --limpiar
```

Nunca toca datos reales ni pedidos históricos. Si algún usuario de ensayo figura en la auditoría (que no se puede borrar), queda desactivado y sin contraseña.

### Qué datos de ensayo hay

| Qué | Detalle |
|---|---|
| Productos | ENSAYO Malla Entrenamiento (talles S y M, azul y negro), ENSAYO Buzo Canguro, ENSAYO Gorra Silicona. Precio mayorista $ 10.000 neto (gorra incluida) y 60 de stock por variante. |
| Clientes mayoristas | **ENSAYO Natatorio Uno SRL** (sin cuenta corriente), **ENSAYO Club Dos SA** (con cuenta corriente) y **ENSAYO Pileta Tres SRL** (sin contraseña: para probar la invitación). Todos con email `…@ensayo.invalid`. |
| Vendedor | `vendedor@ensayo.invalid` (rol Vendedor). |
| Mercado Libre | Flex 1 (nuevo, **vence en 1 hora**), Flex 2 (en preparación, vence mañana), Full 1 (lo despacha ML) y Flex 3 (ya entregado, para probar una devolución). |
| Tiendanube | Envío Nube pagado, retiro en el local pagado y retiro con transferencia sin pagar. |
| Mayorista | 2 de Uno con transferencia (uno sin pagar, otro con el pago ya confirmado), 1 de Uno en efectivo para retirar y 1 de Dos en cuenta corriente. |

Los usuarios internos (Maico, Joaquín, Sergio, ventas) entran con sus propios usuarios del panel. Si alguno todavía no tiene uno, que pruebe desde el usuario de otra persona del mismo rol y que lo anote.

> **Importante:** el mínimo de compra de la tienda mayorista es $ 300.000. Para probar la compra como cliente hay que llegar a ese monto (30 unidades de $ 10.000) o bajar el mínimo en *Mayoristas → Configuración* durante la prueba (y volver a ponerlo después). El vendedor, comprando «en nombre del cliente», no tiene mínimo.

## Qué está pendiente de un tercero

Estos casos **no se pueden cerrar** hasta que existan Contabilium, Mercado Libre, ARCA o el servidor. En el guion aparecen marcados **«pendiente de tercero»**: no los tildes ni los cuentes como fallas.

| Caso | Por qué queda pendiente | Quién lo destraba |
|---|---|---|
| Pedido facturado y anulado **en Contabilium** | El sistema solo anota «Facturado en Contabilium»; la factura y la anulación (y el CAE de ARCA) se hacen en Contabilium. | Contabilium / ARCA / Joaquín |
| Edición masiva de publicaciones de Mercado Libre | Todavía no está construida: espera el spike DDEV-23 (qué campos pisa Contabilium). | Contabilium + Kei |
| Envío Nube **real** (etiqueta, retiro del correo, aviso de «despachado» a Tiendanube) | Los pedidos de ensayo no existen en la tienda real; el aviso a Tiendanube solo se puede ver con la app conectada. | App de Tiendanube + dueño de la cuenta |
| Etiqueta de Mercado Libre real, plazo real de Flex y reclamos reales | Con datos de ensayo no hay un pedido real de ML detrás. | App de Mercado Libre + dueño de la cuenta |
| Impresora térmica (etiqueta 10×15 y hoja de picking en papel) | Hace falta la impresora y la etiqueta reales. | Depósito con la impresora |
| Emails que llegan de verdad (registro, pago, despacho, invitación) | Sin servidor ni SMTP no sale ninguno. En el ensayo se ve la cola, no la bandeja de entrada. | Servidor + SMTP (DDEV-7) |

## Cómo anotar un error

Anotá un error por vez. Que alguien que no estaba ahí pueda repetirlo. Cada error lleva:

1. **Qué pantalla:** el nombre del menú y el título (por ejemplo: «Despacho», «Mayoristas → Invitaciones», «Mi cuenta» de la tienda). Si podés, copiá la dirección de arriba del navegador.
2. **Qué hiciste:** los pasos, en orden (por ejemplo: «Entré como Sergio, armé una tanda con 2 pedidos, toqué Marcar como Listo»).
3. **Qué esperabas** y **qué pasó** (copiá el mensaje de error tal cual).
4. **Captura de pantalla** de lo que viste, con el mensaje completo.
5. **Quién sos y la hora aproximada** (con eso Kei lo busca en la auditoría).
6. **El número del paso** del guion y de qué caso es (por ejemplo: «Sergio, paso 4»).

Mandáselo a Kei por el canal acordado. Kei lo carga en Plane con su ticket y avisa cuando está arreglado, para repetir ese paso.

---

## Bloque 1 · Maico (Administrador): clientes, pagos y facturación

Entrás con tu usuario del panel (rol Administrador).

### Caso A · Registro y aprobación de un cliente mayorista nuevo

| # | Qué hacés | Qué tiene que pasar | ✔/✘ | Qué vi |
|---|---|---|---|---|
| 1 | Abrí la tienda (`/mayorista/`) en una ventana privada y tocá **Registrarme**. Cargá una razón social inventada y un CUIT válido (podés usar `30-71234567-1`) con un email que termine en `@ensayo.invalid`. | Aparece «Te avisamos por email cuando aprobemos tu cuenta». Con un CUIT mal escrito avisa que no es válido. | | |
| 2 | En el panel, entrá a **Avisos**. | Hay un aviso «Nuevo registro mayorista». | | |
| 3 | **Mayoristas** → abrí el registro nuevo → **Aprobar**. | Queda aprobado y vinculado a un cliente nuevo. | | |
| 4 | En la ventana privada, ingresá con ese cliente. | Entra a la tienda y ve el catálogo con precios mayoristas (sin IVA, con el IVA aparte). | | |

### Caso B · Pedido mayorista por transferencia: comprobante, pago y vencimiento

| # | Qué hacés | Qué tiene que pasar | ✔/✘ | Qué vi |
|---|---|---|---|---|
| 1 | Entrá a la tienda con `cliente.uno@ensayo.invalid` (contraseña de la consola). Poné 30 o más unidades en el carrito, tocá **Confirmar** y elegí **Transferencia** y un expreso. | Aparece «Pedido confirmado» con los datos para transferir y el aviso de que hay que subir el comprobante. Si ya cargaste los datos bancarios, aparecen; si no, dice que se los pasan por email o WhatsApp. | | |
| 2 | En «Mi cuenta» de la tienda, subí un archivo cualquiera (foto o PDF) como **comprobante**. | Dice «Recibimos el comprobante». Un archivo que no es foto ni PDF se rechaza con un mensaje claro. | | |
| 3 | En el panel: **Pedidos** → el pedido nuevo de Uno → **Confirmar pago**. | El pedido pasa de «Esperando pago» a «Nuevo». Depósito lo ve en **Preparar**. El stock sigue **reservado**. | | |
| 4 | Tomá el otro pedido de Uno que sigue «Esperando pago» (el de ensayo). Anotá hasta cuándo vence (en la ficha del pedido). | Se ve la fecha de vencimiento (3 días por defecto). | | |
| 5 | Pedile a Kei que corra «vencer pedidos» (o esperá a que pase el plazo en una prueba larga). | El pedido sin pago queda **Cancelado**, el stock reservado se libera y el cliente recibe el aviso «venció». Un día antes sale un solo recordatorio. | | |
| 6 | Si el pedido ya tenía comprobante subido, repetí el paso 5. | **No** se cancela solo: avisa «venció con comprobante» para que lo mires. | | |

### Caso C · Efectivo y cuenta corriente

| # | Qué hacés | Qué tiene que pasar | ✔/✘ | Qué vi |
|---|---|---|---|---|
| 1 | Entrá a la tienda con `cliente.uno@ensayo.invalid`. En «Confirmar», mirá los medios de pago. | **No** ofrece cuenta corriente. El efectivo aparece solo si elegís retiro en el local. | | |
| 2 | En el panel, **Mayoristas** → ENSAYO Natatorio Uno → **Habilitar cuenta corriente**. Volvé a la tienda. | Ahora ofrece «Cuenta corriente». | | |
| 3 | Comprá con **efectivo y retiro en el local**. | El pedido entra directo en «Nuevo» (no espera pago) y dice que se paga al retirar. | | |
| 4 | Comprá con **cuenta corriente**. | Entra directo en «Nuevo», sin vencimiento. | | |
| 5 | Mirá **Avisos** pasadas 24 horas (o pedile a Kei que adelante la hora): para el efectivo hay avisos «sin cobrar» y «sin facturar»; para la cuenta corriente **solo «sin facturar»**. | La cuenta corriente **no** genera «sin cobrar». | | |

### Caso D · Facturado en Contabilium y liberación de la reserva

| # | Qué hacés | Qué tiene que pasar | ✔/✘ | Qué vi |
|---|---|---|---|---|
| 1 | Abrí un pedido mayorista ya despachado → **Facturación** → tildá «Facturado», poné el número `A-0001-00001234` y guardá. | Queda «Facturado». El stock **reservado** de ese pedido vuelve a 0 (el físico no cambia: lo baja Contabilium). | | |
| 2 | Guardá de nuevo con otro número. | No se libera una segunda vez. | | |
| 3 | Mirá **Reportes → Mayorista** → «Sin facturar». | El pedido ya no figura como sin facturar. | | |
| 4 | **Pendiente de tercero:** hacer la factura real y anular un pedido ya facturado en Contabilium. | Se hace en Contabilium; después se marca la corrección en el sistema («Corregir en Contabilium»). | pendiente de tercero | |

### Caso E · Invitación de un cliente mayorista (con el envío en modo ensayo)

Usá a **ENSAYO Pileta Tres SRL**, que viene sin contraseña. Con `STORE_EMAIL_DRY_RUN=true`.

| # | Qué hacés | Qué tiene que pasar | ✔/✘ | Qué vi |
|---|---|---|---|---|
| 1 | **Mayoristas → Invitaciones**. Mirá los totales y el botón **Enviar invitaciones**. | El botón está deshabilitado y explica que el envío todavía no se habilitó. | | |
| 2 | Tocá **Habilitar envío** y confirmá. | Dice «Envío de invitaciones habilitado. Todavía no se mandó ninguna.» | | |
| 3 | Tocá **Enviar invitaciones** (con el modo ensayo prendido). | Dice «Ensayo: se mandarían N invitaciones. No se envió ni se encoló nada.» La invitación sigue «Sin enviar». | | |
| 4 | Pedile a Kei que apague el modo ensayo (solo en esta base de ensayo, con el correo simulado) y repetí el paso 3. | La invitación queda en la cola de emails y pasa a «Enviada». En *Mayoristas → Emails* se ve en la cola sin el enlace personal. | | |
| 5 | Kei te pasa el enlace del email simulado. Abrilo en una ventana privada y elegí una contraseña. | Pide la contraseña, los términos y te deja adentro. Una contraseña débil se rechaza. | | |
| 6 | Volvé a abrir el mismo enlace. | Dice que el enlace ya se usó o venció y ofrece pedir otro. Es la misma pantalla que para un enlace inventado. | | |
| 7 | En *Invitaciones*, mirá el estado de Tres. | Figura como «Entró». | | |

---

## Bloque 2 · Joaquín (Contabilium y facturación)

Este bloque es para quien lleva Contabilium. Entra con su usuario Administrador.

| # | Qué hacés | Qué tiene que pasar | ✔/✘ | Qué vi |
|---|---|---|---|---|
| 1 | **Pedidos** → un pedido mayorista despachado → mirá «Facturación». Marcalo «Facturado» con el número de comprobante. | Queda anotado el número y la fecha. El stock reservado se libera. | | |
| 2 | **Devoluciones**: abrí el pedido de ML «Flex 3 (entregado)» → **Devolución** → recibida (ver Bloque 3, caso F). Después, en «Recibidas», tocá **Marcar ajustado en Contabilium**. | Queda marcada como ajustada. | | |
| 3 | Mirá **Avisos**. | Hay un aviso «ajustar stock en Contabilium» por cada devolución recibida, y ninguno repetido. | | |
| 4 | Con un faltante resuelto sobre un pedido **ya facturado** (Bloque 3, caso E): mirá la ficha. | Muestra «Corregir en Contabilium» y hay un aviso para administración. | | |
| 5 | **Pendiente de tercero:** emitir la factura real en Contabilium, ver el CAE de ARCA y anular una factura. | Se hace en Contabilium. El sistema no factura. | pendiente de tercero | |
| 6 | **Pendiente de tercero:** confirmar que el stock y los precios de Contabilium llegan a Tiendanube y a ML después de un cambio. | Lo hace la integración de Contabilium con los canales, no este sistema. | pendiente de tercero | |

---

## Bloque 3 · Sergio (Depósito): preparar, despachar, faltantes y devoluciones

Entrás con un usuario de rol Depósito.

### Caso A · Preparar y despachar un pedido mayorista (transferencia)

| # | Qué hacés | Qué tiene que pasar | ✔/✘ | Qué vi |
|---|---|---|---|---|
| 1 | **Preparar**. | Aparecen los pedidos «Nuevos», incluido el mayorista con el pago confirmado. **No** aparece el que sigue «Esperando pago» ni el Full de ML ni el histórico. | | |
| 2 | Marcá el pedido mayorista y tocá **Armar tanda**. | Se arma la tanda y el pedido pasa a «En preparación». | | |
| 3 | En la tanda, abrí la **hoja de picking (PDF)**. | Se descarga el PDF con los productos juntos y las casillas para tildar. | | |
| 4 | **Despacho** → «En preparación» → **Marcar como Listo**. Después «Listo» → poné el código de seguimiento → **Despachar**. | El pedido pasa a «Listo» y luego a «Despachado» con el seguimiento anotado. El cliente recibe el aviso de despacho. | | |

### Caso B · Efectivo: no se entrega sin cobrar

| # | Qué hacés | Qué tiene que pasar | ✔/✘ | Qué vi |
|---|---|---|---|---|
| 1 | Tomá el pedido mayorista en efectivo (retiro). Armá la tanda, marcalo Listo y **Despachar / Listo para retirar**. | Queda «Listo para retirar» y el cliente recibe el aviso. | | |
| 2 | En **Despacho**, mirá la columna del pedido. | Dice «Cobrar $ … en efectivo» con una casilla «Cobré». | | |
| 3 | Tocá **Entregado** sin tildar «Cobré». | **No** se entrega: avisa que falta cobrar. | | |
| 4 | Tildá «Cobré» y tocá **Entregado**. | Pasa a «Entregado» y el pago queda confirmado. | | |

### Caso C · Mercado Libre Flex y Full

| # | Qué hacés | Qué tiene que pasar | ✔/✘ | Qué vi |
|---|---|---|---|---|
| 1 | **Preparar** y mirá los pedidos de ML. | Aparecen los Flex. El **Full 1** no aparece (lo despacha Mercado Libre). | | |
| 2 | Armá una tanda con **ENSAYO ML Flex 1**. | Pasa a «En preparación». Si intentás meter el Full, dice que es Full y lo deja afuera. | | |
| 3 | Mirá **Avisos** después de unos minutos (el vigilante corre cada 5 minutos). | Hay un aviso «despachar antes de las HH:MM» para Flex 1 (vence en 1 hora). **No** hay uno para Flex 2 (vence mañana) ni para el Full. | | |
| 4 | Marcá Flex 1 como Listo y Despachar. | Queda «Despachado». No se escribe nada en Mercado Libre. | | |
| 5 | **Pendiente de tercero:** imprimir la etiqueta real 10×15 de Mercado Libre de un Flex y ver el plazo real. | Con la app de ML conectada y un pedido real. | pendiente de tercero | |

### Caso D · Tiendanube: Envío Nube y retiro en el local

| # | Qué hacés | Qué tiene que pasar | ✔/✘ | Qué vi |
|---|---|---|---|---|
| 1 | **Preparar** → pedidos de Tiendanube. | Aparecen el Envío Nube y el retiro pagados. **No** aparece el retiro con transferencia sin pagar. | | |
| 2 | Armá la tanda con el Envío Nube, marcalo Listo y Despachar. | Pasa a «Despachado». (Con Tiendanube real, el sistema avisa «empaquetado» y «despachado» a Tiendanube y **solo eso**: nunca toca productos, stock ni precios.) | | |
| 3 | Armá la tanda con el retiro, marcalo Listo y **Despachar / Listo para retirar**. | Queda «Listo para retirar» (no «Despachado»). Después **Entregado**. | | |
| 4 | **Pendiente de tercero:** Envío Nube real (etiqueta del correo, aviso a Tiendanube). | Con la app de Tiendanube conectada y un pedido real. | pendiente de tercero | |
| 5 | **Pendiente de tercero:** imprimir en la impresora térmica real. | Con la impresora conectada. | pendiente de tercero | |

### Caso E · Faltante en un pedido mayorista

| # | Qué hacés | Qué tiene que pasar | ✔/✘ | Qué vi |
|---|---|---|---|---|
| 1 | Tomá un pedido mayorista «En preparación» (armá la tanda si hace falta). Tocá **Marcar faltante** y marcá que falta 1 unidad de una línea. | El pedido pasa a «Esperando cliente». Administración recibe un aviso y el cliente un email de consulta. El stock sigue reservado. | | |
| 2 | Mirá las opciones del pedido. | Solo se puede cancelar o resolver el faltante: no se puede saltear con «Pasar a». | | |
| 3 | Pedile a Maico que lo resuelva con **saldo a favor** (ver Bloque 4, caso B). | El pedido vuelve a «En preparación» con el total más chico y se libera la diferencia de reserva. | | |

### Caso F · Devolución recibida

| # | Qué hacés | Qué tiene que pasar | ✔/✘ | Qué vi |
|---|---|---|---|---|
| 1 | **Pedidos** → **ENSAYO ML Flex 3 (entregado)** → **Cargar devolución esperada**. | Queda una devolución «esperada», una sola aunque toques dos veces. | | |
| 2 | **Devoluciones** → recibir → poné la cantidad que llegó y si sirve para reventa o está dañada. | Queda «Recibida». Se avisa a administración para ajustar el stock en Contabilium. **El sistema no cambia el stock solo.** | | |
| 3 | Probá poner más cantidad de la esperada. | Se rechaza con un mensaje claro. | | |

---

## Bloque 4 · Ventas (rol Ventas)

Entrás con un usuario de rol Ventas.

### Caso A · Alertas de plazo y reclamos

| # | Qué hacés | Qué tiene que pasar | ✔/✘ | Qué vi |
|---|---|---|---|---|
| 1 | Mirá **Avisos**. | Ves los avisos de plazo de Flex, de «sin cobrar» y «sin facturar», y los de reclamos (si hay uno cargado). Cada aviso aparece **una sola vez**. | | |
| 2 | Abrí un aviso. | Te lleva al pedido o al reclamo correcto. | | |
| 3 | Buscá un pedido **histórico** (Pedidos → **Incluir históricos**). | No genera avisos, no se puede cambiar de estado ni aparece en Preparar. | | |
| 4 | **Pendiente de tercero:** reclamos y preguntas reales de Mercado Libre. | Con la app de ML conectada. | pendiente de tercero | |

### Caso B · Edición masiva de publicaciones

| # | Qué hacés | Qué tiene que pasar | ✔/✘ | Qué vi |
|---|---|---|---|---|
| 1 | **Edición masiva de publicaciones de ML.** | Todavía no existe. Hoy el enlace lleva a Mercado Libre. | pendiente de tercero | |
| 2 | Mirá **Catálogo** y **Stock y precios**. | Se ven stock y precio por canal en solo lectura: el sistema no escribe stock ni precios en los canales. | | |

---

## Bloque 5 · Un vendedor (rol Vendedor)

Entrá con `vendedor@ensayo.invalid` (contraseña de la consola).

| # | Qué hacés | Qué tiene que pasar | ✔/✘ | Qué vi |
|---|---|---|---|---|
| 1 | Entrá a la tienda mayorista. | Te pide elegir **en nombre de qué cliente** comprás. | | |
| 2 | Elegí ENSAYO Club Dos SA y armá un pedido chico (1 o 2 unidades) con **cuenta corriente**. | Te deja confirmarlo **sin el mínimo de compra**. Dice que lo cargaste vos en nombre del cliente. | | |
| 3 | Mirá los comprobantes de pago del pedido. | **No** los ves (solo administración). | | |
| 4 | Intentá entrar a **Mayoristas → Configuración** o a **Confirmar pago**. | Te dice que no tenés permiso. | | |
| 5 | Probá cancelar un pedido. | No podés: solo administración cancela. | | |

---

## Cierre de la prueba

Cuando todos terminaron:

1. Cada persona manda su tabla completa con los ✘ detallados (ver **Cómo anotar un error**).
2. Kei carga los errores en Plane y los arregla; se repiten solo los pasos que fallaron.
3. Los casos «pendiente de tercero» pasan a la lista de lanzamiento (`docs/runbooks/lanzamiento.md`) con su responsable.
4. Kei borra los datos de ensayo: `manage.py seed_demo_launch --yes --limpiar`.

## Qué cubre la prueba automática

La misma secuencia de pasos corre sola en cada cambio del código (`tests/test_punta_a_punta.py`), con Mercado Libre y Tiendanube simulados: mayorista (transferencia, vencimiento, efectivo, cuenta corriente, faltante, devolución), ML Flex y Full, Tiendanube con Envío Nube y retiro (verificando que solo se escribe el estado de envío), alertas (sin cobrar, sin facturar, plazos y reclamos, sin avisos de históricos), invitaciones y el propio comando de ensayo. Eso no reemplaza la prueba de las personas: las personas prueban lo que se ve, se entiende y se puede usar; la automática, que la lógica no se rompa.
