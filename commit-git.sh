#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# commit-git.sh — put NSWHunter on GitHub and optionally make a release
#
#   ./commit-git.sh                      push with the default commit message
#   ./commit-git.sh "commit message"     push with your own commit message
#   ./commit-git.sh -r "commit message"  push and make GitHub release vX.Y.Z
#   ./commit-git.sh --no-test            skip the tests
#
# The version number comes from app/version.py (__version__), the release notes from
# CHANGELOG.md (the section "## [X.Y.Z] - YYYY-MM-DD").
#
# What GitHub does next (.github/workflows/docker.yml):
#   push to main     -> ghcr.io/<account>/nswhunter:latest
#   release vX.Y.Z   -> ghcr.io/<account>/nswhunter:X.Y.Z and :X.Y
#
# After that on the server: fetch the stack again (pull and redeploy).
#
# Releasing a new version:
#   1. raise __version__ in app/version.py
#   2. add a section "## [X.Y.Z] - YYYY-MM-DD" at the top of CHANGELOG.md
#   3. ./commit-git.sh -r "what changed"
#
# Safety: the script refuses to commit when there are secrets among the files
# (API keys, filled-in passwords in the compose file, .env, data/).
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

BRANCH="main"
LOCAL_TAG="nswhunter"

cd "$(dirname "$0")"
echo "📁 $(pwd)"

# Where it goes is the remote 'origin' of this folder; no account is named in this script.
REPO_URL="$(git remote get-url origin 2>/dev/null || true)"
if [ -z "$REPO_URL" ]; then
  echo "❌ This folder has no git remote 'origin'. Set it once:" >&2
  echo "     git init -b ${BRANCH} && git remote add origin https://github.com/<account>/<repo>.git" >&2
  exit 1
fi
REPO_SLUG="$(printf '%s' "$REPO_URL" | sed -E 's#^(https://github\.com/|git@github\.com:)##; s#\.git$##')"

# ── Arguments ────────────────────────────────────────────────────────────────
MSG="update from the working folder"
MAKE_RELEASE=0
SKIP_TESTS=0
for arg in "$@"; do
  case "$arg" in
    -r|--release) MAKE_RELEASE=1 ;;
    --no-test)    SKIP_TESTS=1 ;;
    -h|--help)    sed -n '2,26p' "$0"; exit 0 ;;
    -*)           echo "❌ Unknown option: $arg (see -h)" >&2; exit 1 ;;
    *)            MSG="$arg" ;;
  esac
done

