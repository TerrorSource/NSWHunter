"""The torrent clients NSWHunter can hand a release to: qBittorrent, Transmission and uTorrent."""
import base64
import hashlib
import json
import re
from urllib.parse import parse_qsl, urlsplit

import aiohttp

from clients import LARGE, LONG, SHORT, ServiceError, _check, _json, _percent, _read, _wrap

TYPES = ("qbittorrent", "transmission", "utorrent")
LABELS = {"qbittorrent": "qBittorrent", "transmission": "Transmission", "utorrent": "uTorrent"}

# What a login gave, per client id: qBittorrent's session cookie, Transmission's session id,
# uTorrent's token and cookie. The cookie jar of the shared session cannot hold them: it skips
# cookies of a host that is an IP address, and that is where these clients usually run.
_sessions = {}


def _session(client):
    """The remembered login of a client; forgotten as soon as its address or login changes,
    so a Test with other values never rides on the login of the saved ones."""
    key = (client["url"], client.get("username", ""), client.get("password", ""))
    entry = _sessions.get(client.get("id"))
    if not entry or entry["key"] != key:
        entry = _sessions[client.get("id")] = {"key": key}
    return entry


def _basic(client):
    """The Authorization header for HTTP Basic, built by hand: aiohttp.BasicAuth is deprecated."""
    if not client.get("username") and not client.get("password"):
        return {}
    login = f"{client.get('username', '')}:{client.get('password', '')}".encode()
    return {"Authorization": "Basic " + base64.b64encode(login).decode()}


def _cookies(response):
    """The cookies an answer sets, as the value of a Cookie header to send back."""
    pairs = [cookie.split(";", 1)[0].strip() for cookie in response.headers.getall("Set-Cookie", [])]
    return "; ".join(pair for pair in pairs if "=" in pair)


def _state(state, percent):
    return {"state": state, "percent": 100 if state == "done" else percent}


# ---------------------------------------------------------------- hashes


def _bencode_end(data, at):
    """Where the bencoded value that starts at `at` ends. Walks instead of calling itself, so
    a file with endless nesting cannot exhaust the stack. ValueError if it is not bencode."""
    depth = 0
    while True:
        lead = data[at:at + 1]
        if lead == b"i":
            at = data.index(b"e", at) + 1
        elif lead in (b"l", b"d"):
            depth, at = depth + 1, at + 1
        elif lead == b"e" and depth:
            depth, at = depth - 1, at + 1
        elif lead.isdigit():
            colon = data.index(b":", at)
            at = colon + 1 + int(data[at:colon])
            if at > len(data):
                raise ValueError("a string runs past the end")
        else:
            raise ValueError("not bencode")
        if not depth:
            return at


def info_hash(torrent):
    """The info hash of a .torrent file: the SHA-1 of its "info" dictionary exactly as it is
    written in the file, in lower-case hex. Decoding and encoding it again could change it."""
    try:
        if torrent[:1] != b"d":
            raise ValueError("not a dictionary")
        at = 1
        while torrent[at:at + 1] != b"e":
            if not torrent[at:at + 1].isdigit():
                raise ValueError("a key that is not a string")
            value = _bencode_end(torrent, at)
            end = _bencode_end(torrent, value)
            if torrent[torrent.index(b":", at) + 1:value] == b"info" and torrent[value:value + 1] == b"d":
                return hashlib.sha1(torrent[value:end]).hexdigest()
            at = end
    except (ValueError, TypeError) as e:
        raise ServiceError("this is not a torrent file") from e
    raise ServiceError("this is not a torrent file (it has no info part)")


def magnet_hash(uri):
    """The info hash (btih) of a magnet URI as 40 lower-case hex characters; None if it has
    none. Magnet links carry it as hex or, the older way, as 32 base32 characters."""
    if not str(uri).lower().startswith("magnet:"):
        return None
    for key, value in parse_qsl(urlsplit(uri).query):
        found = re.fullmatch(r"urn:btih:([0-9a-f]{40}|[a-z2-7]{32})", value.strip(), re.IGNORECASE)
        if found and key.lower().split(".")[0] == "xt":  # several are written as xt.1, xt.2
            text = found.group(1)
            return text.lower() if len(text) == 40 else base64.b32decode(text.upper()).hex()
    return None


