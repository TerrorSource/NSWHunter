"""NSWHunter as an app of Prowlarr: Prowlarr keeps the indexers of its apps in step with its own.
It knows no NSWHunter, so NSWHunter answers as Radarr does (its API v3, as far as Prowlarr uses
it). In Prowlarr, under Settings > Apps, NSWHunter is added as Radarr, with the address of
NSWHunter and the API key of Settings > General; its Sync Categories (an advanced setting) have
to be the console ones. Each indexer Prowlarr sends becomes a Newznab or Torznab indexer here,
which searches through Prowlarr, and goes when Prowlarr takes it away."""
import hmac

from aiohttp import web

import config
from version import __version__

ROUTE = "/api/v3"
# The fields of an indexer that Prowlarr fills in, with what they are before it does.
FIELDS = {"baseUrl": "", "apiPath": "/api", "apiKey": "", "categories": [], "multiLanguages": [],
          "removeYear": False, "requiredFlags": [], "additionalParameters": ""}
TORRENT_FIELDS = {"minimumSeeders": 1, "seedCriteria.seedRatio": None, "seedCriteria.seedTime": None,
                  "rejectBlocklistedTorrentHashesWhileGrabbing": False}


def allowed(request):
    """Does this request carry the API key (header X-Api-Key, or ?apikey=)?"""
    given = request.headers.get("X-Api-Key") or request.query.get("apikey") or ""
    return bool(config.API_KEY) and hmac.compare_digest(given.encode(), config.API_KEY.encode())


def answer(data, status=200):
    # Prowlarr reads the version of the app from this header, and wants at least 3.1.1.
    return web.json_response(data, status=status, headers={"X-Application-Version": __version__})


def get(data, name, default=None):
    """A value of what Prowlarr sent, whatever the case of its name."""
    for key, value in (data if isinstance(data, dict) else {}).items():
        if key.lower() == name.lower():
            return value
    return default


def field(data, name):
    return next((get(f, "value") for f in get(data, "fields") or [] if get(f, "name") == name), None)


def schema():
    return [{"id": 0, "name": "", "implementation": kind, "implementationName": kind, "configContract": f"{kind}Settings",
             "enableRss": True, "enableAutomaticSearch": True, "enableInteractiveSearch": True, "priority": 25,
             "protocol": protocol, "tags": [],
             "fields": [{"name": n, "value": v} for n, v in {**FIELDS, **extra}.items()]}
            for kind, protocol, extra in (("Newznab", "usenet", {}), ("Torznab", "torrent", TORRENT_FIELDS))]


def synced():
    return [e for e in config.INDEXERS if "app" in e]


def entry_of(data, app_id, old=None):
    """The indexer of NSWHunter for one that Prowlarr sends. ValueError says what is wrong."""
    try:
        priority = min(50, max(1, int(get(data, "priority", 25))))
    except (TypeError, ValueError):
        priority = 25
    url = str(field(data, "baseUrl") or "").rstrip("/") + "/" + str(field(data, "apiPath") or "/api").strip("/")
    entry = {"type": "torznab" if str(get(data, "implementation", "")).lower() == "torznab" else "newznab",
             "name": str(get(data, "name") or "Prowlarr"),
             "enabled": any(bool(get(data, k)) for k in ("enableAutomaticSearch", "enableInteractiveSearch")),
             "url": url, "api_key": str(field(data, "apiKey") or ""),
             "categories": [str(c) for c in field(data, "categories") or []], "priority": priority,
             "app": {**{k: v for k, v in data.items() if k.lower() != "id"}, "id": app_id}}
    clean = config.normalize_entry("INDEXERS", entry, keep_id=False)
    if old:
        clean["id"] = old["id"]
    return clean


def find(request):
    try:
        wanted = int(request.match_info["id"])
    except ValueError:
        return None
    return next((e for e in synced() if e["app"]["id"] == wanted), None)


async def read(request):
    try:
        data = await request.json()
    except ValueError:
        data = None
    if not isinstance(data, dict):
        raise ValueError("Send the indexer as JSON")
    return data


def changed(request, text):
    hunter = request.app["hunter"]
    hunter.event(text)
    hunter.forget_services()
    hunter.save()
    request.app["wake"].set()


async def status(request):
    return answer({"appName": "NSWHunter", "instanceName": "NSWHunter", "version": __version__})


async def indexer_schema(request):
    return answer(schema())


async def indexer_test(request):
    return answer({})  # Prowlarr only wants the version of the header


async def indexer_list(request):
    return answer([e["app"] for e in synced()])


async def indexer_one(request):
    entry = find(request)
    return answer(entry["app"]) if entry else answer({"message": "NotFound"}, 404)


async def indexer_add(request):
    try:
        data = await read(request)
        entry = entry_of(data, max((e["app"]["id"] for e in synced()), default=0) + 1)
    except ValueError as e:
        return answer([{"propertyName": "", "errorMessage": str(e)}], 400)
    config.replace_providers("INDEXERS", [*config.INDEXERS, entry])
    changed(request, f"Prowlarr added the indexer {entry['name']}")
    return answer(entry["app"], 201)


async def indexer_update(request):
    old = find(request)
    if old is None:
        return answer({"message": "NotFound"}, 404)
    try:
        entry = entry_of(await read(request), old["app"]["id"], old)
    except ValueError as e:
        return answer([{"propertyName": "", "errorMessage": str(e)}], 400)
    config.replace_providers("INDEXERS", [entry if e is old else e for e in config.INDEXERS])
    changed(request, f"Prowlarr changed the indexer {entry['name']}")
    return answer(entry["app"], 202)


async def indexer_delete(request):
    old = find(request)
    if old is None:
        return answer({"message": "NotFound"}, 404)
    config.replace_providers("INDEXERS", [e for e in config.INDEXERS if e is not old])
    changed(request, f"Prowlarr removed the indexer {old['name']}")
    return answer({})


def routes():
    return [
        web.get(ROUTE + "/system/status", status),
        web.get(ROUTE + "/indexer/schema", indexer_schema),
        web.post(ROUTE + "/indexer/test", indexer_test),
        web.get(ROUTE + "/indexer", indexer_list),
        web.post(ROUTE + "/indexer", indexer_add),
        web.get(ROUTE + "/indexer/{id}", indexer_one),
        web.put(ROUTE + "/indexer/{id}", indexer_update),
        web.delete(ROUTE + "/indexer/{id}", indexer_delete),
    ]
