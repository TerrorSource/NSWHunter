"""Web panel and scheduler of NSWHunter."""
import asyncio
import base64
import hashlib
import os
import re
import signal
import time
import warnings
from urllib.parse import urlsplit

import aiohttp
from aiohttp import web

import auth
import backup
import clients
import config
import importer
import logs
import tls
import totp
from hunter import Hunter, log
from version import __version__

# Plain string keys on the app object are fine for an app this size.
warnings.filterwarnings("ignore", category=web.NotAppKeyWarning)

HERE = os.path.dirname(os.path.abspath(__file__))
STARTED = int(time.time())  # for the uptime on the Status page
background = set()
# What the panel listens with: the runner of the web app, and the HTTPS side if it is on.
listening = {"runner": None, "tls": None}
pending_totp = {}  # the secret of a second step that is being set up, until its first code proves it

with open(os.path.join(HERE, "panel.html"), encoding="utf-8") as f:
    PANEL = f.read()


def _hash(tag):
    """The hash of the one <script> or <style> of the panel, for the Content-Security-Policy."""
    inside = re.search(rf"<{tag}>(.*?)</{tag}>", PANEL, re.S).group(1)
    return "'sha256-" + base64.b64encode(hashlib.sha256(inside.encode()).digest()).decode() + "'"


# The page may run its own script and style and nothing else, load nothing from elsewhere, talk
# only to this server, and not be shown inside another page.
HEADERS = {
    "Content-Security-Policy": (
        f"default-src 'none'; script-src {_hash('script')}; style-src {_hash('style')}; "
        "img-src 'self' data:; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"),
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}
# What works without a login: the page itself (it holds no data) and logging in.
OPEN = {"/", "/api/session", "/api/login"}
# What works with the made-up password of the first start: choosing one of your own, nothing else.
FIRST = {"/", "/api/session", "/api/login", "/api/logout", "/api/password"}


def spawn(coroutine):
    task = asyncio.create_task(coroutine)
    background.add(task)
    task.add_done_callback(background.discard)
    return task


async def scheduler(app):
    hunter = app["hunter"]
    await asyncio.sleep(3)
    while True:
        await hunter.round()
        hunter.status["next_run"] = int(time.time() + config.SYNC_INTERVAL_MINUTES * 60)
        # A click on "Sync now" ends the wait early.
        app["wake"].clear()
        try:
            await asyncio.wait_for(app["wake"].wait(), config.SYNC_INTERVAL_MINUTES * 60)
        except asyncio.TimeoutError:
            pass


# ---------------------------------------------------------------- web


def refuse(status, text, **more):
    return web.json_response({"ok": False, "error": text, **more}, status=status)


def over_https(request):
    """Did this request come in over HTTPS: on the HTTPS port, or through a reverse proxy that says so?"""
    return request.secure or request.headers.get("X-Forwarded-Proto", "").lower() == "https"


def token_of(request):
    """The token of the login of this browser, or None. Over HTTP only the plain cookie counts."""
    for name in (auth.SECURE_COOKIE, auth.COOKIE) if over_https(request) else (auth.COOKIE,):
        token = request.cookies.get(name)
        if auth.valid(token):
            return token
    return None


def logged_in(request):
    return bool(config.PANEL_PASSWORD) and token_of(request) is not None


@web.middleware
async def guard(request, handler):
    response = await guarded(request, handler)
    for name, value in HEADERS.items():
        response.headers.setdefault(name, value)
    return response


async def guarded(request, handler):
    if request.path == "/health":
        return await handler(request)
    if not auth.host_allowed(request.host):
        name = auth.host_name(request.host)
        return web.Response(status=403, text=(
            f"NSWHunter does not answer to the name '{name}'.\n\n"
            "Open the panel by its IP address, or add this name to the host names of the panel: "
            "under Settings > General > Host Names, or with the environment variable PANEL_HOSTS.\n"))
    # A page of another site cannot make the browser change something here.
    origin = request.headers.get("Origin")
    if request.method != "GET" and origin and urlsplit(origin).netloc.lower() != request.host.lower():
        return refuse(403, "This request comes from another site")
    if request.method == "POST" and request.content_type != "application/json":
        return refuse(415, "JSON required")
    if request.path not in OPEN and not logged_in(request):
        return refuse(401, "Login required", login=True)
    if request.path not in FIRST and config.must_change_password():
        return refuse(403, "Choose a password of your own first", change=True)
    return await handler(request)


