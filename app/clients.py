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
        raise ServiceError(f"{what}: access denied (HTTP {response.status}). Check the API key or the login.")
    if response.status >= 400:
        body = (await response.text())[:200].strip()
        raise ServiceError(f"{what}: HTTP {response.status} {body}")


def _wrap(what, error):
    if isinstance(error, ServiceError):
        return error
    if isinstance(error, TimeoutError):
        return ServiceError(f"{what}: no answer (timeout)")
    return ServiceError(f"{what}: {error}")


# ---------------------------------------------------------------- library


async def library(session, cfg=config):
    """The export of switch-library-manager-web: one entry per game in the library.

    cfg: where the settings come from. The Test buttons pass the values of the form."""
    if not cfg.SLM_URL:
        raise ServiceError("Library: fill in the address")
    headers = {"Authorization": f"Bearer {cfg.SLM_API_KEY}"} if cfg.SLM_API_KEY else {}
    try:
        async with session.get(f"{cfg.SLM_URL}/export/library.json", headers=headers,
                               timeout=LONG) as r:
            await _check(r, "Library")
            data = await r.json(content_type=None)
    except Exception as e:
        raise _wrap("Library", e) from e
    if not isinstance(data, list):
        raise ServiceError("Library: unexpected answer (not a list)")
    return data


async def titledb_versions(session):
    """{title id: {version: "YYYY-MM-DD"}} for every Switch game, from the first address that
    answers."""
    error = ServiceError("Version list: no address set")
    for address in [a.strip() for a in config.TITLEDB_VERSIONS_URL.split(",") if a.strip()]:
        try:
            async with session.get(address, timeout=LONG) as r:
                await _check(r, "Version list")
                return await r.text()
        except Exception as e:  # noqa: BLE001
            error = _wrap("Version list", e)
    raise error


# ---------------------------------------------------------------- prowlarr


def _prowlarr_headers(cfg=config):
    return {"X-Api-Key": cfg.PROWLARR_API_KEY}


async def prowlarr_status(session, cfg=config):
    """Version of Prowlarr and how many usenet indexers it can search."""
    if not cfg.PROWLARR_URL or not cfg.PROWLARR_API_KEY:
        raise ServiceError("Prowlarr: fill in the address and the API key")
    try:
        async with session.get(f"{cfg.PROWLARR_URL}/api/v1/system/status",
                               headers=_prowlarr_headers(cfg), timeout=SHORT) as r:
            await _check(r, "Prowlarr")
            version = (await r.json(content_type=None)).get("version", "?")
        async with session.get(f"{cfg.PROWLARR_URL}/api/v1/indexer",
                               headers=_prowlarr_headers(cfg), timeout=SHORT) as r:
            await _check(r, "Prowlarr")
            indexers = await r.json(content_type=None)
    except Exception as e:
        raise _wrap("Prowlarr", e) from e
    usenet = [i for i in indexers if isinstance(i, dict)
              and str(i.get("protocol", "")).lower() == "usenet" and i.get("enable")]
    if not usenet:
        raise ServiceError("Prowlarr: no enabled usenet indexer found")
    return f"Prowlarr {version}, {len(usenet)} usenet indexer{'s' if len(usenet) != 1 else ''}"


async def prowlarr_search(session, query):
    """Usenet releases for a query; an empty query gives the newest posts of every indexer."""
    params = [("query", query), ("type", "search"), ("limit", "100"), ("offset", "0")]
    params += [("categories", c) for c in config.PROWLARR_CATEGORIES]
    # -1 is Prowlarr's shorthand for "all usenet indexers" (-2 is all torrent indexers).
    params += [("indexerIds", i) for i in (config.PROWLARR_INDEXER_IDS or ["-1"])]
    try:
        async with session.get(f"{config.PROWLARR_URL}/api/v1/search", params=params,
                               headers=_prowlarr_headers(), timeout=LONG) as r:
            await _check(r, "Prowlarr")
            data = await r.json()
    except Exception as e:
        raise _wrap("Prowlarr", e) from e
    releases = []
    for item in data if isinstance(data, list) else []:
        if str(item.get("protocol", "usenet")).lower() != "usenet" or not item.get("guid") or not item.get("title"):
            continue
        categories = [c.get("id") for c in item.get("categories") or [] if isinstance(c, dict)]
        # Prowlarr already searches in the chosen categories only; this holds it to that.
        if categories and not any(in_categories(c) for c in categories):
            continue
        # Console (1000) also covers PS4, Xbox and the rest: a release filed there is not ours.
        if any(c in OTHER_CONSOLES and str(c) not in config.PROWLARR_CATEGORIES for c in categories):
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