# ── Version number and changelog────────────────────────────────────────────────
# The commit message is the title of the GitHub Action run; with "v1.2.0 · …" in front
# the list shows at a glance which build is which version.
APP_VERSION=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' app/version.py)
if ! [[ "$APP_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "❌ Invalid version number in app/version.py: '$APP_VERSION' (expected X.Y.Z)." >&2
  exit 1
fi
VERSION="v$APP_VERSION"
if ! grep -q "^## \[$APP_VERSION\]" CHANGELOG.md; then
  echo "❌ CHANGELOG.md has no section '## [$APP_VERSION]'." >&2
  echo "   Write down what changed first (and raise __version__ if needed)." >&2
  exit 1
fi
if ! [[ "${MSG}" =~ ^v[0-9]+ ]]; then
  MSG="${VERSION} · ${MSG}"
fi
echo "📦 Version: ${VERSION}"

# Warn early when the release already exists (then the version was not raised).
if [ "$MAKE_RELEASE" -eq 1 ]; then
  if ! command -v gh >/dev/null 2>&1; then
    echo "❌ -r needs the gh CLI (brew install gh, then gh auth login)." >&2
    exit 1
  fi
  if gh release view "$VERSION" --repo "$REPO_SLUG" >/dev/null 2>&1; then
    echo "❌ Release $VERSION already exists. Raise __version__ and add a CHANGELOG section." >&2
    exit 1
  fi
fi

# ── 0. Tests before the push────────────────────────────────────────────────────
# A red test on GitHub costs a build and a wait; here it costs half a minute.
# The tests run inside the image itself, so the Dockerfile is tested too.
# Without Docker: in .venv or with python3, if pytest and aiohttp are there.
TEST_LOG="$(mktemp -t nswhunter-tests)"
PY_BIN="python3"
[ -x ".venv/bin/python" ] && PY_BIN=".venv/bin/python"
if [ "$SKIP_TESTS" -eq 1 ]; then
  echo "⚠️  Tests skipped (--no-test)."
elif command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  echo "🧪 Building the image and running the tests…"
  docker build -q -t "${LOCAL_TAG}:prepush" . > "$TEST_LOG" 2>&1 \
    || { tail -20 "$TEST_LOG"; echo "🛑 Building the image failed — nothing committed."; exit 1; }
  docker run --rm --entrypoint sh -v "$(pwd)":/src:ro -w /src "${LOCAL_TAG}:prepush" -c \
    "pip install -q --root-user-action=ignore -r requirements-dev.txt >/dev/null 2>&1 && python3 -m pytest" > "$TEST_LOG" 2>&1 \
    || { tail -25 "$TEST_LOG"; echo "🛑 Tests failed — nothing committed."; exit 1; }
  tail -1 "$TEST_LOG"
elif "$PY_BIN" -c "import pytest, aiohttp" 2>/dev/null; then
  echo "🧪 Tests…"
  "$PY_BIN" -m pytest > "$TEST_LOG" 2>&1 || { tail -25 "$TEST_LOG"; echo "🛑 Tests failed — nothing committed."; exit 1; }
  tail -1 "$TEST_LOG"
else
  echo "⚠️  No Docker and no pytest/aiohttp for $PY_BIN — tests skipped."
  echo "   Once: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt"
fi
rm -f "$TEST_LOG"

# ── 2. Only the files that are needed─────────────────────────────────────────
if [ ! -f .gitignore ]; then
  echo "❌ .gitignore is missing — stopping (or data/ would go along)."
  exit 1
fi

git add -A

# ── 3. SAFETY CHECK: no secrets ─────────────────────────────────────────────
echo "🔒 Checking for secrets…"
STAGED=$(git diff --cached --name-only)
BLOCKED=""

# 3a. Forbidden paths and file names
while IFS= read -r f; do
  [ -z "$f" ] && continue
  case "$f" in
    data/*|*/data/*|.env|*.env|*state.json|*token*.txt)
      BLOCKED="${BLOCKED}\n  • $f" ;;
  esac
done <<< "${STAGED}"

# 3b. Contents. The patterns match REAL values only, not the examples in the
#     source code, the tests and the documentation:
#       • SLM-key  : slm_ followed by 40 characters (the tests use "slm_test")
#       • compose  : a filled-in ..._API_KEY= or ..._PASSWORD= (must be empty; fill it in
#                    on the server, not in this folder)
#       • JWT      : a complete three-part token with a long payload
#       • Telegram : a bot token (digits, a colon, 30 or more characters)
while IFS= read -r f; do
  [ -f "$f" ] || continue
  case "$f" in *.png|*.jpg|*.zip|*.ico) continue ;; esac
  if grep -qE 'slm_[A-Za-z0-9]{40}' "$f" 2>/dev/null; then
    BLOCKED="${BLOCKED}\n  • $f (holds an API key of Switch-library-manager-web)"
  fi
  case "$f" in
    docker-compose*.yml|*.yaml)
      if grep -qE '(API_KEY|PASSWORD)=[^[:space:]]' "$f" 2>/dev/null; then
        BLOCKED="${BLOCKED}\n  • $f (holds a filled-in API key or password)"
      fi ;;
  esac
  if grep -qE '(^|[^0-9])[0-9]{8,10}:[A-Za-z0-9_-]{30,}' "$f" 2>/dev/null; then
    BLOCKED="${BLOCKED}\n  • $f (holds a Telegram bot token)"
  fi
  if grep -qE 'eyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{60,}\.[A-Za-z0-9_-]{20,}' "$f" 2>/dev/null; then
    BLOCKED="${BLOCKED}\n  • $f (holds a real JWT token)"
  fi
done <<< "${STAGED}"

if [ -n "${BLOCKED}" ]; then
  echo ""
  echo "🛑 STOPPED — these files hold secrets and must not go to GitHub:"
  echo -e "${BLOCKED}"
  echo ""
  echo "   Empty the value (or put the file in .gitignore) and run again."
  echo "   Nothing was committed."
  git reset -q
  exit 1
fi
echo "   ✅ no secrets found"

# ── 4. Overview ──────────────────────────────────────────────────────────────
echo ""
echo "📦 Files in this commit:"
git diff --cached --name-status | sed 's/^/   /'
COUNT=$(echo "${STAGED}" | grep -c . || true)
echo "   (${COUNT} file(s))"

# ── 5. Commit ────────────────────────────────────────────────────────────────
echo ""
if git diff --cached --quiet; then
  echo "ℹ️  No new changes to commit."
else
  git commit -q -m "${MSG}"
  echo "✅ Committed: ${MSG%%$'\n'*}"
fi

# ── 6. Push ──────────────────────────────────────────────────────────────────
# Also when there was nothing new to commit: an earlier commit may not have been
# pushed yet (for example when the previous attempt failed on authentication).
echo ""
echo "⬆️  Pushing to ${BRANCH} ..."
if PUSH_OUT=$(git push -u origin "${BRANCH}" 2>&1 && git push --tags 2>&1); then
  echo "${PUSH_OUT}" | sed 's/^/   /'
else
  echo "${PUSH_OUT}" | sed 's/^/   /'
  echo ""
  echo "⚠️  Push failed. Usually that is authentication, or a repo that already has content."
  echo "   • First time? GitHub wants a Personal Access Token as the password"
  echo "     (your normal password no longer works):"
  echo "       https://github.com/settings/tokens   -> scope: repo, workflow"
  echo "     Username = your GitHub username, password = the token."
  echo "   • The repo already had commits (a README made on GitHub)? Fetch them first:"
  echo "       git pull --rebase origin ${BRANCH} && ./commit-git.sh"
  echo ""
  echo "   Your commit is kept; running again pushes it after all."
  exit 1
fi

# ── 7. Release ───────────────────────────────────────────────────────────────
# The release makes the tag vX.Y.Z; GitHub builds the images :X.Y.Z and :X.Y from it.
if [ "$MAKE_RELEASE" -eq 1 ]; then
  echo ""
  echo "🏷️  Making release ${VERSION}…"
  NOTES="$(mktemp -t nswhunter-notes)"
  awk -v v="$APP_VERSION" '
    index($0, "## [" v "]") == 1 { on = 1; next }
    on && /^## \[/ { exit }
    on { print }' CHANGELOG.md > "$NOTES"
  if gh release create "$VERSION" --repo "$REPO_SLUG" --target "$BRANCH" \
       --title "$VERSION" --notes-file "$NOTES"; then
    echo "✅ Release ${VERSION} is on GitHub."
  else
    rm -f "$NOTES"
    echo "⚠️  Making the release failed. The code was pushed; try: gh release create $VERSION" >&2
    exit 1
  fi
  rm -f "$NOTES"
fi

echo ""
echo "🎉 Done -> https://github.com/${REPO_SLUG}"
echo "   Follow the build: https://github.com/${REPO_SLUG}/actions"
