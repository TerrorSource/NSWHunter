"""Settings.

There are single settings (EDITABLE) and three lists of providers (PROVIDERS): the indexers,
the download clients and the connections. Both are changed in the panel and kept in
settings.json in the config folder. For a single setting an environment variable of the same name gives the
first value; a saved value wins. Everything else comes from environment variables only (see
.env.example)."""
import hashlib
import hmac
import json
import os
import secrets
from urllib.parse import urlsplit


def env(name, default=""):
    return os.environ.get(name, default).strip()


def number(name, default):
    try:
        return float(env(name) or default)
    except ValueError:
        return float(default)


def flag(name, default=False):
    value = env(name).lower()
    return default if not value else value in ("1", "true", "yes", "on")


def url(name, default=""):
    return env(name, default).rstrip("/")


def choice(name, allowed, default):
    """An environment variable that must be one of `allowed` (numbers or lower-case words)."""
    value = env(name, str(default)).lower()
    for option in allowed:
        if str(option) == value:
            return option
    return default


TZ = env("TZ", "Etc/UTC")
# Where the settings and the state are kept. The entrypoint of the image sets it: /config, or
# /data for an installation of before version 3.11 that still has them there.
DATA_DIR = env("DATA_DIR", "/config")
PORT = int(number("PORT", 3033))
STATE_FILE = os.path.join(DATA_DIR, "state.json")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")
SESSIONS_FILE = os.path.join(DATA_DIR, "sessions.json")
VERSIONS_FILE = os.path.join(DATA_DIR, "titledb-versions.json")
TITLES_FILE = os.path.join(DATA_DIR, "titledb-games.json")
# The password the first start made up, kept until the user has chosen one of their own.
INITIAL_PASSWORD_FILE = os.path.join(DATA_DIR, "initial-password")
INITIAL_PASSWORD = None  # that password, while it is the one that works (set by first_login)
# An empty file with this name in the config folder asks for a new made-up password at the next start.
RESET_FILE = os.path.join(DATA_DIR, "reset-password")
WAS_RESET = False  # whether this start did that
LOG_DIR = os.path.join(DATA_DIR, "logs")
COVER_DIR = os.path.join(DATA_DIR, "covers")  # the small pictures of the games, fetched once

# Switch-library-manager-web: the library and what is missing.
SLM_URL = url("SLM_URL")
SLM_API_KEY = env("SLM_API_KEY")

# Only these indexers of a Prowlarr (ids from Prowlarr, comma separated). Empty = all of them.
PROWLARR_INDEXER_IDS = [i for i in env("PROWLARR_INDEXER_IDS").replace(" ", "").split(",") if i]

# off: everything waits for your click. A number: the best release of a game goes out by
# itself when its score (1-10, the chance that the download is right) is at least that.
AUTO_LEVELS = ("off", "10", "9", "8", "7", "6", "5")
LEGACY_LEVELS = {"sure": "9", "likely": "7"}  # the names before there were scores
AUTO_DOWNLOAD = env("AUTO_DOWNLOAD", "off").lower()
AUTO_DOWNLOAD = LEGACY_LEVELS.get(AUTO_DOWNLOAD, AUTO_DOWNLOAD)
if AUTO_DOWNLOAD not in AUTO_LEVELS:
    AUTO_DOWNLOAD = "off"
AUTO_BUNDLES = flag("AUTO_BUNDLES")  # also send base+update bundles automatically
# Also send a game of the wishlist automatically. Off: a whole game always waits for a click.
AUTO_WISHLIST = flag("AUTO_WISHLIST")
# A release of a whole game smaller than this many MB is broken or a fake; 0 = no minimum.
MIN_GAME_MB = int(min(10000, max(0, number("MIN_GAME_MB", 20))))
MAX_GRABS_PER_RUN = int(number("MAX_GRABS_PER_RUN", 10))
INCLUDE_DLC = flag("INCLUDE_DLC", True)

