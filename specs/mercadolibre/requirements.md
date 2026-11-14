# Requirements: Integración Mercado Libre (módulo M2)

**Status:** Approved (2026-11-14)
**Last updated:** 2026-11-14
**Tickets:** DDEV-15 a DDEV-23 (M2-01 … M2-09)
**Depende de:** M0 (framework de integraciones, modelo de datos), ya hecho. M1 aporta el patrón de adaptador y el catálogo de Tiendanube.

## Summary

Conectar el sistema con la cuenta vendedora de Deutsch en Mercado Libre, el canal con ~77 % de los pedidos. El sistema:

- lee publicaciones y variaciones;
- recibe todas las ventas, agrupadas por pack;
- sigue los envíos (Flex, Full y las demás modalidades) y baja las etiquetas;
- lee y responde preguntas y mensajes postventa;
- recibe reclamos y devoluciones;
- guarda los datos de facturación del comprador.

Nunca escribe stock ni precio. La facturación y el stock de Mercado Libre los maneja la integración de Contabilium con ML.

M2 entrega la integración, sus servicios y los datos. Las pantallas de trabajo (bandeja de preguntas, mensajes, reclamos, salud de publicaciones) son M6.

## Goals

- Que cada venta de Mercado Libre aparezca en el sistema en menos de 1 minuto con servidor, sin perder ninguna, y que las compras de varios productos (pack) queden en un solo pedido.
- Saber, para cada venta, cómo se envía y hasta cuándo hay que despacharla, y tener la etiqueta lista para imprimir.
- Tener preguntas, mensajes y reclamos en el sistema, con la posibilidad de responder desde el sistema.
- Que el token de Mercado Libre se renueve solo y que, si falla, avise antes de que se corten los pedidos.

## Non-goals

- Escribir stock o precio en Mercado Libre (regla de oro). Los métodos existen pero están bloqueados por el interruptor.
- Pantallas de preguntas, mensajes, reclamos y salud de publicaciones (M6), y edición masiva de publicaciones (M6-05).
- Facturar ventas de Mercado Libre: lo hace Contabilium. En M2 solo se guardan los datos fiscales del comprador.
- Respuestas automáticas o con IA a preguntas (decisión del PRD).
- Catálogo maestro unificado TN + ML (M3).

## User stories

### US-1: Conectar la cuenta y mantener el token (DDEV-15)

Como administrador de Kei, quiero que la cuenta vendedora de Deutsch autorice una app del sistema, para leer y operar Mercado Libre sin depender de otra herramienta.

**Acceptance criteria:**

- THE APP SHALL estar suscripta a los tópicos `orders_v2`, `shipments`, `questions`, `messages`, `claims` e `items`.
- WHEN el dueño de la cuenta autoriza la app (OAuth) THE SYSTEM SHALL guardar cifrados el access token, el refresh token, el vencimiento y el ID del vendedor.
- THE SYSTEM SHALL renovar el access token antes de que venza, guardando el refresh token nuevo que devuelve ML porque el anterior deja de servir.
- IF la renovación falla THEN THE SYSTEM SHALL reintentar y, si sigue fallando, SHALL emitir la alerta `integration.disconnected` con lo que hay que hacer (reautorizar).
- IF una llamada a la API devuelve token inválido THEN THE SYSTEM SHALL intentar una renovación y repetir la llamada una sola vez.
- THE SYSTEM SHALL poder trabajar con usuarios de prueba de Mercado Libre, para testear sin tocar la cuenta real.
- WHEN llega una notificación de Mercado Libre THE SYSTEM SHALL aceptar solo las de la app y el vendedor configurados, y SHALL responder de inmediato. La notificación no viene firmada: el dato real siempre se lee de la API.

### US-2: Publicaciones (DDEV-16)

Como Deutsch, quiero tener en el sistema todas las publicaciones de Mercado Libre con sus variaciones, para vincularlas al catálogo y operar sobre ellas.

**Acceptance criteria:**

