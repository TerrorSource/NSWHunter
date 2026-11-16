#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# commit-git.sh — zet NSWHunter op GitHub en maak optioneel een release
#
#   ./commit-git.sh                      push met standaard commit-bericht
#   ./commit-git.sh "commit-bericht"     push met eigen commit-bericht
#   ./commit-git.sh -r "commit-bericht"  push én maak GitHub-release vX.Y.Z
#   ./commit-git.sh --no-test            sla de tests over
#
# Het versienummer komt uit app/version.py (__version__), de releasetekst uit
# CHANGELOG.md (de sectie "## [X.Y.Z] - JJJJ-MM-DD").
#
# Wat GitHub daarna doet (.github/workflows/docker.yml):
#   push naar main   -> ghcr.io/<account>/nswhunter:latest
#   release vX.Y.Z   -> ghcr.io/<account>/nswhunter:X.Y.Z en :X.Y
#
# Daarna op de NAS / in Portainer: de stack opnieuw ophalen (pull and redeploy).
#
# Nieuwe versie uitbrengen:
#   1. verhoog __version__ in app/version.py
#   2. zet bovenaan CHANGELOG.md een sectie "## [X.Y.Z] - JJJJ-MM-DD"
#   3. ./commit-git.sh -r "wat er veranderd is"
#
# Veiligheid: het script weigert te committen als er geheimen tussen de
# bestanden zitten (API keys, ingevulde wachtwoorden in de compose, .env, data/).
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

REPO_SLUG="<account>/NSWHunter"
REPO_URL="https://github.com/${REPO_SLUG}.git"
BRANCH="main"
LOCAL_TAG="nswhunter"

cd "$(dirname "$0")"
echo "📁 $(pwd)"

# ── Argumenten ───────────────────────────────────────────────────────────────
MSG="update vanuit werkmap"
MAKE_RELEASE=0
SKIP_TESTS=0
for arg in "$@"; do
  case "$arg" in
    -r|--release) MAKE_RELEASE=1 ;;
    --no-test)    SKIP_TESTS=1 ;;
    -h|--help)    sed -n '2,26p' "$0"; exit 0 ;;
    -*)           echo "❌ Onbekende optie: $arg (zie -h)" >&2; exit 1 ;;
    *)            MSG="$arg" ;;
  esac
done

