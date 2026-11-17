"""The torrent clients, against stand-ins for qBittorrent, Transmission and uTorrent."""
import asyncio
import base64
import hashlib

import aiohttp
import pytest
from aiohttp.test_utils import TestServer

import torrent
from clients import ServiceError
from fake_torrents import PASSWORD, USER, bencode, make_torrent_fakes

PATHS = {"qbittorrent": "/qbt", "transmission": "/tr", "utorrent": "/ut"}
LABELS = torrent.LABELS

HASH = "c12fe1c06bba254a9dc9f519b335aa7c1367a88a"
MAGNET = f"magnet:?xt=urn:btih:{HASH.upper()}&dn=Hades+Update+v131072&tr=http%3A%2F%2Ftracker.example%2Fannounce"
BASE32 = "magnet:?dn=Hades&xt=urn:btih:" + base64.b32encode(bytes.fromhex(HASH)).decode()

# A tiny but valid .torrent: one file of four pieces.
INFO = {"length": 1048576, "name": "Hades [0100AAAA0000A800][v131072].nsp", "piece length": 262144,
        "pieces": bytes(range(80))}
TORRENT = bencode({"announce": "http://tracker.example/announce", "creation date": 1700000000, "info": INFO})
TORRENT_HASH = hashlib.sha1(bencode(INFO)).hexdigest()

EVERY = pytest.mark.parametrize("kind", torrent.TYPES)
# Every client twice: as an older version and as the newest, where the API differs.
BOTH = pytest.mark.parametrize("modern", [False, True], ids=["old", "new"])
FILES = pytest.mark.parametrize("files", [True, False], ids=["with files", "without files"])


def run(test, modern=False):
    """Start the fake clients and run `test(session, fakes, clients)`; clients holds, per
    type, a client as the settings store it, pointed at its stand-in."""
    async def body():
        fakes = make_torrent_fakes()
        fakes["mood"]["modern"] = modern
        server = TestServer(fakes)
        await server.start_server()
        base = str(server.make_url("")).rstrip("/")
        clients = {kind: {"id": kind[:2] + "12cd", "type": kind, "name": LABELS[kind], "url": base + PATHS[kind],
                          "username": USER, "password": PASSWORD, "category": "games"} for kind in torrent.TYPES}
        torrent._sessions.clear()
        try:
            async with aiohttp.ClientSession() as session:
                await test(session, fakes, clients)
        finally:
            await server.close()
    asyncio.run(body())


async def refused(action):
    """The message of the ServiceError that `action` has to end in."""
    with pytest.raises(ServiceError) as error:
        await action
    return str(error.value)


# ---------------------------------------------------------------- status and login


@EVERY
@BOTH
def test_status_tells_the_version(kind, modern):
    expected = {
        "qbittorrent": ["qBittorrent v4.6.7", "qBittorrent v5.2.0"],
        "transmission": ["Transmission 4.0.6", "Transmission 4.1.0"],
        # The desktop edition only tells its build, the server edition its version too.
        "utorrent": ["uTorrent (build 46090)", "uTorrent 3.3 (build 46090)"],
    }

    async def test(session, fakes, clients):
        assert await torrent.status(session, clients[kind]) == expected[kind][modern]
    run(test, modern)


@EVERY
@BOTH
def test_wrong_password(kind, modern):
    async def test(session, fakes, clients):
        client = {**clients[kind], "password": "not-the-password"}
        for action in (lambda: torrent.status(session, client), lambda: torrent.states(session, client),
                       lambda: torrent.add(session, client, "magnet", MAGNET)):
            assert await refused(action()) == f"{LABELS[kind]}: wrong username or password"
        assert fakes["torrents"][kind] == {}
    run(test, modern)


@EVERY
def test_a_changed_login_does_not_ride_on_the_old_session(kind):
    async def test(session, fakes, clients):
        await torrent.status(session, clients[kind])
        # The same client, as the Test button sends it with another password filled in.
        changed = {**clients[kind], "password": "not-the-password"}
        assert await refused(torrent.status(session, changed)) == f"{LABELS[kind]}: wrong username or password"
        await torrent.status(session, clients[kind])
    run(test)


