"""Web panel and scheduler of NSWHunter."""
import asyncio
import base64
import binascii
import hashlib
import hmac
import os
import time
import warnings

import aiohttp
from aiohttp import web

import clients
import config
from hunter import Hunter, log
from version import __version__

# Plain string keys on the app object are fine for an app this size.
warnings.filterwarnings("ignore", category=web.NotAppKeyWarning)

HERE = os.path.dirname(os.path.abspath(__file__))
background = set()


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
        try:
            await hunter.round()
        except Exception as e:  # noqa: BLE001
            hunter.event(f"Round failed: {e!r}", "error")
        hunter.status["next_run"] = int(time.time() + config.SYNC_INTERVAL_MINUTES * 60)
        # A click on "Sync now" ends the wait early.
        app["wake"].clear()
        try:
            await asyncio.wait_for(app["wake"].wait(), config.SYNC_INTERVAL_MINUTES * 60)
        except asyncio.TimeoutError:
            pass


# ---------------------------------------------------------------- web


logged_in = {}  # the last login that was right, so the slow password check runs once


def allowed(header):
    """Is this Authorization header the panel's user and password?"""
    # The check of a password is slow on purpose. A browser sends the same header with every
    # request: remember the one that was right, for as long as the password stays the same.
    mark = (hashlib.sha256(header.encode()).hexdigest(), config.PANEL_USER, config.PANEL_PASSWORD)
    if logged_in.get("mark") == mark:
        return True
    try:
        kind, _, encoded = header.partition(" ")
        user, _, password = base64.b64decode(encoded, validate=True).decode().partition(":")
    except (binascii.Error, UnicodeDecodeError):
        return False
    if kind.lower() != "basic" or not hmac.compare_digest(user.encode(), config.PANEL_USER.encode()):
        return False
    if not config.check_password(password):
        return False
    logged_in["mark"] = mark
    return True


@web.middleware
async def guard(request, handler):
    if request.path == "/health":
        return await handler(request)
    if config.PANEL_PASSWORD:
        if not allowed(request.headers.get("Authorization", "")):
            return web.Response(status=401, text="Login required",
                                headers={"WWW-Authenticate": 'Basic realm="NSWHunter"'})
    # A page on another site cannot send JSON here without the browser asking first.
    if request.method == "POST" and request.content_type != "application/json":
        return web.Response(status=415, text="JSON required")
    return await handler(request)


async def panel(request):
    return web.FileResponse(os.path.join(HERE, "panel.html"), headers={"Cache-Control": "no-store"})


async def health(request):
    return web.json_response({"ok": True, "version": __version__})


async def api_state(request):
    view = request.app["hunter"].view()
    view["version"] = __version__
    view["now"] = int(time.time())
    return web.json_response(view)


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


async def do_search(hunter, body):
    return {"found": await hunter.search_now(str(body["key"]))}


async def do_ignore(hunter, body):
    """Ignore one item, or every item of a game at once (keys)."""
    for key in body.get("keys") or [body["key"]]:
        hunter.state["items"][str(key)]["ignored"] = bool(body["ignored"])
    hunter.save()


async def do_block(hunter, body):
    """Reject one release: it disappears and is never offered or sent again."""
    item = hunter.state["items"][str(body["key"])]
    guid = str(body["guid"])
    item["blocked"].append(guid)
    item["candidates"] = [c for c in item["candidates"] if c["guid"] != guid]
    hunter.save()


async def do_unsend(hunter, body):
    """Forget that a release was sent, so the item can be judged again."""
    hunter.state["items"][str(body["key"])]["grab"] = None
    hunter.save()


async def do_dismiss(hunter, body):
    """Take a failed download off the list. The release stays skipped."""
    item = hunter.state["items"][str(body["key"])]
    item["failed"] = [f for f in item.get("failed", []) if f["guid"] != str(body["guid"])]
    hunter.save()


async def api_settings(request):
    return web.json_response(config.editable())


async def api_settings_save(request):
    """Save the Configuration tab, test the connections with the new values, start a round."""
    hunter = request.app["hunter"]
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
    return web.json_response({"ok": True, "services": services, **config.editable()})


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


async def start(app):
    app["session"] = aiohttp.ClientSession(headers={"User-Agent": f"NSWHunter/{__version__}"})
    app["hunter"] = Hunter(app["session"], notify)
    app["wake"] = asyncio.Event()
    spawn(scheduler(app))
    spawn(watcher(app))


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
        web.get("/api/state", api_state),
        web.post("/api/sync", api_sync),
        web.get("/api/settings", api_settings),
        web.post("/api/settings", api_settings_save),
        web.post("/api/test", api_test),
        web.post("/api/grab", action(do_grab)),
        web.post("/api/search", action(do_search)),
        web.post("/api/ignore", action(do_ignore)),
        web.post("/api/block", action(do_block)),
        web.post("/api/unsend", action(do_unsend)),
        web.post("/api/dismiss", action(do_dismiss)),
    ])
    return app


if __name__ == "__main__":
    config.load_saved()
    log(f"NSWHunter {__version__} starting on port {config.PORT}")
    if config.problems():
        log(f"Not set up yet. Open the panel on port {config.PORT} and fill in the Configuration tab.")
    web.run_app(make_app(), port=config.PORT, print=None, access_log=None)
