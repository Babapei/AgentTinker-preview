#!/bin/sh
# One process owns both SQLite stores; the host must persist the whole data directory.
set -eu

set -- agenttinker-server \
    --host 0.0.0.0 \
    --port "${PORT:-8000}" \
    --database "${AGENTTINKER_DATABASE:-/data/runs.sqlite}" \
    --web-dist /app/web/dist

if [ "${AGENTTINKER_REQUIRE_ACCESS_PASSWORD:-0}" = "1" ]; then
    set -- "$@" --require-access-password
fi
exec "$@"
