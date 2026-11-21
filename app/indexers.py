"""Where releases are found: a Prowlarr with its own indexers, or a Newznab (usenet) or Torznab
(torrent) indexer that is asked directly.

Every release comes back in one shape, whatever found it:
    guid, title, size, indexer (its name), source (id of the entry in the settings), protocol
    ("usenet" or "torrent"), seeders (torrents only), published (ISO date), downloadUrl,
    infoUrl, grabs, and for a Prowlarr: indexerId (the id Prowlarr has for the indexer).
"""
import asyncio
import email.utils
import ipaddress
import socket
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlsplit, urlunsplit

import config
from clients import LARGE, LONG, SHORT, ServiceError, _check, _json, _read, _wrap

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
ATTR = ("{http://www.newznab.com/DTD/2010/feeds/attributes/}attr", "{http://torznab.com/schemas/2015/feed}attr")


def by_id(source):
    """The entry of the settings a release was found by, enabled or not; None if it is gone."""
    return next((i for i in config.providers("INDEXERS") if i["id"] == source), None)


def in_categories(category, wanted):
    """Is a Newznab category one of the wanted ones? A main category (1000 = Console) covers
    its subcategories (1010-1990)."""
    for number in wanted:
        number = int(number)
        if category == number or (number % 1000 == 0 and number < category < number + 1000):
            return True
    return False


def filed_right(categories, wanted):
    """Is a release with these categories one to look at? The indexer already searches in
    the wanted categories only; this holds it to that. And Console (1000) also covers PS4,
    Xbox and the rest: a release filed under one of those is not ours."""
    if categories and not any(in_categories(c, wanted) for c in categories):
        return False
    return not any(c in OTHER_CONSOLES and str(c) not in wanted for c in categories)


# ---------------------------------------------------------------- prowlarr


def _key(indexer):
    return {"X-Api-Key": indexer.get("api_key", "")}


async def _prowlarr_indexers(session, indexer):
    try:
        async with session.get(f"{indexer['url']}/api/v1/indexer", headers=_key(indexer), timeout=SHORT) as r:
            await _check(r, "Prowlarr")
            found = await _json(r)
    except Exception as e:
        raise _wrap("Prowlarr", e) from e
    return [i for i in found if isinstance(i, dict)] if isinstance(found, list) else []


async def _prowlarr_status(session, indexer):
    """Version of Prowlarr and how many of its indexers can be searched."""
    if not indexer.get("api_key"):
        raise ServiceError("Prowlarr: fill in the API key")
    try:
        async with session.get(f"{indexer['url']}/api/v1/system/status", headers=_key(indexer), timeout=SHORT) as r:
            await _check(r, "Prowlarr")
            version = (await _json(r)).get("version", "?")
    except Exception as e:
        raise _wrap("Prowlarr", e) from e
    enabled = [i for i in await _prowlarr_indexers(session, indexer) if i.get("enable")]
    usenet = sum(1 for i in enabled if str(i.get("protocol", "")).lower() == "usenet")
    torrent = sum(1 for i in enabled if str(i.get("protocol", "")).lower() == "torrent")
    usable = usenet + (torrent if config.wants_torrents() else 0)
    if not usable:
        raise ServiceError("Prowlarr: no enabled usenet indexer found" if not torrent else
                           "Prowlarr: only torrent indexers, and there is no download client for torrents")
    parts = [f"{usenet} usenet indexer{'s' if usenet != 1 else ''}"]
    if torrent:
        parts.append(f"{torrent} torrent indexer{'s' if torrent != 1 else ''}"
                     + ("" if config.wants_torrents() else " (not searched: no torrent client)"))
    return f"Prowlarr {version}, " + ", ".join(parts)


async def priorities(session, indexer):
    """{id Prowlarr has for an indexer: its priority}; a lower number goes first."""
    return {i["id"]: int(i.get("priority") or 25) for i in await _prowlarr_indexers(session, indexer) if "id" in i}