SYNC_INTERVAL_MINUTES = max(5, number("SYNC_INTERVAL_MINUTES", 60))
# Every game that misses something is searched by name once per this many hours. That costs
# one API call per indexer per game: with many games and a strict indexer, choose 24 or 48.
INTERVALS = (6, 12, 24, 48)
SEARCH_INTERVAL_HOURS = choice("SEARCH_INTERVAL_HOURS", INTERVALS, 24)
# At most this many searches by name per round; 0 = no limit.
BACKLOG_PER_RUN = int(number("BACKLOG_PER_RUN", 0))
SEARCH_DELAY_SECONDS = number("SEARCH_DELAY_SECONDS", 3)
SEARCH_BY_TITLE_ID = flag("SEARCH_BY_TITLE_ID")
# How long a sent release may take to show up in the library. Longer than that it counts as
# failed and the next release gets its turn. While the download client is still downloading,
# the clock does not run.
WAITS = (30, 60, 120, 360, 1440)
GRAB_WAIT_MINUTES = choice("GRAB_WAIT_MINUTES", WAITS, 30)
# Importing: put a finished download in the library, as Sonarr and Radarr do. It needs a root
# folder, and the download folder as a volume of the container.
IMPORT_COMPLETED = flag("IMPORT_COMPLETED", True)
# The folder of a game in a root folder, written as Organize of Switch-library-manager-web
# writes it: {TITLE_NAME} and {TITLE_ID}. Empty: a download goes next to the files its game
# already has, as the library names them.
FOLDER_TEMPLATE = env("FOLDER_TEMPLATE", "{TITLE_NAME} [{TITLE_ID}]")
# After a usenet download was put in the library: take it out of the download client too.
REMOVE_COMPLETED = flag("REMOVE_COMPLETED", True)
# After the files of a download were moved to the library: remove its folder if nothing is left in it.
DELETE_EMPTY_FOLDERS = flag("DELETE_EMPTY_FOLDERS", True)
# Where the library is: [{"path": the folder in this container, "library_path": the same folder
# as Switch-library-manager-web names it}]. Set in the panel only (see add_root_folder).
ROOT_FOLDERS = []
# Keep failed downloads out of the lists of the panel, and do not offer the same usenet release
# again when another indexer has it too: it is the same post, and would fail the same way.
HIDE_FAILED_DOWNLOADS = flag("HIDE_FAILED_DOWNLOADS", True)
# How often the download clients are asked how the sent releases are doing.
WATCH_SECONDS = max(5, number("WATCH_SECONDS", 120))

# Every update of every game with its date, used to tell which update a release is. Several
# addresses, comma separated: the first that answers. The list of switch-library-manager-web
# knows new updates sooner than blawar/titledb.
TITLEDB_VERSIONS_URL = env(
    "TITLEDB_VERSIONS_URL",
    "https://github.com/DeLFuS77/switch-library-manager-web/releases/download/data/versions.json,"
    "https://raw.githubusercontent.com/blawar/titledb/master/versions.json")
# The name, picture and release date of every Switch game, for Add Game: titles.json of
# switch-library-manager-web, compressed with zstd (a plain JSON file works too).
TITLEDB_TITLES_URL = env(
    "TITLEDB_TITLES_URL",
    "https://github.com/DeLFuS77/switch-library-manager-web/releases/download/data/titles.json.zst")
TELEGRAM_API_URL = url("TELEGRAM_API_URL", "https://api.telegram.org")


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


# The login of the panel. Without a password the first start makes one up (see first_login).
PANEL_USER = env("PANEL_USER", "admin")
PANEL_PASSWORD = hash_password(env("PANEL_PASSWORD"))
MIN_PASSWORD = 8
# Extra host names the panel answers to, comma separated: the name of a reverse proxy, for
# example. An IP address and a name inside the home network always work (see auth.py).
PANEL_HOSTS = env("PANEL_HOSTS").lower().replace(" ", "")

# info: what happens. debug: also every search and every call to a service. trace: also every
# release that was judged, with the verdict.
LOG_LEVELS = ("info", "debug", "trace")
LOG_LEVEL = choice("LOG_LEVEL", LOG_LEVELS, "info")
LOG_KEEPS = (7, 14, 30, 90)  # there is a log file per day; this many days of them are kept
LOG_KEEP_DAYS = choice("LOG_KEEP_DAYS", LOG_KEEPS, 14)

# The second step of the login: the secret an authenticator app shares with the panel. Empty:
# the login is the password alone. Set and removed in the panel only (see set_totp).
TOTP_SECRET = ""

# The panel over HTTPS as well, on a port of its own; HTTP stays as it is. Without a certificate
# of your own NSWHunter makes one itself (see tls.py).
SSL_ENABLED = flag("SSL_ENABLED")
SSL_PORT = int(min(65535, max(1, number("SSL_PORT", 3443))))
SSL_CERT_PATH = env("SSL_CERT_PATH")
SSL_KEY_PATH = env("SSL_KEY_PATH")

# Backups of the settings and the state. A relative folder is under DATA_DIR.
def backup_folder(asked):
    """The folder of the backups: "backups" in the config folder (/config/backups), unless
    another one is asked for. Before version 3.11 it was the volume /backup; that only still
    counts where the container has that volume, else its backups would be gone with it."""
    asked = (asked or "").strip()
    if not asked or (asked.rstrip("/") == "/backup" and not os.path.ismount("/backup")):
        return os.path.join(DATA_DIR, "backups")
    return asked


