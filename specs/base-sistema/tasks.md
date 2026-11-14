# Tasks: Base del sistema (módulo M0)

**Status:** In progress (aprobado 2026-11-14)
**Last updated:** 2026-11-14
**Design:** [design.md](./design.md)


> **Avance 2026-11-14:** T1–T22 hechos y verificados: 84 tests en verde contra Postgres 17 local, ruff limpio, `makemigrations --check` y `check --deploy` sin problemas, panel probado en el navegador (login, integraciones, usuarios), simulacro de restauración local OK. Pendiente: T23 (crear el repo en GitHub: falta definir la cuenta) y T24 (cierre).

Ordered by dependency. Each task includes its tests. `§` points to the design.md section.

## Bloque A: Proyecto y documentación

- [x] **T1: Django project skeleton with uv**
  Satisfies: US-3
  Notes: `pyproject.toml` with Python 3.12 (`uv python install 3.12`), Django 5.2, procrastinate, django-environ, httpx, cryptography, django-axes, django-htmx, django-tailwind-cli, sentry-sdk, gunicorn; dev group: pytest, pytest-django, factory-boy, responses, ruff, coverage. Structure per §2 (`config/` with base, local, test and prod settings; `apps/`; `tests/`). Settings read from env; `.env.example` without values. es-AR, America/Argentina/Buenos_Aires. `/health/` endpoint (DB check). Test: `/health/` returns 200.

- [x] **T2: Local database and README**
  Satisfies: US-3
  Depends on: T1
  Notes: create `deutsch_dev` and `deutsch_test` in the local Postgres 17. README with step-by-step setup on Windows without Docker (uv sync, createdb, migrate, runserver, worker). Check that `uv run pytest` passes.

- [x] **T3: ADR 0001 in the repo and in Plane**
  Satisfies: US-1, US-2
  Notes: `docs/adr/0001-arquitectura-base.md` with §1, §2 (component diagram), §8 (hosting: Hetzner approved, deployment deferred), §11 and §12 (ERP principles). Publish it as a page in Plane DDEV and link it from DDEV-1 and DDEV-2.

## Bloque B: Modelo de datos núcleo (DDEV-4)

- [x] **T4: `core` app: base models, money and source of truth**
  Satisfies: US-4
  Depends on: T1
  Notes: abstract `TimeStampedModel`; Decimal money helpers; `DataSource` model + data migration (all `contabilium`); `core.sources.is_owned_by_system()` and the `SourceOfTruthViolation` exception. Tests: initial values; a change to `system` is reflected; the exception is raised.

- [x] **T5: `catalog`, `inventory` and `pricing` apps**
  Satisfies: US-4
  Depends on: T4
  Notes: models per §3. `inventory.services.apply_sync_level(variant, warehouse, qty, source)` creates a `sync_adjustment` movement for the difference and updates `StockLevel` (the only way to touch stock). `pricing.services.current_price(list, variant, at)`. Default warehouse "Local" + MINORISTA/MAYORISTA lists by data migration. Tests: movement for the difference, no movement if the value is unchanged, price by validity date.

- [x] **T6: `customers` and `sales` apps**
  Satisfies: US-4
  Depends on: T5
  Notes: models per §3 (Customer, Address, SalesDocument with `doc_type` and `fiscal` JSON, SalesLine with snapshots, Payment, Shipment). Unique internal numbering per `doc_type` (Postgres sequence). Tests: numbering without collisions, totals, the return–order relation.

- [x] **T7: `integrations` models (Channel, ExternalRef, etc.) and ERD**
  Satisfies: US-4, US-9
  Depends on: T6
  Notes: Channel (+ seed of the 5 channels), ExternalRef with generic FK and uniqueness, ChannelCredential, ChannelWriteSwitch (seed: everything off), InboundEvent, SyncRun, RateLimitBucket. Generate the ERD as mermaid in `docs/erd.md`. Tests: the same external_id cannot be repeated per channel and type; one product can have IDs in 3 channels.

## Bloque C: Usuarios, permisos y auditoría (DDEV-5, DDEV-6)

- [x] **T8: Custom user, login and password recovery**
  Satisfies: US-5
  Depends on: T1 (must exist before the first migration, so it goes together with T4)
  Notes: `accounts.User` with login by email; login/logout/password reset views in Spanish (2 h token); django-axes; base panel layout (Tailwind + HTMX, header, menu by permissions). No signup URL. Tests: login OK/failed, single-use reset, inactive user cannot log in and an open session is cut.

- [x] **T9: Roles, specific permissions and denials**
  Satisfies: US-5
  Depends on: T8
  Notes: data migration with the groups Administrador, Depósito, Ventas and Vendedor and their M0 permissions; `UserPermissionDenial` model + auth backend that subtracts it; `PanelPermissionRequiredMixin`. Tests: added permission works, a role permission removed by denial is denied, 403 without data; test that walks every panel URL and fails if one has no declared permission.

- [x] **T10: "Usuarios" screens**
  Satisfies: US-5
  Depends on: T9
  Notes: list, create (sends the set-password email), edit role and permissions, deactivate/reactivate. Permission `accounts.manage_users`. Each change is audited (once T11 exists, recorded with `audit.record`). Tests with one user per role.