async def _prowlarr_search(session, indexer, query):
    params = [("query", query), ("type", "search"), ("limit", "100"), ("offset", "0")]
    params += [("categories", c) for c in indexer["categories"]]
    # -1 is Prowlarr's shorthand for "all usenet indexers" (-2 is all torrent indexers). With a
    # torrent client set up nothing is passed: Prowlarr then searches every indexer it has.
    chosen = config.PROWLARR_INDEXER_IDS or ([] if config.wants_torrents() else ["-1"])
    params += [("indexerIds", i) for i in chosen]
    try:
        async with session.get(f"{indexer['url']}/api/v1/search", params=params, headers=_key(indexer),
                               timeout=LONG) as r:
            await _check(r, "Prowlarr")
            data = await _json(r, LARGE)
    except Exception as e:
        raise _wrap("Prowlarr", e) from e
    releases = []
    for item in data if isinstance(data, list) else []:
        protocol = str(item.get("protocol", "usenet")).lower()
        if protocol not in ("usenet", "torrent") or not item.get("guid") or not item.get("title"):
            continue
        if protocol == "torrent" and not config.wants_torrents():
            continue  # nothing could take it
        categories = [c.get("id") for c in item.get("categories") or [] if isinstance(c, dict)]
        if not filed_right(categories, indexer["categories"]):
            continue
        releases.append({
            "guid": item["guid"], "title": item["title"], "size": item.get("size") or 0,
            "indexer": item.get("indexer") or "", "indexerId": item.get("indexerId"),
            "source": indexer["id"], "protocol": protocol, "seeders": item.get("seeders"),
            "published": item.get("publishDate") or "",
            "downloadUrl": item.get("downloadUrl") or item.get("magnetUrl") or "",
            "infoUrl": item.get("infoUrl") or "", "grabs": item.get("grabs") or 0,
        })
    return releases


def _via_prowlarr(indexer, download_url):
    """Prowlarr builds download links from the address it was called on. Point them at the
    address in the settings so they also work when that differs (reverse proxy, other network)."""
    base, link = urlsplit(indexer["url"]), urlsplit(download_url)
    return urlunsplit((base.scheme, base.netloc, link.path, link.query, ""))


async def grab(session, release):
    """Let Prowlarr send the release to the download client configured in Prowlarr itself."""
    indexer = by_id(release.get("source"))
    if indexer is None or indexer["type"] != "prowlarr":
        raise ServiceError("The download client of Prowlarr only takes what Prowlarr found")
    body = {"guid": release["guid"], "indexerId": release["indexerId"]}
    try:
        async with session.post(f"{indexer['url']}/api/v1/search", json=body, headers=_key(indexer),
                                timeout=LONG) as r:
            if r.status == 404:
                raise ServiceError("Prowlarr no longer knows this release; search again and retry")
            await _check(r, "Prowlarr")
    except Exception as e:
        raise _wrap("Prowlarr", e) from e


# ---------------------------------------------------------------- newznab and torznab


def _api(indexer):
    address = indexer["url"]
    return address if address.endswith("/api") else address + "/api"


async def _newznab(session, indexer, params):
    """One call to the API of a Newznab or Torznab indexer. Returns the root of its XML."""
    name = indexer["name"]
    params = {**params, "apikey": indexer.get("api_key", "")}
    try:
        async with session.get(_api(indexer), params=params, timeout=LONG) as r:
            await _check(r, name)
            root = ET.fromstring(await _read(r, LARGE))
    except ET.ParseError as e:
        raise ServiceError(f"{name}: the answer is not the XML of a Newznab indexer") from e
    except Exception as e:
        raise _wrap(name, e) from e
    if root.tag == "error":
        # <error code="100" description="Incorrect user credentials"/>
        raise ServiceError(f"{name}: {root.get('description') or 'error ' + str(root.get('code'))}")
    return root


async def _newznab_status(session, indexer):
    root = await _newznab(session, indexer, {"t": "caps"})
    server = root.find("server")
    # The capabilities are open to everyone; a search shows whether the key is right.
    await _newznab(session, indexer, {"t": "search", "q": "nswhunter connection test", "limit": "1",
                                      "cat": ",".join(indexer["categories"])})
    title = (server.get("title") if server is not None else "") or indexer["name"]
    return f"{title}, the API key is right"


async def _newznab_search(session, indexer, query):
    params = {"t": "search", "cat": ",".join(indexer["categories"]), "limit": "100", "extended": "1"}
    if query:
        params["q"] = query
    root = await _newznab(session, indexer, params)
    protocol = config.PROVIDERS["INDEXERS"][indexer["type"]]["protocol"]
    releases = []
    for item in root.iter("item"):
        attrs = {}
        categories = []
        for attr in [a for tag in ATTR for a in item.findall(tag)]:
            if attr.get("name") == "category" and str(attr.get("value", "")).isdigit():
                categories.append(int(attr.get("value")))
            else:
                attrs[attr.get("name")] = attr.get("value")
        enclosure = item.find("enclosure")
        link = (enclosure.get("url") if enclosure is not None else "") or item.findtext("link") or ""
        if protocol == "torrent" and not link:
            link = attrs.get("magneturl") or ""
        title, guid = item.findtext("title") or "", item.findtext("guid") or link
        if not title or not guid or not filed_right(categories, indexer["categories"]):
            continue
        try:
            published = email.utils.parsedate_to_datetime(item.findtext("pubDate") or "").isoformat()
        except (TypeError, ValueError):
            published = ""
        size = attrs.get("size") or (enclosure.get("length") if enclosure is not None else 0) or 0
        releases.append({
            "guid": guid, "title": title, "size": int(size) if str(size).isdigit() else 0,
            "indexer": indexer["name"], "indexerId": None, "source": indexer["id"], "protocol": protocol,
            "seeders": int(attrs["seeders"]) if str(attrs.get("seeders", "")).isdigit() else None,
            "published": published, "downloadUrl": urljoin(indexer["url"] + "/", link),
            "infoUrl": item.findtext("comments") or "", "grabs": int(attrs["grabs"]) if str(attrs.get("grabs", "")).isdigit() else 0,
            # A direct indexer has the priority it was given in the settings.
            "priority": indexer.get("priority", 25),
        })
    return releases