BACKUP_FOLDER = backup_folder(env("BACKUP_FOLDER"))
# With a password the backups are encrypted: a backup holds every key and password of the settings.
BACKUP_PASSWORD = env("BACKUP_PASSWORD")
BACKUP_INTERVAL_DAYS = int(min(90, max(1, number("BACKUP_INTERVAL_DAYS", 7))))
BACKUP_RETENTION_DAYS = int(min(365, max(1, number("BACKUP_RETENTION_DAYS", 28))))

# How the panel shows things; kept here so every browser shows the same.
THEMES = ("auto", "dark", "light")
UI_THEME = choice("UI_THEME", THEMES, "auto")
DATE_FORMATS = ("browser", "iso", "dmy", "mdy", "long")
UI_DATE_FORMAT = choice("UI_DATE_FORMAT", DATE_FORMATS, "browser")
TIME_FORMATS = ("browser", "24", "12")
UI_TIME_FORMAT = choice("UI_TIME_FORMAT", TIME_FORMATS, "browser")
UI_RELATIVE_DATES = flag("UI_RELATIVE_DATES", True)
LONG_DATE_FORMATS = ("browser", "dmy", "mdy")
UI_LONG_DATE_FORMAT = choice("UI_LONG_DATE_FORMAT", LONG_DATE_FORMATS, "browser")
UI_COLOR_IMPAIRED = flag("UI_COLOR_IMPAIRED")  # blue and orange instead of green and red


# ---------------------------------------------------------------- single settings

# name -> kind: "url", "text", "secret", "bool", "path", "file" (a file in the container, or
# empty), a range of whole numbers, or the tuple of allowed values.
EDITABLE = {
    "SLM_URL": "url", "SLM_API_KEY": "secret",
    "AUTO_DOWNLOAD": AUTO_LEVELS, "AUTO_WISHLIST": "bool", "MIN_GAME_MB": range(0, 10001), "INCLUDE_DLC": "bool", "SEARCH_INTERVAL_HOURS": INTERVALS,
    "GRAB_WAIT_MINUTES": WAITS, "HIDE_FAILED_DOWNLOADS": "bool",
    "IMPORT_COMPLETED": "bool", "REMOVE_COMPLETED": "bool", "DELETE_EMPTY_FOLDERS": "bool", "FOLDER_TEMPLATE": "template",
    "PANEL_USER": "text", "PANEL_PASSWORD": "secret", "PANEL_HOSTS": "text",
    "SSL_ENABLED": "bool", "SSL_PORT": range(1, 65536), "SSL_CERT_PATH": "file", "SSL_KEY_PATH": "file",
    "LOG_LEVEL": LOG_LEVELS, "LOG_KEEP_DAYS": LOG_KEEPS,
    "BACKUP_FOLDER": "path", "BACKUP_INTERVAL_DAYS": range(1, 91), "BACKUP_RETENTION_DAYS": range(1, 366),
    "BACKUP_PASSWORD": "secret",
    "UI_THEME": THEMES, "UI_DATE_FORMAT": DATE_FORMATS, "UI_TIME_FORMAT": TIME_FORMATS,
    "UI_RELATIVE_DATES": "bool", "UI_LONG_DATE_FORMAT": LONG_DATE_FORMATS, "UI_COLOR_IMPAIRED": "bool",
}
SECRETS = [name for name, kind in EDITABLE.items() if kind == "secret"]
# Kept in the settings file too, but no setting of a form: set by steps of their own in the panel.
PRIVATE = ("TOTP_SECRET", "ROOT_FOLDERS")
# A key or password belongs to the address it was saved for: it is never sent to another one.
BOUND = {"SLM_URL": "SLM_API_KEY"}


def origin(address):
    """Scheme, host and port of an address: where a key that goes with it would be sent."""
    parts = urlsplit(address or "")
    try:
        return parts.scheme.lower(), (parts.hostname or "").lower(), parts.port
    except ValueError:
        return parts.scheme.lower(), parts.netloc.lower(), None


def panel_hosts():
    return {h for h in PANEL_HOSTS.split(",") if h}


def check_bound(new, clear):
    """A changed address with a saved key that was not typed again: refuse. Otherwise anyone
    who can reach the form could have a saved key sent to an address of their own."""
    for address, secret in BOUND.items():
        # An emptied address sends nothing anywhere.
        if not new.get(address) or origin(new[address]) == origin(globals()[address]):
            continue
        if globals()[secret] and secret not in new and secret not in clear:
            raise ValueError(f"{secret}: fill it in again, because the address changed. "
                             "A saved key or password is only sent to the address it was saved for.")


