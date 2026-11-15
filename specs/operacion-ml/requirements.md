# Requirements: Operación de Mercado Libre (módulo M6)

**Status:** Approved (2026-11-14)
**Last updated:** 2026-11-14
**Tickets:** DDEV-36 (M6-01), DDEV-37 (M6-02), DDEV-38 (M6-03), DDEV-39 (M6-04). DDEV-40 (M6-05, edición masiva) se pospone hasta el spike DDEV-23.
**Depende de:** M2 (preguntas, mensajes, reclamos y publicaciones de ML ya se guardan y se pueden responder por API), M3 (catálogo y stock), M4 (estado Con reclamo) y M0 (alertas, permisos).

## Summary

Las pantallas para atender Mercado Libre desde el sistema sin entrar a ML:

- bandeja de **preguntas**, con la publicación, el stock por talle y color y la guía de talles a la vista, y respuestas guardadas;
- bandeja de **mensajes postventa** por pedido;
- **reclamos** con su plazo y avisos antes de que venza;
- **salud de publicaciones**, para ver qué está pausado, con problemas o con baja calidad.

M2 ya trae los datos y las funciones para responder. M6 agrega las pantallas, los permisos y las alertas.

## Goals

- Responder preguntas rápido y bien: sin cambiar de pantalla para saber si hay stock de un talle.
- Que ningún mensaje postventa quede sin leer.
- Que ningún reclamo venza sin respuesta, para no perder reputación.
- Saber qué publicaciones tienen problemas y por qué.

## Non-goals

- **Edición masiva de publicaciones (M6-05):** se pospone hasta que el spike DDEV-23 confirme qué campos no pisa Contabilium.
- Responder con IA: fuera de la fase 1 (decisión del PRD).
- Responder un reclamo o gestionar la mediación desde el sistema: se responde en Mercado Libre con un enlace directo. El sistema muestra, ordena y avisa.
- Modificar publicaciones (incluida la reactivación de pausadas): queda para M6-05 o se hace en ML.
- Preguntas o mensajes de Tiendanube: TN no tiene ese circuito por API.

## User stories

### US-1: Bandeja de preguntas (DDEV-36)

Como Ventas o Vendedor, quiero responder las preguntas de ML con la ficha del producto y el stock a la vista, para responder rápido y bien.

**Acceptance criteria:**

- THE SYSTEM SHALL tener una pantalla "Preguntas" con las preguntas sin responder, de la más vieja a la más nueva, y un contador en el menú.
- THE SYSTEM SHALL mostrar en cada pregunta el texto, el comprador, cuánto hace que la hicieron (en rojo si pasaron más de 12 horas, configurable) y la publicación (título, foto y enlace a ML).
- WHEN se abre una pregunta THE SYSTEM SHALL mostrar al lado:
  - las variaciones de la publicación con el stock en Mercado Libre por talle y color;
  - el stock del catálogo maestro de cada variante vinculada;
  - la guía de talles de la publicación en ML, si tiene;
  - las preguntas anteriores de esa publicación con su respuesta (hasta 10).
- THE SYSTEM SHALL permitir escribir la respuesta y enviarla a ML con la función de M2. IF Mercado Libre la rechaza (pregunta borrada, texto con datos de contacto, demasiado largo) THEN THE SYSTEM SHALL mostrar el motivo en castellano y conservar el texto escrito.
- THE SYSTEM SHALL mostrar una lista de respondidas (por quién, cuándo, desde el sistema o desde ML) con búsqueda por texto y publicación.
- THE SYSTEM SHALL permitir guardar **respuestas guardadas** (título y texto) compartidas por todo el equipo, e insertarlas en la respuesta para editarlas antes de enviar. Las crean y editan Ventas y Administrador.
- WHEN una pregunta lleva más de 12 horas sin responder (configurable) THE SYSTEM SHALL emitir la alerta `ml.question_unanswered_long` (tipo que ya existe) a Ventas y Administrador, una vez por pregunta.
- THE SYSTEM SHALL auditar cada respuesta enviada desde el sistema.

### US-2: Bandeja de mensajes postventa (DDEV-37)

Como Ventas o Vendedor, quiero ver las conversaciones de cada venta con los no leídos destacados y responder desde el sistema.

**Acceptance criteria:**

