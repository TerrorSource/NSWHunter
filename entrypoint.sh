#!/bin/sh
# NSWHunter - start de app als PUID:PGID (standaard 1000:1000).
#
# De container start als root (de standaard). Dit script:
#   1. zorgt dat /data van PUID:PGID is;
#   2. laat alle root-rechten vallen en start NSWHunter als die gebruiker.
# Start je de container zelf al als een gebruiker (compose 'user:'), dan start NSWHunter direct.
set -eu

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"

case "$PUID$PGID" in
  *[!0-9]*) echo "[nswhunter] PUID en PGID moeten getallen zijn (nu: PUID=$PUID PGID=$PGID)." >&2; exit 1 ;;
esac

if [ "$(id -u)" = "0" ]; then
  owner="$(stat -c '%u:%g' /data)"
  if [ "$owner" != "$PUID:$PGID" ]; then
    echo "[nswhunter] Rechten van /data aanpassen naar $PUID:$PGID (was $owner)."
    chown -R "$PUID:$PGID" /data || echo "[nswhunter] Waarschuwing: kon de rechten van /data niet aanpassen." >&2
  fi
  exec setpriv --reuid="$PUID" --regid="$PGID" --clear-groups --inh-caps=-all -- "$@"
fi

exec "$@"