def clean_text(name, value):
    value = str(value if value is not None else "").strip()
    if len(value) > 500 or any(ord(c) < 32 for c in value):
        raise ValueError(f"{name}: invalid value")
    return value


def clean_url(name, value):
    value = clean_text(name, value).rstrip("/")
    if value and not value.lower().startswith(("http://", "https://")):
        raise ValueError(f"{name}: start the address with http:// or https://")
    return value


def clean_numbers(name, value):
    parts = value if isinstance(value, list) else str(value or "").replace(" ", "").split(",")
    parts = [str(p) for p in parts if str(p)]
    if not parts or not all(p.isdigit() and len(p) <= 6 for p in parts):
        raise ValueError(f"{name}: fill in numbers, separated by commas (1000 = Console)")
    return parts


def clean_bool(value):
    return value if isinstance(value, bool) else str(value).strip().lower() in ("1", "true", "yes", "on")


def clean_chat(name, value):
    value = clean_text(name, value)
    if value and not (value.lstrip("-").isdigit() or value.startswith("@")):
        raise ValueError(f"{name}: a chat ID is a number (with a minus in front for a group) or @channelname")
    return value


def normalize(name, value):
    """A value from the form or the settings file in the shape the app uses. ValueError with a
    message for the user if it cannot be right."""
    kind = EDITABLE[name]
    if kind == "bool":
        return clean_bool(value)
    if isinstance(kind, range) or (isinstance(kind, tuple) and isinstance(kind[0], int)):
        try:
            number_value = int(str(value).strip())
        except ValueError:
            number_value = None
        if number_value not in kind:
            allowed = f"a number from {kind[0]} to {kind[-1]}" if isinstance(kind, range) else ", ".join(map(str, kind))
            raise ValueError(f"{name}: choose {allowed}")
        return number_value
    if kind == "url":
        return clean_url(name, value)
    value = clean_text(name, value)
    if name == "AUTO_DOWNLOAD":
        value = LEGACY_LEVELS.get(value.lower(), value)
    if isinstance(kind, tuple):
        value = value.lower()
        if value not in kind:
            raise ValueError(f"{name}: choose from {', '.join(kind)}")
    elif kind == "path":
        if not value or ".." in value.split("/") or "\\" in value:
            raise ValueError(f"{name}: fill in a folder, like /backup")
    elif kind == "template":
        if value and "{TITLE_NAME}" not in value and "{TITLE_ID}" not in value:
            raise ValueError(f"{name}: the template needs {{TITLE_NAME}} or {{TITLE_ID}}")
        rest = value.replace("{TITLE_NAME}", "").replace("{TITLE_ID}", "")
        if "{" in rest or "}" in rest:
            raise ValueError(f"{name}: only {{TITLE_NAME}} and {{TITLE_ID}} can be used")
        if "/" in value or "\\" in value or len(value) > 120:
            raise ValueError(f"{name}: the name of one folder, without a slash")
    elif kind == "file":
        if value and (not value.startswith("/") or ".." in value.split("/") or "\\" in value):
            raise ValueError(f"{name}: fill in the whole path of a file in the container, like /config/certs/panel.pem")
    elif name == "PANEL_USER" and (not value or ":" in value):
        raise ValueError("PANEL_USER: fill in a name, without a colon")
    elif name == "PANEL_PASSWORD":
        if value and not value.startswith("scrypt$") and len(value) < MIN_PASSWORD:
            raise ValueError(f"PANEL_PASSWORD: use at least {MIN_PASSWORD} characters")
        value = hash_password(value)
    elif name == "PANEL_HOSTS":
        value = value.lower().replace(" ", "")
        if any(not h or not all(c.isalnum() or c in ".-" for c in h) for h in value.split(",") if value):
            raise ValueError("PANEL_HOSTS: fill in host names separated by commas, without http:// and without a port")
    return value


# ---------------------------------------------------------------- providers