@EVERY
@BOTH
def test_one_login_serves_many_calls_and_an_expired_one_is_renewed_once(kind, modern):
    async def test(session, fakes, clients):
        client = clients[kind]
        await torrent.status(session, client)
        await torrent.states(session, client)
        assert await torrent.add(session, client, "magnet", MAGNET) == HASH
        assert fakes["logins"][kind] == 1
        fakes["expire"]()
        # The upload is the hard one to repeat: a form can be sent only once.
        assert await torrent.add(session, client, "file", TORRENT) == TORRENT_HASH
        assert fakes["logins"][kind] == 2
        fakes["expire"]()
        assert set(await torrent.states(session, client)) == {HASH, TORRENT_HASH}
        fakes["expire"]()
        await torrent.status(session, client)
        assert fakes["logins"][kind] == 4
    run(test, modern)


@EVERY
@BOTH
def test_by_host_name_where_the_cookie_jar_joins_in(kind, modern):
    async def test(session, fakes, clients):
        # For a host with a name the session keeps the cookies as well, next to the ones the
        # module carries itself: the two must not get in each other's way.
        client = {**clients[kind], "url": clients[kind]["url"].replace("127.0.0.1", "localhost")}
        await torrent.status(session, client)
        assert await torrent.add(session, client, "file", TORRENT) == TORRENT_HASH
        fakes["expire"]()
        assert set(await torrent.states(session, client)) == {TORRENT_HASH}
        assert fakes["logins"][kind] == 2
        if kind != "transmission":  # which has no cookie
            assert len(session.cookie_jar) == 1
    run(test, modern)


def test_transmission_is_spoken_to_in_the_spelling_of_its_version():
    async def test(session, fakes, clients):
        client = clients["transmission"]
        await torrent.status(session, client)
        await torrent.add(session, client, "magnet", MAGNET)
        await torrent.states(session, client)
    for modern, names in ((False, ["session-get", "torrent-add", "torrent-set", "torrent-get"]),
                          (True, ["session_get", "torrent_add", "torrent_set", "torrent_get"])):
        async def checked(session, fakes, clients, names=names):
            await test(session, fakes, clients)
            assert fakes["calls"] == [("transmission", name) for name in names]
        run(checked, modern)


# ---------------------------------------------------------------- handing over


@EVERY
@BOTH
def test_add_a_magnet(kind, modern):
    async def test(session, fakes, clients):
        assert await torrent.add(session, clients[kind], "magnet", MAGNET) == HASH
        assert fakes["torrents"][kind][HASH]["category"] == "games"
    run(test, modern)


@EVERY
def test_add_a_magnet_with_a_base32_hash(kind):
    async def test(session, fakes, clients):
        assert await torrent.add(session, clients[kind], "magnet", BASE32) == HASH
        assert set(fakes["torrents"][kind]) == {HASH}
    run(test)


@EVERY
@BOTH
def test_add_a_file(kind, modern):
    async def test(session, fakes, clients):
        assert await torrent.add(session, clients[kind], "file", TORRENT) == TORRENT_HASH
        assert fakes["torrents"][kind][TORRENT_HASH]["category"] == "games"
        assert TORRENT_HASH in await torrent.states(session, clients[kind])
    run(test, modern)


@EVERY
@BOTH
def test_without_a_category_none_is_set(kind, modern):
    async def test(session, fakes, clients):
        client = {**clients[kind], "category": ""}
        await torrent.add(session, client, "magnet", MAGNET)
        await torrent.add(session, client, "file", TORRENT)
        assert [t["category"] for t in fakes["torrents"][kind].values()] == ["", ""]
        assert not {"setprops", "torrent-set", "torrent_set"} & {name for _, name in fakes["calls"]}
    run(test, modern)


def test_transmission_3_gets_its_label_too():
    async def test(session, fakes, clients):
        fakes["mood"]["transmission3"] = True  # torrent-add ignores labels there; torrent-set knows them
        await torrent.add(session, clients["transmission"], "file", TORRENT)
        assert fakes["torrents"]["transmission"][TORRENT_HASH]["category"] == "games"
    run(test)


