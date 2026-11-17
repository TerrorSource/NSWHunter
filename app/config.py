"""Settings. The ones in EDITABLE can be changed on the Configuration tab of the panel and are
then kept in /data/settings.json; a saved value wins from the environment variable of the same
name. Everything else comes from environment variables only (see .env.example)."""
import hashlib
import hmac
import json
import os
import secrets


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
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")
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

# off: everything waits for your click. A number: the best release of a game goes out by
# itself when its score (1-10, the chance that the download is right) is at least that.
AUTO_LEVELS = ("off", "10", "9", "8", "7", "6", "5")
LEGACY_LEVELS = {"sure": "9", "likely": "7"}  # the names before there were scores
AUTO_DOWNLOAD = env("AUTO_DOWNLOAD", "off").lower()
AUTO_DOWNLOAD = LEGACY_LEVELS.get(AUTO_DOWNLOAD, AUTO_DOWNLOAD)
if AUTO_DOWNLOAD not in AUTO_LEVELS:
    AUTO_DOWNLOAD = "off"
AUTO_BUNDLES = flag("AUTO_BUNDLES")  # also send base+update bundles automatically
MAX_GRABS_PER_RUN = int(number("MAX_GRABS_PER_RUN", 10))
INCLUDE_DLC = flag("INCLUDE_DLC")

SYNC_INTERVAL_MINUTES = max(5, number("SYNC_INTERVAL_MINUTES", 60))
# Every game that misses something is searched by name once per this many hours. That costs
# one API call per indexer per game: with many games and a strict indexer, choose 24 or 48.
INTERVALS = (6, 12, 24, 48)
try:
    SEARCH_INTERVAL_HOURS = int(env("SEARCH_INTERVAL_HOURS", "24"))
except ValueError:
    SEARCH_INTERVAL_HOURS = 24
if SEARCH_INTERVAL_HOURS not in INTERVALS:
    SEARCH_INTERVAL_HOURS = 24
# At most this many searches by name per round; 0 = no limit.
BACKLOG_PER_RUN = int(number("BACKLOG_PER_RUN", 0))
SEARCH_DELAY_SECONDS = number("SEARCH_DELAY_SECONDS", 3)
SEARCH_BY_TITLE_ID = flag("SEARCH_BY_TITLE_ID")
# A sent release that has not arrived in the library after this long counts as failed.
# How long a sent release may take to show up in the library. Longer than that it counts as
# failed and the next release gets its turn. While the download client is still downloading,
# the clock does not run.
WAITS = (30, 60, 120, 360, 1440)
try:
    GRAB_WAIT_MINUTES = int(env("GRAB_WAIT_MINUTES", "60"))
except ValueError:
    GRAB_WAIT_MINUTES = 60
if GRAB_WAIT_MINUTES not in WAITS:
    GRAB_WAIT_MINUTES = 60
# How often the download client is asked how the sent releases are doing.
WATCH_SECONDS = max(5, number("WATCH_SECONDS", 120))

# Every update of every game with its date, used to tell which update a release is. Several
# addresses, comma separated: the first that answers. The list of switch-library-manager-web
# knows new updates sooner than blawar/titledb.
TITLEDB_VERSIONS_URL = env(
    "TITLEDB_VERSIONS_URL",
    "https://github.com/DeLFuS77/switch-library-manager-web/releases/download/data/versions.json,"
    "https://raw.githubusercontent.com/blawar/titledb/master/versions.json")

def hash_password(password):
    """A password as it is kept: scrypt with its own salt, never the password itself."""
    if not password or password.startswith("scrypt$"):
        return password
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${digest.hex()}"


def check_password(password):
    """Is this the panel password? PANEL_PASSWORD holds the hash."""
    try:
        _, salt, digest = PANEL_PASSWORD.split("$")
        given = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1, dklen=32)
    except ValueError:
        return False
    return hmac.compare_digest(given.hex(), digest)


