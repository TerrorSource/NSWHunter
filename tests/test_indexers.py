"""Direct indexers next to Prowlarr, several connections, the games list, backups and the log."""
import datetime
import os
import shutil
import time

import pytest

import backup
import config
import hunter as hunter_module
import indexers
import logs
from fakes import PNG
from test_hunter import ALAN, HADES, HOLLOW, providers, run, titles

NAB = {"id": "nb", "type": "newznab", "name": "FakeNab", "enabled": True, "url": "BASE/nab", "api_key": "nab_test",
       "categories": ["1000"], "priority": 5}
TOR = {"id": "tz", "type": "torznab", "name": "FakeTor", "enabled": True, "url": "BASE/tor", "api_key": "nab_test",
       "categories": ["1000"], "priority": 30}
PROWLARR = providers("BASE")["INDEXERS"][0]


def test_newznab_indexer_is_searched_directly():
    async def test(hunter, fakes):
        nab = config.INDEXERS[0]
        assert await indexers.status(hunter.session, nab) == "FakeNab, the API key is right"
        found = await indexers.search(hunter.session, nab, "hades")
        # The one filed under PS4 is left out, as with Prowlarr.
        assert [r["title"] for r in found] == ["Hades.Update.v131072.NSW-NABGRP"]
        release = found[0]
        assert (release["protocol"], release["size"], release["grabs"], release["source"], release["priority"]) == (
            "usenet", 151000000, 3, "nb", 5)
        assert release["published"].startswith("2021-03-02T10:00:00") and release["downloadUrl"].endswith("/nab/get/0")
        assert release["infoUrl"].endswith("/nab/details/0#comments") and release["indexer"] == "FakeNab"
        # Without a query: the newest posts.
        assert len(await indexers.search(hunter.session, nab, "")) == 2
        with pytest.raises(hunter_module.clients.ServiceError, match="FakeNab: Incorrect user credentials"):
            await indexers.status(hunter.session, {**nab, "api_key": "wrong"})
        with pytest.raises(hunter_module.clients.ServiceError, match="not the XML of a Newznab indexer"):
            await indexers.search(hunter.session, {**nab, "url": config.SLM_URL + "/versions.json?x="}, "hades")
    run(test, INDEXERS=[NAB])


def test_a_round_with_only_a_direct_indexer_finds_and_sends():
    async def test(hunter, fakes):
        await hunter.round()
        assert all(s["ok"] for s in hunter.state["services"].values())
        assert titles(hunter, HADES) == ["Hades.Update.v131072.NSW-NABGRP"]
        assert titles(hunter, HOLLOW) == ["Hollow Knight Update v131072 NSW-NABGRP"]
        best = hunter.state["items"][HADES]["candidates"][0]
        assert (best["priority"], best["protocol"], best["indexer"]) == (5, "usenet", "FakeNab")
        await hunter.grab(HADES, best["guid"])
        assert fakes["fetched"] == ["/nab/get/0"]  # the NZB came from the indexer itself
        assert [name for name, _, _ in fakes["sent"]] == ["Hades.Update.v131072.NSW-NABGRP.nzb"]
        grab = hunter.state["items"][HADES]["grab"]
        assert (grab["client"], grab["client_name"], grab["client_id"]) == ("nz", "NZBGet", "1")
    run(test, INDEXERS=[NAB])


def test_one_indexer_that_fails_does_not_cost_the_others():
    async def test(hunter, fakes):
        await hunter.round()
        services = hunter.state["services"]
        assert services["INDEXERS:px"]["ok"] is True and services["INDEXERS:nb"]["ok"] is False
        assert services["INDEXERS:nb"]["text"] == "FakeNab: Incorrect user credentials"
        assert services["INDEXERS:nb"]["name"] == "FakeNab" and hunter.status["error"] is None
        assert len(titles(hunter, ALAN)) == 4  # what Prowlarr found is there
        # The key is put right: the next round it answers again and its releases join.
        config.INDEXERS[1]["api_key"] = "nab_test"
        hunter.state["searched"] = {}
        await hunter.round()
        assert services["INDEXERS:nb"]["ok"] is True
        assert "Hades.Update.v131072.NSW-NABGRP" in titles(hunter, HADES) and "Hades_Update_v1.0.2_NSW-GRP" in titles(hunter, HADES)
        # Both score the same; the one of the indexer with the lower priority number is not the tie-breaker
        # before the date: the newer post goes first.
        assert titles(hunter, HADES)[0] == "Hades.Update.v131072.NSW-NABGRP"
    run(test, INDEXERS=[PROWLARR, {**NAB, "api_key": "wrong"}])


