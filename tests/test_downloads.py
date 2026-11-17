"""A torrent from the search to the torrent client and back: the whole way, with stand-ins.
And taking a download out of each kind of download client again."""
import asyncio

import aiohttp
import pytest
from aiohttp.test_utils import TestServer

import config
import downloads
import torrent
from clients import ServiceError
from fake_torrents import PASSWORD, USER, make_torrent_fakes
from fakes import MAGNET, TORRENT, make_fakes
from test_hunter import HADES, HOLLOW, providers, run, titles
from test_indexers import TOR

PROWLARR = providers("BASE")["INDEXERS"][0]


def with_torrent_client(kind, test):
    """Run `test(hunter, fakes, torrents)` with a torrent client of this kind next to NZBGet."""
    path = {"qbittorrent": "/qbt", "transmission": "/tr", "utorrent": "/ut"}[kind]

    async def body(hunter, fakes):
        clients = make_torrent_fakes()
        server = TestServer(clients)
        await server.start_server()
        saved = config.DOWNLOAD_CLIENTS
        config.DOWNLOAD_CLIENTS = saved + [{
            "id": "tc", "type": kind, "name": torrent.LABELS[kind], "enabled": True,
            "url": str(server.make_url("")).rstrip("/") + path, "username": "tester", "password": "torrent-test",
            "category": "games"}]
        try:
            await test(hunter, fakes, clients["torrents"][kind])
        finally:
            config.DOWNLOAD_CLIENTS = saved
            await server.close()
    run(body, INDEXERS=[PROWLARR, TOR])


@pytest.mark.parametrize("kind", torrent.TYPES)
def test_a_torrent_goes_to_the_torrent_client_and_is_followed(kind):
    async def test(hunter, fakes, torrents):
        await hunter.round()
        assert all(s["ok"] for s in hunter.state["services"].values())
        # With a torrent client Prowlarr is asked for every indexer, and the Torznab indexer joins.
        assert fakes["indexer_ids"][0] == []
        found = {c["title"]: c for c in hunter.state["items"][HADES]["candidates"]}
        assert "Hades_Update_v1.0.2_NSW-GRP" in found  # usenet is still there
        direct, through = found["Hades Update v131072 NSW-TORGRP"], found["Hades Update v131072"]
        assert (direct["protocol"], direct["seeders"], direct["indexer"], direct["priority"]) == ("torrent", 12, "FakeTor", 30)
        assert (through["protocol"], through["seeders"], through["indexer"]) == ("torrent", 5, "Tracker")
        # A torrent file: the client gets it in the category, and its hash is what it is known by.
        await hunter.grab(HADES, direct["guid"])
        grab = hunter.state["items"][HADES]["grab"]
        assert (grab["client"], grab["client_name"], grab["client_id"]) == ("tc", torrent.LABELS[kind], torrent.info_hash(TORRENT))
        assert torrents[grab["client_id"]]["category"] == "games" and fakes["sent"] == []
        # A link that leads on to a magnet link: the magnet goes to the client.
        hollow = hunter.state["items"][HOLLOW]["candidates"][0]
        assert hollow["title"] == "Hollow Knight Update v131072 NSW-TORGRP" and hollow["seeders"] == 0
        await hunter.grab(HOLLOW, hollow["guid"])
        magnet = torrent.magnet_hash(MAGNET)
        assert hunter.state["items"][HOLLOW]["grab"]["client_id"] == magnet and magnet in torrents
        # How far it is, as the client says.
        torrents[grab["client_id"]]["progress"] = 0.42
        await hunter.watch()
        assert (grab["state"], grab["percent"]) == ("downloading", 42)
        torrents[grab["client_id"]]["progress"] = 1.0
        torrents[magnet]["error"] = True
        await hunter.watch()
        assert grab["state"] == "done" and len(fakes["rescans"]) == 1
        # The one with an error is a failed download; the next release of that game gets its turn.
        item = hunter.state["items"][HOLLOW]
        assert item["grab"] is None and [f["title"] for f in item["failed"]] == [hollow["title"]]
    with_torrent_client(kind, test)


def test_usenet_still_goes_to_the_usenet_client():
    async def test(hunter, fakes, torrents):
        await hunter.round()
        usenet = next(c for c in hunter.state["items"][HADES]["candidates"] if c["protocol"] == "usenet")
        await hunter.grab(HADES, usenet["guid"])
        assert hunter.state["items"][HADES]["grab"]["client"] == "nz" and len(fakes["sent"]) == 1 and torrents == {}
    with_torrent_client("qbittorrent", test)


