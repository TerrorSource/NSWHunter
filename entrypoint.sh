#!/bin/sh
# NSWHunter - start the app as PUID:PGID (default 1000:1000).
#
# The container starts as root (the default). This script:
#   1. makes PUID:PGID the owner of /data;
#   2. drops all root privileges and starts NSWHunter as that user.
# If you start the container as a user yourself (compose 'user:'), NSWHunter starts right away.
set -eu

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"

case "$PUID$PGID" in
  *[!0-9]*) echo "[nswhunter] PUID and PGID must be numbers (now: PUID=$PUID PGID=$PGID)." >&2; exit 1 ;;
esac

if [ "$(id -u)" = "0" ]; then
  owner="$(stat -c '%u:%g' /data)"
  if [ "$owner" != "$PUID:$PGID" ]; then
    echo "[nswhunter] Changing the owner of /data to $PUID:$PGID (was $owner)."
    chown -R "$PUID:$PGID" /data || echo "[nswhunter] Warning: could not change the owner of /data." >&2
  fi
  exec setpriv --reuid="$PUID" --regid="$PGID" --clear-groups --inh-caps=-all -- "$@"
fi

exec "$@"
