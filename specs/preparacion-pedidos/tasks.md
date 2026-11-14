# Tasks: Preparación y despacho de pedidos (módulo M5)

**Status:** Done (2026-11-14) · DDEV-33 espera la prueba con la térmica real
**Last updated:** 2026-11-14
**Design:** [design.md](./design.md)

Ordenadas por dependencia. Cada tarea incluye sus tests. `§` = sección de design.md.

## Bloque A: Base

- [x] **T1: App `fulfillment`, modelos y permisos**
  Satisfies: US-1, US-3, US-4
  Notas:
  - App `apps/fulfillment` con `PickBatch`, `PickBatchOrder` (restricción única de tanda activa) y `Carrier` (§1).
  - `Shipment`: `packages`, `label_printed_at`, `label_print_count` (migración en `sales`).
  - Permisos `fulfillment.view_pickbatch` y `manage_carriers` en los roles, con etiquetas en castellano.
  - Acciones de auditoría: `fulfillment.batch_created`, `order_removed`, `batch_closed`, `shipment.label_printed`.
  - Settings `SENDER_*`, `TN_ADMIN_ORDER_URL`, `FULFILLMENT_MAX_BATCH` y entradas en `.env.example`.
  - Dependencias `reportlab` y `pypdf` con uv.

- [x] **T2: Señal `order_status_changed`**
  Satisfies: US-4
  Depends on: T1
  Notas:
  - `sales/signals.py`; `change_status` la envía con `on_commit` (old, new, system).
  - Test: se envía una vez por cambio real y no cuando el estado no cambia.

## Bloque B: Tandas (DDEV-32)

- [x] **T3: `batches.py`: preparables, crear tanda y exclusiones**
  Satisfies: US-1
  Depends on: T1
  Notas:
  - `preparable_orders()`: Nuevos de TN, ML sin Full y manuales, sin tanda activa; orden por fecha límite y antigüedad (§2).
  - `create_batch()`: lock, exclusiones con motivo en castellano, `change_status` a En preparación, tope `FULFILLMENT_MAX_BATCH`, auditoría.
  - Tests: exclusiones (no Nuevo, otra tanda, Full), tanda vacía no se crea, tope.

- [x] **T4: Lista de picking, sacar pedido y cierre automático**
  Satisfies: US-1, US-4
  Depends on: T2, T3
  Notas:
  - `picking_list()` agrupada por variante (o SKU sin catálogo aparte), con destinos y orden por SKU.
  - `remove_order()` devuelve a Nuevo; `on_status_changed` resuelve o saca; `close_if_done()`.
  - Tests: agrupación y cantidades; cierre por despacho, retiro y cancelación del canal; devolver a Nuevo desde la ficha saca de la tanda.

- [x] **T5: PDF de doble control**
  Satisfies: US-2
  Depends on: T4
  Notas:
  - `pdf.checklist_pdf()` A4: encabezado por página, parte 1 (Juntado / Verificado) y parte 2 por pedido (Armado / Controlado, firmas), bloques sin cortar (§3).
  - Tests: texto de ambas partes extraíble con pypdf; 50 pedidos en menos de 3 s.

## Bloque C: Etiquetas (DDEV-33)

- [x] **T6: Etiquetas de Mercado Libre en lote**
  Satisfies: US-3
  Depends on: T1
  Notas:
  - `labels.ml_labels()`: reusa `shipments.get_label`, saltea las no listas con el motivo, une PDF con pypdf o concatena ZPL (§4).
  - `mark_printed()` con auditoría.
  - Errores de token o red con `integrations.errors.friendly`, sin 500.
  - Tests con respx: una lista y una no lista, cantidad de páginas, ZPL, contador de impresiones.

- [x] **T7: Rótulo propio 10×15 y expresos**
  Satisfies: US-3
  Depends on: T1
  Notas:
  - `pdf.carrier_label_pdf()` 100 × 150 mm, una página por bulto, Code128 del pedido, remitente desde settings.
  - `labels.carrier_label()` guarda expreso y bultos en el envío.
  - Pantalla de expresos (alta, baja lógica) para `manage_carriers`.
  - Tests: tamaño de página, N páginas por bulto, falta de domicilio.

## Bloque D: Despacho (DDEV-34)

- [x] **T8: `dispatch.advance()` en lote**
  Satisfies: US-4
  Depends on: T2
  Notas:
  - Acciones listo / despachar / entregar con retiro vs envío, guía opcional, éxito parcial con motivos (§5).
  - Tests: lote mixto, Tiendanube encola el aviso, permisos.

## Bloque E: Pantallas

- [x] **T9: Pantallas Preparar, Tandas y detalle de tanda**
  Satisfies: US-1, US-2, US-3
  Depends on: T4, T5, T6, T7
  Notas:
  - Preparar: filtros, casillas, "Armar tanda", mensajes con los que quedaron afuera.
  - Tandas y detalle: picking en pantalla (tildes visuales con localStorage), pedidos, sacar pedido, PDF, etiquetas ML de la tanda, rótulos de transporte.
  - Mobile: tarjetas, casillas grandes, botón fijo abajo.

- [x] **T10: Pantalla Despacho y cambios en la ficha y el menú**
  Satisfies: US-3, US-4
  Depends on: T6, T7, T8
  Notas:
  - Despacho agrupado por estado, acciones en lote, guía por fila, etiquetas de los marcados.
  - Ficha del pedido: tanda, botón de etiqueta o rótulo, "ya impresa", aviso de Envío Nube.
  - Menú: Preparar, Tandas, Despacho, Expresos según permisos.
  - Tests de permisos por rol en todas las URLs; presupuesto de consultas en `test_rendimiento.py`.

## Bloque F: Cierre

- [x] **T11: Revisión y cierre de M5**
  Depends on: T1–T10
  Notas:
  - Suite completa y ruff en verde; revisión en el navegador (escritorio y celular) con datos de ejemplo.
  - Commit, push y CI en verde.
  - DDEV-32..34 en Plane (DDEV-33 queda en curso hasta probar con la térmica real); DDEV-35 comentado como pospuesto a M8.
  - Actualizar el resumen visual.

## Qué depende de Deutsch

- Datos del remitente y lista de expresos.
- Formato de la térmica (PDF o ZPL) y prueba con la impresora real.
