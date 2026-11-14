# Auditoría M0–M4 (2026-11-14)

Revisión de lo construido hasta M4: olvidos contra specs, bugs, lógica, mensajes al usuario y rendimiento.

## Bugs y errores de lógica

| # | Gravedad | Hallazgo | Corrección |
|---|---|---|---|
| B1 | Alta | Un reclamo sobre un pedido **ya entregado** hace oscilar el estado Con reclamo → Entregado → Con reclamo en cada sincronización (3 registros de auditoría cada 5 min). Causa: la regla "entregado" de `sales/sync._target` se aplica también cuando el estado es Con reclamo. | La regla "entregado" no aplica si hay reclamo abierto o el estado es Con reclamo. Al cerrarse el reclamo vuelve al estado anterior y recién ahí corre "entregado". |
| B2 | Media | Mercado Libre: un pedido pagado con cupón o descuento (monto pagado < total) quedaría para siempre en Esperando pago, porque "pagado" se calcula sumando pagos ≥ total. | En ML, "pagado" también es verdadero si el estado del canal es `paid` en todas las órdenes del pack. |
| B3 | Media | "Cobrado" se calcula de 3 formas distintas (`manual.is_paid`: cualquier pago confirmado; filtro de la lista y `sync.facts`: suma ≥ total). Con un pago parcial la ficha dice "cobrado" y la lista "pendiente". | Una sola función `sales.payments.is_paid(doc)` usada por la ficha, la lista, las alertas y la sincronización. |
| B4 | Media | La revisión de Flex/Colecta por vencer corre cada 10 min; el requisito (US-5, constraints) pide 5 min o menos. | `orders_watch` cada 5 min. |
| B5 | Media | Si un worker se cae mientras procesa un evento, el evento queda en "procesando" para siempre y nadie lo reencola. | Tarea periódica que reencola eventos en procesando o pendientes sin tarea hace más de 15 min. |
| B6 | Media | Recepción de devolución: se puede registrar más cantidad que la esperada, y una cantidad con decimales. | Validar entero, mayor a 0 y no mayor que lo esperado. |
| B7 | Baja | "Llegó una devolución" crea primero una devolución esperada; si la persona abandona el formulario queda una esperada huérfana, y cada clic crea otra. | Si el pedido ya tiene una devolución esperada sin recibir, reutilizarla en lugar de crear otra. |
| B8 | Baja | La pantalla de recepción da error 500 si la devolución no tiene `ReturnInfo`. | 404 amable. |
| B9 | Baja | Pedido manual: se aceptan cantidades con decimales y precios negativos. Un producto inexistente da página 404 en lugar de error en el formulario. | Validar en `create_manual_order` y devolver el error en el formulario. |
| B10 | Baja | Al cambiar estado, el mensaje dice "Se informa a Tiendanube" aunque el pedido ya estaba en ese estado (no cambió nada). | Mensaje según si cambió o no. |
| B11 | Baja | `check_stock` usa `stock_levels.first()` sin orden (con más de un depósito puede tomar cualquiera). | Usar el depósito por defecto. |
| B12 | Baja | `check_manual_pending` recorre todos los pedidos manuales de la historia, uno por uno. | Filtrar en la consulta solo los pendientes de cobro o factura. |

## Mensajes que ve el cliente

| # | Hallazgo | Corrección |
|---|---|---|
| E1 | No hay páginas propias de error 404, 500 ni de CSRF vencido: en producción se ven las de Django, en inglés. | Plantillas `404.html`, `500.html` (sin depender de la base) y `403_csrf.html` en castellano. |
| E2 | El bloqueo por intentos fallidos de login muestra el texto en inglés de django-axes. | Plantilla propia: "Por seguridad bloqueamos el ingreso por 30 minutos…". |
| E3 | Alertas y la pantalla Integraciones muestran errores técnicos crudos ("ChannelHTTPError: GET /orders respondió 401"). | Traductor `integrations.errors.friendly(exc)`: 401/403 → "venció o se revocó la autorización, hay que reconectar"; 429 → "el canal limitó las consultas, se reintenta solo"; 5xx/timeout → "el canal no responde, se reintenta solo"; 404 → "el canal ya no tiene ese dato". El detalle técnico queda en el registro para Kei. |
| E4 | "Faltan ML_APP_ID o ML_REDIRECT_URI en la configuración" / "Falta TN_APP_ID" se muestran al usuario. | "La app de Mercado Libre todavía no está configurada en el sistema. Avisale a Kei Software." |
| E5 | "Mercado Libre rechazó el código (400)" y "No se pudo contactar a Mercado Libre: <error httpx>". | "La autorización venció o ya se usó: tocá Conectar de nuevo." / "Mercado Libre no responde. Probá en unos minutos." |
| E6 | "Importación … encolada" (jerga). | "Empezó la importación. Puede tardar unos minutos; los datos van apareciendo solos." |

## Rendimiento (medido con datos simulados)

| Pantalla | Volumen | Resultado |
|---|---|---|
| Pedidos (lista) | 12.000 pedidos | 0,66 s, 9 consultas. Cumple (< 1 s). |
| Ficha de pedido / variante | — | 15 consultas, ~30 ms. Sin N+1. |
| Catálogo, sin vincular, avisos, auditoría, devoluciones | 1.500 variantes | < 0,1 s, ≤ 8 consultas. |
| **Stock y precios por canal** | 6.000 variantes | **2,3 s y 4 MB de HTML** (muestra todo de una vez). |
| **Calidad de datos** | 6.000 variantes | **2,3 s y 10 MB de HTML**. |

| # | Corrección |
|---|---|
| P1 | Paginar "Stock y precios" y "Calidad" (100 filas por página, filtros que ya existen se mantienen). El Excel sigue exportando todo. |
| P2 | Índice para el orden de la lista de pedidos (envío por documento y fecha límite). |
| P3 | Test de regresión: la cantidad de consultas de las pantallas principales no crece con el volumen. |

## Olvidos contra specs

- `specs/mercadolibre/tasks.md` T17 quedó sin tildar aunque se hizo (commit, CI y Plane). Se tilda.
- TN T13–T14 siguen pendientes a propósito: dependen de la app de Tiendanube Partners.
- Requisito US-4 "registrar una devolución que llegó sin estar esperada, buscando el pedido": hoy se hace desde la ficha del pedido. Se agrega un buscador de pedido en la pantalla Devoluciones.
