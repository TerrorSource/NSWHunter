"""The four services NSWHunter talks to: the library, Prowlarr, and the download clients."""
import base64
import re
from urllib.parse import urlsplit, urlunsplit

import aiohttp

import config

SHORT = aiohttp.ClientTimeout(total=30)
LONG = aiohttp.ClientTimeout(total=180)  # a Prowlarr search waits for the slowest indexer


class ServiceError(Exception):
    pass


async def _check(response, what):
    if response.status == 401 or response.status == 403:
        raise ServiceError(f"{what}: geen toegang (HTTP {response.status}). Controleer de API key of de inlog.")
    if response.status >= 400:
        body = (await response.text())[:200].strip()
        raise ServiceError(f"{what}: HTTP {response.status} {body}")


def _wrap(what, error):
    if isinstance(error, ServiceError):
        return error
    if isinstance(error, TimeoutError):
        return ServiceError(f"{what}: geen antwoord (time-out)")
    return ServiceError(f"{what}: {error}")


# ---------------------------------------------------------------- library


async def library(session):
    """The export of switch-library-manager-web: one entry per game in the library."""
    headers = {"Authorization": f"Bearer {config.SLM_API_KEY}"} if config.SLM_API_KEY else {}
    try:
        async with session.get(f"{config.SLM_URL}/export/library.json", headers=headers,
                               timeout=LONG) as r:
            await _check(r, "Bibliotheek")
            data = await r.json(content_type=None)
    except Exception as e:
        raise _wrap("Bibliotheek", e) from e
    if not isinstance(data, list):
        raise ServiceError("Bibliotheek: onverwacht antwoord (geen lijst)")
    return data


async def titledb_versions(session):
    """{title id: {version: "YYYY-MM-DD"}} for every Switch game."""
    try:
        async with session.get(config.TITLEDB_VERSIONS_URL, timeout=LONG) as r:
            await _check(r, "titledb")
            return await r.text()
    except Exception as e:
        raise _wrap("titledb", e) from e


# ---------------------------------------------------------------- prowlarr


def _prowlarr_headers():
    return {"X-Api-Key": config.PROWLARR_API_KEY}


async def prowlarr_status(session):
    try:
        async with session.get(f"{config.PROWLARR_URL}/api/v1/system/status",
                               headers=_prowlarr_headers(), timeout=SHORT) as r:
            await _check(r, "Prowlarr")
            return (await r.json()).get("version", "?")
    except Exception as e:
        raise _wrap("Prowlarr", e) from e


async def prowlarr_search(session, query):
    """Usenet releases for a query; an empty query gives the newest posts of every indexer."""
    params = [("query", query), ("type", "search"), ("limit", "100"), ("offset", "0")]
    params += [("categories", c) for c in config.PROWLARR_CATEGORIES]
    # -2 is Prowlarr's shorthand for "all usenet indexers".
    params += [("indexerIds", i) for i in (config.PROWLARR_INDEXER_IDS or ["-2"])]
    try:
        async with session.get(f"{config.PROWLARR_URL}/api/v1/search", params=params,
                               headers=_prowlarr_headers(), timeout=LONG) as r:
            await _check(r, "Prowlarr")
            data = await r.json()
    except Exception as e:
        raise _wrap("Prowlarr", e) from e
    releases = []
    for item in data if isinstance(data, list) else []:
        if item.get("protocol", "usenet") != "usenet" or not item.get("guid") or not item.get("title"):
            continue
        releases.append({
            "guid": item["guid"],
            "title": item["title"],
            "size": item.get("size") or 0,
            "indexer": item.get("indexer") or "",
            "indexerId": item.get("indexerId"),
            "published": item.get("publishDate") or "",
            "downloadUrl": item.get("downloadUrl") or "",
            "infoUrl": item.get("infoUrl") or "",
            "grabs": item.get("grabs") or 0,
        })
    return releases


def _via_prowlarr(download_url):
    """Prowlarr builds download links from the address it was called on. Point them at
    PROWLARR_URL so they also work when that differs (reverse proxy, other network)."""
    base, link = urlsplit(config.PROWLARR_URL), urlsplit(download_url)
    return urlunsplit((base.scheme, base.netloc, link.path, link.query, ""))