def session_cookie(request, response):
    """Log this browser in: a cookie that scripts cannot read and other sites cannot send."""
    secure = over_https(request)
    token = auth.start(request.remote or "", request.headers.get("User-Agent", ""))
    response.set_cookie(auth.SECURE_COOKIE if secure else auth.COOKIE, token, max_age=auth.LIFETIME, httponly=True,
                        samesite="Strict", secure=secure, path="/")
    return response


async def panel(request):
    return web.Response(text=PANEL, content_type="text/html")


async def health(request):
    """For Docker: healthy as long as the last round did not break."""
    error = request.app["hunter"].status.get("error")
    return web.json_response({"ok": not error, "version": __version__}, status=503 if error else 200)


async def api_session(request):
    return web.json_response({"ok": True, "logged_in": logged_in(request), "version": __version__,
                              "change": logged_in(request) and config.must_change_password()})


async def api_password(request):
    """Choose a name and a password of your own. This is all the made-up password of the first
    start can do, and it ends that password."""
    try:
        body = await request.json()
        user, password = str(body["user"]).strip(), str(body["password"])
        if not password:
            raise ValueError("PANEL_PASSWORD: fill in a password")
        if config.check_password(password):
            raise ValueError("PANEL_PASSWORD: choose another password than the one you logged in with")
        config.update({"PANEL_USER": user, "PANEL_PASSWORD": password})
    except ValueError as e:
        return refuse(400, str(e).partition(": ")[2] or "Invalid request")
    except (KeyError, TypeError, AttributeError):
        return refuse(400, "Invalid request")
    request.app["hunter"].event(f"Password changed for {user}")
    auth.end_all()
    return session_cookie(request, web.json_response({"ok": True}))


async def api_login(request):
    address = request.remote or "?"
    wait = auth.wait_for(address)
    if wait:
        return refuse(429, f"Too many wrong logins. Try again in {wait} seconds.", wait=wait)
    try:
        body = await request.json()
        user, password = str(body["user"]), str(body["password"])
    except (KeyError, ValueError, TypeError, AttributeError):
        return refuse(400, "Invalid request")
    def wrong(text, **more):
        auth.failed(address)
        wait = auth.wait_for(address)
        if wait:
            request.app["hunter"].event(f"{auth.FREE_TRIES} wrong logins from {address}: it has to wait", "warn")
        return refuse(401, text, wait=wait, **more)

    if not config.PANEL_PASSWORD or not auth.check_login(user, password):
        return wrong("Wrong username or password")
    if config.TOTP_SECRET:
        # The second step: the code of the authenticator app. Asked only after the right password.
        given = str(body.get("code") or "").strip()
        if not given:
            return refuse(401, "Fill in the code of your authenticator app", totp=True)
        step = totp.verify(config.TOTP_SECRET, given, after=auth.used_step)
        if step is None:
            return wrong("That code is not right. Codes change every 30 seconds.", totp=True)
        auth.used_step = step
    auth.succeeded(address)
    return session_cookie(request, web.json_response({"ok": True}))


async def api_sessions(request):
    return web.json_response({"ok": True, "sessions": auth.listing(token_of(request))})


async def api_sessions_end(request):
    """Log one browser out, or every browser but this one."""
    try:
        body = await request.json()
        if body.get("others"):
            ended = auth.end_others(token_of(request))
        else:
            ended = int(auth.end_id(str(body["id"])))
    except (KeyError, ValueError, TypeError, AttributeError):
        return refuse(400, "Invalid request")
    if ended:
        request.app["hunter"].event(f"Logged out {ended} other session(s)" if body.get("others") else "Logged out a session")
    return web.json_response({"ok": True, "ended": ended, "sessions": auth.listing(token_of(request))})


