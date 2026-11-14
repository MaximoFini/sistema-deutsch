# Tasks: Centro de pedidos (módulo M4)

**Status:** Done (2026-11-14)
**Last updated:** 2026-11-14
**Design:** [design.md](./design.md)

> **Avance 2026-11-14:** T1–T11 hechos. Hay 40 tests nuevos (277 en total) en verde. Pantallas revisadas en el navegador con pedidos de ejemplo, en escritorio y en celular. La revisión encontró y corrigió tres problemas: el domicilio de TN en la ficha, la cancelación parcial de un pack de ML y el menú del panel en el celular.

Ordenadas por dependencia. Cada tarea incluye sus tests. `§` = sección de design.md.

## Bloque A: Modelo y estados (DDEV-28)

- [x] **T1: Cambios de modelo, permisos y alertas**
  Satisfies: US-1–US-5
  Notas:
  - En `SalesDocument`:
    - `status` con choices;
    - `status_before_claim`, `status_changed_at`, `channel_reference`;
    - campos de facturación en Contabilium.
  - `SalesLine.condition`, `Shipment.Method.OTHER`, modelo `ReturnInfo`.
  - Migración de datos: `channel_reference` para los documentos existentes.
  - M1 y M2 completan `channel_reference` en sus upserts.
  - Permisos de `sales` asignados a los roles, con sus etiquetas.
  - Acciones de auditoría nuevas.
  - Los 6 tipos de alerta (migración de datos).
  - Settings `ORDERS_FLEX_WARNING_MINUTES` y `ORDERS_MANUAL_PENDING_HOURS`.

- [x] **T2: `states.py`: máquina de estados y `change_status`**
  Satisfies: US-2
  Depends on: T1
  Notas:
  - Tabla `TRANSITIONS` y `allowed_transitions(doc, user)` para la UI (incluye despachar vs. retiro).
  - Validación, permisos y regla de cancelar solo manuales.
  - Lock, auditoría y efectos en `on_commit`: marcar en TN solo si el cambio es de un usuario, y la alerta de cancelación.
  - Tests: cada transición permitida, prohibidas, permisos, auditoría, llamadas a TN con `respx`, el sistema no escribe a TN.

- [x] **T3: `sync.py`: sincronización automática**
  Satisfies: US-2, US-5
  Depends on: T2
  Notas:
  - `facts(doc)` y las 7 reglas en orden.
  - Al crear: estado inicial, alerta `orders.new` y control de stock (`orders.out_of_stock`).
  - Se llama desde los upserts de TN y ML, la actualización de envíos y la de reclamos de ML.
  - Tests:
    - Full;
    - cancelado en TN y en ML;
    - entregado;
    - pago pendiente → confirmado;
    - reclamo abierto y cerrado;
    - idempotencia;
    - no pisa estados finales;
    - integración con las muestras de M1 y M2.

## Bloque B: Pedidos manuales y devoluciones (DDEV-29, DDEV-30)

- [x] **T4: `manual.py`**
  Satisfies: US-3
  Depends on: T2
  Notas:
  - `create_manual_order`, `find_or_create_customer`, `update_payment` y `update_invoice`.
  - Rechazo de mayoristas; precio de referencia por defecto.
  - Tests de cada punto.

- [x] **T5: `returns.py`**
  Satisfies: US-4
  Depends on: T1
  Notas:
  - `ensure_expected_for_claim` (enganchado a ML `upsert_claim`), `create_expected`, `receive`, `receive_unexpected` y `mark_adjusted`.
  - Tests: esperada desde reclamo una sola vez, recibir con condición, alerta, ajustado, no toca stock.

## Bloque C: Alertas periódicas (DDEV-31)

- [x] **T6: Tarea `orders_watch`**
  Satisfies: US-5
  Depends on: T3, T4
  Notas:
  - Flex/Colecta por vencer y manuales pendientes, con dedupe.
  - Tests con fecha simulada.

## Bloque D: Pantallas (DDEV-27, 29, 30)

- [x] **T7: Lista de pedidos**
  Satisfies: US-1
  Depends on: T3
  Notas:
  - Filtros combinables, orden por urgencia, anotaciones sin N+1, paginación.
  - Tabla y tarjetas para celular; badges de estado.
  - Menú del panel.
  - Tests de filtros, orden, cantidad de consultas y permisos.

- [x] **T8: Ficha del pedido y cambio de estado**
  Satisfies: US-1, US-2
  Depends on: T7
  Notas:
  - Secciones: líneas, cliente y datos fiscales, pagos, envío, mensajes, reclamo, devoluciones, historial (auditoría + estado del canal).
  - Botones de transiciones permitidas, con campo de seguimiento para TN.
  - Tests: secciones, botones según permiso y estado, POST de estado, transición inválida → mensaje.

- [x] **T9: Alta y edición de pedido manual**
  Satisfies: US-3
  Depends on: T4, T8
  Notas:
  - Formulario con cliente (buscador o nuevo), líneas con buscador de SKU por HTMX, entrega, cobro y facturación.
  - Edición de cobro y factura en la ficha.
  - Tests del flujo completo y de mayorista rechazado.

- [x] **T10: Pantallas de devoluciones**
  Satisfies: US-4
  Depends on: T5, T8
  Notas:
  - Pestañas Esperadas y Recibidas.
  - Formulario de recepción por línea.
  - Cargar esperada o no esperada desde la ficha.
  - Marcar ajustado.
  - Tests de permisos y flujos.

## Bloque E: Cierre

- [x] **T11: Cierre de M4**
  Depends on: T1–T10
  Notas:
  - Datos de ejemplo en la base local: pedidos TN y ML, un pack, un Full, uno manual, un reclamo con devolución.
  - Revisión de las pantallas, también en vista de celular.
  - Suite y CI en verde.
  - Commit y push.
  - Actualización de DDEV-27..31 en Plane y del resumen visual.