@EVERY
@BOTH
def test_a_torrent_the_client_already_has_is_no_error(kind, modern):
    async def test(session, fakes, clients):
        client = clients[kind]
        for content in (("magnet", MAGNET), ("file", TORRENT)):
            assert await torrent.add(session, client, *content) == await torrent.add(session, client, *content)
        assert set(fakes["torrents"][kind]) == {HASH, TORRENT_HASH}
    run(test, modern)


@EVERY
def test_what_is_no_torrent_is_not_sent(kind):
    async def test(session, fakes, clients):
        client = clients[kind]
        assert await refused(torrent.add(session, client, "file", b"<html>Login required</html>")) == (
            f"{LABELS[kind]}: this is not a torrent file")
        assert await refused(torrent.add(session, client, "magnet", "magnet:?dn=Hades")) == (
            f"{LABELS[kind]}: the magnet link has no info hash (btih)")
        assert await refused(torrent.add(session, client, "nzb", b"")) == f"{LABELS[kind]}: unknown kind of torrent: nzb"
        assert fakes["calls"] == [] and fakes["torrents"][kind] == {}
    run(test)


# ---------------------------------------------------------------- following


@EVERY
@BOTH
def test_states_follow_a_download(kind, modern):
    async def test(session, fakes, clients):
        client = clients[kind]
        assert await torrent.states(session, client) == {}
        await torrent.add(session, client, "magnet", MAGNET)
        entry = fakes["torrents"][kind][HASH]

        async def now():
            return (await torrent.states(session, client))[HASH]
        assert await now() == {"state": "downloading", "percent": 0}
        entry["progress"] = 0.427
        assert await now() == {"state": "downloading", "percent": 42}
        entry["paused"] = True
        assert await now() == {"state": "downloading", "percent": 42}
        # Complete: done, whether it seeds or was stopped after.
        entry["progress"] = 1.0
        assert await now() == {"state": "done", "percent": 100}
        entry["paused"] = False
        assert await now() == {"state": "done", "percent": 100}
        entry.update(progress=0.5, error=True)
        assert await now() == {"state": "failed", "percent": 50}
    run(test, modern)


@EVERY
def test_states_cover_every_torrent(kind):
    async def test(session, fakes, clients):
        await torrent.add(session, clients[kind], "magnet", MAGNET)
        await torrent.add(session, clients[kind], "file", TORRENT)
        fakes["torrents"][kind][TORRENT_HASH]["progress"] = 1.0
        assert await torrent.states(session, clients[kind]) == {
            HASH: {"state": "downloading", "percent": 0}, TORRENT_HASH: {"state": "done", "percent": 100}}
    run(test)


async def native(session, fakes, client, values):
    """The state the module makes of what the client reports in its own terms."""
    fakes["torrents"][client["type"]][HASH]["native"] = values
    return (await torrent.states(session, client))[HASH]


def test_qbittorrent_states():
    async def test(session, fakes, clients):
        client = clients["qbittorrent"]
        await torrent.add(session, client, "magnet", MAGNET)
        # pausedUP is what qBittorrent 4 calls stoppedUP, and the same for DL.
        for name in ("uploading", "stalledUP", "queuedUP", "forcedUP", "checkingUP", "pausedUP", "stoppedUP"):
            assert await native(session, fakes, client, {"state": name, "progress": 1}) == {
                "state": "done", "percent": 100}, name
        for name in ("error", "missingFiles"):
            assert (await native(session, fakes, client, {"state": name, "progress": 0.3}))["state"] == "failed", name
        for name in ("downloading", "metaDL", "forcedMetaDL", "stalledDL", "queuedDL", "forcedDL", "pausedDL",
                     "stoppedDL", "allocating", "moving", "unknown"):
            assert await native(session, fakes, client, {"state": name, "progress": 0.3}) == {
                "state": "downloading", "percent": 30}, name
        # While it checks, the progress is how far the check is: no percentage of the download.
        for name in ("checkingDL", "checkingResumeData"):
            assert await native(session, fakes, client, {"state": name, "progress": 1}) == {
                "state": "downloading", "percent": None}, name
        assert (await native(session, fakes, client, {"state": "moving", "progress": 1}))["state"] == "done"
    run(test)


