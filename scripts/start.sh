#!/usr/bin/env sh
# Start the portfolio API. Every start prepares the database first:
#   1. wait for the database   2. apply migrations   3. seed missing content   4. create the admin (optional)
#
# Usage:
#   scripts/start.sh dev     Django dev server with auto-reload   (HOST, PORT; default 127.0.0.1:8000)
#   scripts/start.sh prod    Gunicorn, for Docker/production       (PORT, WEB_CONCURRENCY; default 0.0.0.0:8000, 3 workers)
#   scripts/start.sh init    Prepare the database, then exit       (e.g. a release/pre-deploy step)
#
# Settings (environment variables, or backend/.env):
#   AUTO_SEED=true|false            Seed on start (default true). Seeding only adds missing content,
#                                   so edits made in the admin are never overwritten.
#   DB_WAIT_TIMEOUT=60              Seconds to wait for the database.
#   DJANGO_SUPERUSER_USERNAME/PASSWORD/EMAIL   Create the admin account on first start.
set -eu

cd "$(dirname "$0")/.."

# Use the project's virtualenv when running locally and none is active.
if [ -z "${VIRTUAL_ENV:-}" ] && [ -x .venv/bin/python ]; then
  PATH="$(pwd)/.venv/bin:$PATH"
fi

# Application code lives in src/.
export PYTHONPATH="$(pwd)/src${PYTHONPATH:+:$PYTHONPATH}"

MODE="${1:-prod}"

log() { printf '\033[1;36m[start]\033[0m %s\n' "$*"; }

# Read a setting from the environment, falling back to backend/.env.
setting() {
  python - "$1" "$2" <<'PY'
import os, sys
from dotenv import dotenv_values
name, default = sys.argv[1], sys.argv[2]
print(os.environ.get(name) or dotenv_values(".env").get(name) or default)
PY
}

prepare() {
  log "Waiting for the database"
  python manage.py wait_for_db --timeout "$(setting DB_WAIT_TIMEOUT 60)"

  log "Applying migrations"
  python manage.py migrate --noinput

  case "$(setting AUTO_SEED true | tr '[:upper:]' '[:lower:]')" in
    false|0|no|off) log "Seeding skipped (AUTO_SEED is off)" ;;
    *)              log "Seeding missing content"; python manage.py seed_portfolio ;;
  esac

  python manage.py ensure_superuser
}

# Meeting reminders: checked every minute in the background, restarted if it ever stops.
# BOOKING_REMINDERS=false turns it off (e.g. when cron runs send_booking_reminders instead).
start_reminders() {
  case "$(setting BOOKING_REMINDERS true | tr '[:upper:]' '[:lower:]')" in
    false|0|no|off) log "Meeting reminders off (BOOKING_REMINDERS)"; return ;;
  esac
  log "Starting meeting reminders (checked every minute)"
  (
    while true; do
      python manage.py send_booking_reminders --loop 60 || log "Reminders stopped; restarting in 30s"
      sleep 30
    done
  ) &
}

case "$MODE" in
  dev)
    prepare
    ADDR="${HOST:-127.0.0.1}:${PORT:-8000}"
    log "Starting the dev server on http://$ADDR"
    exec python manage.py runserver "$ADDR"
    ;;
  prod)
    prepare
    start_reminders
    log "Starting gunicorn (Uvicorn workers: HTTP + live WebSocket) on 0.0.0.0:${PORT:-8000}"
    exec gunicorn config.asgi:application \
      --worker-class uvicorn_worker.UvicornWorker \
      --bind "0.0.0.0:${PORT:-8000}" \
      --workers "${WEB_CONCURRENCY:-3}" \
      --access-logfile - \
      --error-logfile -
    ;;
  init)
    prepare
    log "Database ready"
    ;;
  *)
    echo "Usage: $0 {dev|prod|init}" >&2
    exit 64
    ;;
esac