# The lists of things that can be added in the panel. Per type: the name shown, and its fields
# with their kind ("url", "text", "secret", "bool", "numbers", "chat" or "priority").
INDEXER_FIELDS = {"url": "url", "api_key": "secret", "categories": "numbers", "priority": "priority"}
# remote_path / local_path: where the download client says its downloads are, and where the
# same folder is in this container. Only for importing, and only if the two differ.
PATHS = {"remote_path": "folder", "local_path": "folder"}
TORRENT_FIELDS = {"url": "url", "username": "text", "password": "secret", "category": "text", **PATHS}
# What a connection is told about; each can be switched off per connection.
TRIGGERS = {
    "on_grab": "bool",    # a release was sent automatically
    "on_arrive": "bool",  # what was sent is in the library
    "on_fail": "bool",    # a download failed, did not arrive, or was downloaded but never seen
    "on_choice": "bool",  # releases await a choice
    "on_health": "bool",  # a round broke
}
PROVIDERS = {
    "INDEXERS": {
        # Prowlarr searches its own indexers and has a priority for each of them.
        "prowlarr": {"label": "Prowlarr", "fields": {"url": "url", "api_key": "secret", "categories": "numbers"}},
        "newznab": {"label": "Newznab (usenet indexer)", "protocol": "usenet", "fields": INDEXER_FIELDS},
        "torznab": {"label": "Torznab (torrent indexer)", "protocol": "torrent", "fields": INDEXER_FIELDS},
    },
    "DOWNLOAD_CLIENTS": {
        "nzbget": {"label": "NZBGet", "protocol": "usenet", "fields": {
            "url": "url", "username": "text", "password": "secret", "category": "text", **PATHS}},
        "sabnzbd": {"label": "SABnzbd", "protocol": "usenet", "fields": {
            "url": "url", "api_key": "secret", "category": "text", **PATHS}},
        "qbittorrent": {"label": "qBittorrent", "protocol": "torrent", "fields": TORRENT_FIELDS},
        "transmission": {"label": "Transmission", "protocol": "torrent", "fields": TORRENT_FIELDS},
        "utorrent": {"label": "uTorrent", "protocol": "torrent", "fields": TORRENT_FIELDS},
        # Lets Prowlarr hand a usenet release it found to the download client set up in Prowlarr.
        "prowlarr": {"label": "The download client of Prowlarr", "protocol": "prowlarr", "fields": {}},
    },
    "CONNECTIONS": {
        "telegram": {"label": "Telegram", "fields": {"bot_token": "secret", "chat_id": "chat", "ask": "bool", **TRIGGERS}},
        "discord": {"label": "Discord", "fields": {"webhook": "secret", **TRIGGERS}},
        "apprise": {"label": "Apprise", "fields": {"urls": "secret", **TRIGGERS}},
    },
}
KINDS = tuple(PROVIDERS)
DEFAULTS = {"categories": ["1000"], "priority": 25, "category": "games", "ask": False, **{t: True for t in TRIGGERS}}
INDEXERS, DOWNLOAD_CLIENTS, CONNECTIONS = [], [], []


def providers(kind, enabled=False):
    return [e for e in globals()[kind] if e.get("enabled") or not enabled]


def indexers():
    return providers("INDEXERS", enabled=True)


def download_clients():
    return providers("DOWNLOAD_CLIENTS", enabled=True)


def connections():
    return providers("CONNECTIONS", enabled=True)


def protocol_of(client):
    return PROVIDERS["DOWNLOAD_CLIENTS"][client["type"]]["protocol"]


def client_for(protocol, source_type=""):
    """The download client a release of this protocol goes to: the first one in the list that
    takes it. The download client of Prowlarr only takes what a Prowlarr found."""
    for client in download_clients():
        kind = protocol_of(client)
        if kind == protocol or (kind == "prowlarr" and protocol == "usenet" and source_type == "prowlarr"):
            return client
    return None


def wants_torrents():
    """Is there a client that takes torrents? Without one, torrents are not searched at all."""
    return any(protocol_of(c) == "torrent" for c in download_clients())


