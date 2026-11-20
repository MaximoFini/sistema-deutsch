# Design: Cierre y lanzamiento · M9-03 (cuentas e invitaciones)

**Status:** US-3 implementado (2026-11-18) · US-2 implementado (2026-11-20, salvo lo pendiente de terceros); US-1 y US-4 no están en este documento
**Requirements:** [requirements.md](./requirements.md) (US-3, R3.1 a R3.8; US-2, R2.1 a R2.5)

## Qué cambió respecto de lo aprobado

R3.1 y R3.2 hablaban de importar un archivo. Los 642 clientes mayoristas ya están cargados en la base (`Customer`, desde Contabilium), así que el importador parte de ellos y no de un Excel. La validación (CUIT módulo 11, email, repetidos) es la misma; la "vista previa con errores" es el informe de **no incluidos**. No hay plantilla descargable.

## Modelo

- `CustomerAccount.accepted_terms_at` ahora admite vacío: el cliente acepta los términos al crear su contraseña.
- `Invitation` (una por cuenta): `status` (sin enviar, enviada, aceptada, vencida, rebotada), `token_hash` (SHA-256; el token nunca se guarda), `sent_to`, `sent_at`, `sent_count`, `expires_at`, `accepted_at`, `last_email` (el `OutboundEmail` de la cola). "Vencida" y "rebotada" se reflejan con `invitations.sync_states()` (enlace pasado de fecha, o email de la cola en estado "falló").
- Plantilla de email `invitation` (migración de datos, editable como las demás). Variables: `{cliente}`, `{enlace}`, `{vence}`. Está en `NEVER_EXPIRE`.

## Preparar (`apps/wholesale/invitations.py`, `manage.py invitar_mayoristas preparar [--dry-run]`)

`plan()` decide, sin escribir, qué pasa con cada `Customer` mayorista activo; `prepare()` lo aplica. Idempotente.

- Crea `User` con contraseña inutilizable (`set_unusable_password`), `CustomerAccount` aprobada y vinculada, `credit_enabled=False`, y una `Invitation` sin enviar. No toca el `Customer` (ni stock ni precios) y no encola emails.
- No incluidos, con motivo: sin email, email inválido, CUIT/documento inválido (DNI u otro tipo, o dígito verificador malo), email repetido (entre clientes o ya usado por otro usuario, incluidos los internos), CUIT repetido (entre clientes o ya usado por la cuenta de otro cliente). Si dos clientes comparten email o CUIT, ninguno entra hasta corregirlo.
- Un cliente que ya se había registrado solo con ese CUIT: se aprueba y vincula esa cuenta (conserva su contraseña, no se crea otra, no hay invitación). No se llama a `accounts.approve` para no encolar el email de "aprobamos tu cuenta".
- Volver a correrlo no duplica; no reactiva cuentas suspendidas ni cambia la cuenta corriente.

## Enviar (`send_invitations(accounts, user)`)

Apagado por defecto. Exige `STORE_INVITATIONS_ENABLED=true` (si no, `InvitationsDisabled` con el mensaje en castellano) y el permiso `wholesale.manage_customers`. Por cada cuenta genera un token (`secrets.token_urlsafe(32)`), guarda su hash, vence a los `STORE_INVITATION_DAYS` (7) y encola el email con `mail.enqueue`. Reenviar reemplaza el enlace anterior. Límite de ritmo `STORE_INVITATIONS_PER_HOUR` (200): lo que no entra queda para la próxima. Con `STORE_EMAIL_DRY_RUN=true` registra una acción de auditoría con la cantidad y las cuentas y no encola nada ni cambia estados. La cola sigue mandando solo si `STORE_EMAILS_ENABLED` (SMTP) está activo.

## Cliente (tienda)

- `/mayorista/invitacion/<token>/`: elige contraseña (validadores de Django), acepta términos, queda con sesión. Usado, vencido o inventado dan la misma pantalla y ofrecen pedir otro. Sin caché.
- `/mayorista/invitacion/pedir/`: CUIT + email. Siempre responde lo mismo. Solo manda si el interruptor está prendido, los datos coinciden con una cuenta con invitación sin aceptar y pasaron 15 minutos desde el último enlace. Límite por IP por hora (`STORE_INVITATION_REQUESTS_PER_IP_HOUR`, 5), campo trampa anti-bots. El ingreso tiene un enlace a esta pantalla.

## Panel (permiso `manage_customers`)

`/clientes-mayoristas/invitaciones/`: totales (invitados, sin enviar, enviadas, entraron, vencidas, rebotadas, no incluidos con motivos), tabla filtrable por estado y búsqueda, "Enviar invitaciones", "Reenviar a los que no entraron", "Enviar a los marcados", reenviar por fila y "Corregir email". Los botones de envío quedan deshabilitados con la explicación mientras el interruptor esté apagado. Corregir el email actualiza `User` y `Customer`, anula el enlace ya enviado (y el email pendiente en la cola), y deja auditoría `invitation.email_corrected` con el antes y el después. La pantalla "Emails pendientes" oculta el enlace personal de las invitaciones.

