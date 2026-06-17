#!/usr/bin/env bash
# luna — backup Postgres (self-hosted trong container). pg_dump → file nén, xoay vòng.
#
# Cài cron trên VM (chạy 02:00 hằng ngày, log riêng):
#   0 2 * * *  /opt/luna/deploy/backup.sh >> /var/log/luna-backup.log 2>&1
#
# Khôi phục:
#   gunzip -c <file>.sql.gz | docker exec -i luna-db psql -U luna -d luna
set -euo pipefail

CONTAINER="${LUNA_DB_CONTAINER:-luna-db}"
DB_USER="${POSTGRES_USER:-luna}"
DB_NAME="${POSTGRES_DB:-luna}"
BACKUP_DIR="${LUNA_BACKUP_DIR:-/opt/luna/backups}"
RETENTION_DAYS="${LUNA_BACKUP_RETENTION_DAYS:-14}"

mkdir -p "$BACKUP_DIR"
stamp="$(date +%Y%m%d-%H%M%S)"
out="$BACKUP_DIR/luna-$stamp.sql.gz"

echo "[$(date -Iseconds)] dumping $DB_NAME from $CONTAINER → $out"
docker exec "$CONTAINER" pg_dump -U "$DB_USER" -d "$DB_NAME" | gzip > "$out"

# Xoay vòng: xoá dump cũ hơn RETENTION_DAYS ngày.
find "$BACKUP_DIR" -name 'luna-*.sql.gz' -mtime "+$RETENTION_DAYS" -delete

echo "[$(date -Iseconds)] done. Hiện có: $(ls -1 "$BACKUP_DIR"/luna-*.sql.gz 2>/dev/null | wc -l | tr -d ' ') bản."
