# Tasks: Integración Tiendanube (módulo M1)

**Status:** In progress (aprobado 2026-11-14)
**Last updated:** 2026-11-14
**Design:** [design.md](./design.md)

> **Avance 2026-11-14:** T1–T12 hechos con la API de Tiendanube simulada: 48 tests nuevos (132 en total) en verde. Pendiente: T13 (prueba con la tienda real y spike de Envío Nube), que espera a que el usuario cree la app en Partners siguiendo `docs/runbooks/tiendanube-app.md`, y T14 (cierre).

Ordenadas por dependencia. Cada tarea incluye sus tests (API simulada con `respx`). `§` = sección de design.md.

## Bloque A: Base del adaptador

- [x] **T1: Ajustes en M0 y modelo**
  Satisfies: US-2, US-3, US-4
  Notas:
  - Migración con:
    - `Product.categories` e `images`;
    - `Variant.needs_review` y `review_notes`;
    - `PriceListItem.promotional_price`;
    - `Shipment.address`.
  - Alertas nuevas: `catalog.unknown_sku`, `integration.write_failed`, `integration.disconnected`, `privacy.data_request`.
  - Acciones de auditoría nuevas: `integration.connected`, `privacy.customer_redacted`.
  - Permiso `integrations.manage_connection`, asignado al rol Administrador.
  - `run_reconciliation(channel, job, fn=None)`.
  - Tests de los cambios de M0.

- [x] **T2: Settings y `TiendanubeClient`**
  Satisfies: US-1, US-2, US-3
  Depends on: T1
  Notas:
  - Variables de entorno de §2 en settings y `.env.example`.
  - El cliente usa `ChannelClient` de M0 con:
    - base `api.tiendanube.com/2025-03/{store_id}`;
    - headers `Authorization: Bearer` y `User-Agent`;
    - `get_all()` que pagina siguiendo el header `Link`.
  - Tests: headers, paginación de 3 páginas, 429 con reintento.

- [x] **T3: Adaptador, firma y deduplicación**
  Satisfies: US-1, US-3
  Depends on: T2
  Notas:
  - `TiendanubeAdapter` registrado en el registry: `verify_webhook` (HMAC hex o base64), `topic`, `dedupe_key` por minuto y tabla de handlers.
  - Tests: firma válida, firma inválida, sin firma, dedupe en el mismo minuto y en minutos distintos.

## Bloque B: Conexión (DDEV-10)

- [x] **T4: OAuth y registro de webhooks**
  Satisfies: US-1
  Depends on: T3
  Notas:
  - Vista "conectar": state en sesión y redirect a Tiendanube.
  - Callback: valida el state, canjea el código, guarda la credencial cifrada, verifica los scopes y audita `integration.connected`.
  - Si `TN_WEBHOOKS_BASE_URL` está configurado: registro idempotente de webhooks.
  - Encola las importaciones iniciales.
  - Comando `tn_register_webhooks`.
  - Tests: state inválido, canje OK, scopes de más o de menos, webhooks sin duplicar, modo local sin webhooks.

- [x] **T5: Desinstalación y privacidad**
  Satisfies: US-1
  Depends on: T4, T9
  Notas:
  - Handler de `app/uninstalled`: borra la credencial, audita y emite la alerta `integration.disconnected`.
  - Vistas de privacidad con HMAC y procesamiento encolado: `customers/redact`, `store/redact` y `customers/data_request`.
  - Tests de anonimización. Los documentos de venta se conservan.

## Bloque C: Catálogo (DDEV-11)

- [x] **T6: Upsert de producto**
  Satisfies: US-2
  Depends on: T3
  Notas:
  - `catalog.upsert_product(tn_json)` según el mapeo de §5: unidades, atributos, SKU vacío, barcode duplicado, precio con `set_price` y stock con `apply_sync_level` solo si `STOCK_FEED_CHANNEL=tiendanube`.
  - Datos por canal en `ExternalRef.extra`.
  - Tests: alta, segunda pasada sin cambios (no crea filas ni movimientos), cambio de precio y de stock, variante sin SKU, `stock: null`.

