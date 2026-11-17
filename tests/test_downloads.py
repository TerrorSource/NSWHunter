"""A torrent from the search to the torrent client and back: the whole way, with stand-ins."""
import pytest
from aiohttp.test_utils import TestServer

import config
import torrent
from fake_torrents import make_torrent_fakes
from fakes import MAGNET, TORRENT
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