def normalize_entry(kind, entry, keep_id=True):
    """One indexer, download client or connection from the form or the settings file, in the
    shape the app uses. An empty secret keeps the saved one, unless the address changed: a
    saved key is only sent to the address it was saved for."""
    if kind not in PROVIDERS or not isinstance(entry, dict):
        raise ValueError("Invalid request")
    type_ = str(entry.get("type", "")).lower()
    if type_ not in PROVIDERS[kind]:
        raise ValueError(f"Unknown type: {type_ or '(none)'}")
    spec = PROVIDERS[kind][type_]
    old = next((e for e in globals()[kind] if e["id"] == entry.get("id")), None) if keep_id else None
    if old and old["type"] != type_:
        raise ValueError("The type of an entry cannot be changed; add a new one")
    name = clean_text("Name", entry.get("name") or spec["label"])[:60] or spec["label"]
    clean = {"id": old["id"] if old else secrets.token_hex(4), "type": type_, "name": name,
             "enabled": clean_bool(entry.get("enabled", True))}
    kept = []
    for field, field_kind in spec["fields"].items():
        value = entry.get(field, DEFAULTS.get(field, ""))
        label = f"{name}: {field.replace('_', ' ')}"
        if field_kind == "secret":
            value = str(value or "").strip()
            if len(value) > 2000 or any(ord(c) < 32 for c in value):
                raise ValueError(f"{label}: invalid value")
            if not value and old and field not in (entry.get("clear") or []):
                value = old.get(field, "")
                if value:
                    kept.append(field)
        elif field_kind == "url":
            value = clean_url(label, value)
            if not value:
                raise ValueError(f"{label}: fill in the address")
        elif field_kind == "numbers":
            value = clean_numbers(label, value)
        elif field_kind == "bool":
            value = clean_bool(value)
        elif field_kind == "folder":
            value = clean_folder(label, value) if str(value or "").strip() else ""
        elif field_kind == "chat":
            value = clean_chat(label, value)
        elif field_kind == "priority":
            try:
                value = int(str(value).strip())
            except ValueError:
                value = 0
            if not 1 <= value <= 50:
                raise ValueError(f"{label}: a number from 1 to 50; the lowest goes first")
        else:
            value = clean_text(label, value)
        clean[field] = value
    if kept and old and "url" in spec["fields"] and origin(clean["url"]) != origin(old.get("url")):
        raise ValueError(f"{name}: fill in the {kept[0].replace('_', ' ')} again, because the address changed. "
                         "A saved key or password is only sent to the address it was saved for.")
    if bool(clean.get("remote_path")) != bool(clean.get("local_path")):
        raise ValueError(f"{name}: fill in the Remote Path and the Local Path both, or neither")
    if type_ == "discord" and clean["webhook"] and not clean["webhook"].lower().startswith("https://"):
        raise ValueError(f"{name}: a Discord webhook starts with https://")
    return clean


def save_provider(kind, entry):
    """Add an entry, or replace the one with the same id. Returns the saved entry."""
    clean = normalize_entry(kind, entry)
    entries = [e for e in globals()[kind]]
    if any(e["id"] == clean["id"] for e in entries):
        entries = [clean if e["id"] == clean["id"] else e for e in entries]
    else:
        entries.append(clean)
    globals()[kind] = entries
    write({**saved(), kind: entries})
    return clean


def delete_provider(kind, entry_id):
    if kind not in PROVIDERS:
        raise ValueError("Invalid request")
    globals()[kind] = [e for e in globals()[kind] if e["id"] != entry_id]
    write({**saved(), kind: globals()[kind]})


def shown_providers():
    """The lists as the panel gets them: of a secret only whether one is set."""
    result = {}
    for kind in KINDS:
        result[kind] = []
        for entry in globals()[kind]:
            fields = PROVIDERS[kind][entry["type"]]["fields"]
            shown = {k: v for k, v in entry.items() if fields.get(k) != "secret"}
            shown["secrets"] = {k: bool(entry.get(k)) for k, f in fields.items() if f == "secret"}
            result[kind].append(shown)
    return result


# ---------------------------------------------------------------- the settings file


class SettingsBroken(Exception):
    """The settings file is there and cannot be read: nothing may be written over it."""


def saved():
    """What the settings file holds. No file: nothing yet. A file that is damaged is no reason to
    start anew: writing over it would lose every key and password in it."""
    try:
        with open(SETTINGS_FILE) as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}
    except ValueError as e:
        raise SettingsBroken(f"{SETTINGS_FILE} is damaged and cannot be read ({e})") from e
    if not isinstance(data, dict):
        raise SettingsBroken(f"{SETTINGS_FILE} is damaged: it does not hold settings")
    return {k: v for k, v in data.items() if k in EDITABLE or k in KINDS or k in PRIVATE}


def write(data):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = SETTINGS_FILE + ".tmp"
    # Keys and passwords: readable for the app user only.
    with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, SETTINGS_FILE)