def _own_hash(kind, content):
    """The info hash of what is about to be handed over, worked out here: not every client
    tells it back. Also refuses what is no magnet link or torrent file before it is sent."""
    if kind == "file":
        return info_hash(content)
    if kind != "magnet":
        raise ServiceError(f"unknown kind of torrent: {kind}")
    found = magnet_hash(content)
    if not found:
        raise ServiceError("the magnet link has no info hash (btih)")
    return found


# ---------------------------------------------------------------- qBittorrent


async def _qbittorrent_login(session, client):
    """Log in and return the session cookie. Its name differs per version ("SID", later
    "QBT_SID_" plus the port), so whatever the answer sets is taken along."""
    base = client["url"]
    form = {"username": client.get("username", ""), "password": client.get("password", "")}
    async with session.post(f"{base}/api/v2/auth/login", data=form, headers={"Referer": base},
                            timeout=SHORT) as r:
        if r.status == 403:
            raise ServiceError("qBittorrent: too many wrong logins, qBittorrent blocks this address for a while")
        # A wrong login is 401 in new versions; older ones answer 200 with the text "Fails.".
        if r.status != 401:
            await _check(r, "qBittorrent")
        if r.status == 401 or (await _read(r)).strip() == b"Fails.":
            raise ServiceError("qBittorrent: wrong username or password")
        return _cookies(r)


async def _qbittorrent(session, client, path, params=None, fields=None, torrent=None, accept=()):
    """One call to the WebUI API, logged in: (HTTP status, text of the answer). A call with
    `fields` is a POST. accept: error statuses the caller wants to judge itself."""
    base, entry = client["url"], _session(client)
    for attempt in (1, 2):
        if "cookie" not in entry:
            entry["cookie"] = await _qbittorrent_login(session, client)
        # qBittorrent refuses a request whose Referer is not its own address (CSRF protection).
        headers = {"Referer": base}
        if entry["cookie"]:
            headers["Cookie"] = entry["cookie"]
        form = None
        if fields is not None:
            form = aiohttp.FormData()  # built per attempt: a form can be sent only once
            for key, value in fields.items():
                form.add_field(key, value)
            if torrent:
                form.add_field("torrents", torrent[1], filename=torrent[0], content_type="application/x-bittorrent")
        async with session.request("GET" if form is None else "POST", f"{base}/api/v2/{path}", params=params,
                                   data=form, headers=headers, timeout=SHORT if form is None else LONG) as r:
            if r.status == 403 and attempt == 1:
                del entry["cookie"]  # the session ran out: log in again, once
                continue
            if r.status not in accept:
                await _check(r, "qBittorrent")
            return r.status, (await _read(r, LARGE)).decode("utf-8", "replace")


async def _qbittorrent_status(session, client):
    _, version = await _qbittorrent(session, client, "app/version")
    return f"qBittorrent {version.strip()[:40]}"


async def _qbittorrent_add(session, client, kind, content):
    wanted = _own_hash(kind, content)
    fields = {"urls": content} if kind == "magnet" else {}
    if client.get("category"):
        fields["category"] = client["category"]  # qBittorrent makes the category if it is new
    code, text = await _qbittorrent(
        session, client, "torrents/add", fields=fields, accept=(409, 415),
        torrent=(f"{wanted}.torrent", content) if kind == "file" else None)
    if code == 415:
        raise ServiceError("qBittorrent: this is not a valid torrent file")
    # Old versions answer "Ok." or "Fails."; new ones answer JSON, and 409 when nothing was
    # added. A torrent that qBittorrent already has is refused too, and that is no failure.
    if code == 409 or text.strip() == "Fails.":
        if wanted not in await _qbittorrent_states(session, client, wanted):
            raise ServiceError("qBittorrent refused the torrent")
        return wanted
    try:
        ids = json.loads(text)["added_torrent_ids"]
    except (ValueError, TypeError, KeyError):
        ids = []
    # qBittorrent's own id wins: for a torrent of version 2 only it is not the SHA-1.
    own = str(ids[0]).lower() if isinstance(ids, list) and len(ids) == 1 else ""
    return own if re.fullmatch(r"[0-9a-f]{40}", own) else wanted


