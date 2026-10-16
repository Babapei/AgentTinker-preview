#!/usr/bin/env bash
# Stable entry point for the cloud environment's installation script.
set -euo pipefail

repository_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$repository_root"

if ! command -v uv >/dev/null 2>&1; then
  printf '%s\n' 'Setup requires uv in the execution environment.' >&2
  exit 1
fi

uv sync --locked

if ! command -v npm >/dev/null 2>&1; then
  printf '%s\n' 'Setup requires Node.js >=22.12 and npm for the web inspector.' >&2
  exit 1
fi
npm --prefix web ci

# Setup installs dependencies only; model validation is run separately.
