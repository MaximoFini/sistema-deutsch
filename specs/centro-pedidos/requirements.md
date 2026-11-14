# Requirements: Centro de pedidos (módulo M4)

**Status:** Approved (2026-11-14)
**Last updated:** 2026-11-14
**Tickets:** DDEV-27 a DDEV-31 (M4-01 … M4-05)
**Depende de:** M1 (pedidos TN), M2 (ventas ML, envíos, reclamos), M3 (catálogo maestro) y M0 (alertas, permisos, auditoría). Todos programados.

## Summary

Un único lugar donde el equipo de Deutsch ve y mueve todos los pedidos: Tiendanube, Mercado Libre y pedidos manuales. Cada pedido tiene un estado interno con transiciones definidas, que se sincroniza solo con lo que informan los canales. Suma la carga de pedidos manuales, la recepción de devoluciones y las alertas de pedidos. Es el primer módulo de uso diario, sobre todo para Depósito.

## Goals

- Ver todos los pedidos de todos los canales en una lista, también desde el celular, y encontrar cualquiera por canal, estado, fecha, comprador o SKU.
- Que nadie saltee pasos: solo transiciones de estado definidas, todas auditadas.
- Que lo que pasa en los canales (cancelación, entrega, reclamo, Full) se refleje solo, sin carga manual.
- Que ningún pedido Flex se despache tarde y que ningún pedido manual quede sin cobrar o sin facturar sin que alguien se entere.
- Registrar las devoluciones que llegan, para que se ajuste el stock en Contabilium.

## Non-goals

- Picking, etiquetas y pantalla de despacho: son M5. M4 deja los estados y las acciones que M5 va a usar.
- Pantallas de preguntas, mensajes y reclamos de ML: son M6. En la ficha del pedido se muestran en modo lectura.
- Facturar desde el sistema (futuro, F-02): M4 solo registra el número de comprobante que se hizo en Contabilium.
- Ajustar el stock de Contabilium: no hay API. El sistema avisa y alguien lo marca como ajustado.
- Pedidos mayoristas: se cargan desde la tienda mayorista (M8-12).

## User stories

### US-1: Lista unificada y ficha del pedido (DDEV-27)

Como equipo de Deutsch, quiero ver todos los pedidos de todos los canales en un solo lugar.

**Acceptance criteria:**