def test_when_no_indexer_answers_the_round_goes_on_without_searching():
    async def test(hunter, fakes):
        await hunter.round()
        assert hunter.status["error"] is None and not hunter.working("INDEXERS")
        assert hunter.state["library"]["games"] == 8 and titles(hunter, HADES) == []
    run(test, INDEXERS=[{**NAB, "api_key": "wrong"}])


def test_torrents_are_not_searched_without_a_torrent_client():
    async def test(hunter, fakes):
        await hunter.round()
        assert titles(hunter, HOLLOW) == [] and "Hades Update v131072" not in titles(hunter, HADES)
        assert fakes["indexer_ids"][0] == ["-1"]  # Prowlarr is asked for its usenet indexers only
        assert all(c["protocol"] == "usenet" for i in hunter.state["items"].values() for c in i["candidates"])
    run(test, INDEXERS=[PROWLARR, TOR])


def test_a_removed_or_disabled_entry_no_longer_reports():
    async def test(hunter, fakes):
        await hunter.round()
        assert "INDEXERS:nb" in hunter.state["services"]
        config.INDEXERS = [config.INDEXERS[0], {**config.INDEXERS[1], "enabled": False}]
        await hunter.round()
        assert "INDEXERS:nb" not in hunter.state["services"] and "INDEXERS:px" in hunter.state["services"]
    run(test, INDEXERS=[PROWLARR, {**NAB, "api_key": "wrong"}])


def test_every_connection_gets_the_message_and_one_that_fails_says_so():
    discord = {"id": "dc", "type": "discord", "name": "Discord", "enabled": True, "webhook": "BASE/discord/good"}
    gone = {"id": "dx", "type": "discord", "name": "Old channel", "enabled": True, "webhook": "BASE/discord/secret-token"}
    off = {"id": "do", "type": "discord", "name": "Off", "enabled": False, "webhook": "BASE/discord/good"}
    telegram = {"id": "tg", "type": "telegram", "name": "Telegram", "enabled": True, "bot_token": "TESTTOKEN", "chat_id": "42"}

    async def test(hunter, fakes):
        await hunter.tell("Arrived: something", "arrive")
        assert fakes["discord"] == ["Arrived: something"] and fakes["telegram"] == ["NSWHunter\nArrived: something"]
        services = hunter.state["services"]
        assert services["CONNECTIONS:dc"]["ok"] and services["CONNECTIONS:tg"]["ok"] and "CONNECTIONS:do" not in services
        assert services["CONNECTIONS:dx"] == {**services["CONNECTIONS:dx"], "ok": False, "name": "Old channel",
                                              "text": "Discord: the webhook is wrong or was removed"}
        assert await hunter.test("CONNECTIONS", config.CONNECTIONS[0]) == "Test message sent"
        assert fakes["discord"][-1] == "This is a test message."
        # The address of a webhook is its secret: no message shows it.
        with pytest.raises(hunter_module.clients.ServiceError) as error:
            await hunter.test("CONNECTIONS", {**gone, "webhook": "http://127.0.0.1:1/secret-token"})
        assert "secret-token" not in str(error.value) and "127.0.0.1" not in str(error.value)
    run(test, CONNECTIONS=[discord, gone, off, telegram])


def test_every_game_of_the_library_is_listed():
    async def test(hunter, fakes):
        await hunter.round()
        games = {g["name"]: g for g in hunter.library()}
        # The Switch 2 title is left out here too; a game that misses nothing is listed.
        assert len(games) == 7 and [g["name"] for g in hunter.library()][0] == "Alan Wake Remastered"
        alan, stardew, ea = games["Alan Wake Remastered"], games["Stardew Valley"], games["EA SPORTS FC™ 25"]
        assert (alan["version"], alan["local"], alan["latest"], alan["update_missing"], alan["dlc_missing"]) == (
            "1.0.1", 65536, 196608, True, 1)
        assert alan["size"] == 12_380_000_000 and alan["id"] == ALAN
        assert (stardew["update_missing"], stardew["dlc_missing"]) == (False, 0)
        # Missing DLC is counted even when it is not searched.
        assert (ea["dlc_missing"], ea["dlc_owned"]) == (2, 1) and not config.INCLUDE_DLC
    run(test)


