#!/usr/bin/env bash
set -euo pipefail

# Restore a dump into a SCRATCH database and print its row counts next to
# the ones the live database holds. The live database is never touched:
# testing a backup must not be the thing that breaks the original.
#
#   scripts/restore.sh backups/vehicle_maintenance_20261004_2235.sql.gz
#   scripts/restore.sh <dump> otra_base_de_pruebas

cd "$(dirname "$0")/.."

FILE=${1:?uso: scripts/restore.sh backups/xxxx.sql.gz [base_destino]}
TARGET_DB=${2:-vehicle_restore_test}

# Strictly validated, so every interpolation below is inert: no quoting
# gymnastics and nothing to inject.
if [[ ! "$TARGET_DB" =~ ^[a-z_][a-z0-9_]*$ ]]; then
    echo "nombre de base no válido: $TARGET_DB" >&2
    exit 1
fi

if [ ! -f "$FILE" ]; then
    echo "no existe el dump: $FILE" >&2
    exit 1
fi

# Source of the truth for the comparison below: PGURL if set, else
# NEON_DATABASE_URL from .env, else the local compose database (the
# F21 behaviour, for dumps taken locally). Same parsing as backup.sh:
# grep instead of sourcing, and libpq rejects the SQLAlchemy scheme.
PGURL=${PGURL:-}
if [ -z "$PGURL" ] && [ -f .env ]; then
    # || true: an .env without that line means "compare against the
    # local database" (the F21 behaviour), not an error — pipefail +
    # set -e would otherwise kill the script silently here.
    PGURL=$(grep -E '^NEON_DATABASE_URL=' .env | head -n1 | cut -d= -f2- | tr -d "\"'" || true)
fi
PGURL=$(printf '%s' "$PGURL" | sed 's|postgresql+psycopg://|postgresql://|')

# Every count and the table list come from the SOURCE itself — over the
# URL when there is one (Neon), from the local database otherwise.
q_source() {
    if [ -n "$PGURL" ]; then
        printf '%s\n' "$PGURL" | docker compose exec -T -i \
            -e SQL="$1" postgres \
            sh -c 'read U; psql -d "$U" -tAq -v ON_ERROR_STOP=1 -c "$SQL"'
    else
        # < /dev/null: compose's client drains the stdin it inherits
        # even without -i, and inside the comparison loop that stdin IS
        # the herestring feeding the loop — it would be eaten whole.
        docker compose exec -T -e SQL="$1" -e DB="$SOURCE_DB" postgres \
            sh -c 'psql -U "$POSTGRES_USER" -d "$DB" -tAq -v ON_ERROR_STOP=1 -c "$SQL"' < /dev/null
    fi
}

# The restored side always lives in the local scratch database: the
# restore never writes to the source it is verifying. stdin from
# /dev/null, for the same reason as q_source below: psql -c reads
# nothing, but the compose client would drain the loop's herestring.
q_target() {
    docker compose exec -T -e SQL="$1" -e DB="$TARGET_DB" postgres \
        sh -c 'psql -U "$POSTGRES_USER" -d "$DB" -tAq -v ON_ERROR_STOP=1 -c "$SQL"' < /dev/null
}

in_postgres() {
    docker compose exec -T \
        -e SOURCE_DB="$SOURCE_DB" \
        -e TARGET_DB="$TARGET_DB" \
        postgres sh -s
}

SOURCE_DB=$(docker compose exec -T postgres sh -c 'printf %s "$POSTGRES_DB"')

echo "destino: $TARGET_DB (base de pruebas; la real no se toca)"

# 1. Scratch database, created on demand.
in_postgres <<'SQL'
psql -U "$POSTGRES_USER" -d postgres -tAc \
    "SELECT 1 FROM pg_database WHERE datname = '$TARGET_DB'" | grep -q 1 ||
    psql -U "$POSTGRES_USER" -d postgres -c "CREATE DATABASE $TARGET_DB"
SQL

# 2. Empty schema: restoring over leftovers fails halfway and tells you
#    nothing about the dump itself.
in_postgres <<'SQL'
psql -U "$POSTGRES_USER" -d "$TARGET_DB" -c \
    "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
SQL

# 3. The dump itself. stdin flows through sh into psql, ON_ERROR_STOP
#    turns any bad statement into a failed script, and -o /dev/null
#    keeps the sequence bookkeeping out of the way: the table below is
#    the output that matters.
if ! gzip -dc "$FILE" | docker compose exec -T \
    -e TARGET_DB="$TARGET_DB" postgres \
    sh -c 'psql -U "$POSTGRES_USER" -d "$TARGET_DB" -v ON_ERROR_STOP=1 -q -o /dev/null'; then
    echo "restauración fallida: $FILE" >&2
    exit 1
fi

# 4. The table list and the counts come from the SOURCE itself — the
#    URL's database when set, the local one otherwise — and sit next to
#    what the restore holds. Equal numbers are the whole point: this is
#    the proof, not the exit code.
tables=$(q_source "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename")
origin_label="local"
if [ -n "$PGURL" ]; then
    origin_label="url-externa"
fi

echo
echo "tabla                    origen($origin_label)   restaurado($TARGET_DB)"
while IFS= read -r table; do
    if [ -z "$table" ]; then
        continue
    fi
    live=$(q_source "SELECT count(*) FROM \"$table\"")
    back=$(q_target "SELECT count(*) FROM \"$table\"")
    if [ "$live" = "$back" ]; then
        mark="ok"
    else
        mark="DIFERENTE"
    fi
    printf "%-24s %10s %12s  %s\n" "$table" "$live" "$back" "$mark"
done <<< "$tables"

echo
echo "listo: $TARGET_DB restaurada y comprobada"
echo "limpieza: docker compose exec -T postgres sh -c"
echo "           'psql -U \"\$POSTGRES_USER\" -d postgres -c \"DROP DATABASE $TARGET_DB\"'"
