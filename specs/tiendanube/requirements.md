# Requirements: Integración Tiendanube (módulo M1)

**Status:** Approved (2026-11-14)
**Last updated:** 2026-11-14
**Tickets:** DDEV-10 a DDEV-14 (M1-01 … M1-05)
**Depende de:** M0 (framework de integraciones, modelo de datos), ya hecho.

## Summary

Conectar el sistema con la tienda de Deutsch en Tiendanube (tienda 8434848). El sistema lee el catálogo (productos, variantes, stock, precios, fotos y descripciones) y recibe todos los pedidos sin perder ni duplicar ninguno. Cuando el depósito despacha, el sistema marca el pedido en Tiendanube para que el cliente reciba el aviso. Nunca escribe stock, precios ni productos en Tiendanube (regla de oro).

## Goals

- Que cada pedido de Tiendanube aparezca en el sistema en menos de 1 minuto con el servidor desplegado, y que ninguno se pierda aunque falle un webhook.
- Tener en el sistema el catálogo completo de Tiendanube (≈282 productos / 719 variantes) y mantenerlo al día. Ese contenido lo reusa después la tienda mayorista.
- Que el depósito marque empaquetado, enviado o entregado desde el sistema, y que Tiendanube avise al cliente.
- Saber si la etiqueta de Envío Nube se puede obtener por API (spike).

## Non-goals

- Escribir stock, precios, productos o categorías en Tiendanube. Lo prohíbe la regla de oro: el adaptador trae la escritura construida pero bloqueada por el interruptor.
- Pantallas de pedidos y de preparación. Son M4 y M5; en M1 solo se ven los datos en el panel de integraciones y en el admin de soporte.
- Catálogo maestro unificado TN + ML. Es M3; en M1 los productos de TN se cargan en el modelo de catálogo y quedan vinculados por ID externo.
- Importar el historial de 12 meses. Es M9-01; en M1 se importan solo los últimos 30 días, para probar.
- Facturación, cuentas de clientes y la tienda mayorista.

## User stories

### US-1: Conectar la tienda (DDEV-10)

Como administrador de Kei, quiero instalar una app propia del sistema en la tienda de Deutsch, para que el sistema tenga acceso solo a lo que necesita.

**Acceptance criteria:**

- THE APP SHALL pedir permisos mínimos: pedidos (lectura y escritura), productos (lectura) y clientes (lectura). No SHALL pedir permisos de escritura de productos.
- WHEN el administrador completa la instalación (OAuth) THE SYSTEM SHALL guardar el token cifrado y el ID de la tienda, y SHALL registrar los webhooks necesarios.
- IF ya hay webhooks registrados THEN THE SYSTEM SHALL no duplicarlos: reinstalar es seguro.
- WHEN Tiendanube avisa que la app se desinstaló THE SYSTEM SHALL marcar el canal como desconectado y emitir una alerta.
- THE SYSTEM SHALL atender los webhooks obligatorios de privacidad de Tiendanube (borrado de datos de la tienda o de un cliente, y pedido de datos de un cliente), anonimizando los datos personales del cliente cuando se pidan.
- THE SYSTEM SHALL verificar la firma (HMAC) de cada webhook de Tiendanube y SHALL rechazar los que no la tengan válida.

### US-2: Catálogo de Tiendanube (DDEV-11)

Como Deutsch, quiero que el sistema tenga el catálogo de Tiendanube al día, para usarlo en pedidos, preparación y la tienda mayorista.

**Acceptance criteria:**

- WHEN se corre la importación inicial THE SYSTEM SHALL traer todos los productos y variantes, con SKU, código de barras, atributos (talle, color), peso, medidas, precio, precio promocional, stock, fotos, descripción y categorías, respetando el límite de velocidad de la API.
- THE SYSTEM SHALL vincular cada producto y variante con su ID de Tiendanube (`ExternalRef`) y SHALL reconocerlos en importaciones siguientes, sin duplicarlos.
- WHEN Tiendanube avisa que se creó, modificó o borró un producto THE SYSTEM SHALL actualizarlo. Un producto borrado se marca inactivo, no se borra.
- THE SYSTEM SHALL correr una conciliación diaria del catálogo completo, para recuperar cambios que no llegaron por webhook.
- THE SYSTEM SHALL registrar el stock de Tiendanube como movimiento de sincronización en el stock del sistema y el precio como precio vigente de la lista MINORISTA, sin escribir nunca en Tiendanube.
- IF una variante no tiene SKU THEN THE SYSTEM SHALL importarla igual (vinculada por ID) y SHALL marcarla para revisión en el informe de calidad de datos (M3-03).

