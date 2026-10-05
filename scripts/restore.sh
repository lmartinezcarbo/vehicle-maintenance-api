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

# 4. What came back, next to what the live database holds. Equal numbers
#    are the whole point: this is the proof, not the exit code.
in_postgres <<'SQL'
echo
echo "tabla                    origen($SOURCE_DB)   restaurado($TARGET_DB)"
for table in users vehicles maintenance_records payments expenses; do
    live=$(psql -U "$POSTGRES_USER" -d "$SOURCE_DB" -tAc \
        "SELECT count(*) FROM $table" 2>/dev/null || echo "-")
    back=$(psql -U "$POSTGRES_USER" -d "$TARGET_DB" -tAc \
        "SELECT count(*) FROM $table" 2>/dev/null || echo "-")
    if [ "$live" = "$back" ]; then
        mark="ok"
    else
        mark="DIFERENTE"
    fi
    printf "%-24s %8s %14s  %s\n" "$table" "$live" "$back" "$mark"
done
SQL

echo
echo "listo: $TARGET_DB restaurada y comprobada"
echo "limpieza: docker compose exec -T postgres sh -c"
echo "           'psql -U \"\$POSTGRES_USER\" -d postgres -c \"DROP DATABASE $TARGET_DB\"'"