async def api_totp(request):
    """The second step of the login: begin setting it up, switch it on with a first code, or
    switch it off with a code."""
    hunter = request.app["hunter"]
    try:
        body = await request.json()
        what, given = str(body["action"]), str(body.get("code") or "")
    except (KeyError, ValueError, TypeError, AttributeError):
        return refuse(400, "Invalid request")
    if what == "begin":
        if config.TOTP_SECRET:
            return refuse(400, "Two-step login is already on")
        secret = pending_totp["secret"] = totp.new_secret()
        address = totp.uri(secret, config.PANEL_USER)
        return web.json_response({"ok": True, "secret": secret, "uri": address, "qr": totp.qr(address)})
    if what == "enable":
        secret = pending_totp.get("secret")
        if config.TOTP_SECRET or not secret:
            return refuse(400, "Begin setting up two-step login first")
        step = totp.verify(secret, given)
        if step is None:
            return refuse(400, "That code is not right. Check the time of your phone and try the next code.")
        config.set_totp(secret)
        pending_totp.clear()
        auth.used_step = step
        hunter.event("Two-step login switched on", "warn")
        return web.json_response({"ok": True, "totp": True})
    if what == "disable":
        if not config.TOTP_SECRET:
            return web.json_response({"ok": True, "totp": False})
        address = request.remote or "?"
        if auth.wait_for(address):
            return refuse(429, f"Too many wrong codes. Try again in {auth.wait_for(address)} seconds.")
        step = totp.verify(config.TOTP_SECRET, given, after=auth.used_step)
        if step is None:
            auth.failed(address)
            return refuse(400, "That code is not right. Codes change every 30 seconds.")
        config.set_totp("")
        hunter.event("Two-step login switched off", "warn")
        return web.json_response({"ok": True, "totp": False})
    return refuse(400, "Invalid request")


async def secure(hunter):
    """Start, move or stop the HTTPS side of the panel as the settings say. A certificate that
    cannot be used leaves the panel on HTTP alone, and is said on the Status page."""
    if listening["tls"] is not None:
        await listening["tls"].stop()
        listening["tls"] = None
    hunter.state["services"].pop("ssl", None)
    if not config.SSL_ENABLED or listening["runner"] is None:
        return
    try:
        site = web.TCPSite(listening["runner"], port=config.SSL_PORT, ssl_context=tls.context())
        await site.start()
    except tls.TlsError as e:
        hunter.service("ssl", False, f"HTTPS is not on: {e}")
        hunter.event(f"HTTPS is not on: {e}", "error")
        return
    except OSError as e:
        hunter.service("ssl", False, f"HTTPS is not on: port {config.SSL_PORT} cannot be used ({e.strerror or e})")
        hunter.event(f"HTTPS is not on: port {config.SSL_PORT} cannot be used ({e.strerror or e})", "error")
        return
    listening["tls"] = site
    own = "" if config.SSL_CERT_PATH else ", with a certificate NSWHunter made itself"
    hunter.service("ssl", True, f"on port {config.SSL_PORT}{own}")
    hunter.event(f"HTTPS is on, on port {config.SSL_PORT}{own}")


async def api_logout(request):
    response = web.json_response({"ok": True})
    auth.end(request.cookies.get(auth.COOKIE))
    response.del_cookie(auth.COOKIE, path="/")
    if over_https(request):
        # The secure cookie can only be taken away the way it was given: over HTTPS, and as secure.
        auth.end(request.cookies.get(auth.SECURE_COOKIE))
        response.del_cookie(auth.SECURE_COOKIE, path="/", secure=True, httponly=True, samesite="Strict")
    return response


async def api_state(request):
    view = request.app["hunter"].view()
    view["version"] = __version__
    view["now"] = int(time.time())
    view["started"] = STARTED
    view["user"] = config.PANEL_USER
    view["ui"] = {"theme": config.UI_THEME, "date": config.UI_DATE_FORMAT, "time": config.UI_TIME_FORMAT,
                  "relative": config.UI_RELATIVE_DATES}
    return web.json_response(view)


def changes():
    """The changelog as the Updates page shows it: per version its date and what changed.
    The file sits next to the code in the image, and a folder higher in the repository."""
    for path in (os.path.join(HERE, "CHANGELOG.md"), os.path.join(HERE, os.pardir, "CHANGELOG.md")):
        try:
            with open(path, encoding="utf-8") as f:
                lines = f.read().splitlines()
            break
        except OSError:
            continue
    else:
        return []
    versions, kind = [], ""
    for line in lines:
        head = re.match(r"## \[(.+?)\] - (\S+)", line)
        if head:
            versions.append({"version": head[1], "date": head[2], "changes": []})
            kind = ""
        elif line.startswith("### "):
            kind = line[4:].strip()
        elif versions and line.strip():
            # A line that is not a point of a list is a note about the version as a whole.
            text = re.sub(r"\*\*|`", "", line[2:] if line.startswith("- ") else line).strip()
            versions[-1]["changes"].append({"kind": kind if line.startswith("- ") else "", "text": text})
    return versions


