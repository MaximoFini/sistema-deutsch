# Tasks: Tienda mayorista · etapa A (módulo M8a)

**Status:** Done (2026-11-15) · etapa B (Contabilium, ARCA, subdominio) pendiente
**Last updated:** 2026-11-15
**Design:** [design.md](./design.md)

Ordenadas por dependencia. Cada tarea incluye sus tests. `§` = sección de design.md.

## Bloque A: Base

- [x] **T1: App `wholesale`, modelos, permisos, alertas y configuración**
  Satisfies: US-2–US-9
  Notas:
  - Modelos de §2 con migraciones: `StoreSettings` con su fila inicial y `EmailTemplate` con los textos propuestos (migración de datos).
  - Permisos de la tabla de §2 asignados a los roles, con etiquetas en castellano.
  - Las 5 alertas nuevas.
  - `private_storage` fuera de `MEDIA_ROOT`.
  - Settings `WHOLESALE_PATH`, `WHOLESALE_HOST` y `.env.example`.

- [x] **T2: Sistema de diseño de marca**
  Satisfies: US-1
  Depends on: T1
  Notas:
  - Leer el manual y el PDF de variantes del logo en Drive.
  - Tokens en `static/brand/tokens.css` con `@theme` de Tailwind; Source Sans 3.
  - Logo en SVG o PNG.
  - Componentes en `templates/store/components/` y `templates/store/base.html` con encabezado, pie y slogan.
  - Página `/mayorista/estilo/` solo para usuarios internos.
  - Contraste AA verificado.

- [x] **T3: Rutas, host y separación de accesos**
  Satisfies: US-2, US-7
  Depends on: T1
  Notas:
  - URLs en `/mayorista/` y `WholesaleHostMiddleware`.
  - `StoreAccessMixin`; el panel rechaza a los clientes.
  - Ingreso, salida y recuperación de contraseña con plantillas de la tienda, con el mismo bloqueo de axes.
  - Páginas legales desde `StoreSettings`.
  - Tests de que un cliente no entra al panel y un anónimo no ve la tienda.

## Bloque B: Clientes

- [x] **T4: Registro y aprobación**
  Satisfies: US-2
  Depends on: T3
  Notas:
  - `validate_cuit` (módulo 11).
  - Formulario de registro con campo trampa y límite por IP; estado pendiente.
  - Cola en el panel `/clientes-mayoristas/` con edición, aprobación (vincula o crea el `Customer`), rechazo con motivo, cuenta corriente y suspensión.
  - Auditoría y emails encolados.
  - Lista de clientes mayoristas y sus pedidos para Vendedor.

- [x] **T5: Cola de emails**
  Satisfies: US-6
  Depends on: T1
  Notas:
  - `mail.enqueue` con layout HTML de marca y versión texto.
  - Tarea `send_pending_emails` con reintentos y alerta.
  - Pantalla de plantillas editables y de emails pendientes en el panel.

## Bloque C: Compra

- [x] **T6: Catálogo y disponibilidad**
  Satisfies: US-3
  Depends on: T2, T3
  Notas:
  - `store_products`, `available` y `net_price`.
  - Listado con filtros, búsqueda y paginación; agotados al final.
  - Ficha con fotos y descripción de Tiendanube.
  - Rendimiento: 1.000 productos en menos de 1 s.

- [x] **T7: Grilla y carrito**
  Satisfies: US-4
  Depends on: T6
  Notas:
  - Grilla talles × colores con límites y totales en JS.
  - `Cart` persistente con netos, IVA y saldo a favor.
  - Mínimo con o sin IVA.

- [x] **T8: Checkout y reserva**
  Satisfies: US-4, US-5
  Depends on: T7
  Notas:
  - `place_order` con lock, detección de cambios por hash, precios congelados, `SalesDocument`, `Shipment`, `Payment`, `WholesaleOrder`, saldo aplicado y reserva.
  - Montos con IVA aparte (`recalculate_totals` para el canal mayorista).
  - Confirmación con próximos pasos.
  - Test de carrera por la última unidad.

## Bloque D: Operación

- [x] **T9: Pagos, vencimiento y centro de pedidos**
  Satisfies: US-5
  Depends on: T8, T5
  Notas:
  - Subida de comprobantes con validación de contenido y descarga protegida.
  - Confirmar pago en la ficha de M4.
  - Tarea de vencimiento y recordatorio.
  - Efectivo: "Cobrar $X" en la entrega.
  - Generalizar en M4 el cobro, la factura y la cancelación a "manual o mayorista".
  - Liberar la reserva al facturar o cancelar.
  - Filtros y colores del canal.

- [x] **T10: Pedidos en nombre de clientes**
  Satisfies: US-7
  Depends on: T8
  Notas:
  - Buscador, sesión `acting_customer_id`, franja visible.
  - Sin mínimo, `placed_by` y auditoría.
  - "Cargado por Deutsch" en el historial del cliente.

- [x] **T11: Mi cuenta**
  Satisfies: US-6
  Depends on: T9
  Notas:
  - Historial con estados para el cliente, detalle, seguimiento y comprobantes.
  - Repetir pedido.
  - Factura y saldo a favor.
  - Pedir cambio de datos.
  - Emails de despachado y listo para retirar vía señal.

- [x] **T12: Faltantes**
  Satisfies: US-8
  Depends on: T9
  Notas:
  - Marcar faltante desde la ficha y la tanda.
  - Resolución por línea con ajuste de reserva, saldo o reintegro, y corrección en Contabilium.
  - Estados vía `change_status`; email y alerta.

- [x] **T13: Reportes mayoristas**
  Satisfies: US-9
  Depends on: T9
  Notas:
  - Pestaña `/reportes/mayorista/` con Excel.
  - Presupuesto de consultas.

## Bloque E: Cierre

- [x] **T14: Spike de Contabilium, revisión y cierre**
  Depends on: T1–T13
  Notas:
  - `docs/spikes/contabilium-ecommerce.md`.
  - Suite y ruff en verde.
  - Revisión en el navegador (escritorio y celular): registro, aprobación, compra completa con cada medio de pago, pedido en nombre de, faltante.
  - Commit, push y CI.
  - Plane: tickets de M8a, más DDEV-35 y 42.
  - Resumen visual.

## Qué depende de Deutsch o de terceros

- Datos bancarios, días de vencimiento y textos legales: se cargan en el panel.
- Revisar los textos de los emails.
- Validar el sistema de diseño en `/mayorista/estilo/`.
- SMTP (DDEV-7) para que salgan los emails.
- Etapa B: Contabilium Ecommerce, ARCA y subdominio.
