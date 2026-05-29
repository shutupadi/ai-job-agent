#!/usr/bin/env bash
# WARNING: drops all jobs, applications, runs.
set -euo pipefail
docker compose exec db psql -U "${POSTGRES_USER:-jobagent}" -d "${POSTGRES_DB:-jobagent}" -c \
  "TRUNCATE applications, cover_letters, resume_versions, jobs, runs, settings_kv RESTART IDENTITY CASCADE;"
echo "Database truncated."