def test_transmission_states():
    async def test(session, fakes, clients):
        client = clients["transmission"]
        await torrent.add(session, client, "magnet", MAGNET)
        half = {"percent_done": 0.5, "left_until_done": 500, "size_when_done": 1000}
        full = {"percent_done": 1, "left_until_done": 0, "size_when_done": 1000}
        # 0 stopped, 1 and 2 checking, 3 and 4 downloading, 5 and 6 seeding.
        for status in (0, 1, 2, 3, 4):
            assert await native(session, fakes, client, {"status": status, **half}) == {
                "state": "downloading", "percent": 50}, status
        for status in (0, 5, 6):
            assert await native(session, fakes, client, {"status": status, **full}) == {
                "state": "done", "percent": 100}, status
        # 1 and 2 are a warning and an error of the tracker, which pass; 3 is a local error.
        for error in (1, 2):
            assert (await native(session, fakes, client, {"status": 4, "error": error, **half}))["state"] == "downloading"
            assert (await native(session, fakes, client, {"status": 6, "error": error, **full}))["state"] == "done"
        assert await native(session, fakes, client, {"status": 0, "error": 3, **half}) == {
            "state": "failed", "percent": 50}
        # A magnet link of which nothing is known yet has no size: stopped is then not done.
        unknown = {"percent_done": 0, "left_until_done": 0, "size_when_done": 0}
        for status in (0, 4):
            assert await native(session, fakes, client, {"status": status, **unknown}) == {
                "state": "downloading", "percent": 0}, status
    run(test)


def test_utorrent_states():
    async def test(session, fakes, clients):
        client = clients["utorrent"]
        await torrent.add(session, client, "magnet", MAGNET)
        # Position 1 is the status in bits: 1 started, 2 checking, 8 checked, 16 error,
        # 32 paused, 64 queued, 128 loaded. Position 4 is the progress in per mille, 18 the
        # bytes still to go.
        for status in (201, 136, 233, 137):  # seeding, stopped, paused, forced
            assert await native(session, fakes, client, {1: status, 4: 1000, 18: 0}) == {
                "state": "done", "percent": 100}, status
        for status in (201, 136, 233, 200):  # downloading, stopped, paused, queued
            assert await native(session, fakes, client, {1: status, 4: 999, 18: 1024}) == {
                "state": "downloading", "percent": 99}, status
        for status, progress in ((152, 310), (217, 1000)):
            assert (await native(session, fakes, client, {1: status, 4: progress}))["state"] == "failed", status
        # While it checks, the progress is how far the check is.
        assert (await native(session, fakes, client, {1: 130, 4: 1000, 18: 0}))["state"] == "downloading"
        # Complete in per mille by rounding, but with bytes to go: not done yet.
        assert (await native(session, fakes, client, {1: 201, 4: 1000, 18: 4096}))["state"] == "downloading"
    run(test)


# ---------------------------------------------------------------- removing


@EVERY
@BOTH
@FILES
def test_remove_takes_that_one_torrent_out(kind, modern, files):
    # What each client is asked, in the words of its version.
    asked = {"qbittorrent": "torrents/delete", "transmission": "torrent_remove" if modern else "torrent-remove",
             "utorrent": "removedata" if files else "remove"}

    async def test(session, fakes, clients):
        client = clients[kind]
        await torrent.add(session, client, "magnet", MAGNET)
        await torrent.add(session, client, "file", TORRENT)
        assert await torrent.remove(session, client, HASH, files) is None
        assert fakes["calls"][-1] == (kind, asked[kind])
        assert fakes["removed"] == [(kind, HASH, files)]
        assert set(fakes["torrents"][kind]) == {TORRENT_HASH}
        assert set(await torrent.states(session, client)) == {TORRENT_HASH}
    run(test, modern)


@EVERY
@BOTH
@FILES
def test_remove_what_the_client_no_longer_has_is_no_error(kind, modern, files):
    async def test(session, fakes, clients):
        client = clients[kind]
        await torrent.add(session, client, "file", TORRENT)
        # Never added, and then one that was removed before.
        await torrent.remove(session, client, HASH, files)
        assert set(fakes["torrents"][kind]) == {TORRENT_HASH}
        await torrent.remove(session, client, TORRENT_HASH, files)
        await torrent.remove(session, client, TORRENT_HASH, files)
        assert fakes["removed"] == [(kind, HASH, files), (kind, TORRENT_HASH, files), (kind, TORRENT_HASH, files)]
        assert fakes["torrents"][kind] == {}
    run(test, modern)