CHANGES = changes()


async def api_updates(request):
    return web.json_response({"ok": True, "version": __version__, "versions": CHANGES})


async def api_history(request):
    return web.json_response({"history": request.app["hunter"].history(), "now": int(time.time())})


async def api_search_all(request):
    """Search every game by name in a round that starts now."""
    games = request.app["hunter"].search_all()
    request.app["wake"].set()
    return web.json_response({"ok": True, "games": games})


async def api_test_all(request):
    """Ask the library, every indexer and every download client whether it answers."""
    await request.app["hunter"].test_connections()
    return web.json_response({"ok": True})


LOG_FILE = re.compile(r"nswhunter_\d{4}-\d{2}-\d{2}\.txt|nswhunter\.txt(\.\d)?")


async def api_logfiles(request):
    """The log files in /data/logs: one per day, the newest first."""
    try:
        names = [n for n in os.listdir(config.LOG_DIR) if LOG_FILE.fullmatch(n)]
    except OSError:
        names = []
    files = [{"name": n, "size": os.path.getsize(os.path.join(config.LOG_DIR, n)),
              "at": int(os.path.getmtime(os.path.join(config.LOG_DIR, n)))} for n in sorted(names, reverse=True)]
    return web.json_response({"ok": True, "folder": config.LOG_DIR, "files": files})


async def api_logfile(request):
    name = request.query.get("name", "")
    full = os.path.join(config.LOG_DIR, name)
    # Only a name of a log file: nothing else can be reached through it.
    if not LOG_FILE.fullmatch(name) or not os.path.isfile(full):
        return refuse(404, "That log file is not there")
    return web.FileResponse(full, headers={
        "Content-Disposition": f'attachment; filename="{name}"', "Content-Type": "text/plain; charset=utf-8"})


async def api_tasks(request):
    hunter = request.app["hunter"]
    return web.json_response({"ok": True, "tasks": hunter.tasks(), "runs": hunter.state.get("task_runs", []),
                              "now": int(time.time())})


async def api_task(request):
    """Run one of the tasks now. A task that is part of a round starts a round."""
    try:
        started = await request.app["hunter"].run_task(str((await request.json())["name"]))
        if started:
            request.app["wake"].set()
    except clients.ServiceError as e:
        return web.json_response({"ok": False, "error": str(e)}, status=502)
    except (KeyError, ValueError, TypeError):
        return web.json_response({"ok": False, "error": "Invalid request"}, status=400)
    hunter = request.app["hunter"]
    return web.json_response({"ok": True, "round": started, "tasks": hunter.tasks(), "runs": hunter.state.get("task_runs", [])})


async def api_cover(request):
    """The small picture of a game, as switch-library-manager-web has it; kept after the first time."""
    found = await request.app["hunter"].cover(request.match_info["id"].upper())
    if found is None:
        return web.Response(status=404)
    kind, data = found
    # The browser may keep it: a picture of a game does not change from one look to the next.
    return web.Response(body=data, content_type=kind, headers={"Cache-Control": "private, max-age=604800"})


async def api_games(request):
    return web.json_response({"games": request.app["hunter"].library(), "now": int(time.time())})


async def api_log(request):
    return web.json_response({"events": request.app["hunter"].log(), "now": int(time.time())})


async def api_sync(request):
    request.app["wake"].set()
    return web.json_response({"ok": True})


def action(handler):
    """Run a panel action; a problem with one of the services becomes a readable message."""
    async def wrapped(request):
        try:
            body = await request.json()
            return web.json_response({"ok": True, **(await handler(request.app["hunter"], body) or {})})
        except clients.ServiceError as e:
            return web.json_response({"ok": False, "error": str(e)}, status=502)
        except (KeyError, ValueError, TypeError):
            return web.json_response({"ok": False, "error": "Invalid request"}, status=400)
    return wrapped


async def do_grab(hunter, body):
    await hunter.grab(str(body["key"]), str(body["guid"]))


async def do_grab_best(hunter, body):
    """Send the best release of every item that awaits a choice, from a score on."""
    score = int(body["min_score"])
    if not 1 <= score <= 10:
        raise ValueError
    return {"sent": await hunter.grab_best(score)}


