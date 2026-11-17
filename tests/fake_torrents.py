"""Stand-ins for qBittorrent, Transmission and uTorrent, in one small web app.

qBittorrent is served under /qbt, Transmission under /tr and uTorrent under /ut, so the
address of a client is the address of this app plus one of those. Used by the tests, and
runnable by itself to try the panel without the real clients:
    python tests/fake_torrents.py            (listens on port 9001)
"""
import asyncio
import base64
import hashlib
import re
import secrets
from urllib.parse import urlsplit

from aiohttp import web

USER, PASSWORD = "tester", "torrent-test"
BASIC = "Basic " + base64.b64encode(f"{USER}:{PASSWORD}".encode()).decode()
SIZE = 1_000_000  # every torrent is this many bytes

# What each stand-in calls itself: [as an older version, as the newest one].
VERSIONS = {"qbittorrent": ["v4.6.7", "v5.2.0"], "transmission": ["4.0.6 (38c164933e)", "4.1.0 (ae226418eb)"]}
UTORRENT_BUILD = 46090

# Transmission's names before 4.1, for the snake_case ones it uses since.
OLD_NAMES = {
    "session_get": "session-get", "torrent_add": "torrent-add", "torrent_get": "torrent-get",
    "torrent_set": "torrent-set", "torrent_added": "torrent-added", "torrent_duplicate": "torrent-duplicate",
    "hash_string": "hashString", "percent_done": "percentDone", "left_until_done": "leftUntilDone",
    "size_when_done": "sizeWhenDone", "error_string": "errorString", "rpc_version": "rpc-version",
    "torrent_remove": "torrent-remove", "delete_local_data": "delete-local-data",
}


def bencode(value):
    """A value in the format of .torrent files: int, bytes or str, list, dict."""
    if isinstance(value, int):
        return b"i%de" % value
    if isinstance(value, str):
        value = value.encode()
    if isinstance(value, bytes):
        return b"%d:%s" % (len(value), value)
    if isinstance(value, list):
        return b"l" + b"".join(bencode(v) for v in value) + b"e"
    items = sorted((k.encode() if isinstance(k, str) else k, v) for k, v in value.items())
    return b"d" + b"".join(bencode(k) + bencode(v) for k, v in items) + b"e"


def bdecode(data, at=0):
    """(value, where it ends) of the bencoded value that starts at `at`."""
    lead = data[at:at + 1]
    if lead == b"i":
        end = data.index(b"e", at)
        return int(data[at + 1:end]), end + 1
    if lead in (b"l", b"d"):
        values, at = [], at + 1
        while data[at:at + 1] != b"e":
            value, at = bdecode(data, at)
            values.append(value)
        return (values if lead == b"l" else dict(zip(values[::2], values[1::2]))), at + 1
    colon = data.index(b":", at)
    end = colon + 1 + int(data[at:colon])
    return data[colon + 1:end], end


def torrent_hash(data):
    """The info hash of a .torrent file, None if it is not one."""
    try:
        return hashlib.sha1(bencode(bdecode(data)[0][b"info"])).hexdigest()
    except Exception:  # noqa: BLE001
        return None


def magnet_hash(uri):
    found = re.search(r"xt=urn:btih:([0-9A-Za-z]+)", str(uri))
    text = found.group(1) if found else ""
    return text.lower() if len(text) == 40 else base64.b32decode(text.upper()).hex() if len(text) == 32 else None


