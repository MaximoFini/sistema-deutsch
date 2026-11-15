# Auditoría M6 (2026-11-15)

Revisión de la operación de Mercado Libre: preguntas, mensajes, reclamos y salud.

## Bugs y errores de lógica

| # | Gravedad | Hallazgo | Corrección |
|---|---|---|---|
| A1 | **Alta** | **Mensaje duplicado al comprador.** El botón "Enviar mensaje" no se bloquea, y un doble clic (o reenviar el formulario) manda el mismo mensaje dos veces. ML no lo frena. Con las preguntas no pasa porque ML rechaza la segunda respuesta, pero aparece un error confuso. | (1) Bloquear "Enviar respuesta" y "Enviar mensaje" al enviar ("Enviando…"), como en M5. (2) Del lado del servidor, si en esa conversación ya se envió el mismo texto en los últimos 2 minutos, no reenviarlo y avisar "Ese mensaje ya se envió". (3) Si la pregunta ya figura respondida, no llamar a ML: avisar y mostrar la respuesta. |
| A2 | **Alta** | **Avalancha de avisos al conectar ML.** La primera vez que se importan las preguntas sin responder (las viejas incluidas), la tarea manda un aviso por cada una que pasó 12 h. En la prueba fueron 749 avisos de una vez. Lo mismo pasa con los reclamos ya cerca del plazo. | Avisar solo por preguntas hechas en los últimos 3 días (configurable, `ML_QUESTION_ALERT_MAX_AGE_DAYS`). Si en una corrida hay más de 10 avisos nuevos de preguntas, mandar uno solo de resumen ("Hay 37 preguntas sin responder hace más de 12 h") en lugar de uno por pregunta. |
| A3 | Media | **La tarea de avisos repite trabajo.** Cada 5 minutos recorre todas las preguntas viejas y todos los reclamos, y prueba crear el aviso de cada uno aunque ya exista. Con 1.000 preguntas viejas son 3.776 consultas y 2,4 s por corrida, para nada. | Saltear en la consulta las que ya tienen aviso: `Exists(Alert con ese dedupe_key)` o un campo `alerted_at`, lo que quede más simple. |
| A4 | Media | **La pantalla de una pregunta puede quedar colgada.** Si la guía de talles venció en el caché, se pide a ML dentro de la misma página, con el timeout normal de 20 s y 3 reintentos. Si ML está lento, la pregunta tarda más de un minuto en abrir. | Cargar la guía con HTMX después de mostrar la página (fragmento `/ml/preguntas/<pk>/talles/`), con un cliente de 4 s de timeout y sin reintentos. Mientras carga: "Cargando guía de talles…". Si falla, se muestra la del caché o nada. |
| A5 | Media | Al enviar un mensaje, si ML lo bloquea, se muestra el motivo en inglés tal como lo manda ML ("…: The message could not be sent because…"). | Traducir los motivos conocidos de ML (conversación cerrada, mediación en curso, límite de mensajes, comprador bloqueado). Para lo desconocido: "Mercado Libre no permite enviar este mensaje ahora. Probá respondiendo desde Mercado Libre." El texto original va al log. |
| A6 | Baja | Las variaciones en la pregunta salen como "Negro / M": el orden de los atributos lo decide Postgres, igual que lo que pasó en M5. | Usar el mismo orden que M5 (talle primero, después color) con una función compartida. |
| A7 | Baja | Si ML dice que la pregunta "ya fue respondida", M2 la marca respondida pero sin texto. En "Respondidas" aparece vacía hasta la próxima sincronización. | Mostrar "Respondida desde Mercado Libre (el texto llega en la próxima sincronización)" cuando no hay texto. |

## Rendimiento (3.000–5.000 elementos)

| Pantalla u operación | Volumen | Resultado |
|---|---|---|
| Preguntas sin responder | 5.000 preguntas | 0,03 s, 8 consultas |
| Reclamos | 500 reclamos | 0,03 s |
| Salud | 4.000 publicaciones | 0,53 s, 7 consultas |
| Contadores del menú | — | 0,02 s |
| **Mensajes** | 5.000 conversaciones / 20.000 mensajes (un año) | **1,14 s**: calcula el último mensaje de todas las conversaciones antes de paginar. |
| **Tarea de avisos** | 1.000 preguntas viejas | **2,4 s y 3.776 consultas cada 5 min** (ver A3) |

| # | Corrección |
|---|---|
| R1 | Mensajes: por defecto mostrar las conversaciones con actividad en los últimos 60 días, más todas las que tienen no leídos, con un enlace "Ver más viejas". Calcular el último texto solo para las filas de la página. Objetivo: menos de 0,3 s con un año de mensajes. |
| R2 | Agregar a `test_rendimiento.py` un caso con muchas conversaciones y otro para la tarea de avisos (cantidad de consultas acotada en la segunda corrida). |
