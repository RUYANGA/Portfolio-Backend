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

# Uploaded files live in /app/media. Without a volume there, every redeploy deletes them.
MEDIA_DIR=/app/media
if grep -qs " $MEDIA_DIR " /proc/mounts; then
  printf '\033[1;36m[start]\033[0m Media storage: persistent volume mounted at %s\n' "$MEDIA_DIR"
else
  printf '\033[1;33m[start] WARNING:\033[0m %s is not a mounted volume; uploads will be lost on redeploy.\n' "$MEDIA_DIR"
fi
if ! ( touch "$MEDIA_DIR/.write-test" && rm -f "$MEDIA_DIR/.write-test" ) 2>/dev/null; then
  printf '\033[1;31m[start] ERROR:\033[0m %s is not writable by %s (uid %s); uploads will fail.\n' "$MEDIA_DIR" "$(id -un)" "$(id -u)"
fi

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