async def do_search(hunter, body):
    query = " ".join(str(body.get("query") or "").split())[:100]  # words of the user's own, if any
    return {"found": await hunter.search_now(str(body["key"]), query or None)}


async def do_ignore(hunter, body):
    """Ignore one item, or every item of a game at once (keys)."""
    for key in body.get("keys") or [body["key"]]:
        hunter.state["items"][str(key)]["ignored"] = bool(body["ignored"])
    hunter.save()


async def do_block(hunter, body):
    """Reject one release: it disappears and is not offered or sent again."""
    hunter.reject(str(body["key"]), str(body["guid"]))


async def do_restore(hunter, body):
    """Take back a rejection: one release, or all of which no name was kept."""
    hunter.restore(str(body["key"]), str(body["guid"]) if body.get("guid") else None)


async def do_unsend(hunter, body):
    """Take a release out of the queue; if asked also out of the download client, and onto the blocklist."""
    await hunter.unsend(str(body["key"]), remove=bool(body.get("remove")), block=bool(body.get("block")))


async def do_import(hunter, body):
    """Try once more to put a finished download in the library."""
    await hunter.import_now(str(body["key"]))


async def api_browse(request):
    """The File Browser of the panel: the folders of a path in this container."""
    try:
        body = await request.json()
        return web.json_response({"ok": True, **importer.browse(str(body.get("path") or "/"), bool(body.get("files")))})
    except (ValueError, TypeError, AttributeError):
        return refuse(400, "Invalid request")


async def api_root_folders(request):
    return web.json_response({"ok": True, "folders": importer.root_folders()})


async def api_root_folders_change(request):
    """Add a root folder, or remove one. Removing only makes NSWHunter forget it: the folder stays."""
    try:
        body = await request.json()
        what, path = str(body["action"]), str(body["path"])
        if what == "add":
            config.add_root_folder(path, str(body.get("library_path") or ""))
            request.app["hunter"].event(f"Root folder added: {path}")
        elif what == "remove":
            config.remove_root_folder(path)
            request.app["hunter"].event(f"Root folder removed: {path}")
        else:
            raise KeyError
    except ValueError as e:
        return refuse(400, str(e).partition(": ")[2] if str(e).startswith("Path") else str(e))
    except (KeyError, TypeError, AttributeError):
        return refuse(400, "Invalid request")
    return web.json_response({"ok": True, "folders": importer.root_folders()})


async def do_dismiss(hunter, body):
    """Take a failed download off the list. The release stays rejected."""
    hunter.dismiss(str(body["key"]), str(body["guid"]))


async def api_settings(request):
    return web.json_response(config.editable())


async def api_settings_save(request):
    """Save single settings of a settings page and use them from now on."""
    hunter = request.app["hunter"]
    login = (config.PANEL_USER, config.PANEL_PASSWORD)
    try:
        body = await request.json()
        values, clear = dict(body.get("values") or {}), list(body.get("clear") or [])
        after = config.overlay(values, clear)
        if after.SSL_ENABLED and any(name.startswith("SSL_") for name in values):
            if after.SSL_PORT == config.PORT:
                raise ValueError(f"SSL_PORT: port {config.PORT} is the one of HTTP; choose another")
            tls.context(after)  # with a certificate that cannot be used HTTPS is not switched on
        changed = config.update(values, clear)
    except tls.TlsError as e:
        return web.json_response({"ok": False, "error": f"HTTPS: {e}"}, status=400)
    except ValueError as e:
        return web.json_response({"ok": False, "error": str(e)}, status=400)
    except (AttributeError, TypeError):
        return web.json_response({"ok": False, "error": "Invalid request"}, status=400)
    hunter.event("Settings saved: " + (", ".join(changed) or "nothing changed"))
    if any(name.startswith("SSL_") for name in changed):
        await secure(hunter)
    logs.setup()
    request.app["wake"].set()
    response = web.json_response({"ok": True, **config.editable()})
    if login != (config.PANEL_USER, config.PANEL_PASSWORD):
        # A new login: every other browser has to log in again, this one stays.
        auth.end_all()
        session_cookie(request, response)
    return response


def tested(handler):
    """A Test button: the outcome is a text, good or bad, never a failed request."""
    async def wrapped(request):
        try:
            text = await handler(request.app["hunter"], await request.json())
        except (clients.ServiceError, ValueError) as e:
            return web.json_response({"ok": False, "text": str(e)})
        except (AttributeError, TypeError, KeyError):
            return web.json_response({"ok": False, "text": "Invalid request"}, status=400)
        return web.json_response({"ok": True, "text": text})
    return wrapped