- WHEN se corre la importación inicial THE SYSTEM SHALL traer todas las publicaciones (activas, pausadas y cerradas recientes) con título, estado, tipo de publicación, categoría, precio, stock propio y stock en Full, modalidad de envío, atributos, fotos, permalink y variaciones, contemplando el modelo de User Products.
- THE SYSTEM SHALL asociar cada publicación o variación a la variante del catálogo por SKU (atributo `SELLER_SKU` o `seller_custom_field`) cuando lo tiene, y SHALL guardar el vínculo como `ExternalRef` de Mercado Libre.
- IF una publicación o variación no tiene SKU o su SKU no existe en el catálogo THEN THE SYSTEM SHALL guardarla igual y SHALL marcarla para revisión (informe de calidad de datos, M3-03).
- WHEN llega una notificación de `items` THE SYSTEM SHALL releer la publicación y actualizarla.
- THE SYSTEM SHALL correr una conciliación diaria de publicaciones.
- THE SYSTEM SHALL guardar stock y precio de Mercado Libre solo como dato del canal (para comparar en M3-02). No SHALL alimentar el stock del sistema ni escribir en Mercado Libre.

### US-3: Ventas y packs (DDEV-17)

Como Deutsch, quiero que cada venta de Mercado Libre aparezca sola en el sistema, agrupada por pack cuando el comprador compró varios productos.

**Acceptance criteria:**

- WHEN llega una notificación de `orders_v2` THE SYSTEM SHALL leer la orden y crear o actualizar el pedido con sus líneas por SKU (vinculadas a la variante si existe), comprador, totales, pago y envío.
- THE SYSTEM SHALL agrupar en un solo pedido (`SalesDocument`) todas las órdenes de un mismo pack. Una orden sin pack es su propio pedido.
- THE SYSTEM SHALL reflejar cancelaciones y cambios de estado en `channel_status`, sin tocar el estado interno (M4).
- IF el mismo pedido llega varias veces o fuera de orden THEN THE SYSTEM SHALL tener un solo documento con la versión más nueva.
- THE SYSTEM SHALL correr una conciliación periódica que trae las órdenes modificadas en las últimas 48 h (y desde la última conciliación exitosa).
- WHEN se conecta la cuenta THE SYSTEM SHALL importar las ventas de los últimos 30 días.
- IF una línea tiene un SKU que no está en el catálogo THEN THE SYSTEM SHALL guardarla igual y SHALL emitir la alerta `catalog.unknown_sku`.

### US-4: Envíos (DDEV-18)

Como depósito, quiero saber cómo se envía cada venta y hasta cuándo tengo para despacharla, y tener la etiqueta lista.

**Acceptance criteria:**

- THE SYSTEM SHALL identificar la modalidad de cada envío: **Flex**, **Full**, **Colecta**, **punto de entrega / correo**, **acordar con el vendedor** u **otra**.
- WHILE el envío es Flex o Colecta THE SYSTEM SHALL guardar la fecha y hora límite de despacho y SHALL poder bajar la etiqueta en **PDF 10×15 y en ZPL**. El formato por defecto se configura (`ML_LABEL_FORMAT`), porque la impresora todavía no está confirmada.
- WHILE el envío es Full THE SYSTEM SHALL marcar el pedido como despachado por Mercado Libre: no se prepara en el depósito.
- WHEN llega una notificación de `shipments` THE SYSTEM SHALL actualizar el estado del envío (listo para despachar, despachado, entregado, no entregado, cancelado), hasta entregado.
- IF la etiqueta todavía no está disponible (por ejemplo, venta sin pagar) THEN THE SYSTEM SHALL informarlo sin error y SHALL permitir reintentar.

### US-5: Preguntas (DDEV-19)

Como vendedor, quiero recibir las preguntas de Mercado Libre en el sistema y responderlas desde ahí.

**Acceptance criteria:**

- WHEN llega una notificación de `questions` THE SYSTEM SHALL guardar la pregunta con su publicación, el comprador (apodo) y el estado.
- THE SYSTEM SHALL ofrecer un servicio para responder una pregunta que envía la respuesta a ML y registra quién respondió y cuándo (auditoría `ml.question_answered`).
- IF ML rechaza la respuesta (pregunta borrada, usuario bloqueado, ya respondida, texto inválido) THEN THE SYSTEM SHALL marcar la pregunta con el motivo y SHALL NOT romper la bandeja ni perder la respuesta escrita.
- THE SYSTEM SHALL conciliar periódicamente las preguntas sin responder.

### US-6: Mensajes postventa (DDEV-20)

Como vendedor, quiero ver y responder los mensajes postventa de cada venta desde el sistema.

