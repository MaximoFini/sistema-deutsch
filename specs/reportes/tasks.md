# Tasks: Reportes (módulo M7)

**Status:** Done (2026-11-15) · falta validar el neto con la cuenta real de ML
**Last updated:** 2026-11-15
**Design:** [design.md](./design.md)

Ordenadas por dependencia. Cada tarea incluye sus tests. `§` = sección de design.md.

## Bloque A: Datos

- [x] **T1: App `reports`, permiso y campos nuevos**
  Satisfies: US-1–US-5
  Notas:
  - App `apps/reports` con permiso `view_reports` asignado solo al Administrador.
  - Campos `SalesLine.channel_fee`, `Shipment.seller_cost`, `SalesDocument.ready_at`/`dispatched_at`/`net_pending` y `StockMovement.on_hand_after`, con migraciones (§1).
  - Índices de §3.

- [x] **T2: Llenado hacia adelante**
  Satisfies: US-3, US-4, US-5
  Depends on: T1
  Notas:
  - `change_status` fija `ready_at` y `dispatched_at`; `ready_at` también al crear pedidos pagados.
  - `inventory.services` guarda `on_hand_after`.
  - ML: upsert de órdenes con `sale_fee` y `net_pending`; `shipments.refresh` pide `/costs` con el cliente rápido (§5).
  - Tests de cada uno; ninguna escritura en canales.

- [x] **T3: Backfills**
  Satisfies: US-3, US-4, US-5
  Depends on: T2
  Notas:
  - Comando `reports_backfill` con los modos `timestamps`, `stock` y `ml_fees`.
  - Tarea Procrastinate de comisiones ML en tandas, respetando el límite de la API, más una corrida diaria.
  - Encolado automático al migrar.
  - Tests: idempotencia, auditoría y respx.

## Bloque B: Consultas

- [x] **T4: Filtros, indicadores y series**
  Satisfies: US-1, US-3
  Depends on: T1
  Notas:
  - `Filters` con atajos, rango con tope de 2 años, canal y zona horaria Argentina.
  - `kpis` con período anterior, `sales_by_day`, `channel_share` y `heatmap`.

- [x] **T5: Tabla de ventas y productos**
  Satisfies: US-2, US-4
  Depends on: T1
  Notas:
  - `sales_table` con los 8 agrupamientos y "Sin vincular".
  - `top_products`.
  - `stockouts` con LAG y días sin stock.

- [x] **T6: Operación**
  Satisfies: US-5
  Depends on: T2
  Notas:
  - Agregado `Percentile`.
  - `response_times`, `dispatch_times`, `flex_on_time` y `manual_pending`.

## Bloque C: Pantallas

- [x] **T7: Resumen con gráficos**
  Satisfies: US-1, US-3
  Depends on: T4
  Notas:
  - Filtros en la URL, 7 indicadores con variación.
  - Chart.js 4.4.x (cdnjs) con colores por canal.
  - Tabla de calor y avisos de neto pendiente y de TN sin comisión.
  - Versión para celular.

- [x] **T8: Ventas, Productos y Operación + Excel**
  Satisfies: US-2, US-4, US-5
  Depends on: T5, T6
  Notas:
  - Tablas ordenables y paginadas.
  - Excel `write_only` por pantalla con los mismos filtros.
  - Menú "Reportes" solo para Administrador.

- [x] **T9: Permisos y rendimiento**
  Satisfies: Constraints
  Depends on: T7, T8
  Notas:
  - 403 para los demás roles.
  - Volumen de 10.000 pedidos en `test_rendimiento.py`: menos de 2 s por pantalla y Excel de 50.000 filas en menos de 10 s.

## Bloque D: Cierre

- [x] **T10: Revisión y cierre de M7**
  Depends on: T1–T9
  Notas:
  - Suite y ruff en verde.
  - Revisión en el navegador (escritorio y celular) con datos de ejemplo de varios meses.
  - Commit, push y CI.
  - Plane: DDEV-41 en curso hasta validar el neto de ML con la cuenta real; DDEV-42 comentado como pospuesto a M8.
  - Resumen visual.

## Qué depende de terceros

- Cuenta real de ML: confirmar qué costo de envío informa ML como del vendedor en cada modalidad.