async def _qbittorrent_states(session, client, only=None):
    _, text = await _qbittorrent(session, client, "torrents/info", params={"hashes": only} if only else None)
    try:
        torrents = json.loads(text)
    except ValueError as e:
        raise ServiceError("qBittorrent: the answer is not JSON") from e
    found = {}
    for torrent in torrents if isinstance(torrents, list) else []:
        if not isinstance(torrent, dict):
            continue
        name, percent = str(torrent.get("state", "")), _percent(torrent.get("progress"), 1)
        if name in ("error", "missingFiles"):
            state = "failed"
        # A complete torrent is "uploading" or in a state that ends on UP: stalledUP, queuedUP,
        # forcedUP, checkingUP, and pausedUP, which qBittorrent 5 renamed to stoppedUP.
        elif name == "uploading" or name.endswith("UP") or (name == "moving" and percent == 100):
            state = "done"
        else:
            state = "downloading"
            if name.startswith("checking"):
                percent = None  # while checking, the progress is that of the check
        found[str(torrent.get("hash", "")).lower()] = _state(state, percent)
    found.pop("", None)
    return found


# ---------------------------------------------------------------- Transmission


def _snake(name):
    """torrent-add and hashString in the spelling of Transmission 4.1: torrent_add, hash_string."""
    return re.sub(r"(?<=[a-z0-9])([A-Z])", r"_\1", name).replace("-", "_").lower()


def _snake_keys(values):
    return {_snake(key): value for key, value in values.items()} if isinstance(values, dict) else {}


async def _transmission(session, client, method, arguments):
    """One RPC call; returns its answer with the keys in snake_case. Calls are written in the
    old spelling, which every Transmission up to 4.x takes. A server that announces RPC
    version 6 (Transmission 4.1) or later gets JSON-RPC 2.0 with the snake_case names
    instead, because the old protocol is deprecated there and will be removed."""
    entry = _session(client)
    for attempt in (1, 2):
        headers = _basic(client)
        if entry.get("id"):
            headers["X-Transmission-Session-Id"] = entry["id"]
        if entry.get("jsonrpc"):
            params = {_snake(k): [_snake(f) for f in v] if k == "fields" else v for k, v in arguments.items()}
            body = {"jsonrpc": "2.0", "id": 1, "method": _snake(method), "params": params}
        else:
            body = {"method": method, "arguments": arguments}
        async with session.post(f"{client['url']}/transmission/rpc", json=body, headers=headers,
                                timeout=LONG if method == "torrent-add" else SHORT) as r:
            if r.status == 409 and attempt == 1:
                # Not an error but the handshake: the right session id is in this answer,
                # also when the one we had ran out. Only a server with JSON-RPC names its version.
                entry["id"] = r.headers.get("X-Transmission-Session-Id", "")
                major = r.headers.get("X-Transmission-Rpc-Version", "").split(".")[0]
                entry["jsonrpc"] = major.isdigit() and int(major) >= 6
                continue
            if r.status == 401:
                raise ServiceError("Transmission: wrong username or password")
            await _check(r, "Transmission")
            data = await _json(r, LARGE)
        break
    if not isinstance(data, dict):
        raise ServiceError("Transmission: unexpected answer")
    if entry.get("jsonrpc"):
        if data.get("error"):
            error = _snake_keys(data["error"])
            why = _snake_keys(error.get("data")).get("error_string") or error.get("message") or "the call failed"
            raise ServiceError(f"Transmission: {str(why)[:200]}")
        return _snake_keys(data.get("result"))
    if data.get("result") != "success":
        raise ServiceError(f"Transmission: {str(data.get('result') or 'unexpected answer')[:200]}")
    return _snake_keys(data.get("arguments"))


