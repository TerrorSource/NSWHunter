"""Web panel and scheduler of NSWHunter."""
import asyncio
import base64
import hashlib
import os
import re
import time
import warnings
from urllib.parse import urlsplit

import aiohttp
from aiohttp import web

import auth
import backup
import clients
import config
import logs
from hunter import Hunter, log
from version import __version__

# Plain string keys on the app object are fine for an app this size.
warnings.filterwarnings("ignore", category=web.NotAppKeyWarning)

HERE = os.path.dirname(os.path.abspath(__file__))
background = set()

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


def logged_in(request):
    return bool(config.PANEL_PASSWORD) and auth.valid(request.cookies.get(auth.COOKIE))


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
            "on the Configuration tab under Panel, or with the environment variable PANEL_HOSTS.\n"))
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
    secure = request.secure or request.headers.get("X-Forwarded-Proto", "").lower() == "https"
    response.set_cookie(auth.COOKIE, auth.start(), max_age=auth.LIFETIME, httponly=True,
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
    if not config.PANEL_PASSWORD or not auth.check_login(user, password):
        auth.failed(address)
        wait = auth.wait_for(address)
        if wait:
            request.app["hunter"].event(f"{auth.FREE_TRIES} wrong logins from {address}: it has to wait", "warn")
        return refuse(401, "Wrong username or password", wait=wait)
    auth.succeeded(address)
    return session_cookie(request, web.json_response({"ok": True}))


async def api_logout(request):
    auth.end(request.cookies.get(auth.COOKIE))
    response = web.json_response({"ok": True})
    response.del_cookie(auth.COOKIE, path="/")
    return response


async def api_state(request):
    view = request.app["hunter"].view()
    view["version"] = __version__
    view["now"] = int(time.time())
    view["user"] = config.PANEL_USER
    view["ui"] = {"theme": config.UI_THEME, "date": config.UI_DATE_FORMAT, "time": config.UI_TIME_FORMAT,
                  "relative": config.UI_RELATIVE_DATES}
    return web.json_response(view)


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
    return {"found": await hunter.search_now(str(body["key"]))}


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
    """Forget that a release was sent, so the item can be judged again."""
    hunter.state["items"][str(body["key"])]["grab"] = None
    hunter.save()


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
        changed = config.update(dict(body.get("values") or {}), list(body.get("clear") or []))
    except ValueError as e:
        return web.json_response({"ok": False, "error": str(e)}, status=400)
    except (AttributeError, TypeError):
        return web.json_response({"ok": False, "error": "Invalid request"}, status=400)
    hunter.event("Settings saved: " + (", ".join(changed) or "nothing changed"))
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
    return web.json_response({"ok": True, "folder": backup.folder(), "backups": backup.listing()})


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
            backup.restore(name)
            # Use what was put back at once: the settings, the log files, the state.
            config.load_saved()
            config.first_login()
            logs.setup()
            hunter.load()
            hunter.event(f"Backup put back: {name}", "warn")
            request.app["wake"].set()
        else:
            raise ValueError
    except backup.BackupError as e:
        return web.json_response({"ok": False, "error": str(e)}, status=400)
    except (ValueError, AttributeError, TypeError, KeyError):
        return web.json_response({"ok": False, "error": "Invalid request"}, status=400)
    return web.json_response({"ok": True, "folder": backup.folder(), "backups": backup.listing()})


async def api_backup_download(request):
    """A backup holds keys and passwords: like everything else, only for who is logged in."""
    try:
        name = request.query.get("name", "")
        return web.FileResponse(backup.path(name), headers={
            "Content-Disposition": f'attachment; filename="{name}"', "Content-Type": "application/zip"})
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
        web.get("/api/state", api_state),
        web.get("/api/log", api_log),
        web.get("/api/games", api_games),
        web.get("/api/cover/{id}", api_cover),
        web.get("/api/tasks", api_tasks),
        web.post("/api/task", api_task),
        web.get("/api/history", api_history),
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
    ])
    return app


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
    web.run_app(make_app(), port=config.PORT, print=None, access_log=None)
