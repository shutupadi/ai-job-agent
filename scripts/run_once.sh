#!/usr/bin/env bash
# Trigger one full pipeline run inside the running backend container.
set -euo pipefail
docker compose exec backend python -m app.scheduler.jobs run-once "$@"
