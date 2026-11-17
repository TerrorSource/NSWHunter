"""Who may use the panel: the login and its sessions, the brake on guessing a password, and the
host names the panel answers to."""
import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import time

import config

COOKIE = "nswhunter_session"
LIFETIME = 30 * 86400  # a login lasts this long
FREE_TRIES = 5  # wrong logins from one address before it has to wait
MAX_WAIT = 900
FORGET = 3600  # wrong logins are forgotten this long after the last one

# sha256 of a session token -> {"ends", "made", "seen", "address", "agent"}: when the login ends
# and was made, when it was last used, and from where and with what browser.
sessions = {}
failures = {}  # address -> (number of wrong logins in a row, time of the last one)
used_step = 0  # the step of time of the last code of the second step that was used
SEEN_EVERY = 300  # "last seen" is written to the file at most this often

# Names that only exist inside a home network: no public DNS can make them point somewhere.
LOCAL_SUFFIXES = (".local", ".lan", ".home", ".home.arpa", ".internal", ".intranet", ".localhost", ".localdomain")


# ---------------------------------------------------------------- sessions


def _key(token):
    return hashlib.sha256(token.encode()).hexdigest()


def load():
    """The sessions of before a restart, so an update does not log everyone out."""
    sessions.clear()
    try:
        with open(config.SESSIONS_FILE) as f:
            saved = json.load(f)
    except (FileNotFoundError, ValueError):
        return
    now = time.time()
    for key, value in (saved.items() if isinstance(saved, dict) else ()):
        if isinstance(value, (int, float)):  # as an older version kept it: only when it ends
            value = {"ends": value, "made": value - LIFETIME, "seen": 0, "address": "", "agent": ""}
        if isinstance(value, dict) and isinstance(value.get("ends"), (int, float)) and value["ends"] > now:
            sessions[key] = {"ends": int(value["ends"]), "made": int(value.get("made") or 0), "seen": int(value.get("seen") or 0),
                             "address": str(value.get("address") or "")[:64], "agent": str(value.get("agent") or "")[:300]}


def save():
    os.makedirs(config.DATA_DIR, exist_ok=True)
    tmp = config.SESSIONS_FILE + ".tmp"
    # Only hashes of the tokens are kept, and only the app user can read them.
    with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
        json.dump(sessions, f)
    os.replace(tmp, config.SESSIONS_FILE)


def start(address="", agent=""):
    """A new session. Returns the token for the cookie."""
    now = time.time()
    for key in [k for k, session in sessions.items() if session["ends"] <= now]:
        del sessions[key]
    token = secrets.token_urlsafe(32)
    sessions[_key(token)] = {"ends": int(now + LIFETIME), "made": int(now), "seen": int(now),
                             "address": str(address)[:64], "agent": str(agent)[:300]}
    save()
    return token


def valid(token):
    """Is this the token of a login that still lasts? Using it is remembered as "last seen"."""
    session = sessions.get(_key(token)) if token else None
    now = time.time()
    if session is None or session["ends"] <= now:
        return False
    if now - session["seen"] > SEEN_EVERY:
        session["seen"] = int(now)
        save()
    return True


def end(token):
    if token and sessions.pop(_key(token), None) is not None:
        save()


def end_all():
    """After a new password: every browser has to log in again."""
    sessions.clear()
    save()


def listing(token):
    """The logins that still last, newest first, for the panel. The id is a piece of the hash
    of the token: enough to point at one, useless to log in with."""
    own, now = _key(token) if token else "", time.time()
    return sorted(({"id": key[:16], "made": s["made"], "seen": s["seen"], "ends": s["ends"], "address": s["address"],
                    "agent": s["agent"], "current": key == own}
                   for key, s in sessions.items() if s["ends"] > now), key=lambda s: s["made"], reverse=True)


def end_id(public_id):
    """End the login with this id. True if there was one."""
    found = [key for key in sessions if key[:16] == public_id and len(str(public_id)) == 16]
    for key in found:
        del sessions[key]
    if found:
        save()
    return bool(found)


def end_others(token):
    """End every login but the one of this token. Returns how many."""
    own = _key(token) if token else ""
    others = [key for key in sessions if key != own]
    for key in others:
        del sessions[key]
    if others:
        save()
    return len(others)


# ---------------------------------------------------------------- logging in


def check_login(user, password):
    """Is this the panel's user and password? Both are always checked, so the time it takes
    does not tell which of the two was wrong."""
    right_user = hmac.compare_digest(str(user).encode(), config.PANEL_USER.encode())
    right_password = config.check_password(str(password))
    return right_user and right_password


def wait_for(address):
    """Seconds this address has to wait before its next login; 0 if it may try now."""
    count, last = failures.get(address, (0, 0))
    now = time.time()
    if now - last > FORGET:
        failures.pop(address, None)
        return 0
    if count < FREE_TRIES:
        return 0
    wait = min(MAX_WAIT, 30 * 2 ** (count - FREE_TRIES))
    return max(0, int(last + wait - now + 0.999))


def failed(address):
    if len(failures) > 2000:  # an attacker with many addresses must not fill the memory
        failures.clear()
    count, _ = failures.get(address, (0, 0))
    failures[address] = (count + 1, time.time())


def succeeded(address):
    failures.pop(address, None)


# ---------------------------------------------------------------- host names


def host_name(host):
    """The name in a Host header, without the port."""
    host = (host or "").strip().lower()
    if host.startswith("["):  # [::1]:3033
        return host[1:].split("]")[0]
    name, _, port = host.rpartition(":")
    return name if name and port.isdigit() else host


def host_allowed(host):
    """May the panel answer to this Host header?

    A website can make a name of its own point at an address in your network (DNS rebinding)
    and then talk to the panel through your browser. The browser sends that name as the host,
    so only names that cannot be such a name are answered: an IP address, a name without a
    dot, a name that only exists inside a home network, and the names in PANEL_HOSTS."""
    name = host_name(host)
    if not name:
        return False
    try:
        ipaddress.ip_address(name)
        return True
    except ValueError:
        pass
    if "." not in name or name.endswith(LOCAL_SUFFIXES):
        return True
    return name in config.panel_hosts()
