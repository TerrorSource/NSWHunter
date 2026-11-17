"""What every talk with a service shares, the library, and the two usenet download clients.
The indexers are in indexers.py, the torrent clients in torrent.py, sending in downloads.py."""
import base64
import json
import re
from urllib.parse import urlsplit, urlunsplit

import aiohttp

import config

SHORT = aiohttp.ClientTimeout(total=30)
LONG = aiohttp.ClientTimeout(total=180)  # a Prowlarr search waits for the slowest indexer
# No answer may be bigger than this: a service that sends without end must not fill the memory.
SMALL = 2 * 2**20
LARGE = 96 * 2**20  # a library of thousands of games, the list of every update, a big NZB


class ServiceError(Exception):
    pass


async def _check(response, what):
    if response.status == 401 or response.status == 403:
        raise ServiceError(f"{what}: access denied (HTTP {response.status}). Check the API key or the login.")
    if response.status >= 400:
        body = (await response.text())[:200].strip()
        raise ServiceError(f"{what}: HTTP {response.status} {body}")


async def _read(response, limit=SMALL):
    """The body of an answer, refused when it is bigger than `limit` bytes."""
    data = bytearray()
    async for chunk in response.content.iter_chunked(65536):
        data += chunk
        if len(data) > limit:
            raise ServiceError(f"the answer is bigger than {limit // 2**20} MB")
    return bytes(data)


async def _json(response, limit=SMALL):
    try:
        return json.loads(await _read(response, limit))
    except ValueError as e:
        raise ServiceError("the answer is not JSON") from e


def _percent(done, total):
    """How far a download is, 0-100; None if that cannot be told."""
    try:
        return max(0, min(100, int(100 * float(done) / float(total)))) if float(total) > 0 else None
    except (TypeError, ValueError):
        return None


def _wrap(what, error):
    if isinstance(error, ServiceError):
        return error if str(error).startswith(what) else ServiceError(f"{what}: {error}")
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
            data = await _json(r, LARGE)
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
                return (await _read(r, LARGE)).decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001
            error = _wrap("Version list", e)
    raise error


# ---------------------------------------------------------------- download clients


def basic(username, password):
    """The header of a login by name and password."""
    return {"Authorization": "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode()}


def nzb_filename(title):
    return re.sub(r'[\\/:*?"<>|]+', " ", title).strip()[:180] + ".nzb"


async def nzbget(session, client, method, params):
    """One JSON-RPC call to an NZBGet. client: its entry of the download clients."""
    headers = {}
    if client.get("username"):
        login = f"{client['username']}:{client.get('password', '')}".encode()
        headers["Authorization"] = "Basic " + base64.b64encode(login).decode()
    try:
        async with session.post(f"{client['url']}/jsonrpc", headers=headers, timeout=LONG,
                                json={"method": method, "params": params, "id": 1}) as r:
            await _check(r, "NZBGet")
            data = await _json(r, LARGE)
    except Exception as e:
        raise _wrap("NZBGet", e) from e
    if data.get("error"):
        raise ServiceError(f"NZBGet: {data['error']}")
    return data.get("result")


async def sabnzbd(session, client, fields, nzb=None):
    """One call to the API of a SABnzbd. client: its entry of the download clients."""
    if not client.get("api_key"):
        raise ServiceError("SABnzbd: fill in the API key")
    form = aiohttp.FormData()
    for key, value in {**fields, "apikey": client["api_key"], "output": "json"}.items():
        form.add_field(key, value)
    if nzb:
        form.add_field("name", nzb[1], filename=nzb[0], content_type="application/x-nzb")
    try:
        async with session.post(f"{client['url']}/api", data=form, timeout=LONG) as r:
            await _check(r, "SABnzbd")
            data = await _json(r, LARGE)
    except Exception as e:
        raise _wrap("SABnzbd", e) from e
    if data.get("status") is False:
        raise ServiceError(f"SABnzbd: {data.get('error', 'refused')}")
    return data


async def library_rescan(session):
    """Ask switch-library-manager-web to scan its folders again. True if it will. A key with
    only "Read only" is refused; then the library is seen at its own next scan."""
    headers = {"Authorization": f"Bearer {config.SLM_API_KEY}"} if config.SLM_API_KEY else {}
    try:
        async with session.post(f"{config.SLM_URL}/sync", headers=headers, timeout=SHORT) as r:
            return r.status < 300
    except Exception:  # noqa: BLE001
        return False
