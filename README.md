# Sistema Deutsch

Centro de pedidos y capa operativa de Deutsch sobre Contabilium (fase 1), diseñado como núcleo de un ERP que más adelante reemplaza a Contabilium.

- Tickets y PRD: Plane, proyecto **Desarrollo Deutsch** (DDEV).
- Decisiones técnicas: [`docs/adr/0001-arquitectura-base.md`](docs/adr/0001-arquitectura-base.md).
- Specs (Spec-Driven Development): `specs/<feature>/` con `requirements.md`, `design.md` y `tasks.md`.

## Regla de oro

Contabilium es dueño de stock, precios y facturación. El sistema **no escribe stock ni precio** en Mercado Libre ni Tiendanube: hay un interruptor por canal, apagado, que además exige `ALLOW_CHANNEL_WRITES=true` en el servidor.

## Levantar el proyecto en local (Windows, sin Docker)

Requisitos: [uv](https://docs.astral.sh/uv/) y PostgreSQL 17 instalados.

1. Dependencias (instala Python 3.12 si hace falta):
   ```bash
   uv sync
   ```
2. Base de datos: el proyecto usa **su propio Postgres** en el puerto 5433, con los datos en `local/pgdata` (no toca otro Postgres que tengas instalado). La primera vez:
   ```bash
   # elegí una contraseña y ponela también en DATABASE_URL de .env (copiado de .env.example, puerto 5433)
   "C:/Program Files/PostgreSQL/17/bin/initdb.exe" -D local/pgdata -U deutsch -W --auth=scram-sha-256 -E UTF8 --locale=C
   ```
   Cada vez que prendas la PC (arranca el servidor de base):
   ```bash
   "C:/Program Files/PostgreSQL/17/bin/pg_ctl.exe" -D local/pgdata -o "-p 5433" -l local/postgres.log start
   ```
   Y una sola vez, crear la base: `createdb -h localhost -p 5433 -U deutsch deutsch_dev`
3. Migraciones y superusuario de soporte:
   ```bash
   uv run python manage.py migrate
   uv run python manage.py createsuperuser
   ```
4. CSS (descarga el binario de Tailwind la primera vez) y servidor:
   ```bash
   uv run python manage.py tailwind build
   uv run python manage.py runserver
   ```
5. Worker de tareas (otra terminal): procesa eventos de canales, emails y tareas periódicas.
   ```bash
   uv run python manage.py procrastinate worker
   ```

Panel: http://localhost:8000 · soporte técnico (Django admin, solo superusuarios): http://localhost:8000/soporte/

## Tests y calidad

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

Los tests usan la base de `.env` y crean una base temporal `test_<nombre>` (el usuario necesita permiso `CREATEDB`).

## Estructura

```
config/          settings (base, local, test, prod), urls
apps/core        modelos base, fuente de verdad, logs sin secretos, health
apps/accounts    usuarios, roles, permisos sumados/quitados, login
apps/audit       auditoría inmutable
apps/alerts      alertas en panel y por email
apps/catalog     productos y variantes
apps/inventory   depósitos, stock y movimientos
apps/pricing     listas de precio con vigencia
apps/customers   clientes con datos fiscales
apps/sales       documentos de venta genéricos, pagos, envíos
apps/integrations framework de canales: webhooks, cola, reintentos, credenciales, interruptores
deploy/          Docker, compose, Caddy, backups (despliegue diferido)
```

## Despliegue

Diferido hasta tener servidor (Hetzner, ver ADR). Todo lo necesario está en `deploy/` y `.github/workflows/`; ver [`deploy/README.md`](deploy/README.md).
