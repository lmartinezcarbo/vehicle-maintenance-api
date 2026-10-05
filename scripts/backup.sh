#!/usr/bin/env bash
set -euo pipefail

# Dump the database into backups/, keeping the newest KEEP dumps.
#
# The output contains password hashes and email addresses: backups/ is
# gitignored and this file must never leave this machine.
#
# Automation lives on the host, not in the repository (optional):
#   crontab -e
#   0 3 * * * /path/to/vehicle-maintenance-api/scripts/backup.sh

cd "$(dirname "$0")/.."

KEEP=${KEEP:-7}
DIR=backups
PREFIX=vehicle_maintenance
# Nanoseconds: three runs inside the same second would otherwise share a
# name and silently overwrite each other instead of rotating.
STAMP=$(date +%Y%m%d_%H%M%S_%N)
FILE="$DIR/${PREFIX}_$STAMP.sql.gz"

if [ -e "$FILE" ]; then
    echo "ya existe $FILE, no se sobrescribe" >&2
    exit 1
fi

mkdir -p "$DIR"

# pipefail: a failed pg_dump must fail the script, and the partial file
# must not stay behind pretending to be a backup.
if ! docker compose exec -T postgres sh -c \
    'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' | gzip > "$FILE"; then
    rm -f "$FILE"
    echo "backup fallido" >&2
    exit 1
fi

if [ ! -s "$FILE" ]; then
    rm -f "$FILE"
    echo "backup vacío" >&2
    exit 1
fi

echo "backup: $FILE ($(du -h "$FILE" | cut -f1), sha256 $(sha256sum "$FILE" | cut -c1-12)…)"

# Rotation: newest first, everything past KEEP is dropped. No filenames
# with spaces are ever generated, so the word splitting here is safe.
kept=0
for candidate in $(ls -1t "$DIR/${PREFIX}"_*.sql.gz 2>/dev/null || true); do
    kept=$((kept + 1))
    if [ "$kept" -gt "$KEEP" ]; then
        echo "rotación: fuera $candidate"
        rm -f "$candidate"
    fi
done
