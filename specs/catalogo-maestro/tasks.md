# Tasks: Catálogo maestro (módulo M3)

**Status:** Done (2026-11-14), salvo la prueba con un export real de Contabilium
**Last updated:** 2026-11-14
**Design:** [design.md](./design.md)

> **Avance 2026-11-14:** T1–T10 hechos. Hay 41 tests nuevos (237 en total) en verde. Las pantallas se revisaron con datos de ejemplo en la base local (catálogo, sin vincular, importación CSV, stock y precios, calidad, Excel).

Ordenadas por dependencia. Cada tarea incluye sus tests. `§` = sección de design.md.

## Bloque A: Modelo y vinculación (DDEV-24)

- [x] **T1: Modelo, permisos y settings**
  Satisfies: US-1, US-2, US-3
  Notas: en `ListingVariation`, `link_source`, `linked_by` y `linked_at`; modelo `ContabiliumImport`; permisos `manage_links`, `import_contabilium`, `view_channel_stock` y `view_quality` asignados a roles, con sus etiquetas en castellano; `view_variant` para todos los roles; acciones de auditoría `catalog.link_changed` y `catalog.contabilium_imported`; settings `CATALOG_*` y `CONTABILIUM_WHOLESALE_INCLUDES_VAT`; dependencia `openpyxl`; migración.

- [x] **T2: `linking.py`**
  Satisfies: US-2
  Depends on: T1
  Notas:
  - `auto_link` por SKU y, para Contabilium, por código de barras, con su ExternalRef espejo.
  - `link_manual` y `unlink_manual`, ambas auditadas.
  - `relink_for_variant`.
  - Integración con M2 (`listings.upsert_item` usa `auto_link`) y con M1 (`relink_for_variant` al terminar `upsert_product`).
  - Tests: automático, por barras, el vínculo manual no se pisa, el desvinculado a propósito se respeta, reemplazo, relink posterior.

## Bloque B: Importador de Contabilium (DDEV-24)

- [x] **T3: Lectura y normalización del archivo**
  Satisfies: US-3
  Depends on: T1
  Notas:
  - `parse_file` para xlsx y csv con `;` o `,`, con detección de la fila de encabezados en las primeras 10 filas.
  - Columnas por sinónimos (sin acentos).
  - Números en formato argentino; errores por fila; repetidos.
  - Tests: cada formato, encabezado en la fila 3, sin columna de código → error con las columnas encontradas, números, repetidos, archivo de más de 5 MB.

- [x] **T4: Vista previa y aplicar**
  Satisfies: US-3
  Depends on: T2, T3
  Notas:
  - `build_preview` (coinciden, sin coincidir, repetidos, errores, precios mayoristas que cambian) sin escribir datos.
  - `apply_import`:
    - en una transacción;
    - crea o actualiza Listing y ListingVariation de contabilium, con `auto_link`;
    - carga MAYORISTA con `set_price`, solo si cambió y con IVA opcional;
    - marca como `missing` los códigos que no vienen;
    - no toca `StockLevel`;
    - registra la auditoría;
    - una importación no se aplica dos veces.
  - Tests de cada punto.

## Bloque C: Pantallas del catálogo (DDEV-24)

- [x] **T5: Lista y ficha de variante**
  Satisfies: US-1
  Depends on: T2
  Notas:
  - `/catalogo/` con búsqueda (SKU, nombre o código de barras), filtros (sin ML, sin Contabilium, para revisar, inactivas) y paginación.
  - `/catalogo/<id>/` con los bloques por canal y los precios vigentes.
  - Menú del panel.
  - Tests: búsquedas, filtros, ficha con los vínculos de los 3 canales, permisos.

- [x] **T6: Sin vincular y vincular a mano**
  Satisfies: US-2
  Depends on: T2, T5
  Notas:
  - `/catalogo/sin-vincular/` con filtro por canal y marca de "desvinculado a mano".
  - Buscador HTMX de variantes.
  - POST para vincular, reemplazar (con confirmación) o desvincular.
  - Tests: flujo completo, confirmación del reemplazo, permisos (Depósito → 403).

- [x] **T7: Pantallas de importación de Contabilium**
  Satisfies: US-3
  Depends on: T4, T5
  Notas:
  - Subida e historial; vista previa con ejemplos por grupo; botones Confirmar y Descartar.
  - Tests: subida, vista previa, confirmar, descartar, permiso (solo Administrador).

## Bloque D: Vistas de control (DDEV-25, DDEV-26)

- [x] **T8: Stock y precio por canal**
  Satisfies: US-4
  Depends on: T4, T5
  Notas:
  - `channel_view.build_rows` con pocas consultas: ML propio y Full separados, diferencias de stock y de precio, fecha de última actualización.
  - Pantalla con filtro "solo con diferencias", resaltado y búsqueda.
  - Exportación a Excel.
  - Tests: columnas con datos de los 3 canales, Full separado, filtro, Excel, solo lectura, cantidad de consultas.

- [x] **T9: Panel de calidad**
  Satisfies: US-5
  Depends on: T8
  Notas:
  - `quality.find_issues` con los 11 códigos y sus severidades.
  - Pantalla con contadores, filtros por tipo y severidad y enlaces.
  - Exportación a Excel.
  - Tests: un caso por código, filtros, Excel, cantidad de consultas acotada.

## Bloque E: Cierre

- [x] **T10: Cierre de M3**
  Depends on: T1–T9
  Notas:
  - Prueba en el navegador con datos de ejemplo: catálogo, sin vincular, importación de un CSV de prueba, stock y precios, calidad.
  - Suite y CI en verde.
  - Commit y push.
  - Actualización de DDEV-24..26 en Plane.

## Qué queda pendiente (externo)

- Probar el importador con un export real de Contabilium y ajustar los sinónimos y el IVA del precio mayorista si hace falta.
- Datos reales de TN y ML en las vistas: cuando se conecten las apps de M1 y M2.
