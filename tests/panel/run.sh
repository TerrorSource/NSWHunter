#!/bin/sh
# The browser test of the panel: the image as it is built, the fake services of the unit tests,
# and a real browser that logs in, sets the panel up and clicks through every page.
#
#   tests/panel/run.sh            build the image and test it
#   IMAGE=name tests/panel/run.sh test an image that is there already
#
# Needs Docker and nothing else. Everything it starts is removed again, also when a test fails.
set -eu
cd "$(dirname "$0")/../.."

BROWSER_IMAGE="mcr.microsoft.com/playwright/python:v1.65.2-noble"
NET="nswhunter-paneltest"
APP="nswhunter-paneltest-app"
FAKES="nswhunter-paneltest-fakes"

cleanup() {
  docker rm -f "$APP" "$FAKES" >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
}
trap cleanup EXIT
cleanup

if [ -z "${IMAGE:-}" ]; then
  IMAGE="nswhunter:paneltest"
  docker build -q -t "$IMAGE" . >/dev/null
fi
docker network create "$NET" >/dev/null
docker run -d --name "$FAKES" --network "$NET" -v "$PWD":/src:ro -w /src/tests --entrypoint python3 "$IMAGE" fakes.py >/dev/null
# As docker-compose.yml starts it: as a user, read-only, without any capability. The folders
# are empty, so this is a first start: the panel makes up a password.
docker run -d --name "$APP" --network "$NET" --user 1000:1000 --read-only --cap-drop ALL --security-opt no-new-privileges:true \
  --tmpfs /tmp --tmpfs /data:uid=1000,gid=1000 --tmpfs /backup:uid=1000,gid=1000 \
  -e TITLEDB_VERSIONS_URL="http://$FAKES:9000/versions.json" -e TELEGRAM_API_URL="http://$FAKES:9000" \
  -e SEARCH_DELAY_SECONDS=0 "$IMAGE" >/dev/null

ready=""
for _ in $(seq 40); do
  if docker exec "$APP" python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:3033/health', timeout=2)" >/dev/null 2>&1; then
    ready=1; break
  fi
  sleep 1
done
[ -n "$ready" ] || { echo "The panel did not start:" >&2; docker logs "$APP" >&2; exit 1; }

if ! docker run --rm --network "$NET" --ipc=host -v "$PWD/tests/panel":/panel:ro -w /panel \
  -e PANEL_URL="http://$APP:3033" -e FAKES_URL="http://$FAKES:9000" \
  -e FIRST_PASSWORD="$(docker exec "$APP" cat /data/initial-password)" "$BROWSER_IMAGE" \
  sh -c "pip install -q --root-user-action=ignore -r requirements.txt && python3 -m pytest -q -p no:cacheprovider ."; then
  # What the panel itself said while the test ran, without the line of the made-up password.
  echo "--- the log of the panel ---" >&2
  docker logs "$APP" 2>&1 | grep -v "password:" | tail -40 >&2
  exit 1
fi
