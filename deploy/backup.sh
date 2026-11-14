#!/usr/bin/env bash
# Backup diario de las bases (cron 03:00 ART en el servidor):
#   0 3 * * * /srv/deutsch/deploy/backup.sh >> /var/log/deutsch-backup.log 2>&1
#
# Variables (en /srv/deutsch/backup.env, chmod 600):
#   BACKUP_STACKS="prod staging"   stacks de compose a respaldar
#   AGE_RECIPIENT=age1...          clave pública age para cifrar
#   SFTP_TARGET=uXXXX@uXXXX.your-storagebox.de   Storage Box de Hetzner
#   RETENTION_DAYS=30
set -euo pipefail

source /srv/deutsch/backup.env
STAMP=$(date +%Y%m%d-%H%M)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

fail() {
  echo "ERROR: $1"
  docker compose -p prod exec -T web python manage.py emit_alert backup.failed \
    "Falló el backup diario" --body "$1" --dedupe-key "backup-$(date +%Y%m%d)" || true
  exit 1
}

for stack in $BACKUP_STACKS; do
  file="$WORK/${stack}-${STAMP}.dump"
  docker compose -p "$stack" exec -T db sh -c 'pg_dump -Fc -U "$POSTGRES_USER" "$POSTGRES_DB"' > "$file" \
    || fail "pg_dump de $stack"
  [ -s "$file" ] || fail "dump vacío de $stack"
  age -r "$AGE_RECIPIENT" -o "$file.age" "$file" || fail "cifrado de $stack"
  rm "$file"
done

# Archivos subidos (comprobantes, etiquetas)
docker run --rm -v prod_media:/media -v "$WORK":/out alpine tar czf "/out/media-${STAMP}.tgz" -C /media . \
  || fail "copia de media"

sftp -b - "$SFTP_TARGET" <<EOF || fail "subida a Storage Box"
-mkdir deutsch
cd deutsch
put $WORK/*
EOF

# Retención: borra remotos con más de RETENTION_DAYS días
cutoff=$(date -d "-${RETENTION_DAYS:-30} days" +%Y%m%d)
sftp -b - "$SFTP_TARGET" <<< "ls -1 deutsch" 2>/dev/null | grep -oE '[a-z]+-[0-9]{8}' | sort -u | while read -r name; do
  day=${name##*-}
  if [ "$day" -lt "$cutoff" ]; then
    echo "rm deutsch/${name}*" | sftp -b - "$SFTP_TARGET" || true
  fi
done

echo "Backup OK $STAMP"