async def _transmission_status(session, client):
    answer = await _transmission(session, client, "session-get", {"fields": ["version"]})
    # "4.0.6 (38c164933e)": the part between brackets is the revision it was built from.
    return f"Transmission {str(answer.get('version', '?')).split(' ')[0][:40]}"


async def _transmission_add(session, client, kind, content):
    wanted, category = _own_hash(kind, content), client.get("category")
    arguments = {"filename": content} if kind == "magnet" else {"metainfo": base64.b64encode(content).decode()}
    if category:
        arguments["labels"] = [category]
    answer = await _transmission(session, client, "torrent-add", arguments)
    # A torrent that Transmission already has comes back as torrent-duplicate, without error.
    added = _snake_keys(answer.get("torrent_added"))
    found = str((added or _snake_keys(answer.get("torrent_duplicate"))).get("hash_string") or wanted).lower()
    if added and category:
        # torrent-add knows labels since Transmission 4.0, torrent-set since 3.0: say it again
        # for the older one. Before 3.0 there are no labels and the key is ignored.
        await _transmission(session, client, "torrent-set", {"ids": [found], "labels": [category]})
    return found


async def _transmission_states(session, client):
    fields = ["hashString", "status", "error", "percentDone", "leftUntilDone", "sizeWhenDone"]
    answer = await _transmission(session, client, "torrent-get", {"fields": fields})
    found = {}
    for torrent in answer.get("torrents") or []:
        torrent = _snake_keys(torrent)
        activity, size = torrent.get("status"), torrent.get("size_when_done") or 0
        if torrent.get("error") == 3:  # a local error, such as a full disk; 1 and 2 come from the tracker
            state = "failed"
        # 5 and 6: waiting to seed, seeding. 0 is stopped, which says nothing about how far it is.
        elif activity in (5, 6) or (activity == 0 and size > 0 and torrent.get("left_until_done") == 0):
            state = "done"
        else:
            state = "downloading"
        found[str(torrent.get("hash_string", "")).lower()] = _state(state, _percent(torrent.get("percent_done"), 1))
    found.pop("", None)
    return found


# ---------------------------------------------------------------- uTorrent


async def _utorrent_login(session, client):
    """Fetch the token every call has to carry, and the GUID cookie that belongs to it."""
    async with session.get(f"{client['url']}/gui/token.html", headers=_basic(client), timeout=SHORT) as r:
        if r.status == 401:
            raise ServiceError("uTorrent: wrong username or password")
        await _check(r, "uTorrent")
        page = (await _read(r)).decode("utf-8", "replace")
        found = re.search(r"<div[^>]*\bid=['\"]token['\"][^>]*>([^<]+)</div>", page)
        if not found:
            raise ServiceError("uTorrent: no token in the answer. Is this the address of the WebUI?")
        return {"token": found.group(1).strip(), "cookie": _cookies(r)}


async def _utorrent(session, client, params, torrent=None):
    """One call to the WebUI: the JSON it answers. params: (key, value) pairs in the order
    uTorrent wants them. With `torrent` (file name, bytes) it is the upload of a file."""
    entry = _session(client)
    for attempt in (1, 2):
        if "token" not in entry:
            entry.update(await _utorrent_login(session, client))
        headers = _basic(client)
        if entry["cookie"]:
            headers["Cookie"] = entry["cookie"]
        form = None
        if torrent:
            form = aiohttp.FormData()  # built per attempt: a form can be sent only once
            form.add_field("torrent_file", torrent[1], filename=torrent[0], content_type="application/x-bittorrent")
        # uTorrent only accepts the token as the first parameter.
        async with session.request("GET" if form is None else "POST", f"{client['url']}/gui/", data=form,
                                   params=[("token", entry["token"]), *params], headers=headers,
                                   timeout=SHORT if form is None else LONG) as r:
            # A token lasts half an hour and dies with a restart of uTorrent. It then answers
            # "invalid request": 400 in practice, 300 according to its documentation.
            if r.status in (300, 400, 401) and attempt == 1:
                del entry["token"]
                continue
            await _check(r, "uTorrent")
            data = await _json(r, LARGE)
        break
    if not isinstance(data, dict):
        raise ServiceError("uTorrent: unexpected answer")
    return data


