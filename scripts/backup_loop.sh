#!/bin/sh
# R1 fix: cron-friendly hourly backup loop.
#
# Runs scripts/backup_local_state.py every BACKUP_INTERVAL_SECONDS
# (default 3600) and prunes backups older than BACKUP_RETENTION_DAYS
# (default 14).  Designed to be the entrypoint of a Docker sidecar OR
# a host-side cron entry.
#
# Usage as a sidecar (add to docker-compose.yml):
#
#   backup:
#     image: sleeping-passenger-backend:dev
#     entrypoint: ["/app/scripts/backup_loop.sh"]
#     volumes:
#       - ./runtime:/app/runtime
#       - ./backup_local_state:/app/backup_local_state
#     restart: unless-stopped
#     environment:
#       BACKUP_INTERVAL_SECONDS: "3600"
#       BACKUP_RETENTION_DAYS: "14"
#
# Usage as host cron:
#   */60 * * * *  cd /path/to/repo && python scripts/backup_local_state.py
#
# Note: this script never touches .env or anything outside runtime/.
set -eu

INTERVAL="${BACKUP_INTERVAL_SECONDS:-3600}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
OUT_DIR="${BACKUP_OUT_DIR:-/app/backup_local_state}"

echo "[backup_loop] interval=${INTERVAL}s retention=${RETENTION_DAYS}d out=${OUT_DIR}"

while true; do
    echo "[backup_loop] starting backup at $(date -u +%FT%TZ)"
    if python /app/scripts/backup_local_state.py --output "${OUT_DIR}"; then
        echo "[backup_loop] OK"
    else
        echo "[backup_loop] FAILED (exit $?)" >&2
    fi

    # Prune anything older than RETENTION_DAYS.  Use mtime + -delete so we
    # don't shell-out to xargs (avoids a portability headache on alpine).
    find "${OUT_DIR}" -maxdepth 1 -type d -mtime "+${RETENTION_DAYS}" \
        -name "20*" -exec rm -rf {} + 2>/dev/null || true

    sleep "${INTERVAL}"
done
