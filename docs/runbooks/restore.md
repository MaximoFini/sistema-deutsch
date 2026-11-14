# Runbook: restaurar un backup

## Simulacros realizados

| Fecha | Dónde | Dump | Resultado |
|---|---|---|---|
| 2026-11-14 | Local (Postgres del proyecto, puerto 5433) | `pg_dump -Fc` de `deutsch_dev` (190 KB) | OK: 87 migraciones, 5 canales, 1 usuario restaurados en base temporal |
| _pendiente_ | Servidor (primer despliegue) | backup nocturno desde Storage Box | — |

## Pasos (servidor)

1. Bajar el backup del día desde la Storage Box: `sftp uXXXX@uXXXX.your-storagebox.de` → `get deutsch/prod-AAAAMMDD-HHMM.dump.age`
2. Descifrar: `age -d -i /root/backup-key.txt -o prod.dump prod-AAAAMMDD-HHMM.dump.age`
3. **Verificar sin tocar la base real:** `deploy/restore.sh prod.dump postgres://USUARIO:CONTRASEÑA@localhost:5432/postgres`
4. Restaurar de verdad (solo ante pérdida de datos, con el sistema detenido):
   ```bash
   docker compose -p prod stop web worker
   docker compose -p prod exec -T db sh -c 'dropdb -U "$POSTGRES_USER" "$POSTGRES_DB" && createdb -U "$POSTGRES_USER" "$POSTGRES_DB"'
   docker compose -p prod exec -T db sh -c 'pg_restore --no-owner -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < prod.dump
   docker compose -p prod start web worker
   ```
5. Después de restaurar: correr la conciliación de todos los canales desde el panel para recuperar los pedidos que entraron entre el backup y el incidente (los canales reenvían o se recuperan por conciliación).