def make_torrent_fakes():
    app = web.Application()
    # {client type: {info hash: torrent}}. A test changes a torrent to play a download:
    # "progress" (0.0 to 1.0), "paused" and "error". "native" overrules what the client then
    # reports, in the client's own terms: the fields of qBittorrent's torrents/info, the
    # snake_case fields of Transmission's torrent_get, {position: value} of a uTorrent row.
    app["torrents"] = {"qbittorrent": {}, "transmission": {}, "utorrent": {}}
    # How the stand-ins behave; a test may change it at any moment.
    mood = app["mood"] = {
        "modern": False,  # True: like the newest versions (see VERSIONS) instead of older ones
        "transmission3": False,  # True: like Transmission 3, where torrent-add knows no labels yet
        "delay": 0,  # seconds to wait before answering anything
        "broken": False,  # True: answer everything with an error page that repeats the request
        "stuck": False,  # True: uTorrent refuses to remove a torrent and keeps it
    }
    app["logins"] = {"qbittorrent": 0, "transmission": 0, "utorrent": 0}  # logins and handshakes
    app["calls"] = []  # (client type, what was asked) of every call that was let in
    # (client type, info hash, with the files or not) of every removal that was asked for,
    # also of a torrent the client does not have.
    app["removed"] = []
    live = {}  # the sessions that are valid now

    def expire():
        """Every session ends, as after a restart of the clients or a long silence."""
        live.update(qbittorrent=set(), transmission=secrets.token_hex(24), token=secrets.token_urlsafe(40),
                    guid=secrets.token_hex(10))

    expire()
    app["expire"] = expire

    @web.middleware
    async def moods(request, handler):
        if mood["delay"]:
            await asyncio.sleep(mood["delay"])
        if mood["broken"]:
            return web.Response(status=500, text="Could not handle: " + await request.text())
        return await handler(request)

    app.middlewares.append(moods)

    def store(kind, found, category, name="Hades Update v131072"):
        """Take a torrent in. False if it is none or the client already has it."""
        if not found or found in app["torrents"][kind]:
            return False
        app["torrents"][kind][found] = {"name": name, "category": category or "", "progress": 0.0,
                                        "paused": False, "error": False, "native": {}}
        return True

    # ------------------------------------------------------------ qBittorrent

    def qbittorrent_cookie():
        return "QBT_SID_8080" if mood["modern"] else "SID"

    def same_site(request):
        """qBittorrent's CSRF protection: the Referer has to be its own address."""
        return urlsplit(request.headers.get("Referer", "")).netloc == request.host

    async def qbittorrent_login(request):
        form = await request.post()
        if not same_site(request):
            return web.Response(status=401)
        if (form.get("username"), form.get("password")) != (USER, PASSWORD):
            return web.Response(status=401) if mood["modern"] else web.Response(text="Fails.")
        session = secrets.token_urlsafe(24)
        live["qbittorrent"].add(session)
        app["logins"]["qbittorrent"] += 1
        response = web.Response(text="" if mood["modern"] else "Ok.")
        response.set_cookie(qbittorrent_cookie(), session, path="/", httponly=True)
        return response

    def logged_in(handler):
        async def checked(request):
            if not same_site(request):
                return web.Response(status=401)
            if request.cookies.get(qbittorrent_cookie()) not in live["qbittorrent"]:
                return web.Response(status=403, text="Forbidden")
            app["calls"].append(("qbittorrent", request.path.split("/api/v2/")[1]))
            return await handler(request)
        return checked

    async def qbittorrent_version(request):
        return web.Response(text=VERSIONS["qbittorrent"][mood["modern"]])

    async def qbittorrent_add(request):
        form = await request.post()
        if "torrents" in form:
            found = torrent_hash(form["torrents"].file.read())
            if not found:
                return web.Response(status=415, text="Error: 'x' is not a valid torrent file.")
        else:
            found = magnet_hash(form.get("urls", ""))
        added = store("qbittorrent", found, form.get("category"))
        if not mood["modern"]:
            return web.Response(text="Ok." if added else "Fails.")
        if not added:
            return web.Response(status=409, text="Conflict")
        return web.json_response({"success_count": 1, "failure_count": 0, "pending_count": 0,
                                  "added_torrent_ids": [found]})

    async def qbittorrent_info(request):
        only = request.query.get("hashes", "").split("|") if "hashes" in request.query else None
        rows = []
        for found, torrent in app["torrents"]["qbittorrent"].items():
            done = torrent["progress"] >= 1
            # qBittorrent 5 renamed "paused" to "stopped".
            stopped = ("stopped" if mood["modern"] else "paused") + ("UP" if done else "DL")
            state = ("error" if torrent["error"] else stopped if torrent["paused"]
                     else "uploading" if done else "downloading")
            if only is None or found in only:
                rows.append({"hash": found, "name": torrent["name"], "category": torrent["category"],
                             "progress": torrent["progress"], "state": state, **torrent["native"]})
        return web.json_response(rows)

    async def qbittorrent_delete(request):
        form = await request.post()
        for found in form.get("hashes", "").split("|"):
            app["removed"].append(("qbittorrent", found, form.get("deleteFiles") == "true"))
            app["torrents"]["qbittorrent"].pop(found, None)
        return web.Response()  # 200 in every case, also for a hash it does not have

    # ------------------------------------------------------------ Transmission

    def spelled(name):
        return name if mood["modern"] else OLD_NAMES.get(name, name)

    async def transmission(request):
        if request.headers.get("Authorization") != BASIC:
            return web.Response(status=401, text="Unauthorized User")
        if request.headers.get("X-Transmission-Session-Id") != live["transmission"]:
            # The handshake: the right id comes with the refusal. Since 4.1 its RPC version too.
            app["logins"]["transmission"] += 1
            headers = {"X-Transmission-Session-Id": live["transmission"]}
            if mood["modern"]:
                headers["X-Transmission-Rpc-Version"] = "6.0.0"
            return web.Response(status=409, headers=headers)
        body = await request.json()

        def answer(result=None, error=None):
            if mood["modern"]:
                outcome = {"error": {"code": 1, "message": error}} if error else {"result": result or {}}
                return web.json_response({"jsonrpc": "2.0", "id": body.get("id"), **outcome})
            return web.json_response({"result": error or "success", "arguments": result or {}})

        # As a new version this stand-in is stricter than Transmission 4.1, which still takes
        # the old protocol: it only takes JSON-RPC 2.0, as the versions after it will.
        if mood["modern"] and body.get("jsonrpc") != "2.0":
            return answer(error="Invalid Request")
        method, arguments = body.get("method"), body.get("params" if mood["modern"] else "arguments") or {}
        torrents = app["torrents"]["transmission"]
        app["calls"].append(("transmission", method))
        if method == spelled("session_get"):
            return answer({"version": VERSIONS["transmission"][mood["modern"]],
                           spelled("rpc_version"): 18 if mood["modern"] else 17})
        if method == spelled("torrent_add"):
            if "metainfo" in arguments:
                found = torrent_hash(base64.b64decode(arguments["metainfo"]))
            else:
                found = magnet_hash(arguments.get("filename"))
            if not found:
                return answer(error="invalid or corrupt torrent file")
            labels = [] if mood["transmission3"] else arguments.get("labels") or []
            added = store("transmission", found, labels[0] if labels else "")
            key = spelled("torrent_added" if added else "torrent_duplicate")
            return answer({key: {"id": len(torrents), "name": torrents[found]["name"], spelled("hash_string"): found}})
        if method == spelled("torrent_set"):
            for found in arguments.get("ids") or []:
                if found in torrents and "labels" in arguments:
                    torrents[found]["category"] = (arguments["labels"] or [""])[0]
            return answer()
        if method == spelled("torrent_get"):
            rows = []
            for number, (found, torrent) in enumerate(torrents.items(), 1):
                done = torrent["progress"] >= 1
                row = {"id": number, "name": torrent["name"], "hash_string": found,
                       "status": 0 if torrent["paused"] else 6 if done else 4,
                       "error": 3 if torrent["error"] else 0,
                       "error_string": "No data found!" if torrent["error"] else "",
                       "percent_done": torrent["progress"], "size_when_done": SIZE,
                       "left_until_done": int(SIZE * (1 - torrent["progress"])),
                       "labels": [torrent["category"]] if torrent["category"] else [], **torrent["native"]}
                rows.append({spelled(k): v for k, v in row.items() if spelled(k) in arguments.get("fields", [])})
            return answer({"torrents": rows})
        if method == spelled("torrent_remove"):
            for found in arguments.get("ids") or []:
                app["removed"].append(("transmission", found, arguments.get(spelled("delete_local_data")) is True))
                torrents.pop(found, None)  # a hash it does not have is skipped without an error
            return answer()
        return answer(error="Method not found" if mood["modern"] else "method name not recognized")

    # ------------------------------------------------------------ uTorrent

    async def utorrent_token(request):
        if request.headers.get("Authorization") != BASIC:
            return web.Response(status=401)
        app["logins"]["utorrent"] += 1
        response = web.Response(content_type="text/html", text=(
            f"<html><div id='token' style='display:none;'>{live['token']}</div></html>"))
        response.set_cookie("GUID", live["guid"], path="/")
        return response

    def utorrent_row(found, torrent):
        done = torrent["progress"] >= 1
        # 128 loaded + 8 checked, and then: 64 queued + 1 started when it runs, 16 for an error.
        status = 136 + (16 if torrent["error"] else 0 if torrent["paused"] else 65)
        row = [found.upper(), status, torrent["name"], SIZE, int(torrent["progress"] * 1000),
               int(SIZE * torrent["progress"]), 0, 0, 0, 0, -1, torrent["category"], 0, 0, 0, 0, 65536, 1,
               int(SIZE * (1 - torrent["progress"])), "", "", "Error: Files missing" if torrent["error"] else "OK",
               "1", 1700000000, 1700003600 if done else 0, "", "/downloads"]
        for position, value in torrent["native"].items():
            row[position] = value
        return row

    async def utorrent(request):
        if request.headers.get("Authorization") != BASIC:
            return web.Response(status=401)
        query = list(request.query.items())
        # The token counts only as the first parameter, and only with the cookie it came with.
        if not query or query[0] != ("token", live["token"]) or request.cookies.get("GUID") != live["guid"]:
            return web.Response(status=400, text="\ninvalid request")
        torrents = app["torrents"]["utorrent"]
        action = request.query.get("action", "list" if "list" in request.query else "")
        app["calls"].append(("utorrent", action))
        answer = {"build": UTORRENT_BUILD}
        if action == "getversion" and mood["modern"]:  # only the server edition knows this one
            answer["version"] = {"product_code": "server", "major_version": 3, "minor_version": 3,
                                 "engine_version": UTORRENT_BUILD, "ui_version": UTORRENT_BUILD}
        elif action == "add-url":
            store("utorrent", magnet_hash(request.query.get("s")), "")
        elif action == "add-file":
            found = torrent_hash((await request.post())["torrent_file"].file.read())
            # What the real one answers to a torrent it already has is not documented; the
            # strict choice here is an error.
            if not store("utorrent", found, ""):
                answer["error"] = "Can't add torrent: " + ("torrent already in list" if found else "invalid torrent file")
        elif action == "setprops":
            # Each s/v pair belongs to the hash before it. uTorrent writes hashes in capitals.
            found = name = None
            for key, value in query:
                if key == "hash":
                    found = value.lower() if value == value.upper() else None
                elif key == "s":
                    name = value
                elif key == "v" and name == "label" and found in torrents:
                    torrents[found]["category"] = value
        elif action in ("remove", "removedata"):
            # As setprops: only hashes in capitals. What the real one answers for a hash it
            # does not have is not documented; the strict choice here is an error.
            for value in request.query.getall("hash", []):
                found = value.lower() if value == value.upper() else ""
                app["removed"].append(("utorrent", found, action == "removedata"))
                if mood["stuck"]:
                    answer["error"] = "Can't remove torrent: access denied"
                elif torrents.pop(found, None) is None:
                    answer["error"] = "Can't remove torrent: not in list"
        elif action == "list":
            labels = sorted({t["category"] for t in torrents.values() if t["category"]})
            answer.update(label=[[label, sum(t["category"] == label for t in torrents.values())] for label in labels],
                          torrents=[utorrent_row(found, t) for found, t in torrents.items()], torrentc="1094627541")
        return web.json_response(answer)

    app.add_routes([
        web.post("/qbt/api/v2/auth/login", qbittorrent_login),
        web.get("/qbt/api/v2/app/version", logged_in(qbittorrent_version)),
        web.post("/qbt/api/v2/torrents/add", logged_in(qbittorrent_add)),
        web.get("/qbt/api/v2/torrents/info", logged_in(qbittorrent_info)),
        web.post("/qbt/api/v2/torrents/delete", logged_in(qbittorrent_delete)),
        web.post("/tr/transmission/rpc", transmission),
        web.get("/ut/gui/token.html", utorrent_token),
        web.get("/ut/gui/", utorrent),
        web.post("/ut/gui/", utorrent),
    ])
    return app


if __name__ == "__main__":
    web.run_app(make_torrent_fakes(), port=9001)