@EVERY
def test_remove_knows_a_hash_in_capitals(kind):
    async def test(session, fakes, clients):
        await torrent.add(session, clients[kind], "magnet", MAGNET)
        await torrent.remove(session, clients[kind], HASH.upper(), True)
        assert fakes["removed"] == [(kind, HASH, True)] and fakes["torrents"][kind] == {}
    run(test)


@EVERY
def test_remove_refuses_what_is_no_hash(kind):
    async def test(session, fakes, clients):
        client = clients[kind]
        await torrent.add(session, client, "magnet", MAGNET)
        await torrent.add(session, client, "file", TORRENT)
        # "all" means every torrent to qBittorrent, and so does a list to all three.
        for wrong in ("all", "", None, HASH[:39], HASH + "0", f"{HASH}|{TORRENT_HASH}", "recently-active"):
            assert await refused(torrent.remove(session, client, wrong, True)) == (
                f"{LABELS[kind]}: this is not the id of a torrent"), wrong
        assert fakes["removed"] == [] and set(fakes["torrents"][kind]) == {HASH, TORRENT_HASH}
    run(test)


@EVERY
@BOTH
def test_remove_logs_in_again_when_the_session_ran_out(kind, modern):
    async def test(session, fakes, clients):
        await torrent.add(session, clients[kind], "magnet", MAGNET)
        fakes["expire"]()
        await torrent.remove(session, clients[kind], HASH, False)
        assert fakes["torrents"][kind] == {} and fakes["logins"][kind] == 2
    run(test, modern)


@EVERY
def test_remove_that_fails_is_an_error(kind):
    async def test(session, fakes, clients):
        await torrent.add(session, clients[kind], "magnet", MAGNET)
        wrong = {**clients[kind], "password": "not-the-password"}
        assert await refused(torrent.remove(session, wrong, HASH, True)) == f"{LABELS[kind]}: wrong username or password"
        gone = {**clients[kind], "url": "http://127.0.0.1:1"}
        message = await refused(torrent.remove(session, gone, HASH, True))
        assert message.startswith(f"{LABELS[kind]}: ") and PASSWORD not in message
        empty = {**clients[kind], "url": ""}
        assert await refused(torrent.remove(session, empty, HASH, True)) == f"{LABELS[kind]}: fill in the address"
        assert fakes["removed"] == [] and set(fakes["torrents"][kind]) == {HASH}
    run(test)


def test_utorrent_that_keeps_the_torrent_is_an_error():
    async def test(session, fakes, clients):
        client = clients["utorrent"]
        await torrent.add(session, client, "magnet", MAGNET)
        fakes["mood"]["stuck"] = True
        # An error about a torrent that is still there. About one that is gone it is none.
        assert await refused(torrent.remove(session, client, HASH, True)) == (
            "uTorrent: Can't remove torrent: access denied")
        await torrent.remove(session, client, TORRENT_HASH, True)
        assert set(fakes["torrents"]["utorrent"]) == {HASH}
    run(test)


# ---------------------------------------------------------------- when it goes wrong


@EVERY
def test_an_unreachable_address(kind):
    async def test(session, fakes, clients):
        gone = {**clients[kind], "url": "http://127.0.0.1:1"}
        for action in (lambda: torrent.status(session, gone), lambda: torrent.states(session, gone),
                       lambda: torrent.add(session, gone, "magnet", MAGNET)):
            message = await refused(action())
            assert message.startswith(f"{LABELS[kind]}: ") and PASSWORD not in message
        empty = {**clients[kind], "url": ""}
        assert await refused(torrent.status(session, empty)) == f"{LABELS[kind]}: fill in the address"
        assert await refused(torrent.add(session, empty, "magnet", MAGNET)) == f"{LABELS[kind]}: fill in the address"
    run(test)


@EVERY
def test_an_address_of_something_else(kind):
    async def test(session, fakes, clients):
        # The address of another program: every path of the client is unknown there.
        other = {**clients[kind], "url": clients[kind]["url"].rsplit("/", 1)[0] + "/elsewhere"}
        assert (await refused(torrent.status(session, other))).startswith(f"{LABELS[kind]}: HTTP 404")
    run(test)


