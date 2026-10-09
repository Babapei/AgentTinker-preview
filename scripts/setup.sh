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

# Add later frontend installation steps here when its lockfile is committed.
# Setup installs dependencies only; model validation is run separately.
