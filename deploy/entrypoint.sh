#!/bin/sh
# One process owns both SQLite stores; the host must persist the whole data directory.
set -eu

exec agenttinker-server \
    --host 0.0.0.0 \
    --port "${PORT:-8000}" \
    --database "${AGENTTINKER_DATABASE:-/data/runs.sqlite}" \
    --web-dist /app/web/dist
