# Tasks: Cierre y lanzamiento · M9-02 (prueba punta a punta) y M9-03 (cuentas e invitaciones)

**Status:** M9-03 Hecho (2026-11-18), el envío real queda apagado hasta el lanzamiento · M9-02 Hecho (2026-11-20), salvo lo pendiente de terceros
**Design:** [design.md](./design.md)

- [x] **T1: Modelo y migraciones.** `accepted_terms_at` admite vacío; modelo `Invitation`; plantilla `invitation` (0005 y 0006). Settings `STORE_INVITATIONS_ENABLED` (False), `STORE_INVITATION_DAYS`, `STORE_INVITATIONS_PER_HOUR`, `STORE_INVITATION_REQUESTS_PER_IP_HOUR`, `STORE_EMAIL_DRY_RUN`; `.env.example`.
- [x] **T2: Preparar.** `invitations.plan/prepare`, comando `invitar_mayoristas preparar [--dry-run]`, informe de no incluidos con motivo. Idempotente, vincula registros propios.
- [x] **T3: Aceptar.** Pantalla `/mayorista/invitacion/<token>/` y pedir otro enlace desde el ingreso, con respuesta genérica y límite de ritmo.
- [x] **T4: Enviar.** `send_invitations` con interruptor, permiso, límite por hora, ensayo y reenvío; comandos `estado` y `enviar`. `invitation` en `NEVER_EXPIRE`.
- [x] **T5: Seguimiento en el panel.** Totales, tabla filtrable, no incluidos, enviar/reenviar, corrección de email con auditoría; enlace oculto en "Emails pendientes".
- [x] **T6: Tests.** `tests/test_invitaciones.py` (36 casos); se ajustaron dos tests existentes (lista de plantillas y de vistas públicas de la tienda).
- [x] **T7: Preparación real.** `invitar_mayoristas preparar` corrido una vez sobre la base local; no se encoló ningún email.
- [ ] **Pendiente (lanzamiento):** revisar el texto de la plantilla `invitation`, configurar SMTP, definir quién habilita la cuenta corriente, corregir en Contabilium los clientes no incluidos, prender `STORE_INVITATIONS_ENABLED` y enviar.

## US-2 · Prueba punta a punta (DDEV-57) · Hecho (2026-11-20), salvo lo pendiente de terceros

- [x] **P1: Guion.** `docs/runbooks/prueba-punta-a-punta.md`: un bloque por rol (Maico, Joaquín, Sergio, ventas, un vendedor) con tabla de pasos, casilla ✔/✘ y «qué vi»; apartado «cómo anotar un error»; cómo preparar el ensayo; lo pendiente de terceros marcado. (R2.1, R2.2, R2.5)
- [x] **P2: Datos de ensayo.** `manage.py seed_demo_launch` (`apps/core/management/commands/`): se niega en producción, exige `--yes`, es idempotente, imprime contraseñas al azar solo en consola, marca todo lo que crea y `--limpiar` lo borra sin tocar datos reales ni históricos. No manda emails ni toca canales. (R2.4)
- [x] **P3: Prueba automática.** `tests/test_punta_a_punta.py` y `tests/punta_a_punta.py` (14 casos, ~17 s): mayorista transferencia (registro a facturado y vencimiento), efectivo y cuenta corriente, faltante con crédito y devolución, ML Flex y Full, TN Envío Nube y retiro (solo escribe el estado de envío), alertas, invitación de punta a punta y el propio seed. Corre en el CI actual. (R2.3)
- [x] **P4: Sin bugs de lógica nuevos.** La prueba no encontró errores en los circuitos; el único ajuste fue de diseño del seed: la auditoría es inmutable y protege a los usuarios que nombra, así que `--limpiar` desactiva (no borra) a un usuario de ensayo que figure en ella.
- [ ] **Pendiente de terceros (R2.5):** pedido facturado y anulado en Contabilium/ARCA; edición masiva de ML (espera el spike DDEV-23); Envío Nube real y etiqueta real de ML; impresora térmica; emails reales (servidor y SMTP). Que las personas de Deutsch hagan la prueba con el guion y que Kei corrija lo que salga.
