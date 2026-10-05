#!/usr/bin/env bash
set -euo pipefail

# Dump the database into backups/, keeping the newest KEEP dumps.
#
# Target: PGURL if set, else NEON_DATABASE_URL from .env (the real data
# now lives on Neon), else the local compose database. Over a URL the
# dump is made with --no-owner --no-privileges so it restores on any
# server (Neon's neondb_owner role does not exist locally), and the URL
# travels on stdin so the password never shows up in any ps output.
#
# The output contains password hashes and email addresses: backups/ is
# gitignored and this file must never leave this machine.
#
# Automation lives on the host, not in the repository (optional):
#   crontab -e
#   0 3 * * * /path/to/vehicle-maintenance-api/scripts/backup.sh

cd "$(dirname "$0")/.."

# grep + cut instead of sourcing .env: values carry & and ? that a
# shell cannot take raw, and sourcing would execute them. The
# SQLAlchemy scheme (+psycopg) is for SQLAlchemy only: libpq wants a
# plain postgresql:// URL.
PGURL=${PGURL:-}
if [ -z "$PGURL" ] && [ -f .env ]; then
    # || true: an .env without that line IS the local-mode case below,
    # not an error — pipefail + set -e would kill the script silently
    # right here if grep returned 1.
    PGURL=$(grep -E '^NEON_DATABASE_URL=' .env | head -n1 | cut -d= -f2- | tr -d "\"'" || true)
fi
PGURL=$(printf '%s' "$PGURL" | sed 's|postgresql+psycopg://|postgresql://|')
# pg_dump must not be older than the server it dumps: version-matched
# tool for external (Neon = 18) dumps, the compose image for local ones.
PG_DUMP_IMAGE=${PG_DUMP_IMAGE:-postgres:18-alpine}
if [ -n "$PGURL" ]; then
    echo "destino: base externa (PGURL o NEON_DATABASE_URL del .env)"
else
    echo "destino: base local (compose)"
fi

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

dump() {
    if [ -n "$PGURL" ]; then
        # pg_dump refuses to dump a newer server major version (Neon
        # runs 18, the compose image ships 17), so the tool runs in its
        # own throwaway container instead. The URL arrives on stdin:
        # no process ever carries the password in its argv.
        printf '%s\n' "$PGURL" | docker run --rm -i "$PG_DUMP_IMAGE" \
            sh -c 'read U; pg_dump --no-owner --no-privileges "$U"'
    else
        docker compose exec -T postgres sh -c \
            'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"'
    fi
}

# pipefail: a failed pg_dump must fail the script, and the partial file
# must not stay behind pretending to be a backup.
if ! dump | gzip > "$FILE"; then
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
