#!/bin/sh
# Apply migrations, then serve.
#
# Running migrations here rather than in a separate job keeps `docker compose
# up` to one command. It is safe to run on every start: Alembic records what
# it has applied, so a container restart is a no-op rather than a re-run.
#
# The trade-off worth knowing: with several replicas they would race. Alembic
# takes a lock so the losers wait rather than corrupting anything, but at that
# point migrations belong in a deploy step of their own.
set -eu

echo "==> Applying database migrations"
alembic upgrade head

echo "==> Starting API"
exec uvicorn app.main:create_app \
    --factory \
    --host 0.0.0.0 \
    --port 8000 \
    --proxy-headers \
    --forwarded-allow-ips '*'
