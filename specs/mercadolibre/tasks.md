# Tasks: Integración Mercado Libre (módulo M2)

**Status:** In progress (aprobado 2026-11-14)
**Last updated:** 2026-11-14
**Design:** [design.md](./design.md)

> **Avance 2026-11-14:** T1–T16 hechos con la API de Mercado Libre simulada: 64 tests nuevos (196 en total) en verde. Pendiente externo: crear la app (Kei) y que el dueño de la cuenta la autorice para la prueba real, y activar la integración Contabilium ↔ ML para el spike DDEV-23.

Ordenadas por dependencia. Cada tarea incluye sus tests: la API de Mercado Libre se simula con `respx` y las muestras están en `tests/ml_samples.py`. `§` = sección de design.md.

## Bloque A: Modelos y base

- [x] **T1: Modelos nuevos y cambios**
  Satisfies: US-2, US-4, US-5, US-6, US-7
  Notas:
  - `catalog.Listing` y `catalog.ListingVariation`.
  - App nueva `conversations` con `Question`, `Message` y `Claim`, más sus permisos.
  - En `Shipment`: `external_id`, `logistic_type`, `dispatch_deadline`, `substatus`, `label_zpl_file` y los métodos nuevos.
  - Alertas `ml.claim_opened` y `ml.question_unanswered_long`.
  - Permisos `answer_question` y `send_message` en los roles Administrador y Ventas, con sus etiquetas en castellano.
  - Migraciones.

- [x] **T2: Settings, `auth.py` y `MLClient`**
  Satisfies: US-1
  Depends on: T1
  Notas:
  - Variables de §2.
  - `get_access_token` y `force_refresh` con lock en la fila de la credencial. `invalid_grant` desconecta y alerta.
  - El cliente usa Bearer, repite una sola vez ante 401 (después de renovar) y pagina por offset y por scan.
  - Tests: renovación con refresh nuevo, lock (un solo POST), `invalid_grant`, 401 → renueva y repite, error de red → reintento.

- [x] **T3: Adaptador y notificaciones**
  Satisfies: US-1
  Depends on: T2
  Notas:
  - `verify_webhook` por `application_id` y `user_id`.
  - `topic` y `dedupe_key` por minuto.
  - Handlers por tópico.
  - Se registra en el registry y tiene `own_schedule`.
  - Tests: otra app u otro vendedor se ignoran, dedupe.

## Bloque B: Conexión (DDEV-15)

- [x] **T4: OAuth: conectar, callback y "pegar URL de vuelta"**
  Satisfies: US-1
  Depends on: T3
  Notas:
  - State en la sesión y canje del código.
  - Credencial cifrada, auditoría y encolado de las importaciones iniciales.
  - Formulario que acepta la URL completa, extrae `code` y `state` y los valida.
  - Tarea periódica `ml_refresh_token` cada 30 min.
  - Comando `ml_test_user`.
  - Tests: state inválido, canje OK, pegar URL válida e inválida, renovación periódica.

## Bloque C: Publicaciones (DDEV-16)

- [x] **T5: Upsert de publicación y vínculo por SKU**
  Satisfies: US-2
  Depends on: T1, T3
  Notas:
  - `listings.upsert_item(json)`:
    - variaciones;
    - SKU desde `SELLER_SKU` o `seller_custom_field`;
    - vínculo a la `Variant` más `ExternalRef`;
    - marca de revisión;
    - Full, User Products y fotos.
  - Tests: con y sin variaciones, SKU por atributo o por campo, sin SKU, SKU que no está en el catálogo, Full, segunda pasada idempotente.

- [x] **T6: Importación (scan + multiget), notificación `items` y conciliación diaria**
  Satisfies: US-2
  Depends on: T5
  Notas:
  - Scan con `scroll_id` y multiget de a 20.
  - Una publicación con error no frena al resto.
  - Las publicaciones que no aparecen pasan a `closed`.
  - Regla de oro: `write_stock` y `write_price` quedan bloqueados.
  - Tests: scan de 2 páginas, error aislado, cerradas, regla de oro.

## Bloque D: Ventas, envíos y facturación (DDEV-17, 18, 22)

- [x] **T7: Upsert de orden y pack**
  Satisfies: US-3
  Depends on: T5
  Notas:
  - `orders.upsert_order(json)`:
    - snapshot por orden;
    - clave pack u orden;
    - reconstrucción del documento (líneas, pagos, totales, `channel_status`, cliente);
    - control de frescura;
    - alerta de SKU desconocido.
  - Tests:
    - orden suelta;
    - pack de 2 órdenes en cualquier orden → un documento con 2 líneas;
    - cancelación parcial;
    - una orden vieja no pisa una nueva;
    - el estado interno queda intacto;
    - SKU desconocido.