def test_a_round_makes_the_scheduled_backup_and_removes_the_old_ones():
    async def test(hunter, fakes):
        await hunter.round()
        made = backup.listing()
        assert [b["kind"] for b in made] == ["scheduled"] and made[0]["size"] > 100
        assert os.stat(backup.path(made[0]["name"])).st_mode & 0o077 == 0  # it holds the keys
        await hunter.round()
        assert len(backup.listing()) == 1  # not due again
        by_hand = backup.create("manual")
        long_ago = time.time() - 29 * 86400
        for b in backup.listing():
            os.utime(backup.path(b["name"]), (long_ago, long_ago))
        await hunter.round()
        # The old scheduled one is gone and a new one was due; the one made by hand stays.
        kinds = sorted((b["kind"], b["name"] == by_hand, b["at"] > long_ago + 60) for b in backup.listing())
        assert kinds == [("manual", True, False), ("scheduled", False, True)]
        assert "backup" not in hunter.state["services"]
    run(test)


def test_a_backup_folder_that_cannot_be_written_is_reported_and_stops_nothing():
    async def test(hunter, fakes):
        await hunter.round()
        await hunter.round()
        service = hunter.state["services"]["backup"]
        assert service["ok"] is False and "Cannot write in the backup folder" in service["text"]
        assert hunter.status["error"] is None and len(titles(hunter, ALAN)) == 4
        assert sum("Backup failed" in e["text"] for e in hunter.state["events"]) == 1  # said once
    run(test, BACKUP_FOLDER="/proc/nowhere")


def test_only_names_of_backups_reach_a_file():
    saved = config.BACKUP_FOLDER
    config.BACKUP_FOLDER = "backups"
    try:
        name = backup.create()
        assert backup.path(name).endswith(name)
        for wrong in ("../settings.json", "/etc/passwd", name + "/../x", name.replace(".zip", ".txt"), ""):
            with pytest.raises(backup.BackupError):
                backup.path(wrong)
        backup.delete(name)
        with pytest.raises(backup.BackupError, match="no longer there"):
            backup.restore(name)
    finally:
        config.BACKUP_FOLDER = saved


def test_log_levels_and_a_file_per_day(capsys):
    saved = config.LOG_LEVEL, config.LOG_DIR, config.LOG_KEEP_DAYS
    config.LOG_DIR = os.path.join(config.DATA_DIR, "logs-test")
    shutil.rmtree(config.LOG_DIR, ignore_errors=True)
    os.makedirs(config.LOG_DIR)
    today = datetime.date.today()
    try:
        # Files of other days: two inside what is kept, one too old, one of an older version, one of someone else.
        old = os.path.join(config.LOG_DIR, "nswhunter.txt.1")
        for name in (f"nswhunter_{today - datetime.timedelta(days=13)}.txt", f"nswhunter_{today - datetime.timedelta(days=15)}.txt",
                     "nswhunter.txt.1", "notes.txt"):
            open(os.path.join(config.LOG_DIR, name), "w").close()
        long_ago = time.time() - 20 * 86400
        os.utime(old, (long_ago, long_ago))
        config.LOG_LEVEL, config.LOG_KEEP_DAYS = "info", 14
        logs.setup()
        logs.info("said at info")
        logs.debug("a search")
        logs.trace("a verdict")
        config.LOG_LEVEL = "debug"
        logs.debug("another search")
        logs.trace("another verdict")
        config.LOG_LEVEL = "trace"
        logs.trace("a third verdict")
        logs.console("the made-up password")
        out = capsys.readouterr().out
        assert "said at info" in out and "a search" not in out and "a verdict" not in out
        assert "[debug] another search" in out and "another verdict" not in out and "[trace] a third verdict" in out
        # The file of today holds the same lines, but never what is for the output of the container only.
        text = open(os.path.join(config.LOG_DIR, f"nswhunter_{today}.txt")).read()
        assert "said at info" in text and "[trace] a third verdict" in text and "made-up password" not in text
        assert "the made-up password" in out
        assert sorted(os.listdir(config.LOG_DIR)) == sorted([
            f"nswhunter_{today}.txt", f"nswhunter_{today - datetime.timedelta(days=13)}.txt", "notes.txt"])
    finally:
        config.LOG_LEVEL, config.LOG_DIR, config.LOG_KEEP_DAYS = saved
        logs.setup()


