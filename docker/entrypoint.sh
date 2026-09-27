#!/usr/bin/env bash
set -euo pipefail

echo ">>> Waiting for PostgreSQL..."
python - <<'PY'
import os, socket, sys, time

host = os.environ.get("POSTGRES_HOST", "db")
port = int(os.environ.get("POSTGRES_PORT", "5432"))
deadline = time.time() + 60
while time.time() < deadline:
    try:
        with socket.create_connection((host, port), timeout=3):
            print(">>> PostgreSQL is up")
            sys.exit(0)
    except OSError:
        time.sleep(1)
print(">>> PostgreSQL is not reachable", file=sys.stderr)
sys.exit(1)
PY

echo ">>> Applying database migrations..."
python manage.py migrate --noinput

if [ "${DJANGO_COLLECTSTATIC:-1}" = "1" ]; then
  echo ">>> Collecting static files..."
  python manage.py collectstatic --noinput >/dev/null || true
fi

if [ "${DJANGO_SEED_DEMO:-0}" = "1" ]; then
  echo ">>> Seeding demo data..."
  python manage.py seed_demo || true
fi

if [ "${DJANGO_CREATE_SUPERUSER:-0}" = "1" ]; then
  echo ">>> Creating superuser..."
  python manage.py createsuperuser --noinput || true
fi

echo ">>> Executing: $*"
exec "$@"