@EVERY
def test_no_answer_is_a_timeout(kind, monkeypatch):
    monkeypatch.setattr(torrent, "SHORT", aiohttp.ClientTimeout(total=0.05))

    async def test(session, fakes, clients):
        fakes["mood"]["delay"] = 0.4
        assert await refused(torrent.status(session, clients[kind])) == f"{LABELS[kind]}: no answer (timeout)"
    run(test)


def test_a_password_never_shows_in_a_message():
    async def test(session, fakes, clients):
        # An error page that repeats the request, and with it the login form of qBittorrent.
        fakes["mood"]["broken"] = True
        message = await refused(torrent.status(session, clients["qbittorrent"]))
        assert message.startswith("qBittorrent: HTTP 500") and "password=***" in message
        assert PASSWORD not in message
    run(test)


def test_an_unknown_type_of_client():
    async def test(session, fakes, clients):
        client = {**clients["qbittorrent"], "type": "deluge"}
        assert await refused(torrent.status(session, client)) == "Unknown torrent client: deluge"
    run(test)


# ---------------------------------------------------------------- hashes


def test_info_hash():
    assert torrent.info_hash(TORRENT) == TORRENT_HASH
    assert len(TORRENT_HASH) == 40 and TORRENT_HASH == TORRENT_HASH.lower()
    # Written by hand, with the keys of info out of order: the hash is of the bytes as they
    # are in the file, not of a tidied copy.
    info = b"d4:name5:a.nsp6:lengthi7e5:filesld4:pathl1:a1:beeee"
    assert torrent.info_hash(b"d8:announce3:x:y4:info" + info + b"5:otherli1ei-2eee") == hashlib.sha1(info).hexdigest()
    # Only the key "info" of the file itself counts: not a value, not a key further inside.
    decoy = b"d7:comment4:info1:xd4:infod1:ai1eee4:info" + info + b"e"
    assert torrent.info_hash(decoy) == hashlib.sha1(info).hexdigest()


@pytest.mark.parametrize("data", [
    b"", b"e", b"<html>Login required</html>", b"d3:fooi1ee", b"d4:infoi1ee", b"d4:info", b"d4:infod",
    b"d4:infod6:pieces999:xee", b"di1e4:infodee", b"l" * 100_000, b"d1:a" + b"l" * 100_000, "d4:infodee", None])
def test_info_hash_of_what_is_no_torrent(data):
    with pytest.raises(ServiceError):
        torrent.info_hash(data)


def test_magnet_hash():
    assert torrent.magnet_hash(MAGNET) == HASH
    assert torrent.magnet_hash(f"magnet:?xt=urn:btih:{HASH}") == HASH
    # The older way to write the hash: 32 characters of base32, in capitals or not.
    assert len(BASE32.split("btih:")[1]) == 32
    assert torrent.magnet_hash(BASE32) == torrent.magnet_hash(BASE32.lower()) == HASH
    # As some indexers send it: encoded, after other parts, or as one of several.
    assert torrent.magnet_hash(f"magnet:?dn=Hades&xt=urn%3Abtih%3A{HASH.upper()}&tr=udp%3A%2F%2Ft.example%3A6969") == HASH
    assert torrent.magnet_hash(f"MAGNET:?xt.1=urn:ed2k:354b15e68fb8f36d7cd88ff94116cdc1&xt.2=urn:btih:{HASH}") == HASH


@pytest.mark.parametrize("uri", [
    "", "magnet:?dn=Hades", "magnet:?xt=urn:btih:abc123", f"magnet:?xt=urn:btih:{HASH}0", f"magnet:?dn=urn:btih:{HASH}",
    # Only the hash of version 2 of BitTorrent: none of the three clients' ids.
    "magnet:?xt=urn:btmh:1220caf1e1c30e81cb361b9ee167c4aa64228a7fa4fa9f6105232b28ad099f3a302e",
    f"http://tracker.example/download/{HASH}.torrent"])
def test_magnet_hash_when_there_is_none(uri):
    assert torrent.magnet_hash(uri) is None