async def _utorrent_status(session, client):
    # The server edition tells its version; the desktop one ignores the question and, as in
    # every answer, gives only its build number.
    answer = await _utorrent(session, client, [("action", "getversion")])
    version = answer.get("version") if isinstance(answer.get("version"), dict) else {}
    number = ".".join(str(version[key]) for key in ("major_version", "minor_version", "tiny_version")
                      if isinstance(version.get(key), int))
    return f"uTorrent {number + ' ' if number else ''}(build {answer.get('build', '?')})"


async def _utorrent_add(session, client, kind, content):
    wanted = _own_hash(kind, content)
    if kind == "magnet":
        answer = await _utorrent(session, client, [("action", "add-url"), ("s", content)])
    else:
        answer = await _utorrent(session, client, [("action", "add-file")], torrent=(f"{wanted}.torrent", content))
    if answer.get("error") and wanted not in await _utorrent_states(session, client):
        raise ServiceError(f"uTorrent: {str(answer['error'])[:200]}")
    if client.get("category"):
        # Adding takes no label; it is a property to set afterwards. uTorrent writes hashes
        # in capitals.
        await _utorrent(session, client, [("action", "setprops"), ("hash", wanted.upper()),
                                          ("s", "label"), ("v", client["category"])])
    return wanted


async def _utorrent_states(session, client):
    answer = await _utorrent(session, client, [("list", "1")])
    found = {}
    for row in answer.get("torrents") or []:
        # A torrent is a row without names: 0 hash, 1 status (bits), 4 progress in per mille,
        # 18 bytes still to go.
        if not isinstance(row, list) or len(row) < 5 or not isinstance(row[1], int):
            continue
        complete = row[4] == 1000 and (len(row) < 19 or row[18] == 0)
        if row[1] & 16:  # the error bit
            state = "failed"
        elif complete and not row[1] & 2:  # 2: checking, and then the progress is that of the check
            state = "done"
        else:
            state = "downloading"
        found[str(row[0]).lower()] = _state(state, _percent(row[4], 1000))
    return found


# ---------------------------------------------------------------- the three as one


_STATUS = {"qbittorrent": _qbittorrent_status, "transmission": _transmission_status, "utorrent": _utorrent_status}
_ADD = {"qbittorrent": _qbittorrent_add, "transmission": _transmission_add, "utorrent": _utorrent_add}
_STATES = {"qbittorrent": _qbittorrent_states, "transmission": _transmission_states, "utorrent": _utorrent_states}


async def _call(client, functions, *arguments):
    """Run the function of the client's type; every failure leaves as a ServiceError that
    starts with the client's label and never shows the password."""
    if client.get("type") not in TYPES:
        raise ServiceError(f"Unknown torrent client: {client.get('type')}")
    label = LABELS[client["type"]]
    if not client.get("url"):
        raise ServiceError(f"{label}: fill in the address")
    try:
        return await functions[client["type"]](*arguments)
    except Exception as e:
        message = str(_wrap(label, e))
        if client.get("password"):
            message = message.replace(client["password"], "***")
        raise ServiceError(message) from e


async def status(session, client):
    """Connection and login test: the name and version of the client, like "qBittorrent v5.0.2"."""
    return await _call(client, _STATUS, session, client)


async def add(session, client, kind, content):
    """Hand a torrent to the client, in the client's category. kind "magnet": content is the
    magnet URI; kind "file": content is the .torrent file in bytes. Returns the info hash
    (40 lower-case hex), the key under which `states` reports it. A torrent the client
    already has is no error."""
    return await _call(client, _ADD, session, client, kind, content)


async def states(session, client):
    """{info hash: {"state": "downloading" | "done" | "failed", "percent": 0-100 or None}} of
    every torrent the client has. done: the download itself is complete, whether it seeds or
    was stopped after. failed: an error that does not pass by itself."""
    return await _call(client, _STATES, session, client)
