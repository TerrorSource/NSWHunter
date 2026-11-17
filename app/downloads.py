"""Handing a release to a download client, and asking the clients how the downloads are doing."""
import asyncio
import base64

import clients
import config
import indexers
import torrent
from clients import ServiceError, _percent


async def status(session, client):
    """A short text that says the client answers and the login is right. Else a ServiceError."""
    kind = client["type"]
    if kind == "nzbget":
        return f"NZBGet {await clients.nzbget(session, client, 'version', [])}"
    if kind == "sabnzbd":
        # mode=version answers without a key, so ask for something that needs one.
        await clients.sabnzbd(session, client, {"mode": "get_cats"})
        return "SABnzbd, the API key is right"
    if kind in torrent.TYPES:
        return await torrent.status(session, client)
    # The download client of Prowlarr: every Prowlarr in the list has to have one.
    found = [i for i in config.indexers() if i["type"] == "prowlarr"]
    if not found:
        raise ServiceError("There is no Prowlarr among the indexers (Settings > Indexers)")
    names = []
    for indexer in found:
        try:
            async with session.get(f"{indexer['url']}/api/v1/downloadclient",
                                   headers={"X-Api-Key": indexer.get("api_key", "")}, timeout=clients.SHORT) as r:
                await clients._check(r, "Prowlarr")
                names += [c.get("name", "?") for c in await clients._json(r) if c.get("enable")]
        except Exception as e:
            raise clients._wrap("Prowlarr", e) from e
    if not names:
        raise ServiceError("Prowlarr has no enabled download client (Settings > Download Clients)")
    return "via Prowlarr: " + ", ".join(names)


async def send(session, release):
    """Hand one release to the download client that takes its protocol. Returns (the client,
    the client's own id for the download); the id is None if the client gives none."""
    protocol = release.get("protocol") or "usenet"
    source = indexers.by_id(release.get("source"))
    client = config.client_for(protocol, source["type"] if source else "")
    if client is None:
        raise ServiceError(f"There is no download client for {protocol} releases (Settings > Download Clients)")
    kind = client["type"]
    if kind == "prowlarr":
        await indexers.grab(session, release)
        return client, None
    what, content = await indexers.fetch(session, release)
    if kind in torrent.TYPES:
        return client, await torrent.add(session, client, what, content)
    name = clients.nzb_filename(release["title"])
    if kind == "nzbget":
        result = await clients.nzbget(session, client, "append", [
            name, base64.b64encode(content).decode(), client.get("category", ""),
            0, False, False, "", 0, "SCORE", []])
        if not result or result <= 0:
            raise ServiceError("NZBGet refused the NZB")
        return client, str(result)
    answer = await clients.sabnzbd(session, client, {"mode": "addfile", "cat": client.get("category", ""),
                                                     "nzbname": name[:-4]}, nzb=(name, content))
    ids = answer.get("nzo_ids") or []
    return client, str(ids[0]) if ids else None


async def _states(session, client):
    """{the client's id for a download: {"state": "downloading" | "done" | "failed",
    "percent": 0-100 or None}} of what one client has in its queue and its history."""
    kind = client["type"]
    states = {}
    if kind == "nzbget":
        for entry in await clients.nzbget(session, client, "history", [False]) or []:
            status_ = str(entry.get("Status", ""))
            # SUCCESS/ALL, WARNING/HEALTH: the files are there. FAILURE/PAR, DELETED/MANUAL: not.
            done = status_.startswith(("SUCCESS", "WARNING"))
            states[str(entry.get("NZBID"))] = {"state": "done" if done else "failed", "percent": None}
        for entry in await clients.nzbget(session, client, "listgroups", [0]) or []:
            total, left = entry.get("FileSizeMB"), entry.get("RemainingSizeMB")
            percent = _percent(total - left, total) if isinstance(total, (int, float)) and isinstance(
                left, (int, float)) else None
            states[str(entry.get("NZBID"))] = {"state": "downloading", "percent": percent}
    elif kind == "sabnzbd":
        history = await clients.sabnzbd(session, client, {"mode": "history", "limit": "300"})
        for slot in (history.get("history") or {}).get("slots") or []:
            status_ = str(slot.get("status", ""))
            states[str(slot.get("nzo_id"))] = {
                "state": "done" if status_ == "Completed" else "failed" if status_ == "Failed" else "downloading",
                "percent": None}
        queue = await clients.sabnzbd(session, client, {"mode": "queue"})
        for slot in (queue.get("queue") or {}).get("slots") or []:
            states[str(slot.get("nzo_id"))] = {
                "state": "downloading", "percent": _percent(slot.get("percentage"), 100)}
    elif kind in torrent.TYPES:
        states = await torrent.states(session, client)
    return states  # the download client of Prowlarr tells nothing back


async def states(session, only=None):
    """Ask every download client (or only those with an id in `only`) what it has. Returns
    ({client id: {download id: state}}, {client id: what went wrong}). A client that does not
    answer is in the second: nothing may be concluded about its downloads."""
    asked = [c for c in config.providers("DOWNLOAD_CLIENTS") if only is None or c["id"] in only]
    results = await asyncio.gather(*(_states(session, c) for c in asked), return_exceptions=True)
    known, errors = {}, {}
    for client, result in zip(asked, results):
        if isinstance(result, ServiceError):
            errors[client["id"]] = str(result)
        elif isinstance(result, Exception):
            errors[client["id"]] = f"{client['name']}: {result!r}"
        else:
            known[client["id"]] = result
    return known, errors