def test_a_torrent_client_that_does_not_answer_concludes_nothing():
    async def test(hunter, fakes, torrents):
        await hunter.round()
        direct = next(c for c in hunter.state["items"][HADES]["candidates"] if c["indexer"] == "FakeTor")
        await hunter.grab(HADES, direct["guid"])
        grab = hunter.state["items"][HADES]["grab"]
        grab["at"] -= 5 * 3600  # long past the waiting time
        config.DOWNLOAD_CLIENTS[-1]["url"] = "http://127.0.0.1:1"
        await hunter.watch()
        # Not "not arrived": the client could not be asked, so the download is left as it is.
        assert hunter.state["items"][HADES]["grab"] is grab and hunter.state["items"][HADES].get("failed", []) == []
        assert hunter.state["services"]["DOWNLOAD_CLIENTS:tc"]["ok"] is False
    with_torrent_client("transmission", test)


def test_without_a_client_for_the_protocol_a_release_is_refused():
    async def test(hunter, fakes, torrents):
        await hunter.round()
        direct = next(c for c in hunter.state["items"][HADES]["candidates"] if c["indexer"] == "FakeTor")
        config.DOWNLOAD_CLIENTS = [c for c in config.DOWNLOAD_CLIENTS if c["id"] != "tc"]
        with pytest.raises(Exception, match="no download client for torrent releases"):
            await hunter.grab(HADES, direct["guid"])
        assert hunter.state["items"][HADES]["grab"] is None and titles(hunter, HADES)
    with_torrent_client("qbittorrent", test)


# ---------------------------------------------------------------- removing a download

PATHS = {"qbittorrent": "/qbt", "transmission": "/tr", "utorrent": "/ut"}
NAMES = {"nzbget": "NZBGet", "sabnzbd": "SABnzbd", "prowlarr": "The download client of Prowlarr", **torrent.LABELS}
REMOVABLE = pytest.mark.parametrize("kind", ["nzbget", "sabnzbd", *torrent.TYPES])
FILES = pytest.mark.parametrize("files", [True, False], ids=["with files", "without files"])

HASH, OTHER_HASH = torrent.info_hash(TORRENT), torrent.magnet_hash(MAGNET)
SAB, OTHER_SAB = "SABnzbd_nzo_k3x9p2aa", "SABnzbd_nzo_w7m1q4bb"


def with_clients(test):
    """Run `test(session, fakes, torrents, client)` against the stand-ins, without a hunter.
    client(kind) gives a download client of that kind as the settings store it."""
    async def body():
        fakes, torrents = make_fakes(), make_torrent_fakes()
        servers = [TestServer(fakes), TestServer(torrents)]
        for server in servers:
            await server.start_server()
        base, other = (str(server.make_url("")).rstrip("/") for server in servers)
        own = {"nzbget": {"url": base, "username": "nzbget", "password": "tegen"},
               "sabnzbd": {"url": base, "api_key": "sab_test"}, "prowlarr": {},
               **{kind: {"url": other + PATHS[kind], "username": USER, "password": PASSWORD} for kind in PATHS}}

        def client(kind):
            return {"id": kind[:2] + "34ef", "type": kind, "name": NAMES[kind], "enabled": True,
                    "category": "games", **own[kind]}
        torrent._sessions.clear()
        try:
            async with aiohttp.ClientSession() as session:
                await test(session, fakes, torrents, client)
        finally:
            for server in servers:
                await server.close()
    asyncio.run(body())


async def fill(session, fakes, torrents, client, kind):
    """Give the stand-in of this kind two downloads. Returns (the id of the first, of the second)."""
    if kind == "nzbget":
        fakes["downloads"].update({"7": "queue", "8": "SUCCESS/ALL"})
        return "7", "8"
    if kind == "sabnzbd":
        fakes["sab"].update({SAB: "queue", OTHER_SAB: "Completed"})
        return SAB, OTHER_SAB
    return await torrent.add(session, client(kind), "file", TORRENT), await torrent.add(
        session, client(kind), "magnet", MAGNET)


def left(fakes, torrents, kind):
    """The ids of what the stand-in of this kind still has."""
    return set({"nzbget": fakes["downloads"], "sabnzbd": fakes["sab"]}.get(kind, torrents["torrents"].get(kind)))


async def refused(action):
    with pytest.raises(ServiceError) as error:
        await action
    return str(error.value)


@FILES
@pytest.mark.parametrize("where", ["queue", "SUCCESS/ALL", "FAILURE/PAR"])
def test_remove_from_nzbget(where, files):
    async def test(session, fakes, torrents, client):
        fakes["downloads"].update({"7": where, "8": "queue", "9": "SUCCESS/ALL"})
        assert await downloads.remove(session, client("nzbget"), "7", files) is None
        # Asked for the queue and for the history; the one where it is not finds nothing.
        commands = ("GroupFinalDelete", "HistoryFinalDelete") if files else ("GroupDelete", "HistoryDelete")
        assert fakes["removed"] == [("nzbget", command, "7") for command in commands]
        assert fakes["downloads"] == {"8": "queue", "9": "SUCCESS/ALL"}
        assert set(await downloads._states(session, client("nzbget"))) == {"8", "9"}
    with_clients(test)