# The Newznab subcategories of Console that are another console than the Switch. The Switch
# has no category of its own: its releases are filed under Console or Console/Other (1090).
OTHER_CONSOLES = {
    1010,  # NDS
    1020,  # PSP
    1030,  # Wii
    1040,  # XBox
    1050,  # XBox 360
    1060,  # Wiiware
    1070,  # XBox 360 DLC
    1080,  # PS3
    1110,  # 3DS
    1120,  # PS Vita
    1130,  # WiiU
    1140,  # XBox One
    1180,  # PS4
}


def in_categories(category):
    """Is a Newznab category one of the configured ones? A main category (1000 = Console)
    covers its subcategories (1010-1990)."""
    for wanted in config.PROWLARR_CATEGORIES:
        wanted = int(wanted)
        if category == wanted or (wanted % 1000 == 0 and wanted < category < wanted + 1000):
            return True
    return False


async def prowlarr_priorities(session):
    """{indexer id: priority} as set in Prowlarr; a lower number goes first."""
    try:
        async with session.get(f"{config.PROWLARR_URL}/api/v1/indexer",
                               headers=_prowlarr_headers(), timeout=SHORT) as r:
            await _check(r, "Prowlarr")
            indexers = await r.json(content_type=None)
    except Exception as e:
        raise _wrap("Prowlarr", e) from e
    return {i["id"]: int(i.get("priority") or 25) for i in indexers if isinstance(i, dict) and "id" in i}


def _via_prowlarr(download_url):
    """Prowlarr builds download links from the address it was called on. Point them at
    PROWLARR_URL so they also work when that differs (reverse proxy, other network)."""
    base, link = urlsplit(config.PROWLARR_URL), urlsplit(download_url)
    return urlunsplit((base.scheme, base.netloc, link.path, link.query, ""))


async def prowlarr_nzb(session, release):
    if not release.get("downloadUrl"):
        raise ServiceError("Prowlarr gave no download link for this release")
    try:
        async with session.get(_via_prowlarr(release["downloadUrl"]), timeout=LONG) as r:
            await _check(r, "Fetching the NZB")
            data = await r.read()
    except Exception as e:
        raise _wrap("Fetching the NZB", e) from e
    if b"<nzb" not in data[:4000].lower():
        raise ServiceError("Fetching the NZB: the answer of the indexer is not an NZB file")
    return data


async def prowlarr_grab(session, release):
    """Let Prowlarr send the release to the download client configured in Prowlarr itself."""
    body = {"guid": release["guid"], "indexerId": release["indexerId"]}
    try:
        async with session.post(f"{config.PROWLARR_URL}/api/v1/search", json=body,
                                headers=_prowlarr_headers(), timeout=LONG) as r:
            if r.status == 404:
                raise ServiceError("Prowlarr no longer knows this release; search again and retry")
            await _check(r, "Prowlarr")
    except Exception as e:
        raise _wrap("Prowlarr", e) from e


# ---------------------------------------------------------------- download clients


def nzb_filename(title):
    return re.sub(r'[\\/:*?"<>|]+', " ", title).strip()[:180] + ".nzb"


async def _nzbget(session, method, params, cfg=config):
    if not cfg.NZBGET_URL:
        raise ServiceError("NZBGet: fill in the address")
    headers = {}
    if cfg.NZBGET_USER:
        login = f"{cfg.NZBGET_USER}:{cfg.NZBGET_PASSWORD}".encode()
        headers["Authorization"] = "Basic " + base64.b64encode(login).decode()
    try:
        async with session.post(f"{cfg.NZBGET_URL}/jsonrpc", headers=headers, timeout=LONG,
                                json={"method": method, "params": params, "id": 1}) as r:
            await _check(r, "NZBGet")
            data = await r.json(content_type=None)
    except Exception as e:
        raise _wrap("NZBGet", e) from e
    if data.get("error"):
        raise ServiceError(f"NZBGet: {data['error']}")
    return data.get("result")


async def _sabnzbd(session, fields, nzb=None, cfg=config):
    if not cfg.SABNZBD_URL or not cfg.SABNZBD_API_KEY:
        raise ServiceError("SABnzbd: fill in the address and the API key")
    form = aiohttp.FormData()
    for key, value in {**fields, "apikey": cfg.SABNZBD_API_KEY, "output": "json"}.items():
        form.add_field(key, value)
    if nzb:
        form.add_field("name", nzb[1], filename=nzb[0], content_type="application/x-nzb")
    try:
        async with session.post(f"{cfg.SABNZBD_URL}/api", data=form, timeout=LONG) as r:
            await _check(r, "SABnzbd")
            data = await r.json(content_type=None)
    except Exception as e:
        raise _wrap("SABnzbd", e) from e
    if data.get("status") is False:
        raise ServiceError(f"SABnzbd: {data.get('error', 'refused')}")
    return data