# ── Versienummer en changelog ────────────────────────────────────────────────
# Het commit-bericht is de titel van de GitHub Action-run; met "v1.2.0 · …" vooraan
# zie je in de lijst meteen welke versie welke build is.
APP_VERSION=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' app/version.py)
if ! [[ "$APP_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "❌ Ongeldig versienummer in app/version.py: '$APP_VERSION' (verwacht X.Y.Z)." >&2
  exit 1
fi
VERSION="v$APP_VERSION"
if ! grep -q "^## \[$APP_VERSION\]" CHANGELOG.md; then
  echo "❌ CHANGELOG.md heeft geen sectie '## [$APP_VERSION]'." >&2
  echo "   Schrijf eerst op wat er veranderd is (en verhoog zo nodig __version__)." >&2
  exit 1
fi
if ! [[ "${MSG}" =~ ^v[0-9]+ ]]; then
  MSG="${VERSION} · ${MSG}"
fi
echo "📦 Versie: ${VERSION}"

# Waarschuw vroeg als de release al bestaat (dan is de versie niet opgehoogd).
if [ "$MAKE_RELEASE" -eq 1 ]; then
  if ! command -v gh >/dev/null 2>&1; then
    echo "❌ -r heeft de gh CLI nodig (brew install gh, daarna gh auth login)." >&2
    exit 1
  fi
  if gh release view "$VERSION" --repo "$REPO_SLUG" >/dev/null 2>&1; then
    echo "❌ Release $VERSION bestaat al. Verhoog __version__ en voeg een CHANGELOG-sectie toe." >&2
    exit 1
  fi
fi

# ── 0. Tests vóór de push ────────────────────────────────────────────────────
# Een rode test op GitHub kost een build en wachten; lokaal kost hij een halve
# minuut. De tests draaien in het image zelf, dus ook de Dockerfile is getest.
# Zonder Docker: in .venv of met python3, als pytest en aiohttp daar staan.
TEST_LOG="$(mktemp -t nswhunter-tests)"
PY_BIN="python3"
[ -x ".venv/bin/python" ] && PY_BIN=".venv/bin/python"
if [ "$SKIP_TESTS" -eq 1 ]; then
  echo "⚠️  Tests overgeslagen (--no-test)."
elif command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  echo "🧪 Image bouwen en tests draaien…"
  docker build -q -t "${LOCAL_TAG}:prepush" . > "$TEST_LOG" 2>&1 \
    || { tail -20 "$TEST_LOG"; echo "🛑 Image bouwen mislukt — niets gecommit."; exit 1; }
  docker run --rm --entrypoint sh -v "$(pwd)":/src:ro -w /src "${LOCAL_TAG}:prepush" -c \
    "pip install -q --root-user-action=ignore -r requirements-dev.txt >/dev/null 2>&1 && python3 -m pytest" > "$TEST_LOG" 2>&1 \
    || { tail -25 "$TEST_LOG"; echo "🛑 Tests rood — niets gecommit."; exit 1; }
  tail -1 "$TEST_LOG"
elif "$PY_BIN" -c "import pytest, aiohttp" 2>/dev/null; then
  echo "🧪 Tests…"
  "$PY_BIN" -m pytest > "$TEST_LOG" 2>&1 || { tail -25 "$TEST_LOG"; echo "🛑 Tests rood — niets gecommit."; exit 1; }
  tail -1 "$TEST_LOG"
else
  echo "⚠️  Geen Docker en geen pytest/aiohttp voor $PY_BIN — tests overgeslagen."
  echo "   Eén keer: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt"
fi
rm -f "$TEST_LOG"

# ── 1. Repo initialiseren ────────────────────────────────────────────────────
if [ ! -d .git ]; then
  echo "🔧 Nieuwe git-repo aanmaken…"
  git init -q
  git symbolic-ref HEAD "refs/heads/${BRANCH}"
fi

if ! git remote get-url origin >/dev/null 2>&1; then
  echo "🔗 Remote 'origin' instellen → ${REPO_URL}"
  git remote add origin "${REPO_URL}"
fi

# ── 2. Alleen de benodigde bestanden ─────────────────────────────────────────
if [ ! -f .gitignore ]; then
  echo "❌ .gitignore ontbreekt — stoppen (anders komt data/ mee)."
  exit 1
fi

git add -A

# ── 3. VEILIGHEIDSCHECK: geen geheimen ───────────────────────────────────────
echo "🔒 Controle op geheimen…"
STAGED=$(git diff --cached --name-only)
BLOCKED=""

# 3a. Verboden paden/bestandsnamen
while IFS= read -r f; do
  [ -z "$f" ] && continue
  case "$f" in
    data/*|*/data/*|.env|*.env|*state.json|*token*.txt)
      BLOCKED="${BLOCKED}\n  • $f" ;;
  esac
done <<< "${STAGED}"

# 3b. Inhoud. De patronen matchen alleen ECHTE waarden, niet de voorbeelden in
#     de broncode, de tests en de uitleg:
#       • SLM-key  : slm_ gevolgd door 40 tekens (de tests gebruiken "slm_test")
#       • compose  : een ingevulde ..._API_KEY= of ..._PASSWORD= (hoort leeg te zijn;
#                    invullen doe je op de NAS of in Portainer, niet in deze map)
#       • JWT      : volledige 3-delige token met lange payload
#       • Telegram : een bot-token (cijfers, dubbele punt, 30 of meer tekens)
while IFS= read -r f; do
  [ -f "$f" ] || continue
  case "$f" in *.png|*.jpg|*.zip|*.ico) continue ;; esac
  if grep -qE 'slm_[A-Za-z0-9]{40}' "$f" 2>/dev/null; then
    BLOCKED="${BLOCKED}\n  • $f (bevat een API key van Switch-library-manager-web)"
  fi
  case "$f" in
    docker-compose*.yml|*.yaml)
      if grep -qE '(API_KEY|PASSWORD)=[^[:space:]]' "$f" 2>/dev/null; then
        BLOCKED="${BLOCKED}\n  • $f (bevat een ingevulde API key of wachtwoord)"
      fi ;;
  esac
  if grep -qE '(^|[^0-9])[0-9]{8,10}:[A-Za-z0-9_-]{30,}' "$f" 2>/dev/null; then
    BLOCKED="${BLOCKED}\n  • $f (bevat een Telegram-bottoken)"
  fi
  if grep -qE 'eyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{60,}\.[A-Za-z0-9_-]{20,}' "$f" 2>/dev/null; then
    BLOCKED="${BLOCKED}\n  • $f (bevat een echt JWT-token)"
  fi
done <<< "${STAGED}"

if [ -n "${BLOCKED}" ]; then
  echo ""
  echo "🛑 GESTOPT — deze bestanden bevatten geheimen en mogen niet naar GitHub:"
  echo -e "${BLOCKED}"
  echo ""
  echo "   Maak de waarde leeg (of zet het bestand in .gitignore) en draai opnieuw."
  echo "   Er is niets gecommit."
  git reset -q
  exit 1
fi
echo "   ✅ geen geheimen gevonden"

# ── 4. Overzicht ─────────────────────────────────────────────────────────────
echo ""
echo "📦 Bestanden in deze commit:"
git diff --cached --name-status | sed 's/^/   /'
COUNT=$(echo "${STAGED}" | grep -c . || true)
echo "   (${COUNT} bestand(en))"

# ── 5. Committen ─────────────────────────────────────────────────────────────
echo ""
if git diff --cached --quiet; then
  echo "ℹ️  Geen nieuwe wijzigingen om te committen."
else
  git commit -q -m "${MSG}"
  echo "✅ Commit gemaakt: ${MSG%%$'\n'*}"
fi

# ── 6. Pushen ────────────────────────────────────────────────────────────────
# Ook als er niets nieuws te committen viel: een eerdere commit kan nog
# ongepusht zijn (bijv. als de vorige poging strandde op authenticatie).
echo ""
echo "⬆️  Pushen naar ${BRANCH} ..."
if PUSH_OUT=$(git push -u origin "${BRANCH}" 2>&1 && git push --tags 2>&1); then
  echo "${PUSH_OUT}" | sed 's/^/   /'
else
  echo "${PUSH_OUT}" | sed 's/^/   /'
  echo ""
  echo "⚠️  Push mislukt. Meestal is dat authenticatie of een repo die al inhoud heeft."
  echo "   • Eerste keer? GitHub wil een Personal Access Token als wachtwoord"
  echo "     (je gewone wachtwoord werkt niet meer):"
  echo "       https://github.com/settings/tokens   -> scope: repo, workflow"
  echo "     Gebruikersnaam = <account>, wachtwoord = het token."
  echo "   • Repo had al commits (bijv. een README via GitHub)? Haal ze eerst op:"
  echo "       git pull --rebase origin ${BRANCH} && ./commit-git.sh"
  echo ""
  echo "   Je commit is bewaard gebleven; opnieuw draaien pusht 'm alsnog."
  exit 1
fi

# ── 7. Release ───────────────────────────────────────────────────────────────
# De release maakt de tag vX.Y.Z; GitHub bouwt daarop de images :X.Y.Z en :X.Y.
if [ "$MAKE_RELEASE" -eq 1 ]; then
  echo ""
  echo "🏷️  Release ${VERSION} maken…"
  NOTES="$(mktemp -t nswhunter-notes)"
  awk -v v="$APP_VERSION" '
    index($0, "## [" v "]") == 1 { on = 1; next }
    on && /^## \[/ { exit }
    on { print }' CHANGELOG.md > "$NOTES"
  if gh release create "$VERSION" --repo "$REPO_SLUG" --target "$BRANCH" \
       --title "$VERSION" --notes-file "$NOTES"; then
    echo "✅ Release ${VERSION} staat op GitHub."
  else
    rm -f "$NOTES"
    echo "⚠️  Release maken mislukt. De code is wel gepusht; probeer: gh release create $VERSION" >&2
    exit 1
  fi
  rm -f "$NOTES"
fi

echo ""
echo "🎉 Klaar -> https://github.com/${REPO_SLUG}"
echo "   Build volgen: https://github.com/${REPO_SLUG}/actions"
