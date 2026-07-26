#!/usr/bin/env bash
# Dev launcher — spins up a local Postgres if DATABASE_URL is not set in .env.
set -euo pipefail

if grep -q "^DATABASE_URL=" .env 2>/dev/null; then
  docker compose up -d "$@"
else
  docker compose --profile local-db up -d "$@"
fi
