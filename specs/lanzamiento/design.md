# Design: Cierre y lanzamiento · M9-03 (cuentas e invitaciones)

**Status:** Implementado (2026-11-18) · solo lo de US-3 / DDEV-58; US-1, US-2 y US-4 no están en este documento
**Requirements:** [requirements.md](./requirements.md) (US-3, R3.1 a R3.8)

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
