#!/usr/bin/env sh
# Container entrypoint: the database is always ready before the app starts.
#
# Whatever command the container is given (the default `start.sh prod`, or a custom start command
# set in the hosting panel such as `gunicorn config.wsgi:application ...`), migrations run first:
#   wait for the database -> migrate -> seed missing content -> create the admin
#
# start.sh does that preparation itself, so it is handed over directly; any other command runs
# after `start.sh init`. Set SKIP_PREPARE=true to bypass (e.g. for a one-off shell).
set -eu

cd /app
printf '\033[1;36m[start]\033[0m Version %s\n' "${APP_VERSION:-unknown}"

case "${1:-}" in
  ./scripts/start.sh | scripts/start.sh | /app/scripts/start.sh)
    exec "$@"
    ;;
esac

case "$(printf '%s' "${SKIP_PREPARE:-false}" | tr '[:upper:]' '[:lower:]')" in
  true | 1 | yes | on) ;;
  *) ./scripts/start.sh init ;;
esac

exec "$@"