- [x] **T8: Envíos y etiquetas**
  Satisfies: US-4
  Depends on: T7
  Notas:
  - `shipments.refresh(id)` con modalidad, estado y plazo (SLA).
  - `get_label(shipment, fmt)` en PDF o ZPL (también si el ZPL viene en ZIP) con caché.
  - `LabelNotReady`.
  - Notificación `shipments` y conciliación de envíos abiertos cada 15 min.
  - Tests: cada modalidad, plazo, etiquetas en los dos formatos, ZIP, etiqueta no lista.

- [x] **T9: Datos de facturación**
  Satisfies: US-8
  Depends on: T7
  Notas:
  - `billing.refresh(order)` prueba las dos rutas de la API.
  - Mapeo de IVA y domicilio fiscal, sin pisar datos cargados a mano.
  - Copia en `SalesDocument.fiscal`.
  - Tests: RI con CUIT, CF, sin datos, datos manuales intactos.

- [x] **T10: Conciliación de ventas (48 h) e importación de 30 días**
  Satisfies: US-3
  Depends on: T7, T8, T9
  Notas:
  - Tarea periódica cada `ML_POLL_MINUTES`.
  - Ventana `min(última OK − 10 min, ahora − 48 h)`, paginada por offset.
  - Importación inicial por fecha de creación.
  - Al procesar una orden que cambió, se refrescan su envío y su facturación.
  - Tests: ventana, paginación, se saltea si no está conectado.

## Bloque E: Preguntas, mensajes y reclamos (DDEV-19, 20, 21)

- [x] **T11: Preguntas**
  Satisfies: US-5
  Depends on: T3, T5
  Notas:
  - Upsert por notificación.
  - Conciliación de preguntas sin responder.
  - `answer()`: guarda el borrador, mapea los errores, registra auditoría y exige el permiso.
  - Tests: guardar, responder OK, borrada, bloqueado, ya respondida (el borrador se conserva).

- [x] **T12: Mensajes postventa**
  Satisfies: US-6
  Depends on: T7
  Notas:
  - Upsert por notificación.
  - Conciliación de no leídos con `mark_as_read=false`.
  - `send()`: límite de 350 caracteres, adjuntos, `MessagingBlocked`, auditoría y permiso.
  - Tests: guardar entrante y saliente, enviar, límite, bloqueado.

- [x] **T13: Reclamos y devoluciones**
  Satisfies: US-7
  Depends on: T7
  Notas:
  - Upsert por notificación.
  - Plazo y acción requerida tomados de `players`.
  - Estado de la devolución.
  - Alerta `ml.claim_opened` una sola vez.
  - Conciliación cada 15 min.
  - Tests: plazo, devolución en camino y entregada, alerta única.

## Bloque F: Panel, spike y cierre

- [x] **T14: Tarjeta de Mercado Libre en el panel**
  Satisfies: US-1, US-2, US-3
  Depends on: T4, T6, T10
  Notas:
  - Botones Conectar/Reconectar, formulario para pegar la URL e Importar.
  - Muestra el estado: vendedor, vencimiento del token y formato de etiqueta.
  - Tests de permisos.

- [x] **T15: Guía para crear la app en ML Developers**
  Satisfies: US-1
  Notas:
  - `docs/runbooks/mercadolibre-app.md`:
    - crear la app;
    - tópicos;
    - URL de vuelta, en local y con servidor;
    - URL de notificaciones;
    - quién autoriza (el dueño de la cuenta);
    - qué copiar al `.env`;
    - usuarios de prueba.

- [x] **T16: Herramienta del spike Contabilium (DDEV-23, la prueba queda pendiente)**
  Satisfies: US-9
  Depends on: T5
  Notas:
  - Comando `ml_spike_snapshot ITEM_ID`: guarda un JSON de la publicación para comparar antes y después.
  - Esqueleto de `docs/spikes/ml-contabilium.md` con el procedimiento.

- [x] **T17: Cierre de la parte programable de M2**
  Depends on: T1–T16
  Notas:
  - Suite completa y CI en verde.
  - Trazabilidad contra los requirements.
  - Commit y push.
  - Actualización de DDEV-15..23 en Plane.

## Qué queda pendiente (externo)

- **Crear la app en ML Developers (Kei) y la autorización del dueño de la cuenta (Deutsch):** prueba con la cuenta real (ventas, envíos, etiquetas, preguntas, mensajes, reclamos, facturación).
- **Activar la integración Contabilium ↔ ML (Deutsch):** prueba del spike DDEV-23.
