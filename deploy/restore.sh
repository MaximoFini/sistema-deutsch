#!/usr/bin/env bash
# Restaura un dump en una base TEMPORAL y verifica que tenga datos. No toca la base real.
#   Uso local:    deploy/restore.sh <archivo.dump> <DATABASE_URL_ADMIN>
#   Ej.: deploy/restore.sh /tmp/prod.dump postgres://deutsch:...@localhost:5432/postgres
# Si el dump está cifrado (.age): age -d -i clave.txt -o archivo.dump archivo.dump.age
set -euo pipefail

DUMP=${1:?falta el archivo .dump}
ADMIN_URL=${2:?falta la URL de conexión con permiso CREATEDB}
TMPDB="restore_check_$(date +%Y%m%d%H%M%S)"
BASE_URL=${ADMIN_URL%/*}

psql "$ADMIN_URL" -v ON_ERROR_STOP=1 -c "CREATE DATABASE $TMPDB"
cleanup() { psql "$ADMIN_URL" -c "DROP DATABASE IF EXISTS $TMPDB" >/dev/null; }
trap cleanup EXIT

pg_restore --no-owner --no-privileges -d "$BASE_URL/$TMPDB" "$DUMP"

echo "Conteo de filas en la base restaurada:"
psql "$BASE_URL/$TMPDB" -v ON_ERROR_STOP=1 -At -F ' ' -c "
  SELECT 'migraciones', count(*) FROM django_migrations
  UNION ALL SELECT 'usuarios', count(*) FROM accounts_user
  UNION ALL SELECT 'auditoria', count(*) FROM audit_auditlog
  UNION ALL SELECT 'canales', count(*) FROM integrations_channel
  UNION ALL SELECT 'documentos_venta', count(*) FROM sales_salesdocument;"

MIGRATIONS=$(psql "$BASE_URL/$TMPDB" -At -c "SELECT count(*) FROM django_migrations")
[ "$MIGRATIONS" -gt 0 ] || { echo "RESTAURACIÓN INVÁLIDA: sin migraciones"; exit 1; }
echo "RESTAURACIÓN OK ($TMPDB se borra al salir)"
