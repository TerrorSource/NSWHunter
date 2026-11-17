#!/bin/sh
# NSWHunter - start the app without root privileges.
#
# The settings and the state are in /config, as with Sonarr and Radarr, so /data is free for the
# folder of your media. An installation of before version 3.11 has them in /data; that keeps
# working as long as that folder is still mounted there.
#
# Started as a user of your own (compose 'user:', as docker-compose.yml does): NSWHunter starts
# right away, and never was root. The config folder has to belong to that user.
#
# Started as root (no 'user:'): this script
#   1. makes PUID:PGID (default 1000:1000) the owner of the config folder and of what NSWHunter
#      keeps in it, and of /backup if that is a volume;
#   2. drops all root privileges and starts NSWHunter as that user.
# That needs the capabilities CHOWN, DAC_OVERRIDE, SETGID and SETUID.
set -eu

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"

case "$PUID$PGID" in
  *[!0-9]*) echo "[nswhunter] PUID and PGID must be numbers (now: PUID=$PUID PGID=$PGID)." >&2; exit 1 ;;
esac

# Where the settings are. What is there already decides: settings are never started anew next to
# settings that exist.
if [ -z "${DATA_DIR:-}" ]; then
  if [ -f /config/settings.json ]; then
    DATA_DIR=/config
  elif [ -f /data/settings.json ]; then
    DATA_DIR=/data
    echo "[nswhunter] The settings are in /data, as before version 3.11. That keeps working. To have /data free for your media, mount this folder at /config instead."
  elif mountpoint -q /config; then
    DATA_DIR=/config
  elif mountpoint -q /data && [ -z "$(ls -A /data 2>/dev/null)" ]; then
    DATA_DIR=/data  # a first start with a compose file of before version 3.11
  else
    DATA_DIR=/config
  fi
  export DATA_DIR
fi

if [ "$(id -u)" = "0" ]; then
  # Only the config folder itself and what NSWHunter keeps in it, by name: never everything under
  # it, and never /data when that is the folder of your media. The owner of your library and your
  # downloads is not for NSWHunter to change.
  owner="$(stat -c '%u:%g' "$DATA_DIR" 2>/dev/null || echo none)"
  if [ "$owner" != "none" ] && [ "$owner" != "$PUID:$PGID" ]; then
    echo "[nswhunter] Changing the owner of $DATA_DIR to $PUID:$PGID (was $owner)."
    chown "$PUID:$PGID" "$DATA_DIR" 2>/dev/null || true  # if that cannot be done, the check below says what is wrong
    for name in settings.json settings.json.tmp state.json state.json.tmp sessions.json sessions.json.tmp \
                initial-password reset-password titledb-versions.json logs covers certs backups; do
      [ -e "$DATA_DIR/$name" ] && { chown -R "$PUID:$PGID" "$DATA_DIR/$name" || true; }
    done
  fi
  if mountpoint -q /backup; then
    owner="$(stat -c '%u:%g' /backup)"
    if [ "$owner" != "$PUID:$PGID" ]; then
      echo "[nswhunter] Changing the owner of /backup to $PUID:$PGID (was $owner)."
      chown -R "$PUID:$PGID" /backup || echo "[nswhunter] Warning: could not change the owner of /backup." >&2
    fi
  fi
  if ! setpriv --reuid="$PUID" --regid="$PGID" --clear-groups -- test -w "$DATA_DIR"; then
    echo "[nswhunter] $DATA_DIR cannot be written by user $PUID:$PGID. Mount a folder of your server at /config (a volume of the container) that this user may write in." >&2
    exit 1
  fi
  exec setpriv --reuid="$PUID" --regid="$PGID" --clear-groups --inh-caps=-all -- "$@"
fi

# Not root: nothing can be put right from here, so say what is wrong instead of failing later.
me="$(id -u):$(id -g)"
if ! [ -w "$DATA_DIR" ]; then
  echo "[nswhunter] $DATA_DIR cannot be written by user $me. Mount a folder of your server at /config and make that user its owner (chown -R $me <folder>), or change the 'user:' line of the container." >&2
  exit 1
fi
if mountpoint -q /backup && ! [ -w /backup ]; then
  echo "[nswhunter] Warning: /backup cannot be written by user $me, so no backups can be made there. Make that user the owner of its folder on the server (chown -R $me <folder>)." >&2
fi

exec "$@"