- THE SYSTEM SHALL tener una pantalla "Mensajes" con una fila por conversación (venta o pack): comprador, pedido, último mensaje, fecha y cantidad de no leídos. Primero las que tienen no leídos, después por fecha del último mensaje.
- THE SYSTEM SHALL mostrar un contador de conversaciones con no leídos en el menú.
- WHEN se abre una conversación THE SYSTEM SHALL mostrar todos los mensajes en orden (del comprador y nuestros), con adjuntos como enlace, y SHALL marcar como leídos los del comprador.
- THE SYSTEM SHALL permitir responder desde la conversación con la función de M2. IF Mercado Libre bloquea el envío (por ejemplo, conversación cerrada o con mediación) THEN THE SYSTEM SHALL explicar el motivo en castellano y conservar el texto.
- THE SYSTEM SHALL mostrar en la conversación el estado del pedido y un enlace a su ficha. La ficha del pedido (M4) SHALL enlazar a la conversación.
- THE SYSTEM SHALL auditar cada mensaje enviado desde el sistema.

### US-3: Reclamos con plazos y alertas (DDEV-38)

Como Ventas, quiero ver los reclamos abiertos con su plazo para no perder reputación en ML.

**Acceptance criteria:**

- THE SYSTEM SHALL tener una pantalla "Reclamos" con los abiertos primero, ordenados por plazo de respuesta (el más urgente arriba), y los cerrados en una pestaña aparte.
- THE SYSTEM SHALL mostrar por reclamo:
  - tipo y motivo en castellano;
  - pedido asociado con enlace a su ficha;
  - comprador;
  - si requiere acción nuestra;
  - el plazo restante ("vence en 5 h", en rojo si faltan menos de 24 h);
  - si hay devolución y en qué estado;
  - enlace para responderlo en Mercado Libre.
- WHEN un reclamo que requiere acción nuestra está a menos de **24 horas** de su plazo THE SYSTEM SHALL avisar a Ventas y Administrador. WHEN está a menos de **4 horas** THE SYSTEM SHALL volver a avisar. Ambos umbrales son configurables, y no se repite el aviso por el mismo reclamo y umbral.
- THE SYSTEM SHALL mantener el pedido en Con reclamo mientras el reclamo esté abierto (regla de M4, ya existente) y mostrarlo en la ficha del pedido.
- El aviso de reclamo nuevo (`ml.claim_opened`) SHALL llevar a la ficha del reclamo, no a Integraciones.

### US-4: Salud de publicaciones (DDEV-39)

Como Ventas, quiero ver qué publicaciones de ML tienen problemas y por qué, para corregirlas.

**Acceptance criteria:**

- THE SYSTEM SHALL tener una pantalla "Salud de publicaciones" con las publicaciones activas o pausadas que tengan al menos un problema:
  - **pausada**, con el motivo de ML si lo informa (por ejemplo, sin stock o pausada por ML);
  - **en revisión o con infracción** de ML;
  - **atributos obligatorios faltantes** o ficha técnica incompleta, según ML;
  - **calidad baja** según el puntaje de salud de ML (por debajo de un umbral configurable);
  - **revisar datos** del sistema (`needs_review` de M2: SKU faltante o repetido, entre otros).
- THE SYSTEM SHALL mostrar por publicación: foto, título, SKU, estado, cada problema con su motivo en castellano y un enlace para editarla en Mercado Libre.
- THE SYSTEM SHALL permitir filtrar por tipo de problema y buscar por título o SKU, y SHALL mostrar un contador por tipo de problema.
- THE SYSTEM SHALL permitir exportar la lista a Excel.
- WHEN exista la edición masiva (M6-05) THE SYSTEM SHALL permitir abrirla desde esta lista con las publicaciones filtradas. Hasta entonces, el enlace es a Mercado Libre.

## Constraints

- **Regla de oro:** M6 no escribe stock ni precios. Las únicas escrituras en ML son responder preguntas y enviar mensajes, con las funciones de M2.
- Sin servidor, preguntas, mensajes y reclamos entran por la conciliación periódica de M2 (cada 5 minutos). Con servidor entran por notificación.
- Permisos:
  - **Responder preguntas y mensajes:** Ventas, Administrador y Vendedor.
  - **Ver reclamos y salud de publicaciones:** Ventas y Administrador.
  - **Crear y editar respuestas guardadas:** Ventas y Administrador.
  - **Depósito:** no ve estas pantallas.
- Celular: las bandejas se usan desde el teléfono (lista y detalle apilados, botón de enviar grande).

## Open questions

- El texto exacto de los motivos de pausa y salud depende de lo que devuelva ML con la cuenta real. Se cargan los conocidos y lo desconocido se muestra tal cual.

## Decisiones tomadas

- **M6-05:** se pospone hasta el spike DDEV-23.
- **Responder:** Ventas, Administrador y Vendedor.
- **Avisos de reclamo:** 24 h y 4 h antes del plazo, configurables.
- **Guía de talles:** la de la publicación en ML, si existe.