**Acceptance criteria:**

- WHEN llega una notificación de `messages` THE SYSTEM SHALL guardar el mensaje asociado al pack o pedido, con remitente, texto, adjuntos y fecha.
- THE SYSTEM SHALL ofrecer un servicio para enviar una respuesta (texto y adjuntos permitidos por ML) y registrarla en auditoría (`ml.message_sent`).
- IF ML restringe la mensajería (conversación bloqueada, límite de caracteres, plantilla obligatoria, venta Full sin mensajería abierta) THEN THE SYSTEM SHALL mostrar el motivo y SHALL NOT enviar.

### US-7: Reclamos y devoluciones (DDEV-21)

Como Deutsch, quiero recibir reclamos y devoluciones de Mercado Libre asociados al pedido, para responder a tiempo.

**Acceptance criteria:**

- WHEN llega una notificación de `claims` THE SYSTEM SHALL guardar el reclamo con tipo, estado, motivo, etapa y plazo de respuesta, asociado al pedido.
- THE SYSTEM SHALL detectar si el reclamo tiene una devolución y seguir su estado (en camino, entregada al depósito, cerrada).
- WHEN un reclamo nuevo requiere acción del vendedor THE SYSTEM SHALL emitir una alerta (`ml.claim_opened`) para Administrador y Ventas.

### US-8: Datos de facturación del comprador (DDEV-22)

Como Deutsch, quiero tener los datos fiscales del comprador de cada venta, para consultarlos hoy y facturar desde el sistema en el futuro.

**Acceptance criteria:**

- WHEN se importa una venta THE SYSTEM SHALL leer los datos de facturación del comprador (tipo y número de documento, condición de IVA, nombre o razón social, domicilio fiscal) y SHALL guardarlos en el cliente (modelo con datos fiscales) y en el pedido.
- IF la venta no tiene datos de facturación THEN THE SYSTEM SHALL dejar al cliente como consumidor final sin pisar datos existentes.

### US-9: Spike de convivencia con Contabilium (DDEV-23)

Como Kei, quiero saber si la integración de Contabilium con ML pisa lo que editemos desde el sistema, para definir qué campos son seguros en la edición masiva (M6-05).

**Acceptance criteria:**

- THE SPIKE SHALL documentar en `docs/spikes/ml-contabilium.md` la prueba: editar una publicación de prueba desde la API (título, descripción, atributos, fotos) y esperar una sincronización de Contabilium.
- THE SPIKE SHALL dejar la lista de campos seguros y de campos que Contabilium controla.
- Este spike depende de que la integración Contabilium ↔ ML esté activa (externo). Mientras tanto queda pendiente.

## Constraints

- **Regla de oro:** no se escribe stock ni precio. Las escrituras permitidas son respuestas a preguntas y mensajes (y, en M6-05, campos seguros según US-9).
- **Token:** dura pocas horas y el refresh token es de un solo uso. La renovación tiene que ser atómica: dos workers no pueden renovar a la vez.
- **Notificaciones:** ML exige respuesta rápida (HTTP 200) y reintenta si no la recibe. Las notificaciones no están firmadas.
- **Sin servidor todavía** (igual que M1): ventas, envíos, preguntas, mensajes y reclamos entran por consulta periódica cada 5 minutos. Las notificaciones se activan con el despliegue.
- La app en Mercado Libre Developers la crea Kei, y la autorización la tiene que hacer el dueño de la cuenta de Deutsch: necesita a Deutsch. Hasta entonces se desarrolla con la API simulada y, si hace falta, con usuarios de prueba de ML.
- Límites de la API de ML: el cliente común de M0 respeta los 429.

## Open questions

Ninguna bloqueante. Decisiones tomadas el 2026-11-14:

- **Etiquetas:** PDF 10×15 y ZPL, con formato por defecto configurable hasta confirmar la impresora.
- **Modalidades de envío:** se identifican todas; Flex y Full tienen tratamiento especial.
- **Sin servidor:** consulta cada 5 minutos, igual que Tiendanube.
- **Ventas iniciales:** últimos 30 días al conectar, igual que Tiendanube.
- **Pendiente con Deutsch, no bloquea:** que el dueño de la cuenta autorice la app, y la fecha en que se active la integración Contabilium ↔ ML (para el spike US-9).
