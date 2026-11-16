"""Settings, all from environment variables (see .env.example)."""
import os


def env(name, default=""):
    return os.environ.get(name, default).strip()


def number(name, default):
    try:
        return float(env(name) or default)
    except ValueError:
        return float(default)


def flag(name, default=False):
    value = env(name).lower()
    return default if not value else value in ("1", "true", "yes", "on", "ja")


def url(name, default=""):
    return env(name, default).rstrip("/")


TZ = env("TZ", "Etc/UTC")
DATA_DIR = env("DATA_DIR", "/data")
PORT = int(number("PORT", 3033))
STATE_FILE = os.path.join(DATA_DIR, "state.json")
VERSIONS_FILE = os.path.join(DATA_DIR, "titledb-versions.json")

# Switch-library-manager-web: the library and what is missing.
SLM_URL = url("SLM_URL")
SLM_API_KEY = env("SLM_API_KEY")

# Prowlarr: searching the indexers.
PROWLARR_URL = url("PROWLARR_URL")
PROWLARR_API_KEY = env("PROWLARR_API_KEY")
PROWLARR_CATEGORIES = [c for c in env("PROWLARR_CATEGORIES", "1000").replace(" ", "").split(",") if c]
PROWLARR_INDEXER_IDS = [i for i in env("PROWLARR_INDEXER_IDS").replace(" ", "").split(",") if i]

# Where a chosen release goes: nzbget, sabnzbd, or prowlarr (= Prowlarr's own download client).
DOWNLOAD_CLIENT = env("DOWNLOAD_CLIENT", "nzbget").lower()
DOWNLOAD_CATEGORY = env("DOWNLOAD_CATEGORY", "games")
NZBGET_URL = url("NZBGET_URL")
NZBGET_USER = env("NZBGET_USER")
NZBGET_PASSWORD = env("NZBGET_PASSWORD")
SABNZBD_URL = url("SABNZBD_URL")
SABNZBD_API_KEY = env("SABNZBD_API_KEY")

# off: everything waits for your click. sure: releases with the right game and the newest
# internal version number go out by themselves. likely: also releases with only a display
# version (v1.0.4) that were posted after the newest update came out.
AUTO_DOWNLOAD = env("AUTO_DOWNLOAD", "off").lower()
if AUTO_DOWNLOAD not in ("off", "sure", "likely"):
    AUTO_DOWNLOAD = "off"
AUTO_BUNDLES = flag("AUTO_BUNDLES")  # also send base+update bundles automatically
MAX_GRABS_PER_RUN = int(number("MAX_GRABS_PER_RUN", 10))
INCLUDE_DLC = flag("INCLUDE_DLC")

SYNC_INTERVAL_MINUTES = max(5, number("SYNC_INTERVAL_MINUTES", 60))
# Searching by name costs one API call per indexer per game, so the backlog goes slowly.
BACKLOG_PER_RUN = int(number("BACKLOG_PER_RUN", 10))
BACKLOG_DAYS = number("BACKLOG_DAYS", 7)
SEARCH_DELAY_SECONDS = number("SEARCH_DELAY_SECONDS", 3)
SEARCH_BY_TITLE_ID = flag("SEARCH_BY_TITLE_ID")
# A sent release that has not arrived in the library after this long counts as failed.
GRAB_WAIT_HOURS = number("GRAB_WAIT_HOURS", 48)

# Release dates of every update, used when a release name has no internal version number.
TITLEDB_VERSIONS_URL = env(
    "TITLEDB_VERSIONS_URL", "https://raw.githubusercontent.com/blawar/titledb/master/versions.json")

PANEL_USER = env("PANEL_USER", "admin")
PANEL_PASSWORD = env("PANEL_PASSWORD")
NOTIFY_URLS = env("NOTIFY_URLS")


def problems():
    """What is missing before anything can run."""
    missing = []
    if not SLM_URL:
        missing.append("SLM_URL ontbreekt")
    if not PROWLARR_URL or not PROWLARR_API_KEY:
        missing.append("PROWLARR_URL of PROWLARR_API_KEY ontbreekt")
    if DOWNLOAD_CLIENT == "nzbget" and not NZBGET_URL:
        missing.append("NZBGET_URL ontbreekt")
    elif DOWNLOAD_CLIENT == "sabnzbd" and not (SABNZBD_URL and SABNZBD_API_KEY):
        missing.append("SABNZBD_URL of SABNZBD_API_KEY ontbreekt")
    elif DOWNLOAD_CLIENT not in ("nzbget", "sabnzbd", "prowlarr"):
        missing.append("DOWNLOAD_CLIENT moet nzbget, sabnzbd of prowlarr zijn")
    return missing