def test_debug_and_trace_say_what_a_round_does(capsys):
    async def test(hunter, fakes):
        await hunter.round()
    saved = config.LOG_LEVEL
    config.LOG_LEVEL = "trace"
    try:
        run(test)
    finally:
        config.LOG_LEVEL = saved
    out = capsys.readouterr().out
    assert "[debug] Prowlarr: ok - Prowlarr 2.0.0" in out and "[debug] Searched ['hades']" in out
    assert "[trace] Hades (update) <- Hades II Update v65536: ruled out, another game (sequel 'ii')" in out
    assert "[trace] Hades (update) <- Hades_Update_v1.0.2_NSW-GRP: score 7" in out


def test_a_connection_only_hears_what_it_wants_to_hear():
    quiet = {"id": "dq", "type": "discord", "name": "Only failures", "enabled": True, "webhook": "BASE/discord/good",
             "on_grab": False, "on_arrive": False, "on_choice": False, "on_health": False}
    telegram = {"id": "tg", "type": "telegram", "name": "Telegram", "enabled": True, "bot_token": "TESTTOKEN", "chat_id": "42",
                "on_fail": False}

    async def test(hunter, fakes):
        await hunter.tell("Arrived: something", "arrive")
        await hunter.tell("Download failed: something", "fail")
        await hunter.tell("Round failed", "health")
        assert fakes["discord"] == ["Download failed: something"]
        # A trigger that is not named in an entry of an older version counts as switched on.
        assert fakes["telegram"] == ["NSWHunter\nArrived: something", "NSWHunter\nRound failed"]
    run(test, CONNECTIONS=[quiet, telegram])


def test_what_was_sent_arrived_and_failed_is_history():
    async def test(hunter, fakes):
        await hunter.round()
        best = hunter.state["items"][ALAN]["candidates"][0]
        await hunter.grab(ALAN, best["guid"])
        grab = hunter.state["items"][ALAN]["grab"]
        assert (grab["protocol"], grab["indexer"]) == ("usenet", "FakeIndexer")
        fakes["downloads"]["1"] = "FAILURE/PAR"
        await hunter.watch()
        second = hunter.state["items"][ALAN]["candidates"][0]
        await hunter.grab(ALAN, second["guid"])
        fakes["library"][0].update(localUpdate=196608, updateMissing=False)
        await hunter.round()
        history = [(e["kind"], e["name"], e["what"], e["title"]) for e in hunter.history()]
        assert history == [
            ("arrived", "Alan Wake Remastered", "update", second["title"]),
            ("grabbed", "Alan Wake Remastered", "update", second["title"]),
            ("failed", "Alan Wake Remastered", "update", best["title"]),
            ("grabbed", "Alan Wake Remastered", "update", best["title"])]
        first = hunter.history()[-1]
        assert (first["client"], first["indexer"], first["protocol"], first["auto"], first["score"]) == (
            "NZBGet", "FakeIndexer", "usenet", False, 10)
        assert hunter.history()[1 + 1]["note"] == "the download client reports that the download failed"
    run(test)


def test_search_all_searches_every_game_in_the_next_round():
    async def test(hunter, fakes):
        await hunter.round()
        searched = len(fakes["queries"])
        await hunter.round()
        assert len(fakes["queries"]) == searched + 1  # only the newest posts: nobody's turn
        assert hunter.search_all() == 5
        await hunter.round()
        assert len(fakes["queries"]) == searched + 1 + 1 + 5
    run(test)


