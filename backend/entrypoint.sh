#!/bin/sh
# Container start-up: migrate, seed the gallery, optionally bootstrap the demo,
# then serve.
#
# `docker compose up` sets MINILP_BOOTSTRAP_DEMO=1 so a fresh checkout lands on a
# working demo — the §12 M6 acceptance bar is "docker compose up → annotate the
# demo in under 2 minutes", and that is not achievable if the first step is
# reading the README to find out which script to exec into the container and run.
# Both the seed and the bootstrap are idempotent, so a restart is safe.
set -e

echo "==> applying migrations"
alembic upgrade head

echo "==> seeding gallery templates"
python -m app.seed

if [ "${MINILP_BOOTSTRAP_DEMO:-0}" = "1" ]; then
  echo "==> bootstrapping demo projects"
  python -m app.bootstrap_demo
fi

echo "==> starting API on :8000"
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
