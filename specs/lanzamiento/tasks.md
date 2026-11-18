# Tasks: Cierre y lanzamiento · M9-03 (cuentas e invitaciones)

**Status:** Hecho (2026-11-18) · el envío real queda apagado hasta el lanzamiento
**Design:** [design.md](./design.md)

- [x] **T1: Modelo y migraciones.** `accepted_terms_at` admite vacío; modelo `Invitation`; plantilla `invitation` (0005 y 0006). Settings `STORE_INVITATIONS_ENABLED` (False), `STORE_INVITATION_DAYS`, `STORE_INVITATIONS_PER_HOUR`, `STORE_INVITATION_REQUESTS_PER_IP_HOUR`, `STORE_EMAIL_DRY_RUN`; `.env.example`.
- [x] **T2: Preparar.** `invitations.plan/prepare`, comando `invitar_mayoristas preparar [--dry-run]`, informe de no incluidos con motivo. Idempotente, vincula registros propios.
- [x] **T3: Aceptar.** Pantalla `/mayorista/invitacion/<token>/` y pedir otro enlace desde el ingreso, con respuesta genérica y límite de ritmo.
- [x] **T4: Enviar.** `send_invitations` con interruptor, permiso, límite por hora, ensayo y reenvío; comandos `estado` y `enviar`. `invitation` en `NEVER_EXPIRE`.
- [x] **T5: Seguimiento en el panel.** Totales, tabla filtrable, no incluidos, enviar/reenviar, corrección de email con auditoría; enlace oculto en "Emails pendientes".
- [x] **T6: Tests.** `tests/test_invitaciones.py` (36 casos); se ajustaron dos tests existentes (lista de plantillas y de vistas públicas de la tienda).
- [x] **T7: Preparación real.** `invitar_mayoristas preparar` corrido una vez sobre la base local; no se encoló ningún email.
- [ ] **Pendiente (lanzamiento):** revisar el texto de la plantilla `invitation`, configurar SMTP, definir quién habilita la cuenta corriente, corregir en Contabilium los clientes no incluidos, prender `STORE_INVITATIONS_ENABLED` y enviar.