async def prowlarr_nzb(session, release):
    if not release.get("downloadUrl"):
        raise ServiceError("Prowlarr gaf geen downloadlink voor deze release")
    try:
        async with session.get(_via_prowlarr(release["downloadUrl"]), timeout=LONG) as r:
            await _check(r, "NZB ophalen")
            data = await r.read()
    except Exception as e:
        raise _wrap("NZB ophalen", e) from e
    if b"<nzb" not in data[:4000].lower():
        raise ServiceError("NZB ophalen: het antwoord van de indexer is geen NZB-bestand")
    return data


async def prowlarr_grab(session, release):
    """Let Prowlarr send the release to the download client configured in Prowlarr itself."""
    body = {"guid": release["guid"], "indexerId": release["indexerId"]}
    try:
        async with session.post(f"{config.PROWLARR_URL}/api/v1/search", json=body,
                                headers=_prowlarr_headers(), timeout=LONG) as r:
            if r.status == 404:
                raise ServiceError("Prowlarr kent deze release niet meer; zoek opnieuw en probeer nog eens")
            await _check(r, "Prowlarr")
    except Exception as e:
        raise _wrap("Prowlarr", e) from e


# ---------------------------------------------------------------- download clients


def nzb_filename(title):
    return re.sub(r'[\\/:*?"<>|]+', " ", title).strip()[:180] + ".nzb"


async def _nzbget(session, method, params):
    headers = {}
    if config.NZBGET_USER:
        login = f"{config.NZBGET_USER}:{config.NZBGET_PASSWORD}".encode()
        headers["Authorization"] = "Basic " + base64.b64encode(login).decode()
    try:
        async with session.post(f"{config.NZBGET_URL}/jsonrpc", headers=headers, timeout=LONG,
                                json={"method": method, "params": params, "id": 1}) as r:
            await _check(r, "NZBGet")
            data = await r.json(content_type=None)
    except Exception as e:
        raise _wrap("NZBGet", e) from e
    if data.get("error"):
        raise ServiceError(f"NZBGet: {data['error']}")
    return data.get("result")


async def _sabnzbd(session, fields, nzb=None):
    form = aiohttp.FormData()
    for key, value in {**fields, "apikey": config.SABNZBD_API_KEY, "output": "json"}.items():
        form.add_field(key, value)
    if nzb:
        form.add_field("name", nzb[1], filename=nzb[0], content_type="application/x-nzb")
    try:
        async with session.post(f"{config.SABNZBD_URL}/api", data=form, timeout=LONG) as r:
            await _check(r, "SABnzbd")
            data = await r.json(content_type=None)
    except Exception as e:
        raise _wrap("SABnzbd", e) from e
    if data.get("status") is False:
        raise ServiceError(f"SABnzbd: {data.get('error', 'geweigerd')}")
    return data


async def downloader_status(session):
    """Version of the download client, as a connection test."""
    if config.DOWNLOAD_CLIENT == "nzbget":
        return f"NZBGet {await _nzbget(session, 'version', [])}"
    if config.DOWNLOAD_CLIENT == "sabnzbd":
        return f"SABnzbd {(await _sabnzbd(session, {'mode': 'version'})).get('version', '?')}"
    return "via Prowlarr"


async def send(session, release):
    """Hand one release to the download client."""
    if config.DOWNLOAD_CLIENT == "prowlarr":
        await prowlarr_grab(session, release)
        return
    nzb = await prowlarr_nzb(session, release)
    name = nzb_filename(release["title"])
    if config.DOWNLOAD_CLIENT == "nzbget":
        result = await _nzbget(session, "append", [
            name, base64.b64encode(nzb).decode(), config.DOWNLOAD_CATEGORY,
            0, False, False, "", 0, "SCORE", []])
        if not result or result <= 0:
            raise ServiceError("NZBGet heeft de NZB geweigerd")
    else:
        await _sabnzbd(session, {"mode": "addfile", "cat": config.DOWNLOAD_CATEGORY,
                                 "nzbname": name[:-4]}, nzb=(name, nzb))
