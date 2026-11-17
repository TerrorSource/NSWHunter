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
import clients
import config
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
        "img-src data:; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"),
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}
# What works without a login: the page itself (it holds no data) and logging in.
OPEN = {"/", "/api/session", "/api/login", "/api/setup"}


async def notify(title, body):
    """Apprise notification, if NOTIFY_URLS is set. A failed notification never stops a round."""
    if not config.NOTIFY_URLS:
        return
    try:
        import apprise
        sender = apprise.Apprise()
        for target in config.NOTIFY_URLS.split(","):
            sender.add(target.strip())
        await sender.async_notify(title=title, body=body)
    except Exception as e:  # noqa: BLE001
        log("Sending the notification failed:", e)


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
        return refuse(401, "Login required", login=True, setup=not config.PANEL_PASSWORD)
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
    return web.json_response({"ok": True, "logged_in": logged_in(request), "setup": not config.PANEL_PASSWORD,
                              "version": __version__})


async def api_setup(request):
    """The first visit: make the login. Only possible while there is none."""
    if config.PANEL_PASSWORD:
        return refuse(403, "There is a login already")
    try:
        body = await request.json()
        user, password = str(body["user"]).strip(), str(body["password"])
        if not password:
            raise ValueError("PANEL_PASSWORD: fill in a password")
        config.update({"PANEL_USER": user, "PANEL_PASSWORD": password})
    except ValueError as e:
        return refuse(400, str(e).partition(": ")[2] or "Invalid request")
    except (KeyError, TypeError, AttributeError):
        return refuse(400, "Invalid request")
    request.app["hunter"].event(f"Login made for {user}")
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
    return web.json_response(view)


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
    """Save the Configuration tab, test the connections with the new values, start a round."""
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
    services = await hunter.test_connections()
    request.app["wake"].set()
    response = web.json_response({"ok": True, "services": services, **config.editable()})
    if login != (config.PANEL_USER, config.PANEL_PASSWORD):
        # A new login: every other browser has to log in again, this one stays.
        auth.end_all()
        session_cookie(request, response)
    return response


async def api_test(request):
    """A Test button: try one service with the values in the form. Nothing is saved."""
    try:
        body = await request.json()
        cfg = config.overlay(dict(body.get("values") or {}), list(body.get("clear") or []))
        text = await request.app["hunter"].test(str(body.get("service")), cfg)
    except clients.ServiceError as e:
        return web.json_response({"ok": False, "text": str(e)})
    except ValueError as e:
        return web.json_response({"ok": False, "text": str(e)})
    except (AttributeError, TypeError):
        return web.json_response({"ok": False, "text": "Invalid request"}, status=400)
    return web.json_response({"ok": True, "text": text})


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
    app["hunter"] = Hunter(app["session"], notify)
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
        web.post("/api/setup", api_setup),
        web.post("/api/login", api_login),
        web.post("/api/logout", api_logout),
        web.get("/api/state", api_state),
        web.get("/api/log", api_log),
        web.post("/api/sync", api_sync),
        web.get("/api/settings", api_settings),
        web.post("/api/settings", api_settings_save),
        web.post("/api/test", api_test),
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
    log(f"NSWHunter {__version__} starting on port {config.PORT}")
    if not config.PANEL_PASSWORD:
        log(f"No login yet. Open the panel on port {config.PORT} to make one.")
    elif config.problems():
        log(f"Not set up yet. Open the panel on port {config.PORT} and fill in the Configuration tab.")
    web.run_app(make_app(), port=config.PORT, print=None, access_log=None)
