# Tasks: Operación de Mercado Libre (módulo M6)

**Status:** Done (2026-11-14) · falta probar con la cuenta real de ML
**Last updated:** 2026-11-14
**Design:** [design.md](./design.md)

Ordenadas por dependencia. Cada tarea incluye sus tests. `§` = sección de design.md.

## Bloque A: Base

- [x] **T1: Modelos, permisos, alertas y settings**
  Satisfies: US-1–US-4
  Notas:
  - `SavedReply` con permiso `manage_saved_replies`.
  - Índices de `Message` y `Question` (§1).
  - Permisos nuevos (`view_question`, `view_message`, `catalog.view_listing_health`) asignados a los roles. Vendedor suma responder y enviar. Etiquetas en castellano.
  - Alerta `ml.claim_due` (migración de datos). `ml.question_unanswered_long` asignada a Ventas y Admin.
  - Settings `ML_QUESTION_WARNING_HOURS`, `ML_CLAIM_WARNING_HOURS`, `ML_HEALTH_MIN_SCORE`, `ML_LISTING_EDIT_URL`, `ML_CLAIM_URL`, `ML_SIZE_CHART_TTL_HOURS` y `.env.example`.

- [x] **T2: Ajustes en M2**
  Satisfies: US-1, US-3, US-4
  Depends on: T1
  Notas:
  - `listings.upsert_item` guarda `sub_status`, `tags`, `warnings` y `size_grid_id` en `data`.
  - `ml.claim_opened` enlaza a `/ml/reclamos/{pk}/`.
  - Tests de la importación con esos campos.

## Bloque B: Servicios

- [x] **T3: `inbox.py`: preguntas y contexto**
  Satisfies: US-1
  Depends on: T1, T2
  Notas:
  - Bandeja y respondidas con búsqueda.
  - `question_context`: variaciones con stock en ML y en el catálogo, preguntas anteriores (hasta 10).
  - `health.size_chart` con caché en `Listing.data` y TTL; si falla, devuelve `None` (respx).

- [x] **T4: `inbox.py`: conversaciones**
  Satisfies: US-2
  Depends on: T1
  Notas:
  - `threads()` agrupado con no leídos y orden.
  - `thread()` y `mark_read()`.

- [x] **T5: `health.py`: problemas de publicaciones**
  Satisfies: US-4
  Depends on: T2
  Notas:
  - `problems_for` con los 5 tipos.
  - Motivos en `labels.py`.
  - `listings_with_problems` con filtros y contadores.
  - Export a Excel.

- [x] **T6: Tareas periódicas: preguntas viejas y reclamos por vencer**
  Satisfies: US-1, US-3
  Depends on: T1
  Notas:
  - Una tarea cada 5 minutos.
  - Avisos de 24 h y 4 h deduplicados.
  - Aviso de pregunta vieja una sola vez.
  - Tests con reloj fijo.

## Bloque C: Pantallas

- [x] **T7: Preguntas y respuestas guardadas**
  Satisfies: US-1
  Depends on: T3
  Notas:
  - Bandeja con antigüedad en rojo.
  - Detalle en dos columnas (una sola en el celular).
  - Responder con manejo de rechazo y errores amables.
  - Respondidas.
  - ABM de respuestas guardadas e inserción con JS.
  - Aviso de ML desconectado.

- [x] **T8: Mensajes**
  Satisfies: US-2
  Depends on: T4
  Notas:
  - Conversaciones con no leídos primero.
  - Detalle que marca leído, responder y enlace a la ficha.
  - En la ficha del pedido de M4: "Ver conversación (N sin leer)".

- [x] **T9: Reclamos y salud**
  Satisfies: US-3, US-4
  Depends on: T5
  Notas:
  - Lista de abiertos y cerrados, ficha con devolución y enlace a ML.
  - Salud paginada con filtros, contadores, Excel y enlace "editar en ML".

- [x] **T10: Menú con contadores y permisos**
  Satisfies: US-1–US-4
  Depends on: T7, T8, T9
  Notas:
  - Grupo "Mercado Libre" en el menú.
  - Fragmento HTMX `/ml/contadores/` cada 60 s.
  - Tests de permisos por rol en todas las URLs.
  - Presupuestos de consultas en `test_rendimiento.py`.

## Bloque D: Cierre

- [x] **T11: Revisión y cierre de M6**
  Depends on: T1–T10
  Notas:
  - Suite y ruff en verde.
  - Revisión en el navegador (escritorio y celular) con datos de ejemplo de preguntas, mensajes, reclamos y publicaciones.
  - Commit, push y CI.
  - DDEV-36..39 en Plane (en curso hasta probar con la cuenta real). DDEV-40 queda comentado como pospuesto.
  - Resumen visual.

## Qué depende de terceros

- Probar con la cuenta real de ML (app en ML Developers + autorización del dueño): textos de motivos, enlaces a ML y guía de talles.
- M6-05 (edición masiva): spike DDEV-23.
