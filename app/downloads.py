"""Handing a release to a download client, asking the clients how the downloads are doing, and
taking a download out of a client again."""
import asyncio
import base64
import re

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
    try:
        what, content = await indexers.fetch(session, release)
    except ServiceError as e:
        raise clients.IndexerError(str(e)) from e
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


def _megabytes(value):
    """Megabytes as a client gives them (a number, or a number as text) in bytes; None if not."""
    try:
        return int(float(value) * 2**20) if float(value) > 0 else None
    except (TypeError, ValueError):
        return None


def _clock(text):
    """The time left as SABnzbd writes it, "0:12:34" or with days in front "1:02:03:04", in
    seconds; None if it is not that."""
    parts = str(text or "").split(":")
    if not 3 <= len(parts) <= 4 or not all(p.isdigit() for p in parts):
        return None
    seconds = 0
    for part, worth in zip(reversed(parts), (1, 60, 3600, 86400)):
        seconds += int(part) * worth
    return seconds


async def _states(session, client):
    """{the client's id for a download: {"state": "downloading" | "done" | "failed",
    "percent": 0-100 or None, "path": text or None, "size": bytes or None, "left": seconds or
    None}} of what one client has in its queue and its history. path: the folder or file of a
    download that is done, as the client itself names it; None if it is not done or the client
    does not say. left: how long the download still takes at the speed of this moment; None if
    it is done, paused, or the client does not say."""
    kind = client["type"]
    states = {}
    if kind == "nzbget":
        for entry in await clients.nzbget(session, client, "history", [False]) or []:
            status_ = str(entry.get("Status", ""))
            # SUCCESS/ALL, WARNING/HEALTH: the files are there. FAILURE/PAR, DELETED/MANUAL: not.
            done = status_.startswith(("SUCCESS", "WARNING"))
            # FinalDir is only filled when a post-processing script moved the files out of DestDir.
            # A failed one has only its working folder ("Game.#1213"): Remove Failed clears it.
            path = (entry.get("FinalDir") if done else None) or entry.get("DestDir")
            states[str(entry.get("NZBID"))] = {"state": "done" if done else "failed", "percent": None,
                                               "path": path if isinstance(path, str) and path else None,
                                               "size": _megabytes(entry.get("FileSizeMB")), "left": None}
        groups = await clients.nzbget(session, client, "listgroups", [0]) or []
        rate = 0
        if groups:
            # The speed is one number for the whole queue, and the queue is done from the top:
            # a download is ready when everything above it and it itself are in.
            try:
                told = await clients.nzbget(session, client, "status", []) or {}
                rate = 0 if told.get("DownloadPaused") else int(told.get("DownloadRate") or 0)
            except (ServiceError, TypeError, ValueError, AttributeError):
                rate = 0
        ahead = 0
        for entry in groups:
            total, left = entry.get("FileSizeMB"), entry.get("RemainingSizeMB")
            known = isinstance(total, (int, float)) and isinstance(left, (int, float))
            ahead += left * 2**20 if known else 0
            states[str(entry.get("NZBID"))] = {
                "state": "downloading", "percent": _percent(total - left, total) if known else None, "path": None,
                "size": _megabytes(total), "left": int(ahead / rate) if known and rate > 0 else None}
    elif kind == "sabnzbd":
        history = await clients.sabnzbd(session, client, {"mode": "history", "limit": "300"})
        for slot in (history.get("history") or {}).get("slots") or []:
            status_, path = str(slot.get("status", "")), slot.get("storage")
            done = status_ == "Completed"
            size = slot.get("bytes")
            states[str(slot.get("nzo_id"))] = {
                "state": "done" if done else "failed" if status_ == "Failed" else "downloading",
                "percent": None, "path": path if done and isinstance(path, str) and path else None,
                "size": size if isinstance(size, int) and size > 0 else None, "left": None}
        queue = await clients.sabnzbd(session, client, {"mode": "queue"})
        for slot in (queue.get("queue") or {}).get("slots") or []:
            # A job that is paused or waits its turn has a time left that says nothing.
            going = str(slot.get("status", "")) == "Downloading"
            states[str(slot.get("nzo_id"))] = {
                "state": "downloading", "percent": _percent(slot.get("percentage"), 100), "path": None,
                "size": _megabytes(slot.get("mb")), "left": _clock(slot.get("timeleft")) if going else None}
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


async def remove(session, client, download_id, delete_files=True):
    """Take one download out of its client, from the queue or from the history. download_id:
    the id `send` returned. delete_files: also delete what it downloaded. Returns nothing. A
    download the client no longer knows is no error: it is gone, which is what was asked."""
    kind = client["type"]
    if kind == "prowlarr":
        raise ServiceError("A download that went through Prowlarr can only be removed in the download client itself")
    if not download_id:
        raise ServiceError(f"{client['name']} gave no id for this download, so it cannot be removed from here")
    if kind in torrent.TYPES:
        await torrent.remove(session, client, download_id, delete_files)
        return
    download_id = str(download_id)
    # The queue first and then the history: a download only moves from the first to the second,
    # so it cannot slip between the two calls. Where it is not, the client says so without error.
    if kind == "nzbget":
        if not re.fullmatch(r"[0-9]{1,9}", download_id):
            raise ServiceError("NZBGet: this is not the id of a download")
        # The Final commands delete for good. Without them GroupDelete moves the download to
        # the history, and HistoryDelete then takes it out of sight there.
        commands = ("GroupFinalDelete", "HistoryFinalDelete") if delete_files else ("GroupDelete", "HistoryDelete")
        for command in commands:
            # (command, offset, text, ids): the form of before NZBGet 18, where the offset was
            # still needed. Later versions do not use it, but take it.
            await clients.nzbget(session, client, "editqueue", [command, 0, "", [int(download_id)]])
    elif kind == "sabnzbd":
        # Only one job: "all" or a list with commas in its place would delete more.
        if not re.fullmatch(r"SABnzbd_nzo_\w+", download_id):
            raise ServiceError("SABnzbd: this is not the id of a download")
        for mode in ("queue", "history"):
            await clients.sabnzbd(session, client, {"mode": mode, "name": "delete", "value": download_id,
                                                    "del_files": "1" if delete_files else "0"}, strict=False)
    else:
        raise ServiceError(f"Unknown download client: {kind}")