def legacy():
    """The indexer, download client and connections of a version that had one of each: from
    its settings file, else from its environment variables. Returns {kind: [entries]}."""
    try:
        with open(SETTINGS_FILE) as f:
            old = json.load(f)
    except (FileNotFoundError, ValueError):
        old = {}
    old = old if isinstance(old, dict) else {}

    def was(name, default=""):
        return old[name] if name in old else env(name, default)

    lists = {kind: [] for kind in KINDS}
    if was("PROWLARR_URL"):
        lists["INDEXERS"].append({"type": "prowlarr", "url": was("PROWLARR_URL"), "api_key": was("PROWLARR_API_KEY"),
                                  "categories": was("PROWLARR_CATEGORIES", "1000")})
    chosen, category = str(was("DOWNLOAD_CLIENT", "nzbget")).lower(), was("DOWNLOAD_CATEGORY", "games")
    if was("NZBGET_URL"):
        lists["DOWNLOAD_CLIENTS"].append({
            "type": "nzbget", "url": was("NZBGET_URL"), "username": was("NZBGET_USER"),
            "password": was("NZBGET_PASSWORD"), "category": category, "enabled": chosen == "nzbget"})
    if was("SABNZBD_URL"):
        lists["DOWNLOAD_CLIENTS"].append({
            "type": "sabnzbd", "url": was("SABNZBD_URL"), "api_key": was("SABNZBD_API_KEY"),
            "category": category, "enabled": chosen == "sabnzbd"})
    if chosen == "prowlarr":
        lists["DOWNLOAD_CLIENTS"].append({"type": "prowlarr"})
    if was("TELEGRAM_BOT_TOKEN") or was("TELEGRAM_CHAT_ID"):
        lists["CONNECTIONS"].append({
            "type": "telegram", "bot_token": was("TELEGRAM_BOT_TOKEN"), "chat_id": was("TELEGRAM_CHAT_ID"),
            "ask": clean_bool(was("TELEGRAM_ASK", "false"))})
    if env("NOTIFY_URLS"):
        lists["CONNECTIONS"].append({"type": "apprise", "urls": env("NOTIFY_URLS")})
    return lists


def load_saved():
    """Put the saved settings on top of the environment. Called once at start."""
    data = saved()
    kept = dict(data)
    # Not a setting of a form: only its own steps in the panel set or remove it.
    globals()["TOTP_SECRET"] = data["TOTP_SECRET"] if isinstance(data.get("TOTP_SECRET"), str) else ""
    folders = []
    for root in data.get("ROOT_FOLDERS") if isinstance(data.get("ROOT_FOLDERS"), list) else []:
        try:
            folders.append({"path": clean_folder("Path", root["path"]), "library_path": clean_folder("Path", root["library_path"])})
        except (ValueError, KeyError, TypeError):
            continue  # a broken one is left out, the rest still works
    globals()["ROOT_FOLDERS"] = folders
    for name, value in data.items():
        if name in KINDS or name in PRIVATE:
            continue
        try:
            globals()[name] = kept[name] = normalize(name, value)
        except ValueError:
            continue
    globals()["BACKUP_FOLDER"] = backup_folder(BACKUP_FOLDER)  # a saved "/backup" without that volume
    old = legacy() if any(kind not in data for kind in KINDS) else {}
    for kind in KINDS:
        entries = []
        globals()[kind] = []
        for entry in data[kind] if isinstance(data.get(kind), list) else old.get(kind, []):
            try:
                clean = normalize_entry(kind, entry, keep_id=False)
            except ValueError:
                continue  # a broken entry is left out, the rest still works
            if isinstance(entry.get("id"), str) and entry["id"]:
                clean["id"] = entry["id"]
            entries.append(clean)
        globals()[kind] = kept[kind] = entries
    if kept != data:
        # A password saved by an older version becomes a hash; one indexer and one download
        # client of an older version become the first entries of the lists.
        write(kept)