## Seguridad

- Ingreso bloqueado antes de aceptar: contraseña inutilizable; "recuperar contraseña" tampoco manda nada a esos usuarios. `axes` sigue protegiendo el ingreso.
- Sin enumeración: pedir otro enlace responde igual exista o no la cuenta; token inválido da una sola pantalla.
- El token solo se guarda como hash; no aparece en logs ni en auditoría (test). Viaja únicamente en el email de la cola.
- Permisos: las vistas del panel exigen `manage_customers`; un cliente de la tienda es redirigido a la tienda.

## Fuera de alcance / pendiente

SMTP y envío real (DDEV-7), importar cuenta corriente y límites desde un archivo (se habilita aparte), pantalla de control de lanzamiento (US-4).

---

# US-2 · Prueba punta a punta (DDEV-57)

## Piezas

- **Guion** (`docs/runbooks/prueba-punta-a-punta.md`, R2.1, R2.2, R2.5): un bloque por rol con tabla de pasos, resultado ✔/✘ y «qué vi». Lo que depende de terceros se marca «pendiente de tercero» y no cuenta como falla.
- **Datos de ensayo** (`manage.py seed_demo_launch`, R2.4).
- **Prueba automática** (`tests/test_punta_a_punta.py`, `tests/punta_a_punta.py`, R2.3): cada test recorre un circuito por las pantallas y los servicios reales, con canales simulados.

## `seed_demo_launch`

- Seguridad: no corre si `ENVIRONMENT_NAME` es `prod`/`production`; sin `--yes` no hace nada; todo en una transacción.
- Marca: productos «ENSAYO …» con SKU `ENS-…`; clientes «ENSAYO …» con email `@ensayo.invalid`; usuarios `@ensayo.invalid`; pedidos de esos clientes o productos o con referencia «ENSAYO …»; expreso «ENSAYO Expreso». `--limpiar` borra exactamente eso: nunca un pedido histórico (`is_historical`) ni nada sin la marca.
- Idempotente: lo que existe se reutiliza; los pedidos no se arman dos veces. Contraseñas: al azar (14 caracteres sin letras confusas), impresas una vez en la consola, no se guardan; `--nuevas-claves` genera otras.
- Mudo: durante el seed `mail.enqueue` y `alerts.emit` están anulados (no queda ni una fila en la cola de emails ni un aviso, que podría mandar email) y los pedidos de ML y TN se crean sin `ExternalRef`, así que despacharlos no encola ninguna escritura al canal. Los pedidos mayoristas se arman con `checkout.place_order` (el camino real), cargados por el vendedor en nombre del cliente para no necesitar el mínimo de compra.
- Limpieza y auditoría: `AuditLog` es inmutable y protege a los usuarios que nombra, así que un usuario de ensayo que figure en ella (el vendedor, por ejemplo) no se borra: queda desactivado, sin contraseña y sin grupos, y el seed lo reactiva si se vuelve a correr. Si algo que no es de ensayo depende de un dato de ensayo, no se borra nada (todo o nada) y avisa.

## Prueba automática: circuitos (letras del guion)

| | Circuito |
|---|---|
| a | Mayorista transferencia: registro, aprobación, catálogo, carrito, checkout, comprobante, confirmar pago, tanda y picking, despacho, facturado y reserva liberada; y vencimiento por falta de pago (con recordatorio y saldo a favor). |
| b | Efectivo (se cobra al entregar) y cuenta corriente (no genera «sin cobrar»). |
| c | Faltante, crédito por faltante usado en el pedido siguiente y devolución recibida (el stock no lo mueve el sistema). |
| d | ML Flex (notificación, etiqueta, tanda, plazo, despacho, entregado por el canal, escaneado por el canal) y ML Full (lo despacha ML, no se prepara). |
| e | TN Envío Nube y retiro: solo se escribe el estado de envío; ninguna llamada a productos, stock o precios sale a ningún canal. |
| f | Alertas: sin cobrar, sin facturar, plazo de Flex y reclamos; un histórico no genera ninguna. |
| g | Invitación: habilitar, ensayo, envío simulado (locmem), enlace, contraseña, ingreso y token usado. |
| h | Cada circuito comprueba que no quedaron avisos ni emails de más (`assert_only`); el seed es seguro, idempotente y se limpia. |

Los canales son `respx` con `assert_all_mocked` (una llamada no declarada rompe el test) y el correo es locmem. La regla de oro se verifica de dos maneras: `guard.ensure_write_allowed` parcheado para fallar y revisión de todas las llamadas HTTP salientes.
