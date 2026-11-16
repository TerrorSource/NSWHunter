"""Web panel and scheduler of NSWHunter."""
import asyncio
import base64
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
        log("Melding versturen mislukt:", e)


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
            hunter.event(f"Ronde mislukt: {e!r}", "error")
        hunter.status["next_run"] = int(time.time() + config.SYNC_INTERVAL_MINUTES * 60)
        # A click on "Nu synchroniseren" ends the wait early.
        app["wake"].clear()
        try:
            await asyncio.wait_for(app["wake"].wait(), config.SYNC_INTERVAL_MINUTES * 60)
        except asyncio.TimeoutError:
            pass


# ---------------------------------------------------------------- web


@web.middleware
async def guard(request, handler):
    if request.path == "/health":
        return await handler(request)
    if config.PANEL_PASSWORD:
        expected = base64.b64encode(f"{config.PANEL_USER}:{config.PANEL_PASSWORD}".encode()).decode()
        given = request.headers.get("Authorization", "")
        if not hmac.compare_digest(given.encode(), f"Basic {expected}".encode()):
            return web.Response(status=401, text="Inloggen vereist",
                                headers={"WWW-Authenticate": 'Basic realm="NSWHunter"'})
    # A page on another site cannot send JSON here without the browser asking first.
    if request.method == "POST" and request.content_type != "application/json":
        return web.Response(status=415, text="JSON vereist")
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
            return web.json_response({"ok": False, "error": "Ongeldig verzoek"}, status=400)
    return wrapped


async def do_grab(hunter, body):
    await hunter.grab(str(body["key"]), str(body["guid"]))


async def do_search(hunter, body):
    return {"found": await hunter.search_now(str(body["key"]))}


async def do_ignore(hunter, body):
    hunter.state["items"][str(body["key"])]["ignored"] = bool(body["ignored"])
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


async def api_settings(request):
    return web.json_response(config.editable())


async def api_settings_save(request):
    """Save the Configuratie tab, test the connections with the new values, start a round."""
    hunter = request.app["hunter"]
    try:
        body = await request.json()
        changed = config.update(dict(body.get("values") or {}), list(body.get("clear") or []))
    except ValueError as e:
        return web.json_response({"ok": False, "error": str(e)}, status=400)
    except (AttributeError, TypeError):
        return web.json_response({"ok": False, "error": "Ongeldig verzoek"}, status=400)
    hunter.event("Instellingen opgeslagen: " + (", ".join(changed) or "niets gewijzigd"))
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
        return web.json_response({"ok": False, "text": "Ongeldig verzoek"}, status=400)
    return web.json_response({"ok": True, "text": text})


async def start(app):
    app["session"] = aiohttp.ClientSession(headers={"User-Agent": f"NSWHunter/{__version__}"})
    app["hunter"] = Hunter(app["session"], notify)
    app["wake"] = asyncio.Event()
    spawn(scheduler(app))


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
    ])
    return app


if __name__ == "__main__":
    config.load_saved()
    log(f"NSWHunter {__version__} start op poort {config.PORT}")
    if config.problems():
        log(f"Nog niet ingesteld. Open het paneel op poort {config.PORT} en vul de tab Configuratie in.")
    web.run_app(make_app(), port=config.PORT, print=None, access_log=None)