- [x] **T11: `audit` app**
  Satisfies: US-6
  Depends on: T8
  Notes: immutable `AuditLog` (save/delete blocked + Postgres trigger in a migration); `audit.record()`; action catalog `audit/actions.py`; "Auditoría" screen with filters by user, date and action (Administrador only). Tests: record with before/after, UPDATE/DELETE rejected by the database, filters, access denied to other roles.

## Bloque D: Alertas (DDEV-7)

- [x] **T12: `alerts` app: engine, email and panel**
  Satisfies: US-7
  Depends on: T9, T13
  Notes: AlertType (editable by the admin), Alert with dedupe, AlertReceipt; `alerts.emit()`; Procrastinate task `send_alert_email` with 5 retries; SMTP from env (console locally); bell with HTMX counter + "Avisos" page with read/unread. `emit_alert` command. Tests: dedupe, receipts only for the destination roles, email retry, the alert stays visible if the email fails.

## Bloque E: Framework de integraciones (DDEV-9)

- [x] **T13: Procrastinate set up (worker and periodic tasks)**
  Satisfies: US-9
  Depends on: T1
  Notes: Procrastinate Django integration, migrations for its tables, worker command, heartbeat task (feeds `/health/`). Test with Procrastinate's in-memory connector.

- [x] **T14: Encrypted credentials and log masking**
  Satisfies: US-9
  Depends on: T7
  Notes: `integrations.credentials.get/save` with MultiFernet (`FIELD_ENCRYPTION_KEY`); logging filter that masks sensitive keys; repr and admin hide the value. Tests: round trip, rotation, the token does not show up in captured logs.

- [x] **T15: HTTP client with rate limit**
  Satisfies: US-9
  Depends on: T7
  Notes: `ChannelClient` (httpx) with timeouts, retries on 429/5xx with backoff, Postgres token bucket (`SELECT … FOR UPDATE`). Tests with `responses`: retry on 429, wait when the bucket runs out.

- [x] **T16: Write switch (golden rule)**
  Satisfies: US-9
  Depends on: T7, T11
  Notes: `ensure_write_allowed()` + `WriteBlocked`; requires switch on **and** `ALLOW_CHANNEL_WRITES=true`; audits blocked attempts and changes. Tests: blocked by default with no HTTP request, blocked with the switch on but no env var, allowed with both.

- [x] **T17: Webhook reception, idempotent processing and retries**
  Satisfies: US-9
  Depends on: T12, T13, T14
  Notes: `ChannelAdapter` interface + registry; generic view `/hooks/<channel>/` (verify, INSERT ON CONFLICT, enqueue in the same transaction, 200); task `process_event` with backoff (1m, 5m, 25m, 2h, 6h) and, when retries run out, `failed` + alert; `fake` adapter for tests. Tests: duplicate event → one processing, response without waiting for processing, retries and final alert, idempotent handler.

- [x] **T18: Periodic reconciliation and manual reprocessing**
  Satisfies: US-9
  Depends on: T17
  Notes: periodic task per channel that calls `adapter.reconcile()` and records a `SyncRun`; reprocess `failed` events action (audited, `integrations.retry_event` permission). Tests with the fake adapter.

## Bloque F: Monitoreo, backups y despliegue (DDEV-8, DDEV-3)

- [x] **T19: Integrations status panel**
  Satisfies: US-8
  Depends on: T16, T18
  Notes: one card per channel (last SyncRun, pending/failed/done in 24 h, latest errors, write switch, token expiry); switch toggle with permission and double lock. Tests: access by permission, correct counts.

- [x] **T20: Sentry with data scrubbing**
  Satisfies: US-8
  Depends on: T1
  Notes: `sentry-sdk` enabled only if `SENTRY_DSN` exists; `before_send` that masks keys. Test of the scrub function.

- [x] **T21: Backup and restore scripts**
  Satisfies: US-8
  Depends on: T1
  Notes: `deploy/backup.sh` (pg_dump -Fc + age + SFTP, 30-day retention, alert on failure) and `deploy/restore.sh` (restore into a temporary database + check). Drill restore run **locally** now and documented in `docs/runbooks/restore.md`; repeated on the server when it is deployed.

- [x] **T22: Dockerfile, compose and Caddy (ready, not deployed)**
  Satisfies: US-3
  Depends on: T13
  Notes: multi-stage image, `deploy/compose.yml` with web, worker, postgres and caddy, memory limits, prod/staging profiles; Caddyfile for `panel.deutsch.com.ar` and `staging.panel.deutsch.com.ar`. Not run until there is a server (deferred deployment).

- [ ] **T23: GitHub repo and CI**
  Satisfies: US-3
  Depends on: T2
  Notes: create the private repo (account to be confirmed: I'll ask before creating it); `ci.yml` workflow (ruff, pytest with Postgres 17, makemigrations --check, check --deploy). `deploy-staging.yml` and `deploy-prod.yml` (manual with approval) written but disabled until there is a server.

- [ ] **T24: M0 closeout**
  Satisfies: all
  Depends on: T1–T23
  Notes: full test suite green; review traceability against requirements.md; update the DDEV-1..9 tickets in Plane (Done or what is left pending: staging deployment, SMTP mailbox, server restore drill).

## What stays pending outside M0 (because deployment is deferred)

- Automatic deployment to staging and production (DDEV-3, partial): ready but without a server.
- Daily backup running on the server and restore drill on the server (DDEV-8, partial).
- Real email sending: needs the SMTP data of Deutsch's mailbox.