def test_games_get_their_picture_from_the_library():
    async def test(hunter, fakes):
        await hunter.round()
        games = {g["name"]: g for g in hunter.library()}
        assert games["Alan Wake Remastered"]["cover"] and games["Hades"]["cover"] and not games["Stardew Valley"]["cover"]
        assert not games["Pokémon™ Scarlet"]["cover"]  # the library has no picture of it
        # The small picture is preferred; it is fetched once, with the key, and then kept.
        assert await hunter.cover(ALAN) == ("image/png", PNG)
        assert await hunter.cover(ALAN) == ("image/png", PNG)
        assert fakes["covers"] == [("/covers/0100623017A58000.jpg", "Bearer slm_test")]
        assert [n.split("_")[0] for n in os.listdir(config.COVER_DIR)] == [ALAN]
        # A picture on another server is fetched without the key of the library.
        assert await hunter.cover(HADES) == ("image/png", PNG)
        assert fakes["covers"][-1] == ("/elsewhere/hades.png", None)
        # What is not a picture is not passed on, and not asked for again at once.
        assert await hunter.cover(HOLLOW) is None and await hunter.cover(HOLLOW) is None
        assert len(fakes["covers"]) == 3
        for nothing in ("0100CCCC0000C000", "../settings.json", "0100623017A58000/../x", ""):
            assert await hunter.cover(nothing) is None
    shutil.rmtree(config.COVER_DIR, ignore_errors=True)
    run(test)
    shutil.rmtree(config.COVER_DIR, ignore_errors=True)


def test_without_pictures_everything_else_works():
    async def test(hunter, fakes):
        await hunter.round()
        assert hunter.status["error"] is None and all(s["ok"] for s in hunter.state["services"].values())
        assert not any(g["cover"] for g in hunter.library()) and len(titles(hunter, ALAN)) == 4
    # The library does not know the address of the pictures: an older version of it, say.
    saved = hunter_module.clients.cover_addresses

    async def unknown(session):
        raise hunter_module.clients.ServiceError("Library: HTTP 404")
    hunter_module.clients.cover_addresses = unknown
    try:
        run(test)
    finally:
        hunter_module.clients.cover_addresses = saved


def test_tasks_say_when_they_ran_and_can_be_run_by_hand():
    async def test(hunter, fakes):
        await hunter.round()
        hunter.status["next_run"] = int(time.time()) + 3600
        tasks = {t["name"]: t for t in hunter.tasks()}
        assert list(tasks) == ["health", "library", "rss", "search", "downloads", "versions", "backup"]
        assert all(t["last"] and t["duration"] is not None for n, t in tasks.items() if n != "downloads")
        assert (tasks["health"]["interval"], tasks["search"]["interval"], tasks["backup"]["interval"]) == (3600, 86400, 7 * 86400)
        # Nothing in the queue: the downloads are not asked about, and are not planned.
        assert tasks["downloads"]["last"] is None and tasks["downloads"]["next"] is None
        assert tasks["rss"]["next"] == hunter.status["next_run"]
        # Searched a moment ago: the next search is a day away, the next backup a week.
        assert 86000 < tasks["search"]["next"] - time.time() < 86500
        assert 6.9 * 86400 < tasks["backup"]["next"] - time.time() < 7.1 * 86400
        # What ran is kept too, newest first, for the queue of the Tasks page.
        runs = hunter.state["task_runs"]
        assert {r["name"] for r in runs} == set(tasks) - {"downloads"}
        assert all(r["text"] and r["started"] <= r["ended"] and r["duration"] >= 0 for r in runs)
        queries = len(fakes["queries"])
        assert await hunter.run_task("rss") is False and len(fakes["queries"]) == queries + 1
        assert hunter.state["task_runs"][0]["name"] == "rss" and len(hunter.state["task_runs"]) == len(runs) + 1
        # No more than the last twenty are kept.
        for _ in range(25):
            hunter.did("health", time.time())
        assert len(hunter.state["task_runs"]) == 20
        # Search Missing is done by a round that starts now.
        assert await hunter.run_task("search") is True and hunter.state["searched"] == {}
        await hunter.grab(ALAN, hunter.state["items"][ALAN]["candidates"][0]["guid"])
        fakes["progress"]["1"] = (400, 100)
        assert await hunter.run_task("downloads") is False
        assert hunter.state["items"][ALAN]["grab"]["percent"] == 75 and hunter.tasks()[4]["last"]
        hunter.state["tasks"].pop("backup")
        await hunter.run_task("backup")
        assert hunter.state["tasks"]["backup"]["last"] and hunter_module.backup.listing()
        hunter.versions = {}
        await hunter.run_task("versions")
        assert len(hunter.versions) == 4
        with pytest.raises(hunter_module.clients.ServiceError, match="Unknown task"):
            await hunter.run_task("format-disk")
        async with hunter.lock:
            with pytest.raises(hunter_module.clients.ServiceError, match="A round is running"):
                await hunter.run_task("library")
    run(test)