@FILES
@pytest.mark.parametrize("where", ["queue", "Completed", "Failed"])
def test_remove_from_sabnzbd(where, files):
    async def test(session, fakes, torrents, client):
        fakes["sab"].update({SAB: where, OTHER_SAB: where})
        assert await downloads.remove(session, client("sabnzbd"), SAB, files) is None
        assert fakes["removed"] == [("sabnzbd", "queue", SAB, files), ("sabnzbd", "history", SAB, files)]
        assert fakes["sab"] == {OTHER_SAB: where}
        assert set(await downloads._states(session, client("sabnzbd"))) == {OTHER_SAB}
    with_clients(test)


@FILES
@pytest.mark.parametrize("kind", torrent.TYPES)
def test_remove_from_a_torrent_client(kind, files):
    async def test(session, fakes, torrents, client):
        await fill(session, fakes, torrents, client, kind)
        assert await downloads.remove(session, client(kind), HASH, files) is None
        assert torrents["removed"] == [(kind, HASH, files)] and fakes["removed"] == []
        assert left(fakes, torrents, kind) == {OTHER_HASH}
        assert set(await downloads._states(session, client(kind))) == {OTHER_HASH}
    with_clients(test)


@REMOVABLE
def test_remove_takes_the_files_along_unless_told_otherwise(kind):
    async def test(session, fakes, torrents, client):
        first, second = await fill(session, fakes, torrents, client, kind)
        await downloads.remove(session, client(kind), first)
        assert left(fakes, torrents, kind) == {second}
        assert (fakes["removed"] + torrents["removed"])[0] == {
            "nzbget": ("nzbget", "GroupFinalDelete", "7"), "sabnzbd": ("sabnzbd", "queue", SAB, True),
        }.get(kind, (kind, HASH, True))
    with_clients(test)


@REMOVABLE
@pytest.mark.parametrize("missing", [None, ""])
def test_remove_without_an_id_is_refused(kind, missing):
    async def test(session, fakes, torrents, client):
        both = await fill(session, fakes, torrents, client, kind)
        assert await refused(downloads.remove(session, client(kind), missing)) == (
            f"{NAMES[kind]} gave no id for this download, so it cannot be removed from here")
        assert fakes["removed"] == torrents["removed"] == [] and left(fakes, torrents, kind) == set(both)
    with_clients(test)


@pytest.mark.parametrize("download_id", [None, "", "7"])
def test_remove_of_what_went_through_prowlarr_is_refused(download_id):
    async def test(session, fakes, torrents, client):
        fakes["downloads"]["7"] = "queue"
        assert await refused(downloads.remove(session, client("prowlarr"), download_id)) == (
            "A download that went through Prowlarr can only be removed in the download client itself")
        assert fakes["removed"] == torrents["removed"] == [] and fakes["downloads"] == {"7": "queue"}
    with_clients(test)


@REMOVABLE
@FILES
def test_remove_what_the_client_no_longer_knows_is_no_error(kind, files):
    async def test(session, fakes, torrents, client):
        first, second = await fill(session, fakes, torrents, client, kind)
        # Removed once, and then again: the second time the client does not know it any more.
        await downloads.remove(session, client(kind), first, files)
        asked = len(fakes["removed"] + torrents["removed"])
        assert await downloads.remove(session, client(kind), first, files) is None
        assert len(fakes["removed"] + torrents["removed"]) == 2 * asked
        # And one it never had.
        never = {"nzbget": "999", "sabnzbd": "SABnzbd_nzo_never000"}.get(kind, "0123456789abcdef0123456789abcdef01234567")
        assert await downloads.remove(session, client(kind), never, files) is None
        assert left(fakes, torrents, kind) == {second}
    with_clients(test)


@REMOVABLE
def test_remove_refuses_an_id_that_could_mean_more_than_one_download(kind):
    async def test(session, fakes, torrents, client):
        both = await fill(session, fakes, torrents, client, kind)
        # "all" is every download to SABnzbd and to qBittorrent; a list is several.
        for wrong in ("all", "7,8", "7 8", f"{SAB},{OTHER_SAB}", f"{HASH}|{OTHER_HASH}", "failed", "-1"):
            assert "this is not the id of a" in await refused(downloads.remove(session, client(kind), wrong)), wrong
        assert fakes["removed"] == torrents["removed"] == [] and left(fakes, torrents, kind) == set(both)
    with_clients(test)


@REMOVABLE
def test_remove_that_fails_is_an_error(kind):
    async def test(session, fakes, torrents, client):
        first, second = await fill(session, fakes, torrents, client, kind)
        wrong = {**client(kind), "password": "not-the-password", "api_key": "not-the-key"}
        message = await refused(downloads.remove(session, wrong, first))
        assert message.startswith(f"{NAMES[kind]}: ") and ("access denied" in message or "wrong username" in message)
        gone = {**client(kind), "url": "http://127.0.0.1:1"}
        assert (await refused(downloads.remove(session, gone, first))).startswith(f"{NAMES[kind]}: ")
        assert fakes["removed"] == torrents["removed"] == [] and left(fakes, torrents, kind) == {first, second}
    with_clients(test)