- [x] **T7: Importación, webhooks y conciliación diaria del catálogo**
  Satisfies: US-2
  Depends on: T6
  Notas:
  - Tarea `tn_import_catalog` con transacción por producto y errores en `SyncRun.stats`.
  - Handlers `product/created|updated|deleted`.
  - Conciliación diaria: `updated_at_min` más el recorrido de IDs que marca inactivos los borrados.
  - Tests: importación paginada, un producto con error no frena al resto, borrado → inactivo.

## Bloque D: Pedidos (DDEV-12)

- [x] **T8: Upsert de pedido**
  Satisfies: US-3
  Depends on: T6
  Notas:
  - `orders.upsert_order(tn_json)` según el mapeo de §6:
    - cliente (busca por ref, luego por email, si no lo crea; no pisa datos cargados a mano);
    - líneas por ref de variante o por SKU;
    - pago y envío con detección de Envío Nube, retiro u otro;
    - `channel_status`;
    - control de frescura por `updated_at`.
  - Alerta de SKU desconocido.
  - Tests:
    - pedido pagado con Envío Nube;
    - pedido de retiro;
    - pedido cancelado;
    - mismo pedido dos veces → un solo documento;
    - evento viejo no pisa uno nuevo;
    - SKU desconocido → alerta;
    - una actualización no toca el `status` interno.

- [x] **T9: Webhooks, conciliación cada N minutos e importación de 30 días**
  Satisfies: US-3
  Depends on: T8
  Notas:
  - Handlers de los eventos `order/*`.
  - Tarea periódica de conciliación de pedidos cada `TN_ORDERS_RECONCILE_MINUTES`, que registra un `SyncRun(job="orders")`.
  - Tarea `tn_import_orders(days=30)`.
  - Tests: la conciliación usa la última OK menos 10 minutos; la importación inicial filtra por fecha.

## Bloque E: Despacho (DDEV-13)

- [x] **T10: Fulfillment orders**
  Satisfies: US-4
  Depends on: T9
  Notas:
  - `mark_packed`, `mark_dispatched` y `mark_delivered` encolan la tarea `tn_fulfillment_update`.
  - La tarea:
    - hace el PATCH de status y tracking, o un tracking event "delivered" para la entrega;
    - si ya está en ese estado, no hace nada;
    - reintenta con backoff y, si se agota, emite la alerta `integration.write_failed`;
    - audita `order.status_changed`.
  - Tests: cada transición, ya en estado, error → reintentos → alerta, y que no se llame a ningún endpoint de productos.

## Bloque F: Panel, spike y prueba real

- [x] **T11: Tarjeta de Tiendanube en el panel**
  Satisfies: US-1, US-2, US-3
  Depends on: T4, T7, T9
  Notas:
  - Botones Conectar/Reconectar, Importar catálogo e Importar pedidos.
  - Muestra el estado: tienda, scopes y modo webhooks o consulta.
  - Tests de permisos.

- [x] **T12: Guía para crear la app en Partners**
  Satisfies: US-1
  Notas:
  - `docs/runbooks/tiendanube-app.md` con el paso a paso para el usuario:
    - crear la app;
    - scopes;
    - URL de redirección;
    - webhooks de privacidad;
    - qué valores copiar al `.env`.

- [ ] **T13: Prueba con la tienda real y spike de Envío Nube (DDEV-14)**
  Satisfies: US-1, US-2, US-3, US-5
  Depends on: T11, T12 (y que el usuario haya creado la app)
  Notas:
  - Conectar la tienda 8434848, importar el catálogo (verificar ≈282 productos y 719 variantes) e importar los pedidos de 30 días. Todo en lectura.
  - Spike en `docs/spikes/envio-nube.md` (solo GET).
  - Probar el despacho únicamente sobre un pedido de prueba creado para eso.

- [ ] **T14: Cierre de M1**
  Depends on: T1–T13
  Notas: suite completa en verde, CI, trazabilidad contra requirements y actualización de DDEV-10..14 en Plane.

## Qué depende del usuario

- **T12–T13:** crear la app en Tiendanube Partners (requiere aceptar términos) y cargar `TN_APP_ID`, `TN_CLIENT_SECRET` y `TN_USER_AGENT` en `.env`. Hasta entonces, T1–T11 se completan con la API simulada.