PANEL_USER = env("PANEL_USER", "admin")
PANEL_PASSWORD = hash_password(env("PANEL_PASSWORD"))
# Notifications: Telegram from the Configuration tab, and Apprise URLs for anything else.
TELEGRAM_BOT_TOKEN = env("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = env("TELEGRAM_CHAT_ID")
TELEGRAM_API_URL = url("TELEGRAM_API_URL", "https://api.telegram.org")
NOTIFY_URLS = env("NOTIFY_URLS")


# ---------------------------------------------------------------- the Configuration tab

CLIENTS = ("nzbget", "sabnzbd", "prowlarr")
# name -> kind: "url", "text", "secret", "bool", or the tuple of allowed values.
EDITABLE = {
    "SLM_URL": "url", "SLM_API_KEY": "secret",
    "PROWLARR_URL": "url", "PROWLARR_API_KEY": "secret", "PROWLARR_CATEGORIES": "numbers",
    "DOWNLOAD_CLIENT": CLIENTS, "DOWNLOAD_CATEGORY": "text",
    "NZBGET_URL": "url", "NZBGET_USER": "text", "NZBGET_PASSWORD": "secret",
    "SABNZBD_URL": "url", "SABNZBD_API_KEY": "secret",
    "AUTO_DOWNLOAD": AUTO_LEVELS, "INCLUDE_DLC": "bool", "SEARCH_INTERVAL_HOURS": INTERVALS,
    "GRAB_WAIT_MINUTES": WAITS,
    "TELEGRAM_BOT_TOKEN": "secret", "TELEGRAM_CHAT_ID": "text",
    "PANEL_USER": "text", "PANEL_PASSWORD": "secret",
}
SECRETS = [name for name, kind in EDITABLE.items() if kind == "secret"]


def normalize(name, value):
    """A value from the form or the settings file in the shape the app uses. ValueError with a
    message for the user if it cannot be right."""
    kind = EDITABLE[name]
    if kind == "bool":
        return value if isinstance(value, bool) else str(value).strip().lower() in ("1", "true", "yes", "on", "ja")
    if isinstance(kind, tuple) and isinstance(kind[0], int):
        try:
            number_value = int(str(value).strip())
        except ValueError:
            number_value = None
        if number_value not in kind:
            raise ValueError(f"{name}: choose from {', '.join(map(str, kind))}")
        return number_value
    if kind == "numbers":
        parts = value if isinstance(value, list) else str(value or "").replace(" ", "").split(",")
        parts = [str(p) for p in parts if str(p)]
        if not parts or not all(p.isdigit() and len(p) <= 6 for p in parts):
            raise ValueError(f"{name}: fill in numbers, separated by commas (1000 = Console)")
        return parts
    value = str(value if value is not None else "").strip()
    if name == "AUTO_DOWNLOAD":
        value = LEGACY_LEVELS.get(value.lower(), value)
    if len(value) > 500 or any(ord(c) < 32 for c in value):
        raise ValueError(f"{name}: invalid value")
    if kind == "url":
        value = value.rstrip("/")
        if value and not value.lower().startswith(("http://", "https://")):
            raise ValueError(f"{name}: start the address with http:// or https://")
    elif isinstance(kind, tuple):
        value = value.lower()
        if value not in kind:
            raise ValueError(f"{name}: choose from {', '.join(kind)}")
    elif name == "PANEL_USER" and (not value or ":" in value):
        raise ValueError("PANEL_USER: fill in a name, without a colon")
    elif name == "PANEL_PASSWORD":
        value = hash_password(value)
    elif name == "TELEGRAM_CHAT_ID" and value and not (value.lstrip("-").isdigit() or value.startswith("@")):
        raise ValueError("TELEGRAM_CHAT_ID: a chat ID is a number (with a minus in front for a group) or @channelname")
    return value


def saved():
    try:
        with open(SETTINGS_FILE) as f:
            data = json.load(f)
    except (FileNotFoundError, ValueError):
        return {}
    return {k: v for k, v in data.items() if k in EDITABLE} if isinstance(data, dict) else {}


def write(data):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = SETTINGS_FILE + ".tmp"
    # Keys and passwords: readable for the app user only.
    with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, SETTINGS_FILE)


def load_saved():
    """Put the saved settings on top of the environment. Called once at start."""
    data = saved()
    kept = dict(data)
    for name, value in data.items():
        try:
            globals()[name] = kept[name] = normalize(name, value)
        except ValueError:
            continue
    if kept != data:
        write(kept)  # a password saved by an older version: keep only its hash from now on


def update(values, clear=()):
    """Save settings from the Configuration tab and use them from now on.

    An empty secret means "keep what is there": the panel never gets a secret back, so it
    cannot send it again. A name in `clear` empties that secret. Returns what really changed."""
    new = {}
    for name, value in values.items():
        if name not in EDITABLE:
            raise ValueError(f"Unknown setting: {name}")
        if name in SECRETS and str(value or "").strip() == "":
            continue
        new[name] = normalize(name, value)
    for name in clear:
        if name not in SECRETS:
            raise ValueError(f"Unknown setting: {name}")
        new[name] = ""
    write({**saved(), **new})
    changed = sorted(name for name, value in new.items() if globals()[name] != value)
    globals().update(new)
    return changed


def overlay(values, clear=()):
    """The settings as they would be after saving this form, without saving or using them:
    for the Test buttons. Same rules as update(): an empty secret keeps the saved one."""
    import types
    result = types.SimpleNamespace(**{name: globals()[name] for name in EDITABLE})
    for name, value in values.items():
        if name not in EDITABLE:
            raise ValueError(f"Unknown setting: {name}")
        if name in SECRETS and str(value or "").strip() == "":
            continue
        setattr(result, name, normalize(name, value))
    for name in clear:
        if name in SECRETS:
            setattr(result, name, "")
    return result


def editable():
    """What the Configuration tab shows: values, and for secrets only whether one is set."""
    return {
        "values": {n: ",".join(globals()[n]) if EDITABLE[n] == "numbers" else globals()[n]
                   for n in EDITABLE if n not in SECRETS},
        "secrets": {n: bool(globals()[n]) for n in SECRETS},
    }


def auto_min_score():
    """The score from which a release goes out by itself; 0 = never."""
    return 0 if AUTO_DOWNLOAD == "off" else int(AUTO_DOWNLOAD)


def problems():
    """What is missing before anything can run."""
    missing = []
    if not SLM_URL:
        missing.append("SLM_URL is missing")
    if not PROWLARR_URL or not PROWLARR_API_KEY:
        missing.append("PROWLARR_URL or PROWLARR_API_KEY is missing")
    if DOWNLOAD_CLIENT == "nzbget" and not NZBGET_URL:
        missing.append("NZBGET_URL is missing")
    elif DOWNLOAD_CLIENT == "sabnzbd" and not (SABNZBD_URL and SABNZBD_API_KEY):
        missing.append("SABNZBD_URL or SABNZBD_API_KEY is missing")
    elif DOWNLOAD_CLIENT not in ("nzbget", "sabnzbd", "prowlarr"):
        missing.append("DOWNLOAD_CLIENT must be nzbget, sabnzbd or prowlarr")
    return missing