### US-3: Pedidos de Tiendanube (DDEV-12)

Como Deutsch, quiero que cada pedido de Tiendanube entre solo al sistema, para centralizar todo en un lugar.

**Acceptance criteria:**

- WHEN Tiendanube avisa de un pedido creado, pagado, empaquetado, enviado, cancelado o editado THE SYSTEM SHALL traer el pedido completo y crearlo o actualizarlo como `SalesDocument` del canal Tiendanube.
- THE SYSTEM SHALL guardar comprador (cliente con nombre, email, teléfono, documento y domicilio de envío), líneas por SKU (vinculadas a la variante si existe), totales (subtotal, descuentos, envío, total), pago (medio, estado) y forma de envío (Envío Nube, retiro en local, otra).
- IF el mismo pedido llega varias veces THEN THE SYSTEM SHALL tener un solo documento, actualizado con la última versión.
- THE SYSTEM SHALL correr una conciliación periódica que trae los pedidos creados o modificados desde la última conciliación exitosa (con margen), para recuperar los que no llegaron por webhook.
- IF una línea tiene un SKU que no está en el catálogo THEN THE SYSTEM SHALL guardar igual la línea con SKU y descripción del momento, y SHALL emitir una alerta de "SKU desconocido".
- WHEN se conecta la tienda THE SYSTEM SHALL importar los pedidos de los últimos 30 días.
- THE SYSTEM SHALL guardar el estado tal como viene de Tiendanube (`channel_status`), separado del estado interno del sistema (M4).

### US-4: Marcar el despacho en Tiendanube (DDEV-13)

Como depósito, quiero que al despachar desde el sistema el pedido se marque en Tiendanube, para que el cliente reciba el aviso automático.

**Acceptance criteria:**

- THE SYSTEM SHALL ofrecer operaciones para marcar en Tiendanube un pedido como empaquetado, enviado (con código y URL de seguimiento, avisando al cliente) o entregado/retirado. Las va a usar la pantalla de despacho (M5).
- IF Tiendanube rechaza el cambio o no responde THEN THE SYSTEM SHALL reintentar con espera creciente y, si sigue fallando, SHALL emitir una alerta.
- THE SYSTEM SHALL NOT modificar stock, precios, productos ni otros datos del pedido.
- WHEN se marca un pedido THE SYSTEM SHALL registrarlo en auditoría (`order.status_changed` con el estado de Tiendanube anterior y el nuevo).
- IF el pedido ya está en ese estado en Tiendanube THEN THE SYSTEM SHALL no hacer nada y no reintentar.

### US-5: Spike de etiquetas de Envío Nube (DDEV-14)

Como Kei, quiero saber si la API de Tiendanube da la etiqueta y el seguimiento de Envío Nube, para definir cómo se imprimen las etiquetas en M5.

**Acceptance criteria:**

- THE SPIKE SHALL documentar en `docs/spikes/envio-nube.md` qué expone la API (etiqueta PDF, código de seguimiento, estado), probado sobre un pedido real de la tienda.
- IF la API no expone la etiqueta THEN THE SPIKE SHALL dejar definido el plan B: un link directo al pedido en el admin de Tiendanube para imprimirla.

## Constraints

- **Regla de oro:** el adaptador no escribe stock, precios ni productos. Las únicas escrituras permitidas son estados y seguimiento de pedidos.
- **Límite de la API de Tiendanube:** cubeta de 40 pedidos con recarga de 2 por segundo. Hay que identificarse con un User-Agent con contacto.
- **Sin servidor todavía.** Los webhooks necesitan una URL pública con HTTPS. Mientras se desarrolla en local, los pedidos y cambios entran por la conciliación periódica, y los webhooks se registran cuando haya servidor (o se prueban con un túnel temporal). La meta de menos de 1 minuto aplica con el servidor desplegado.
- La app de Tiendanube Partners tiene que crearla alguien con cuenta de socio de Kei. Ese paso es de la persona, no del sistema: requiere aceptar términos.
- Datos personales de compradores: solo lo necesario para despachar, y anonimizables a pedido (webhooks de privacidad).

## Open questions

Ninguna. Resueltas el 2026-11-14:

- **App:** se crea una app nueva en Tiendanube Partners solo para el sistema, con permisos mínimos. La crea el usuario en el panel de socios; Kei guía el paso a paso.
- **Sin servidor:** en local, conciliación de pedidos cada 5 minutos. Los webhooks se registran cuando haya servidor.
- **Pedidos iniciales:** al conectar se importan los últimos 30 días.