async def downloader_status(session, cfg=config):
    """Version of the download client, as a connection test."""
    if cfg.DOWNLOAD_CLIENT == "nzbget":
        return f"NZBGet {await _nzbget(session, 'version', [], cfg)}"
    if cfg.DOWNLOAD_CLIENT == "sabnzbd":
        # mode=version answers without a key, so ask for something that needs one.
        await _sabnzbd(session, {"mode": "get_cats"}, cfg=cfg)
        return "SABnzbd, the API key is right"
    await prowlarr_status(session, cfg)
    try:
        async with session.get(f"{cfg.PROWLARR_URL}/api/v1/downloadclient",
                               headers=_prowlarr_headers(cfg), timeout=SHORT) as r:
            await _check(r, "Prowlarr")
            names = [c.get("name", "?") for c in await r.json(content_type=None) if c.get("enable")]
    except Exception as e:
        raise _wrap("Prowlarr", e) from e
    if not names:
        raise ServiceError("Prowlarr has no enabled download client (Settings > Download Clients)")
    return "via Prowlarr: " + ", ".join(names)


async def send(session, release):
    """Hand one release to the download client. Returns the client's own id for the download,
    to ask later how it is doing; None if the client gives none."""
    if config.DOWNLOAD_CLIENT == "prowlarr":
        await prowlarr_grab(session, release)
        return None
    nzb = await prowlarr_nzb(session, release)
    name = nzb_filename(release["title"])
    if config.DOWNLOAD_CLIENT == "nzbget":
        result = await _nzbget(session, "append", [
            name, base64.b64encode(nzb).decode(), config.DOWNLOAD_CATEGORY,
            0, False, False, "", 0, "SCORE", []])
        if not result or result <= 0:
            raise ServiceError("NZBGet refused the NZB")
        return str(result)
    answer = await _sabnzbd(session, {"mode": "addfile", "cat": config.DOWNLOAD_CATEGORY,
                                      "nzbname": name[:-4]}, nzb=(name, nzb))
    ids = answer.get("nzo_ids") or []
    return str(ids[0]) if ids else None


async def download_states(session):
    """{client id: "downloading" | "done" | "failed"} of what the download client has in its
    queue and its history. Empty when downloads go through Prowlarr: it tells nothing back."""
    states = {}
    if config.DOWNLOAD_CLIENT == "nzbget":
        for entry in await _nzbget(session, "history", [False]) or []:
            status = str(entry.get("Status", ""))
            # SUCCESS/ALL, WARNING/HEALTH: the files are there. FAILURE/PAR, DELETED/MANUAL: not.
            states[str(entry.get("NZBID"))] = "done" if status.startswith(("SUCCESS", "WARNING")) else "failed"
        for entry in await _nzbget(session, "listgroups", [0]) or []:
            states[str(entry.get("NZBID"))] = "downloading"
    elif config.DOWNLOAD_CLIENT == "sabnzbd":
        history = await _sabnzbd(session, {"mode": "history", "limit": "300"})
        for slot in (history.get("history") or {}).get("slots") or []:
            status = str(slot.get("status", ""))
            states[str(slot.get("nzo_id"))] = (
                "done" if status == "Completed" else "failed" if status == "Failed" else "downloading")
        queue = await _sabnzbd(session, {"mode": "queue"})
        for slot in (queue.get("queue") or {}).get("slots") or []:
            states[str(slot.get("nzo_id"))] = "downloading"
    return states


async def library_rescan(session):
    """Ask switch-library-manager-web to scan its folders again. True if it will. A key with
    only "Read only" is refused; then the library is seen at its own next scan."""
    headers = {"Authorization": f"Bearer {config.SLM_API_KEY}"} if config.SLM_API_KEY else {}
    try:
        async with session.post(f"{config.SLM_URL}/sync", headers=headers, timeout=SHORT) as r:
            return r.status < 300
    except Exception:  # noqa: BLE001
        return False


async def telegram(session, text, cfg=config):
    """Send a message through the user's own Telegram bot."""
    if not cfg.TELEGRAM_BOT_TOKEN or not cfg.TELEGRAM_CHAT_ID:
        raise ServiceError("Telegram: fill in the bot token and the chat ID")
    # The address holds the token: no error may ever show it.
    address = f"{config.TELEGRAM_API_URL}/bot{cfg.TELEGRAM_BOT_TOKEN}/sendMessage"
    body = {"chat_id": cfg.TELEGRAM_CHAT_ID, "text": text[:3900], "disable_web_page_preview": True}
    try:
        async with session.post(address, json=body, timeout=SHORT) as r:
            status = r.status
            answer = await r.json(content_type=None) if status != 200 else {}
    except Exception as e:  # noqa: BLE001
        raise ServiceError("Telegram: no connection to Telegram") from e
    if status in (401, 404):
        raise ServiceError("Telegram: the bot token is wrong")
    if status != 200:
        why = str((answer or {}).get("description", f"HTTP {status}"))[:120]
        raise ServiceError(f"Telegram refuses the message: {why}. Is the chat ID right, and did you send the bot a message yet?")
    return "Test message sent"