# ---------------------------------------------------------------- whatever the type


async def status(session, indexer):
    """A short text that says the indexer answers and the key is right. Else a ServiceError."""
    return await (_prowlarr_status if indexer["type"] == "prowlarr" else _newznab_status)(session, indexer)


async def search(session, indexer, query):
    """Releases of one indexer for a query; an empty query gives its newest posts."""
    if indexer["type"] == "prowlarr":
        return await _prowlarr_search(session, indexer, query)
    if indexer["type"] == "torznab" and not config.wants_torrents():
        return []  # nothing could take what it finds
    return await _newznab_search(session, indexer, query)


async def search_all(session, query):
    """Ask every enabled indexer at once. Returns (releases, {indexer id: what went wrong}):
    one indexer that does not answer does not cost the releases of the others."""
    asked = config.indexers()
    results = await asyncio.gather(*(search(session, i, query) for i in asked), return_exceptions=True)
    releases, errors = [], {}
    for indexer, result in zip(asked, results):
        if isinstance(result, ServiceError):
            errors[indexer["id"]] = str(result)
        elif isinstance(result, Exception):
            errors[indexer["id"]] = f"{indexer['name']}: {result!r}"
        else:
            releases += result
    return releases, errors


def _place(address):
    """(host, port) of an http(s) address, the port filled in."""
    parts = urlsplit(address)
    return (parts.hostname or "").lower(), parts.port or (443 if parts.scheme == "https" else 80)


async def _inside(host, port):
    """Is this host an address of your own network or of this machine?"""
    try:
        found = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except OSError:
            return False  # the request itself fails and says why
        found = [ipaddress.ip_address(info[4][0].split("%")[0]) for info in infos]
    return any(not ip.is_global for ip in found)


async def _allowed(address):
    """A download link may point into your own network only at an indexer of the settings:
    a hostile indexer must not make NSWHunter call other services of the network."""
    # shortcut: the name is resolved again for the request itself, so a name that changes its
    # address in between (DNS rebinding) gets through; a resolver of our own would close that.
    host, port = _place(address)
    if (host, port) in {_place(i["url"]) for i in config.providers("INDEXERS")}:
        return
    if await _inside(host, port):
        raise ServiceError(f"The download link points into your own network, at {host}:{port}, "
                           "and that is not the address of an indexer in the settings")


async def fetch(session, release):
    """Get what a download client needs of a release: ("nzb", bytes) for usenet, and for a
    torrent ("file", the .torrent as bytes) or ("magnet", the magnet link)."""
    address = release.get("downloadUrl") or ""
    indexer = by_id(release.get("source"))
    if indexer is not None and indexer["type"] == "prowlarr" and address.startswith(("http://", "https://")):
        address = _via_prowlarr(indexer, address)
    torrent = release.get("protocol") == "torrent"
    name = release.get("indexer") or (indexer["name"] if indexer else "the indexer")
    through = f" through {indexer['name']}" if indexer and indexer["type"] == "prowlarr" and indexer["name"] != name else ""
    what = f"Fetching the {'torrent' if torrent else 'NZB'} from {name}{through}"
    for _ in range(6):  # a link to a torrent often leads on to a magnet link
        if torrent and address.startswith("magnet:"):
            return "magnet", address
        if not address.startswith(("http://", "https://")):
            raise ServiceError("The indexer gave no download link for this release")
        try:
            await _allowed(address)
            async with session.get(address, timeout=LONG, allow_redirects=False) as r:
                if r.status in (301, 302, 303, 307, 308) and r.headers.get("Location"):
                    address = urljoin(address, r.headers["Location"])
                    continue
                await _check(r, what)
                data = await _read(r, LARGE)
        except Exception as e:
            raise _wrap(what, e) from e
        if not torrent:
            if b"<nzb" not in data[:4000].lower():
                raise ServiceError(f"{what}: the answer is not an NZB file")
            return "nzb", data
        if data[:7] == b"magnet:":
            return "magnet", data.decode("utf-8", "replace").strip()
        if data[:1] != b"d":  # a .torrent file is a bencoded dictionary
            raise ServiceError(f"{what}: the answer is not a torrent file")
        return "file", data
    raise ServiceError(f"{what}: the link keeps leading on to another one")