- THE SYSTEM SHALL tener una pantalla "Pedidos" con, por fila:
  - canal y número del canal (TN #1234, venta o pack de ML, manual #N);
  - fecha;
  - comprador;
  - productos (resumen);
  - total;
  - estado de pago (cobrado o pendiente);
  - forma de envío;
  - fecha límite de despacho;
  - estado interno.
- THE SYSTEM SHALL permitir filtrar por canal, estado interno, rango de fechas, comprador, SKU y cobrado/pendiente, y combinar filtros.
- THE SYSTEM SHALL ordenar por defecto lo más urgente primero: fecha límite más cercana, después lo más nuevo.
- WHEN se abre un pedido THE SYSTEM SHALL mostrar una ficha con:
  - líneas, totales, comprador y datos fiscales si los hay;
  - pagos;
  - envío (modalidad, seguimiento, fecha límite);
  - mensajes, reclamo y devolución asociados;
  - historial de estados internos (quién, cuándo, de qué a qué) y el estado crudo del canal.
- THE SYSTEM SHALL ser usable desde el celular: la lista se ve como tarjetas en pantallas angostas y las acciones tienen botones grandes.
- THE SYSTEM SHALL mostrar la lista a los cuatro roles. Las acciones dependen de los permisos (US-2, US-3).

### US-2: Estados internos y sincronización con los canales (DDEV-28)

Como Depósito, Ventas o Administrador, quiero mover los pedidos por estados claros, y que lo que pasa en los canales se refleje solo.

**Acceptance criteria:**

- THE SYSTEM SHALL manejar estos estados:
  - **flujo normal:** Nuevo → En preparación → Listo → Despachado o Listo para retirar → Entregado;
  - **especiales:** Cancelado, Con reclamo, Esperando pago, Esperando cliente.
- THE SYSTEM SHALL permitir solo las transiciones definidas en el diseño. Cada cambio SHALL quedar en auditoría (`order.status_changed`) con estado anterior, estado nuevo, usuario y motivo opcional.
- THE SYSTEM SHALL permitir cambiar estados a usuarios con el permiso `sales.change_order_status`: roles Depósito, Ventas y Administrador. Cancelar un pedido manual SHALL requerir `sales.cancel_manual_order` (Ventas y Administrador).
- WHEN entra un pedido Full de Mercado Libre THE SYSTEM SHALL ponerlo directamente en Despachado: no se prepara.
- WHEN un canal informa que el pedido se canceló THE SYSTEM SHALL pasarlo a Cancelado, salvo que ya esté Entregado.
- WHEN un canal informa que el pedido se entregó THE SYSTEM SHALL pasarlo a Entregado.
- WHEN un pedido entra sin pagar (TN pendiente, ML esperando pago) THE SYSTEM SHALL ponerlo en Esperando pago. WHEN se confirma el pago THE SYSTEM SHALL pasarlo a Nuevo.
- WHEN se abre un reclamo de ML asociado al pedido THE SYSTEM SHALL pasarlo a Con reclamo y recordar el estado anterior. WHEN el reclamo se cierra THE SYSTEM SHALL volver al estado anterior.
- Los cambios automáticos SHALL quedar auditados con el actor "sistema" y el motivo (por ejemplo, "Cancelado en Mercado Libre").
- WHEN un usuario pasa un pedido de **Tiendanube** a Despachado, Listo para retirar o Entregado THE SYSTEM SHALL marcarlo en Tiendanube automáticamente (servicio de M1, con reintentos y alerta si falla). Al despachar se puede cargar un código y una URL de seguimiento.
- THE SYSTEM SHALL NOT escribir estados en Mercado Libre: en ML el despacho y la entrega los informa ML.

### US-3: Pedidos manuales (DDEV-29)

Como Ventas, quiero cargar a mano un pedido que no viene de ningún canal, para prepararlo y despacharlo igual que el resto.

**Acceptance criteria:**

- THE SYSTEM SHALL permitir crear un pedido manual con:
  - cliente (buscar uno existente o crear uno nuevo con nombre, documento, condición de IVA, email y teléfono);
  - productos del catálogo maestro (por SKU o nombre) con cantidad y precio de referencia, que por defecto es el minorista vigente y se puede editar;
  - forma de entrega (retiro en local, transporte, otro), con el domicilio si corresponde;
  - observaciones.
- THE SYSTEM SHALL registrar el cobro: cobrado o pendiente, con medio de pago (efectivo, transferencia, Mercado Pago, otro).
- THE SYSTEM SHALL tener una casilla "Facturado en Contabilium" con el número de comprobante.
- IF el cliente elegido es mayorista THEN THE SYSTEM SHALL avisar que los pedidos mayoristas se cargan desde la tienda mayorista (M8-12) y SHALL NOT crear el pedido.
- THE SYSTEM SHALL permitir editar cobro y facturación después de creado el pedido, con auditoría.
- THE SYSTEM SHALL permitir crear pedidos manuales a usuarios con `sales.add_manual_order` (Ventas y Administrador).

### US-4: Recepción de devoluciones (DDEV-30)

Como Depósito, quiero registrar que llegó una devolución y en qué estado vino, para que se ajuste el stock en Contabilium.

**Acceptance criteria:**

- THE SYSTEM SHALL mostrar una lista de devoluciones **esperadas** y otra de **recibidas**. Las esperadas son:
  - reclamos de ML con devolución en camino o entregada;
  - devoluciones de TN o de pedidos manuales que alguien cargó como esperadas.
- WHEN Depósito registra la recepción THE SYSTEM SHALL pedir, por línea, la cantidad recibida y el estado del producto (apto para reventa o dañado), más un comentario. Con eso crea un documento de devolución (`SalesDocument` de tipo devolución) vinculado al pedido.
- WHEN se registra una devolución recibida THE SYSTEM SHALL emitir una alerta a Administradores para ajustar el stock en Contabilium, y SHALL permitir marcarla como "ajustado en Contabilium" (quién y cuándo).
- THE SYSTEM SHALL permitir registrar una devolución que llegó sin estar esperada, buscando el pedido.

### US-5: Alertas de pedidos (DDEV-31)

Como Depósito o Administrador, quiero que el sistema me avise lo que necesita atención.

**Acceptance criteria:**

- **Depósito:**
  - THE SYSTEM SHALL avisar cuando un pedido Flex o Colecta está a menos de **2 horas** (configurable) de su límite de despacho y todavía no está despachado.
  - THE SYSTEM SHALL avisar cuando entra un pedido Nuevo para preparar. Solo en el panel; el email se puede activar desde la configuración de alertas.
- **Administradores:**
  - THE SYSTEM SHALL avisar cuando se cancela un pedido que ya estaba En preparación o Listo.
  - THE SYSTEM SHALL avisar cuando una venta tiene un producto sin stock en el depósito al momento de entrar.
  - THE SYSTEM SHALL avisar cuando un pedido manual lleva más de 24 horas (configurable) sin cobrar o sin facturar.
- THE SYSTEM SHALL usar el motor de alertas de M0: panel y email según el rol y la configuración de cada tipo de alerta, sin duplicar avisos del mismo evento.

## Constraints

- **Regla de oro:** ninguna acción de M4 escribe stock ni precios en los canales. A Tiendanube solo se le informan estados de despacho y entrega.
- El estado interno (`SalesDocument.status`) es del sistema. El estado crudo del canal (`channel_status`) lo actualizan M1 y M2 y no se mezcla.
- Volumen: menos de 30 pedidos por día. La lista tiene que responder en menos de 1 segundo con 12 meses de pedidos (~10.000).
- Sin servidor, los cambios de los canales entran cada 5 minutos, y las alertas de vencimiento se revisan con esa misma frecuencia o mayor.

## Open questions

Ninguna. Decisiones del 2026-11-14:

- **Cambiar estados:** Depósito, Ventas y Administrador. Cancelar un pedido manual: Ventas y Administrador.
- **Pedidos nuevos:** se avisan solo en el panel.
- **Aviso de Flex:** 2 horas antes, configurable (`ORDERS_FLEX_WARNING_MINUTES`).
- **Despacho en Tiendanube:** al marcarlo en el sistema, se marca automáticamente en Tiendanube.
