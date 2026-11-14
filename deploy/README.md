# Despliegue (diferido)

Decisión 2026-11-14: el servidor se contrata cuando haya algo para mostrar en staging. Todo está preparado; estos son los pasos para ese día.

## 1. Servidor (Hetzner)

1. Crear VPS (2 vCPU / 4 GB, Ubuntu 24.04, ubicación Ashburn) + Storage Box para backups.
2. Instalar Docker y `age`; crear usuario `deploy` con acceso SSH por clave; firewall solo 22/80/443.
3. `docker network create edge`
4. Copiar `deploy/` a `/srv/deutsch/deploy/` y levantar Caddy:
   `docker compose -f /srv/deutsch/deploy/compose.caddy.yml up -d`
5. DNS: registros A de `panel.deutsch.com.ar` y `staging.panel.deutsch.com.ar` → IP del VPS.

## 2. Variables por entorno

`/srv/deutsch/prod.env` y `/srv/deutsch/staging.env` (chmod 600), con las mismas claves que `.env.example` más:
`POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `DATABASE_URL=postgres://…@db:5432/…`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `ENVIRONMENT_NAME`, `APP_ENV_FILE` (ruta al mismo archivo) e `IMAGE`.

## 3. GitHub

Secrets del repo: `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY`. Environment `production` con aprobación obligatoria.
Activar los workflows `deploy-staging.yml` y `deploy-prod.yml` (cambiar `if: false` por la condición indicada en cada uno).

## 4. Backups

`/srv/deutsch/backup.env` (ver cabecera de `backup.sh`) y cron diario. Hacer un simulacro con `restore.sh` y anotarlo en `docs/runbooks/restore.md`.