async def test_library(hunter, body):
    """Try the library with the values in the form. Nothing is saved."""
    cfg = config.overlay(dict(body.get("values") or {}), list(body.get("clear") or []))
    return await hunter.test("slm", cfg)


async def test_provider(hunter, body):
    """Try one indexer, download client or connection as it is in the form. Nothing is saved."""
    kind = str(body["kind"])
    return await hunter.test(kind, config.normalize_entry(kind, body["entry"]))


async def api_provider(request):
    """Add or change one indexer, download client or connection, and say whether it answers."""
    hunter = request.app["hunter"]
    try:
        body = await request.json()
        kind = str(body["kind"])
        entry = config.save_provider(kind, body["entry"])
    except ValueError as e:
        return web.json_response({"ok": False, "error": str(e)}, status=400)
    except (AttributeError, TypeError, KeyError):
        return web.json_response({"ok": False, "error": "Invalid request"}, status=400)
    hunter.event(f"Saved: {entry['name']}")
    text, ok = "switched off", None
    if entry["enabled"] and kind != "CONNECTIONS":  # a connection is not tested by sending a message
        try:
            text, ok = await hunter.test(kind, entry), True
        except clients.ServiceError as e:
            text, ok = str(e), False
        hunter.provider(kind, entry, ok, text)
    hunter.forget_services()
    hunter.save()
    request.app["wake"].set()
    return web.json_response({"ok": True, "id": entry["id"], "tested": ok, "text": text, **config.editable()})


async def api_provider_delete(request):
    hunter = request.app["hunter"]
    try:
        body = await request.json()
        config.delete_provider(str(body["kind"]), str(body["id"]))
    except (ValueError, AttributeError, TypeError, KeyError):
        return web.json_response({"ok": False, "error": "Invalid request"}, status=400)
    hunter.forget_services()
    hunter.save()
    return web.json_response({"ok": True, **config.editable()})


# ---------------------------------------------------------------- backups


async def api_backups(request):
    return web.json_response({"ok": True, "folder": backup.folder(), "backups": backup.listing(),
                              "encrypting": bool(config.BACKUP_PASSWORD)})


async def api_backup(request):
    """Make a backup now, remove one, or put one back."""
    hunter = request.app["hunter"]
    try:
        body = await request.json()
        what, name = str(body["action"]), str(body.get("name", ""))
        if what == "create":
            hunter.save()
            hunter.event(f"Backup made: {backup.create('manual')}")
        elif what == "delete":
            backup.delete(name)
        elif what == "restore":
            backup.restore(name, str(body.get("password") or "") or None)
            # Use what was put back at once: the settings, the log files, the state.
            config.load_saved()
            config.first_login()
            logs.setup()
            hunter.load()
            hunter.event(f"Backup put back: {name}", "warn")
            request.app["wake"].set()
        else:
            raise ValueError
    except backup.WrongPassword as e:
        # The panel asks for the password the backup was made with, and tries again.
        return web.json_response({"ok": False, "error": str(e), "password": True}, status=400)
    except backup.BackupError as e:
        return web.json_response({"ok": False, "error": str(e)}, status=400)
    except (ValueError, AttributeError, TypeError, KeyError):
        return web.json_response({"ok": False, "error": "Invalid request"}, status=400)
    if what == "restore":
        await secure(hunter)
    return web.json_response({"ok": True, "folder": backup.folder(), "backups": backup.listing(),
                              "encrypting": bool(config.BACKUP_PASSWORD)})


async def api_backup_download(request):
    """A backup holds keys and passwords: like everything else, only for who is logged in."""
    try:
        name = request.query.get("name", "")
        return web.FileResponse(backup.path(name), headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "Content-Type": "application/octet-stream" if name.endswith(backup.ENCRYPTED) else "application/zip"})
    except backup.BackupError as e:
        return refuse(404, str(e))


async def watcher(app):
    """Between rounds: follow what was sent to the download client."""
    while True:
        await asyncio.sleep(config.WATCH_SECONDS)
        try:
            await app["hunter"].watch()
        except Exception as e:  # noqa: BLE001
            app["hunter"].event(f"Following the downloads failed: {e!r}", "error")


