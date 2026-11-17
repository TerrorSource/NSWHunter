#!/bin/sh
# NSWHunter - start the app without root privileges.
#
# Started as a user of your own (compose 'user:', as docker-compose.yml does): NSWHunter starts
# right away, and never was root. The folders of /data and /backup have to belong to that user.
#
# Started as root (no 'user:'): this script
#   1. makes PUID:PGID (default 1000:1000) the owner of /data and /backup;
#   2. drops all root privileges and starts NSWHunter as that user.
# That needs the capabilities CHOWN, DAC_OVERRIDE, SETGID and SETUID.
set -eu

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"

case "$PUID$PGID" in
  *[!0-9]*) echo "[nswhunter] PUID and PGID must be numbers (now: PUID=$PUID PGID=$PGID)." >&2; exit 1 ;;
esac

if [ "$(id -u)" = "0" ]; then
  # /data: only the folder itself and what NSWHunter keeps in it, by name. Never everything under
  # it: your library or your downloads may be volumes somewhere inside /data, and their owner is
  # not for NSWHunter to change.
  owner="$(stat -c '%u:%g' /data 2>/dev/null || echo none)"
  if [ "$owner" != "none" ] && [ "$owner" != "$PUID:$PGID" ]; then
    echo "[nswhunter] Changing the owner of /data to $PUID:$PGID (was $owner)."
    chown "$PUID:$PGID" /data || echo "[nswhunter] Warning: could not change the owner of /data." >&2
    for name in settings.json settings.json.tmp state.json state.json.tmp sessions.json sessions.json.tmp \
                initial-password titledb-versions.json logs covers certs backups; do
      [ -e "/data/$name" ] && { chown -R "$PUID:$PGID" "/data/$name" || true; }
    done
  fi
  if [ -d /backup ]; then
    owner="$(stat -c '%u:%g' /backup)"
    if [ "$owner" != "$PUID:$PGID" ]; then
      echo "[nswhunter] Changing the owner of /backup to $PUID:$PGID (was $owner)."
      chown -R "$PUID:$PGID" /backup || echo "[nswhunter] Warning: could not change the owner of /backup." >&2
    fi
  fi
  exec setpriv --reuid="$PUID" --regid="$PGID" --clear-groups --inh-caps=-all -- "$@"
fi

# Not root: nothing can be put right from here, so say what is wrong instead of failing later.
me="$(id -u):$(id -g)"
if ! [ -w /data ]; then
  echo "[nswhunter] /data cannot be written by user $me. Make that user the owner of its folder on the server (chown -R $me <folder>), or change the 'user:' line of the container." >&2
  exit 1
fi
if [ -d /backup ] && ! [ -w /backup ]; then
  echo "[nswhunter] Warning: /backup cannot be written by user $me, so no backups can be made. Make that user the owner of its folder on the server (chown -R $me <folder>)." >&2
fi

exec "$@"