def first_login():
    """Without a password the panel would be open: make one up for the user "admin" and keep
    it readable until the user has chosen one of their own. Returns the made-up password while
    it still has to be changed, else None. Called once at start."""
    global PANEL_PASSWORD, INITIAL_PASSWORD, WAS_RESET
    if os.path.exists(RESET_FILE):
        # Asked for by someone who can write in the config folder: a new made-up password, and no
        # second step. Safer than editing the settings file by hand, where a slip loses it all.
        try:
            os.remove(RESET_FILE)
        except OSError:
            pass  # it cannot be taken away, so it would ask again at every start: not done
        else:
            PANEL_PASSWORD, WAS_RESET = "", True
            if TOTP_SECRET:
                set_totp("")
    if not PANEL_PASSWORD:
        password = secrets.token_urlsafe(12)
        os.makedirs(DATA_DIR, exist_ok=True)
        with os.fdopen(os.open(INITIAL_PASSWORD_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
            f.write(password)
        PANEL_PASSWORD = hash_password(password)
        write({**saved(), "PANEL_USER": PANEL_USER, "PANEL_PASSWORD": PANEL_PASSWORD})
    try:
        with open(INITIAL_PASSWORD_FILE) as f:
            password = f.read().strip()
    except FileNotFoundError:
        password = ""
    # Only while it is the password that works: a login made another way leaves it behind.
    INITIAL_PASSWORD = password if password and check_password(password) else None
    return INITIAL_PASSWORD


def must_change_password():
    """Is the made-up password still in use? Then the panel only lets the user choose one."""
    return INITIAL_PASSWORD is not None


def update(values, clear=()):
    """Save single settings from the panel and use them from now on.

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
        if name == "PANEL_PASSWORD":
            raise ValueError("PANEL_PASSWORD: the panel cannot be without a password")
        new[name] = ""
    check_bound(new, clear)
    write({**saved(), **new})
    changed = sorted(name for name, value in new.items() if globals()[name] != value)
    globals().update(new)
    if "PANEL_PASSWORD" in new:
        # The user has a password of their own now: the made-up one is gone for good.
        globals()["INITIAL_PASSWORD"] = None
        if os.path.exists(INITIAL_PASSWORD_FILE):
            os.remove(INITIAL_PASSWORD_FILE)
    return changed


def clean_folder(name, value):
    """The whole path of a folder, without a slash at the end."""
    value = clean_text(name, value)
    if not value.startswith("/") or ".." in value.split("/") or "\\" in value:
        raise ValueError(f"{name}: fill in the whole path of a folder, like /games/switch")
    return value.rstrip("/") or "/"


def add_root_folder(path, library_path=""):
    """A folder of the library as this container sees it, and as Switch-library-manager-web
    names it (the same, unless the two containers mount it under different paths)."""
    path = clean_folder("Path", path)
    library_path = clean_folder("Path in Switch-library-manager-web", library_path or path)
    # Not the folders NSWHunter keeps its own files in. A library that is a volume somewhere under
    # the config folder is fine too.
    own = [DATA_DIR.rstrip("/") + "/" + name for name in ("logs", "covers", "certs", "backups")] + [os.path.join(DATA_DIR, BACKUP_FOLDER)]
    if path in ("/", DATA_DIR.rstrip("/")) or any(path == folder or path.startswith(folder.rstrip("/") + "/") for folder in own):
        raise ValueError(f"{path} cannot be a root folder: NSWHunter keeps its own files there. Choose the folder of your library.")
    if not os.path.isdir(path):
        raise ValueError(f"{path} is not a folder in this container. Add the folder of your library as a volume of the container first.")
    if not os.access(path, os.W_OK):
        raise ValueError(f"{path} cannot be written by NSWHunter. The user of the container has to own it, or be in its group.")
    if any(root["path"] == path for root in ROOT_FOLDERS):
        raise ValueError(f"{path} is a root folder already")
    folders = ROOT_FOLDERS + [{"path": path, "library_path": library_path}]
    write({**saved(), "ROOT_FOLDERS": folders})
    globals()["ROOT_FOLDERS"] = folders


def remove_root_folder(path):
    folders = [root for root in ROOT_FOLDERS if root["path"] != path]
    write({**saved(), "ROOT_FOLDERS": folders})
    globals()["ROOT_FOLDERS"] = folders


def set_totp(secret):
    """Switch the second step of the login on (with the secret of the authenticator app) or off ("")."""
    data = saved()
    if secret:
        data["TOTP_SECRET"] = secret
    else:
        data.pop("TOTP_SECRET", None)
    write(data)
    globals()["TOTP_SECRET"] = secret


def overlay(values, clear=()):
    """The single settings as they would be after saving this form, without saving or using
    them: for the Test buttons. Same rules as update(): an empty secret keeps the saved one."""
    import types
    result = types.SimpleNamespace(**{name: globals()[name] for name in EDITABLE})
    new = {}
    for name, value in values.items():
        if name not in EDITABLE:
            raise ValueError(f"Unknown setting: {name}")
        if name in SECRETS and str(value or "").strip() == "":
            continue
        new[name] = normalize(name, value)
    check_bound(new, clear)
    for name, value in new.items():
        setattr(result, name, value)
    for name in clear:
        if name in SECRETS:
            setattr(result, name, "")
    return result


def editable():
    """What the settings pages show: values, and for secrets only whether one is set."""
    return {
        "values": {n: globals()[n] for n in EDITABLE if n not in SECRETS},
        "secrets": {n: bool(globals()[n]) for n in SECRETS},
        "totp": bool(TOTP_SECRET),
        "providers": shown_providers(),
        "schema": {kind: {t: {"label": spec["label"], "fields": spec["fields"], "protocol": spec.get("protocol", "")}
                          for t, spec in types.items()} for kind, types in PROVIDERS.items()},
    }


def auto_min_score():
    """The score from which a release goes out by itself; 0 = never."""
    return 0 if AUTO_DOWNLOAD == "off" else int(AUTO_DOWNLOAD)


def problems():
    """What is missing before anything can run."""
    missing = []
    if not SLM_URL:
        missing.append("The library has no address yet (Settings > Connect)")
    if not indexers():
        missing.append("There is no indexer yet (Settings > Indexers)")
    if not download_clients():
        missing.append("There is no download client yet (Settings > Download Clients)")
    return missing