async def listener(app):
    """Wait for presses on the buttons under the questions in Telegram. Telegram is only asked
    while a question is open."""
    hunter = app["hunter"]
    while True:
        try:
            # Telegram keeps the call open until there is news; the pause is for a server that does not.
            await asyncio.sleep(1 if await hunter.telegram_answers() else 15)
        except clients.ServiceError as e:
            hunter.service("telegram", False, str(e))
            await asyncio.sleep(60)
        except Exception as e:  # noqa: BLE001
            hunter.event(f"Listening to Telegram failed: {e!r}", "error")
            await asyncio.sleep(60)


async def start(app):
    auth.load()
    app["session"] = aiohttp.ClientSession(headers={"User-Agent": f"NSWHunter/{__version__}"})
    app["hunter"] = Hunter(app["session"])
    app["wake"] = asyncio.Event()
    spawn(scheduler(app))
    spawn(watcher(app))
    spawn(listener(app))


async def stop(app):
    for task in list(background):
        task.cancel()
    await app["session"].close()


def make_app():
    app = web.Application(middlewares=[guard], client_max_size=64 * 1024)
    app.on_startup.append(start)
    app.on_cleanup.append(stop)
    app.add_routes([
        web.get("/", panel),
        web.get("/health", health),
        web.get("/api/session", api_session),
        web.post("/api/password", api_password),
        web.post("/api/login", api_login),
        web.post("/api/logout", api_logout),
        web.get("/api/sessions", api_sessions),
        web.post("/api/sessions", api_sessions_end),
        web.post("/api/totp", api_totp),
        web.get("/api/state", api_state),
        web.get("/api/log", api_log),
        web.get("/api/games", api_games),
        web.get("/api/cover/{id}", api_cover),
        web.get("/api/tasks", api_tasks),
        web.post("/api/task", api_task),
        web.get("/api/history", api_history),
        web.get("/api/updates", api_updates),
        web.post("/api/search-all", api_search_all),
        web.post("/api/test-all", api_test_all),
        web.get("/api/logfiles", api_logfiles),
        web.get("/api/logfile", api_logfile),
        web.post("/api/sync", api_sync),
        web.get("/api/settings", api_settings),
        web.post("/api/settings", api_settings_save),
        web.post("/api/test", tested(test_library)),
        web.post("/api/provider", api_provider),
        web.post("/api/provider/delete", api_provider_delete),
        web.post("/api/provider/test", tested(test_provider)),
        web.get("/api/backups", api_backups),
        web.post("/api/backup", api_backup),
        web.get("/api/backup/download", api_backup_download),
        web.post("/api/grab", action(do_grab)),
        web.post("/api/grab-best", action(do_grab_best)),
        web.post("/api/search", action(do_search)),
        web.post("/api/ignore", action(do_ignore)),
        web.post("/api/block", action(do_block)),
        web.post("/api/restore", action(do_restore)),
        web.post("/api/unsend", action(do_unsend)),
        web.post("/api/dismiss", action(do_dismiss)),
        web.post("/api/import", action(do_import)),
        web.post("/api/browse", api_browse),
        web.get("/api/rootfolders", api_root_folders),
        web.post("/api/rootfolders", api_root_folders_change),
    ])
    return app


async def serve():
    """Listen on the HTTP port, and on the HTTPS port if the settings ask for it, until the
    container is stopped."""
    app = make_app()
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    listening["runner"] = runner
    await web.TCPSite(runner, port=config.PORT).start()
    await secure(app["hunter"])
    stopped = asyncio.Event()
    for name in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(name, stopped.set)
    await stopped.wait()
    await runner.cleanup()


if __name__ == "__main__":
    config.load_saved()
    logs.setup()
    log(f"NSWHunter {__version__} starting on port {config.PORT}")
    made_up = config.first_login()
    if made_up:
        # Shown at every start until the user has chosen a password of their own. Only here,
        # in the output of the container: not in the log files and not in the panel.
        logs.console("=" * 62)
        logs.console(f"  Log in to the panel on port {config.PORT} with")
        logs.console(f"    username: {config.PANEL_USER}")
        logs.console(f"    password: {made_up}")
        logs.console("  You have to choose a password of your own at the first login.")
        logs.console("=" * 62)
    elif config.problems():
        log(f"Not set up yet. Open the panel on port {config.PORT} and fill in the settings.")
    asyncio.run(serve())
