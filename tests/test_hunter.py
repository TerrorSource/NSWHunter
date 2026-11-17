"""A whole round against stand-ins for the library, Prowlarr and NZBGet."""
import asyncio
import os
import shutil
import time

import aiohttp
import pytest
from aiohttp.test_utils import TestServer

import config
import hunter as hunter_module
from fakes import NZB, make_fakes

ALAN, ALAN_DLC, HADES, SCARLET, HOLLOW, NARUTO = (
    "0100623017A58000", "0100623017A59001", "0100AAAA0000A000", "0100BBBB0000B000", "0100DDDD0000D000",
    "0100EEEE0000E000")
EA_DUTCH, EA_SPANISH = "0100FFFF0000F001", "0100FFFF0000F002"


def providers(base, **settings):
    """The indexer, the download client and the connection the tests work with, as entries of
    the settings. Settings in the old flat style choose between them."""
    token, chat = settings.get("TELEGRAM_BOT_TOKEN", ""), settings.get("TELEGRAM_CHAT_ID", "")
    nzbget = {"id": "nz", "type": "nzbget", "name": "NZBGet", "enabled": True, "url": base,
              "username": "nzbget", "password": "tegen", "category": "games"}
    own = {"id": "pc", "type": "prowlarr", "name": "The download client of Prowlarr", "enabled": True}
    return {
        "INDEXERS": [{"id": "px", "type": "prowlarr", "name": "Prowlarr", "enabled": True, "url": base,
                      "api_key": settings.get("PROWLARR_API_KEY", "prowlarr_test"), "categories": ["1000"]}],
        "DOWNLOAD_CLIENTS": [own if settings.get("DOWNLOAD_CLIENT") == "prowlarr" else nzbget],
        "CONNECTIONS": [{"id": "tg", "type": "telegram", "name": "Telegram", "enabled": True, "bot_token": token,
                         "chat_id": chat, "ask": bool(settings.get("TELEGRAM_ASK"))}] if token else [],
    }


OLD_STYLE = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "TELEGRAM_ASK", "DOWNLOAD_CLIENT", "PROWLARR_API_KEY")


def run(test, **settings):
    """Start the fake services, point the config at them, and run `test(hunter, fakes)`."""
    async def body():
        fakes = make_fakes()
        server = TestServer(fakes)
        await server.start_server()
        base = str(server.make_url("")).rstrip("/")
        values = {
            "SLM_URL": base, "SLM_API_KEY": "slm_test", "TITLEDB_VERSIONS_URL": base + "/versions.json",
            "AUTO_DOWNLOAD": "off", "AUTO_BUNDLES": False, "INCLUDE_DLC": False,
            "SEARCH_DELAY_SECONDS": 0, "BACKLOG_PER_RUN": 0, "SEARCH_INTERVAL_HOURS": 24,
            "SEARCH_BY_TITLE_ID": False, "GRAB_WAIT_MINUTES": 60, "WATCH_SECONDS": 120,
            "TELEGRAM_API_URL": base, "BACKUP_FOLDER": "backups", "PROWLARR_INDEXER_IDS": [],
            **providers(base, **settings), **{k: v for k, v in settings.items() if k not in OLD_STYLE}}
        for kind in config.KINDS:  # "BASE" in an address of an entry: the fake services
            values[kind] = [{k: v.replace("BASE", base) if isinstance(v, str) else v for k, v in e.items()}
                            for e in values[kind]]
        saved = {k: getattr(config, k) for k in values}
        for path in (config.STATE_FILE, config.VERSIONS_FILE):
            if os.path.exists(path):
                os.remove(path)
        shutil.rmtree(os.path.join(config.DATA_DIR, "backups"), ignore_errors=True)
        try:
            for k, v in values.items():
                setattr(config, k, v)
            async with aiohttp.ClientSession() as session:
                await test(hunter_module.Hunter(session), fakes)
        finally:
            for k, v in saved.items():
                setattr(config, k, v)
            await server.close()
    asyncio.run(body())


def titles(hunter, key):
    return [c["title"] for c in hunter.state["items"][key]["candidates"]]


def test_round_finds_and_ranks_candidates():
    async def test(hunter, fakes):
        await hunter.round()
        items = hunter.state["items"]
        # Only games that miss an update; Stardew Valley is up to date.
        assert set(items) == {ALAN, HADES, SCARLET, HOLLOW, NARUTO}
        assert all(s["ok"] for s in hunter.state["services"].values())
        # Highest score first; of equal scores the newest post first.
        assert [(c["score"], c["title"]) for c in items[ALAN]["candidates"]] == [
            (10, "Alan Wake Remastered [0100623017A58800][v196608].nsz"),
            (7, "Alan_Wake_Remastered_Update_v1.0.3_NSW-VENOM"),
            (5, "Alan Wake Remastered [NSP] [Base + Update 1.0.3 + DLC]"),
            (5, "[NSW] Alan Wake Remastered (Update v131072) (EUR)"),
        ]
        assert all(c["priority"] == 10 for c in items[ALAN]["candidates"])
        # The PC release with the same name is outside the Console categories.
        assert titles(hunter, HADES) == ["Hades_Update_v1.0.2_NSW-GRP"]
        assert hunter.state["items"][HADES]["candidates"][0]["score"] == 7
        # The exact name wins from the title with extra words.
        assert titles(hunter, SCARLET) == [
            "Pokemon.Scarlet.Update.v3.0.1.NSW-BigBlueBox",
            "Pokemon Scarlet The Hidden Treasure Update v262144"]
        assert titles(hunter, HOLLOW) == []
        # Nothing goes out by itself when AUTO_DOWNLOAD is off.
        assert fakes["sent"] == []
        # One call for the newest posts, then one search per game.
        assert fakes["queries"] == ["", "alan wake remastered", "hades", "pokemon scarlet", "hollow knight",
                                    "naruto x boruto ultimate ninja storm connections"]
        # Every search asks Prowlarr for its usenet indexers (-1); -2 would be the torrent ones.
        assert all(ids == ["-1"] for ids in fakes["indexer_ids"])
        view = hunter.view()
        assert "downloadUrl" not in str(view) and "secret" not in str(view)
        assert [i["status"] for i in view["items"]] == ["review", "review", "review", "review", "none"]
    run(test)


def test_manual_grab_reaches_nzbget_and_clears_when_library_is_updated():
    async def test(hunter, fakes):
        await hunter.round()
        await hunter.grab(ALAN, hunter.state["items"][ALAN]["candidates"][0]["guid"])
        assert fakes["sent"] == [
            ("Alan Wake Remastered [0100623017A58800][v196608].nsz.nzb", "games", NZB)]
        assert {i["key"]: i["status"] for i in hunter.view()["items"]}[ALAN] == "sent"
        assert hunter.state["items"][ALAN]["grab"]["auto"] is False
        # The update arrives: the library no longer reports it missing.
        fakes["library"][0].update(localUpdate=196608, updateMissing=False)
        await hunter.round()
        assert ALAN not in hunter.state["items"]
        assert any(e["text"].startswith("Arrived: Alan Wake Remastered") for e in hunter.state["events"])
    run(test)


def test_auto_sure_sends_only_certain_latest_updates():
    async def test(hunter, fakes):
        await hunter.round()
        assert sorted(name for name, _, _ in fakes["sent"]) == [
            "Alan Wake Remastered [0100623017A58800][v196608].nsz.nzb",
            "NARUTO X BORUTO Ultimate Ninja STORM CONNECTIONS Update v1.7.1 NSW-SUXXORS.nzb"]
        assert hunter.state["items"][ALAN]["grab"]["auto"] is True
        assert hunter.state["items"][HADES]["grab"] is None
        # A second round does not send them again.
        await hunter.round()
        assert len(fakes["sent"]) == 2
    run(test, AUTO_DOWNLOAD="9")


def test_auto_likely_also_sends_display_versions_posted_after_the_latest_update():
    async def test(hunter, fakes):
        await hunter.round()
        assert sorted(name for name, _, _ in fakes["sent"]) == [
            "Alan Wake Remastered [0100623017A58800][v196608].nsz.nzb",
            "Hades_Update_v1.0.2_NSW-GRP.nzb",
            "NARUTO X BORUTO Ultimate Ninja STORM CONNECTIONS Update v1.7.1 NSW-SUXXORS.nzb",
            "Pokemon.Scarlet.Update.v3.0.1.NSW-BigBlueBox.nzb"]
    run(test, AUTO_DOWNLOAD="7")


def test_display_version_is_matched_to_the_update_by_its_place():
    """The user's real case: releases say v1.7.1, the library says update 11 (v720896), and the
    databases date update 11 three weeks after the release was posted."""
    async def test(hunter, fakes):
        await hunter.round()
        found = hunter.state["items"][NARUTO]["candidates"]
        # v1.7.0 is what the library has; only the three v1.7.1 variants remain, most grabbed first.
        assert [c["title"] for c in found] == [
            "NARUTO X BORUTO Ultimate Ninja STORM CONNECTIONS Update v1.7.1 NSW-SUXXORS",
            "NARUTO X BORUTO Ultimate Ninja STORM CONNECTIONS Update v1.7.1 MULTI4 NSW-SUXXORS",
            "NARUTO X BORUTO ULTIMATE NINJA STORM CONNECTIONS Update v1.7.1 MULTI6 NSW-SUXXORS"]
        assert {(c["score"], c["is_latest"], c["estimated_version"], c["deduced"]) for c in found} == {
            (9, True, 720896, True)}
        assert any("update 11" in reason for reason in found[0]["reasons"])
        # Also the version that is not wanted was noticed: it is a step of the ladder.
        assert hunter.state["seen"][NARUTO] == {"1.7.0": "2026-08-20", "1.7.1": "2026-09-30"}
        shown = next(i for i in hunter.view()["items"] if i["key"] == NARUTO)
        assert [(r["display"], r["update"]) for r in shown["ladder"]] == [("1.7.0", "update 10"), ("1.7.1", "update 11")]
    run(test)


def test_every_game_is_searched_once_per_interval():
    async def test(hunter, fakes):
        await hunter.round()
        first = len(fakes["queries"])
        await hunter.round()
        assert len(fakes["queries"]) == first + 1  # only the newest posts, no search by name
        for game_id in hunter.state["searched"]:
            hunter.state["searched"][game_id] -= 7 * 3600
        await hunter.round()
        assert len(fakes["queries"]) == first + 2  # 7 hours ago, interval 24: still nothing
        config.SEARCH_INTERVAL_HOURS = 6
        await hunter.round()
        assert len(fakes["queries"]) == first + 3 + 5  # now every game again
    run(test)


def test_test_buttons_use_the_values_of_the_form():
    async def test(hunter, fakes):
        prowlarr, nzbget = config.INDEXERS[0], config.DOWNLOAD_CLIENTS[0]
        assert await hunter.test("slm", config.overlay({})) == "8 games in the library"
        # A torrent indexer is counted, and said not to be searched without a torrent client.
        assert await hunter.test("INDEXERS", prowlarr) == (
            "Prowlarr 2.0.0, 1 usenet indexer, 1 torrent indexer (not searched: no torrent client)")
        assert await hunter.test("DOWNLOAD_CLIENTS", nzbget) == "NZBGet 24.5"
        own = {"id": "pc", "type": "prowlarr", "name": "The download client of Prowlarr", "enabled": True}
        assert await hunter.test("DOWNLOAD_CLIENTS", own) == "via Prowlarr: NZBGet"
        for kind, entry in (("slm", config.overlay({"SLM_API_KEY": "slm_wrong"})), ("slm", config.overlay({"SLM_URL": ""})),
                            ("INDEXERS", {**prowlarr, "api_key": "x"}), ("DOWNLOAD_CLIENTS", {**nzbget, "password": "x"})):
            with pytest.raises(hunter_module.clients.ServiceError):
                await hunter.test(kind, entry)
        # Testing changed nothing.
        assert config.SLM_API_KEY == "slm_test" and not os.path.exists(config.SETTINGS_FILE)
    run(test)


def test_order_is_score_then_age_then_indexer_priority():
    def release(score, published, priority, grabs=0):
        return {"score": score, "published": published + "T10:00:00Z", "priority": priority, "grabs": grabs}
    best = release(9, "2026-01-01", 30)
    newer = release(7, "2026-09-30", 25)
    first_indexer = release(7, "2026-09-01", 1)
    second_indexer = release(7, "2026-09-01", 25, grabs=50)
    popular = release(7, "2026-09-01", 25, grabs=90)
    shuffled = [second_indexer, popular, first_indexer, newer, best]
    assert sorted(shuffled, key=hunter_module.best_first) == [best, newer, first_indexer, popular, second_indexer]


def test_same_release_on_two_indexers_keeps_the_one_that_goes_first():
    async def test(hunter, fakes):
        await hunter.round()
        item = hunter.state["items"][HADES]
        kept = item["candidates"][0]
        hunter.priorities = {("px", 1): 10, ("px", 7): 3, ("px", 8): 40}
        twin = {**kept, "guid": "other-indexer", "indexerId": 7, "indexer": "Better"}
        assert hunter.offer(item, twin) is False  # not a new candidate, it replaces its twin
        assert [(c["guid"], c["priority"]) for c in item["candidates"]] == [("other-indexer", 3)]
        hunter.offer(item, {**kept, "guid": "worse-indexer", "indexerId": 8})
        assert [c["guid"] for c in item["candidates"]] == ["other-indexer"]
    run(test)


def test_dlc_is_its_own_item():
    async def test(hunter, fakes):
        await hunter.round()
        item = hunter.state["items"][ALAN_DLC]
        assert item["type"] == "dlc" and item["game_id"] == ALAN
        assert titles(hunter, ALAN_DLC)[0] == "Alan Wake Remastered [0100623017A59001][v0] DLC"
        assert item["candidates"][0]["score"] == 10
        # The DLC release is not offered as the update.
        assert "Alan Wake Remastered [0100623017A59001][v0] DLC" not in titles(hunter, ALAN)
    run(test, INCLUDE_DLC=True)


def test_each_dlc_gets_only_its_own_releases():
    """Twenty DLCs that differ in one word: a release belongs to the DLC it names best, and the
    same release with dots instead of spaces is listed once."""
    async def test(hunter, fakes):
        await hunter.round()
        assert titles(hunter, EA_DUTCH) == ["EA SPORTS FC 25 In-Game Commentary Dutch DLC NSW-VENOM"]
        assert titles(hunter, EA_SPANISH) == ["EA SPORTS FC 25 In-Game Commentary Spanish DLC NSW-VENOM"]
        found = hunter.state["items"][EA_DUTCH]["candidates"][0]
        assert found["score"] == 8 and found["reasons"] == ["name matches", "the title names the DLC"]
    run(test, INCLUDE_DLC=True)


def test_other_releases_stay_after_one_was_sent():
    """The user's case: one release sent, the newer one next to it must stay in view."""
    async def test(hunter, fakes):
        await hunter.round()
        item = hunter.state["items"][ALAN]
        older = next(c for c in item["candidates"] if "v131072" in c["title"])
        before = titles(hunter, ALAN)
        await hunter.grab(ALAN, older["guid"])
        shown = next(i for i in hunter.view()["items"] if i["key"] == ALAN)
        assert shown["status"] == "sent" and shown["sent"] == [older["guid"]]
        assert [c["title"] for c in shown["candidates"]] == before
        # A second one can still be sent; both are marked.
        await hunter.grab(ALAN, item["candidates"][0]["guid"])
        assert item["sent"] == [older["guid"], item["candidates"][0]["guid"]]
    run(test)


def test_sent_update_that_is_not_the_newest_arrives():
    async def test(hunter, fakes):
        await hunter.round()
        item = hunter.state["items"][ALAN]
        await hunter.grab(ALAN, next(c["guid"] for c in item["candidates"] if "v131072" in c["title"]))
        fakes["library"][0].update(localUpdate=131072, version="1.0.2")
        await hunter.round()
        item = hunter.state["items"][ALAN]
        assert item["grab"] is None and item["blocked"] == []
        assert any("There is a newer update still" in e["text"] for e in hunter.state["events"])
        # What it has now is no longer offered; the newest still is.
        assert "[NSW] Alan Wake Remastered (Update v131072) (EUR)" not in titles(hunter, ALAN)
        assert titles(hunter, ALAN)[0] == "Alan Wake Remastered [0100623017A58800][v196608].nsz"
    run(test)


def test_grab_through_prowlarr():
    async def test(hunter, fakes):
        await hunter.round()
        await hunter.grab(HADES, hunter.state["items"][HADES]["candidates"][0]["guid"])
        assert fakes["grabbed"] == [{"guid": "guid-6", "indexerId": 1}]
        assert fakes["sent"] == []
    run(test, DOWNLOAD_CLIENT="prowlarr")


async def send_best(hunter, key=ALAN):
    await hunter.round()
    guid = hunter.state["items"][key]["candidates"][0]["guid"]
    await hunter.grab(key, guid)
    return guid


def test_release_the_client_does_not_know_counts_as_not_arrived_after_the_wait():
    async def test(hunter, fakes):
        first = await send_best(hunter)
        fakes["downloads"].clear()  # removed from the download client by hand
        await hunter.watch()
        assert hunter.state["items"][ALAN]["grab"] is not None  # the hour is not over
        hunter.state["items"][ALAN]["grab"]["at"] = time.time() - 61 * 60
        await hunter.watch()
        item = hunter.state["items"][ALAN]
        assert item["grab"] is None and first in item["blocked"]
        assert first not in [c["guid"] for c in item["candidates"]]
        assert any(e["text"].startswith("Not arrived after 60 minutes") for e in hunter.state["events"])
    run(test)


def test_failed_download_gives_the_next_release_its_turn_at_once():
    async def test(hunter, fakes):
        first = await send_best(hunter)
        assert hunter.state["items"][ALAN]["grab"]["client_id"] == "1"
        fakes["downloads"]["1"] = "FAILURE/PAR"
        config.AUTO_DOWNLOAD = "7"
        for key, item in hunter.state["items"].items():
            item["ignored"] = key != ALAN  # only this game, to keep the test about one thing
        await hunter.watch()
        item = hunter.state["items"][ALAN]
        # Score 10 failed; the next best (7) is sent by itself because 7 is the threshold.
        assert first in item["blocked"] and item["grab"]["title"] == "Alan_Wake_Remastered_Update_v1.0.3_NSW-VENOM"
        assert item["grab"]["auto"] is True and len(fakes["sent"]) == 2
        # The first message is from the round: "4 updates or DLC await your choice".
        assert fakes["telegram"][1].startswith("NSWHunter\nDownload failed: Alan Wake Remastered [0100623017A58800]")
        assert any("Sent automatically: Alan_Wake" in text for text in fakes["telegram"])
    run(test, TELEGRAM_BOT_TOKEN="TESTTOKEN", TELEGRAM_CHAT_ID="42")


def test_download_that_is_busy_is_never_given_up():
    async def test(hunter, fakes):
        await send_best(hunter)
        hunter.state["items"][ALAN]["grab"]["at"] = time.time() - 5 * 3600
        await hunter.watch()
        grab = hunter.state["items"][ALAN]["grab"]
        assert grab["state"] == "downloading" and hunter.state["items"][ALAN]["blocked"] == []
    run(test)


def test_downloaded_then_in_the_library():
    async def test(hunter, fakes):
        await send_best(hunter)
        fakes["downloads"]["1"] = "SUCCESS/ALL"
        await hunter.watch()
        assert hunter.state["items"][ALAN]["grab"]["state"] == "done"
        assert len(fakes["rescans"]) == 1  # the library was asked to scan
        # The library has scanned: the update is there. The next look sees it without a round.
        fakes["library"][0].update(localUpdate=196608, updateMissing=False)
        hunter.state["library"]["fetched"] = 0
        await hunter.watch()
        assert ALAN not in hunter.state["items"]
        assert fakes["telegram"][1:] == ["NSWHunter\nArrived: Alan Wake Remastered (update) is now in the library"]
    run(test, TELEGRAM_BOT_TOKEN="TESTTOKEN", TELEGRAM_CHAT_ID="42")


def test_downloaded_but_never_in_the_library_is_reported_not_retried():
    """Something between the download client and the library is not connected: sending the
    next release would only download more that never arrives."""
    async def test(hunter, fakes):
        first = await send_best(hunter)
        fakes["downloads"]["1"] = "SUCCESS/ALL"
        config.AUTO_DOWNLOAD = "7"
        await hunter.watch()
        hunter.state["items"][ALAN]["grab"]["done_at"] = time.time() - 61 * 60
        await hunter.watch()
        item = hunter.state["items"][ALAN]
        assert item["grab"]["state"] == "stuck" and item["blocked"] == [] and len(fakes["sent"]) == 1
        assert first in [c["guid"] for c in item["candidates"]]
        assert "not in your library" in fakes["telegram"][-1]
        await hunter.watch()
        assert sum("not in your library" in text for text in fakes["telegram"]) == 1  # told once
    run(test, TELEGRAM_BOT_TOKEN="TESTTOKEN", TELEGRAM_CHAT_ID="42")


def test_what_fell_off_is_kept_with_the_reason_and_can_still_be_sent():
    async def test(hunter, fakes):
        await hunter.round()
        fell = {r["title"]: r["reason"] for r in hunter.state["items"][NARUTO]["rejected"]}
        assert fell["NARUTO X BORUTO Ultimate Ninja STORM CONNECTIONS Update v1.7.0 NSW-SUXXORS"] == \
            "v1.7.0 is not newer than your own version"
        hades = hunter.state["items"][HADES]["rejected"]
        assert [r["reason"] for r in hades] == ["for another platform (PS4), not for the Switch"]
        # Releases of other games are not listed as fallen off.
        assert not any("Alan Wake 2" in r["title"] for r in hunter.state["items"][ALAN]["rejected"])
        shown = next(i for i in hunter.view()["items"] if i["key"] == HADES)
        assert shown["rejected"][0]["title"] == "Hades.v1.38.incl.DLC.PS4-CUSA34119"
        assert "downloadUrl" not in shown["rejected"][0]
        await hunter.grab(HADES, hades[0]["guid"])  # the user knows better
        assert fakes["sent"][-1][0] == "Hades.v1.38.incl.DLC.PS4-CUSA34119.nzb"
    run(test)


def test_switch_2_titles_are_left_alone():
    async def test(hunter, fakes):
        await hunter.round()
        assert not any(key.startswith("04") for key in hunter.state["items"])
        assert fakes["queries"].count("hades") == 1  # searched once, for the Switch game
    run(test)


def test_dlc_pack_is_listed_once_per_game():
    async def test(hunter, fakes):
        await hunter.round()
        pack = hunter.state["items"][ALAN + ":pack"]
        assert pack["type"] == "dlcpack" and titles(hunter, ALAN + ":pack") == [
            "Alan Wake Remastered [NSP] [Base + Update 1.0.3 + DLC]"]
        assert "Alan Wake Remastered [NSP] [Base + Update 1.0.3 + DLC]" not in titles(hunter, ALAN_DLC)
        assert hunter.state["library"]["dlc"] == 3  # packs are not counted as missing DLC
    run(test, INCLUDE_DLC=True)


def test_telegram_test_button():
    async def test(hunter, fakes):
        good = {"id": "tg", "type": "telegram", "name": "Telegram", "enabled": True, "bot_token": "TESTTOKEN", "chat_id": "42"}
        assert await hunter.test("CONNECTIONS", good) == "Test message sent"
        assert fakes["telegram"] == ["NSWHunter\nThis is a test message."]
        for values, expected in (({"bot_token": "WRONGTOKEN"}, "bot token is wrong"), ({"chat_id": "7"}, "chat not found"),
                                 ({"chat_id": ""}, "fill in the bot token and the chat ID")):
            with pytest.raises(hunter_module.clients.ServiceError) as error:
                await hunter.test("CONNECTIONS", {**good, **values})
            assert expected in str(error.value) and "TOKEN" not in str(error.value)
    run(test)


def test_wrong_api_key_is_reported_not_raised():
    async def test(hunter, fakes):
        await hunter.round()
        assert hunter.state["services"]["slm"]["ok"] is False
        assert "API key" in hunter.state["services"]["slm"]["text"]
        assert hunter.state["items"] == {}
    run(test, SLM_API_KEY="slm_wrong")


def test_state_survives_a_restart():
    async def test(hunter, fakes):
        await hunter.round()
        again = hunter_module.Hunter(hunter.session)
        assert set(again.state["items"]) == set(hunter.state["items"])
        again.games = hunter.games
        again.reevaluate()
        assert titles(again, ALAN) == titles(hunter, ALAN)
    run(test)


def test_missing_settings_are_listed():
    saved = config.SLM_URL, config.INDEXERS, config.DOWNLOAD_CLIENTS
    try:
        config.SLM_URL, config.INDEXERS, config.DOWNLOAD_CLIENTS = "", [], []
        assert len(config.problems()) == 3
        # An entry that is switched off does not count.
        config.INDEXERS = [{"id": "px", "type": "prowlarr", "name": "Prowlarr", "enabled": False}]
        assert len(config.problems()) == 3
    finally:
        config.SLM_URL, config.INDEXERS, config.DOWNLOAD_CLIENTS = saved


def test_state_of_an_older_version_does_not_stop_the_round():
    """Releases kept by a version that did not know indexer priorities have none."""
    async def test(hunter, fakes):
        await hunter.round()
        for item in hunter.state["items"].values():
            for release in item["candidates"] + item.get("rejected", []):
                del release["priority"]
        await hunter.round()
        await hunter.round()
        assert all(c["priority"] == 10 for c in hunter.state["items"][ALAN]["candidates"])
        assert len(titles(hunter, ALAN)) == 4
    run(test)


def test_failed_download_is_kept_and_can_be_sent_once_more():
    async def test(hunter, fakes):
        first = await send_best(hunter)
        fakes["downloads"]["1"] = "FAILURE/PAR"
        await hunter.watch()
        item = hunter.state["items"][ALAN]
        assert [(f["guid"], f["why"]) for f in item["failed"]] == [
            (first, "the download client reports that the download failed")]
        assert item["grab"] is None and first in item["blocked"]
        shown = next(i for i in hunter.view()["items"] if i["key"] == ALAN)
        assert shown["failed"][0]["title"].startswith("Alan Wake Remastered [0100623017A58800]")
        assert "downloadUrl" not in shown["failed"][0]  # the link holds the Prowlarr key
        # "Try again": the same release goes out once more and is no longer skipped.
        await hunter.grab(ALAN, first)
        assert item["failed"] == [] and first not in item["blocked"] and item["grab"]["guid"] == first
        assert len(fakes["sent"]) == 2
    run(test)


def test_release_unknown_to_the_client_is_listed_as_failed():
    async def test(hunter, fakes):
        first = await send_best(hunter)
        fakes["downloads"].clear()
        hunter.state["items"][ALAN]["grab"]["at"] = time.time() - 61 * 60
        await hunter.watch()
        assert [(f["guid"], f["why"]) for f in hunter.state["items"][ALAN]["failed"]] == [
            (first, "unknown to the download client and not in the library after 60 minutes")]
    run(test)


def test_dismiss_takes_a_failed_download_off_the_list_and_keeps_it_rejected():
    async def test(hunter, fakes):
        first = await send_best(hunter)
        fakes["downloads"]["1"] = "FAILURE/PAR"
        await hunter.watch()
        hunter.dismiss(ALAN, first)
        item = hunter.state["items"][ALAN]
        assert item["failed"] == [] and first in item["blocked"]
        # It moved to what the user rejected, so it can still be restored.
        assert [r["guid"] for r in item["turned_down"]] == [first]
    run(test)


def test_a_round_that_breaks_is_told_and_the_next_good_one_clears_it():
    async def test(hunter, fakes):
        real = hunter.check_services

        async def broken():
            raise TypeError("boom")
        hunter.check_services = broken
        await hunter.round()
        await hunter.round()
        assert hunter.status["error"]["text"] == "Round failed: TypeError('boom')" and not hunter.status["running"]
        assert [e["text"] for e in hunter.state["events"]][:2] == ["Round failed: TypeError('boom')"] * 2
        # Told once, however many rounds break the same way.
        assert [t for t in fakes["telegram"] if "Round failed" in t] == [
            "NSWHunter\nRound failed: TypeError('boom'). The round did not finish; "
            "the Log tab of the panel has the details."]
        hunter.check_services = real
        await hunter.round()
        assert hunter.status["error"] is None and ALAN in hunter.state["items"]
    run(test, TELEGRAM_BOT_TOKEN="TESTTOKEN", TELEGRAM_CHAT_ID="42")


def test_one_game_that_breaks_does_not_stop_the_others(monkeypatch=None):
    async def test(hunter, fakes):
        real = hunter_module.matcher.evaluate

        def picky(game, *args, **kwargs):
            if game.name == "Hades":
                raise ValueError("cannot judge this one")
            return real(game, *args, **kwargs)
        hunter_module.matcher.evaluate = picky
        try:
            await hunter.round()
        finally:
            hunter_module.matcher.evaluate = real
        assert hunter.status["error"] is None and hunter.status["skipped"] > 0
        assert len(titles(hunter, ALAN)) == 4 and titles(hunter, HADES) == []
        skipped = [e["text"] for e in hunter.state["events"] if e["text"].startswith("Skipped")]
        # Written to the log once, not once per release.
        assert skipped == ["Skipped a release of Hades: ValueError('cannot judge this one')"]
    run(test)


def test_a_broken_title_in_the_library_keeps_what_was_known_about_it():
    async def test(hunter, fakes):
        await send_best(hunter)
        fakes["library"][0]["localUpdate"] = "not a number"
        await hunter.round()
        # Not "arrived": the title could not be read, so nothing is concluded from it.
        assert hunter.state["items"][ALAN]["grab"] is not None and hunter.state["arrived"] == []
        assert hunter.status["skipped"] == 1 and HADES in hunter.state["items"]
    run(test)


def test_download_all_sends_the_best_of_each_game_from_a_score():
    async def test(hunter, fakes):
        await hunter.round()
        assert await hunter.grab_best(9) == 2
        sent = sorted(name for name, _, _ in fakes["sent"])
        assert sent == ["Alan Wake Remastered [0100623017A58800][v196608].nsz.nzb",
                        "NARUTO X BORUTO Ultimate Ninja STORM CONNECTIONS Update v1.7.1 NSW-SUXXORS.nzb"]
        # Hades and Scarlet score 7: they wait for a click of their own.
        assert hunter.state["items"][HADES]["grab"] is None
        assert await hunter.grab_best(9) == 0
    run(test)


def test_rejected_release_is_kept_and_can_be_restored():
    async def test(hunter, fakes):
        await hunter.round()
        best = hunter.state["items"][ALAN]["candidates"][0]
        hunter.reject(ALAN, best["guid"])
        item = hunter.state["items"][ALAN]
        assert best["title"] not in titles(hunter, ALAN) and [r["title"] for r in item["turned_down"]] == [best["title"]]
        await hunter.round()  # found again by the search, and still left out
        assert best["title"] not in titles(hunter, ALAN)
        shown = next(i for i in hunter.view()["items"] if i["key"] == ALAN)
        assert shown["turned_down"][0]["title"] == best["title"] and "downloadUrl" not in shown["turned_down"][0]
        hunter.restore(ALAN, best["guid"])
        assert titles(hunter, ALAN)[0] == best["title"] and item["turned_down"] == [] and item["blocked"] == []
    run(test)


def test_rejections_of_an_older_version_are_restored_together():
    async def test(hunter, fakes):
        await hunter.round()
        item = hunter.state["items"][ALAN]
        best = item["candidates"][0]
        item["blocked"].append(best["guid"])  # as an older version left it: the id only
        hunter.reevaluate()
        shown = next(i for i in hunter.view()["items"] if i["key"] == ALAN)
        assert shown["unnamed"] == 1 and best["title"] not in titles(hunter, ALAN)
        hunter.restore(ALAN)
        await hunter.search_game(ALAN)
        assert titles(hunter, ALAN)[0] == best["title"]
    run(test)


def test_progress_of_a_download_is_kept():
    async def test(hunter, fakes):
        await send_best(hunter)
        fakes["progress"]["1"] = (400, 100)
        await hunter.watch()
        grab = hunter.state["items"][ALAN]["grab"]
        assert (grab["state"], grab["percent"]) == ("downloading", 75)
    run(test)


def test_what_arrived_is_remembered():
    async def test(hunter, fakes):
        await send_best(hunter)
        fakes["library"][0].update(localUpdate=196608, updateMissing=False)
        await hunter.round()
        arrived = hunter.view()["arrived"]
        assert [(a["name"], a["what"], a["title"], a["note"]) for a in arrived] == [
            ("Alan Wake Remastered", "update", "Alan Wake Remastered [0100623017A58800][v196608].nsz", "")]
        # Older than thirty days: no longer shown.
        hunter.state["arrived"][0]["at"] -= 31 * 86400
        assert hunter.view()["arrived"] == []
    run(test)


def asked(fakes):
    """(game line, button data) of every question the fake Telegram got."""
    return [(text.split("\n")[1], [b["callback_data"][:2] for b in markup["inline_keyboard"][0]])
            for text, markup in zip(fakes["telegram"], fakes["buttons"]) if markup]


def test_choosing_in_telegram_downloads_and_rejects():
    async def test(hunter, fakes):
        hunter_module.ASK_DELAY = 0
        await hunter.round()
        # One question per item that waits, the highest score first, each asked once.
        assert asked(fakes) == [
            ("Alan Wake Remastered (update)", ["d:", "r:"]),
            ("NARUTO X BORUTO Ultimate Ninja STORM CONNECTIONS (update)", ["d:", "r:"]),
            ("Hades (update)", ["d:", "r:"]), ("Pokémon™ Scarlet (update)", ["d:", "r:"])]
        assert "10/10 · Alan Wake Remastered [0100623017A58800][v196608].nsz" in fakes["telegram"][0]
        await hunter.round()
        assert len(asked(fakes)) == 4
        shown = next(i for i in hunter.view()["items"] if i["key"] == ALAN)
        assert shown["asked"] is True and "ask" not in shown  # the token of the buttons stays inside

        def press(n, button, chat=42):
            data = fakes["buttons"][n]["inline_keyboard"][0][button]["callback_data"]
            fakes["updates"].append({"update_id": 100 + len(fakes["updates"]), "callback_query": {
                "id": "q", "data": data, "message": {"message_id": n + 1, "chat": {"id": chat}}}})

        press(0, 0, chat=666)  # someone else: not obeyed, not even answered
        await hunter.telegram_answers(wait=0)
        assert fakes["sent"] == [] and fakes["answers"] == []
        press(0, 0)  # Download
        press(2, 1)  # Reject for Hades
        await hunter.telegram_answers(wait=0)
        assert [name for name, _, _ in fakes["sent"]] == ["Alan Wake Remastered [0100623017A58800][v196608].nsz.nzb"]
        assert hunter.state["items"][ALAN]["grab"]["title"].startswith("Alan Wake Remastered [")
        assert titles(hunter, HADES) == [] and len(hunter.state["items"][HADES]["turned_down"]) == 1
        assert fakes["answers"] == ["✓ Sent to the download client.", "✕ Rejected."]
        assert fakes["edits"][0]["message_id"] == 1 and fakes["edits"][0]["text"].endswith("✓ Sent to the download client.")
        assert "reply_markup" not in fakes["edits"][0]  # the buttons are gone
        # The same press again, and a press on a question that is settled: nothing happens twice.
        press(0, 0)
        await hunter.telegram_answers(wait=0)
        assert len(fakes["sent"]) == 1 and fakes["answers"][-1] == "This release no longer awaits a choice."
    run(test, TELEGRAM_BOT_TOKEN="TESTTOKEN", TELEGRAM_CHAT_ID="42", TELEGRAM_ASK=True)


def test_telegram_is_not_asked_for_presses_without_an_open_question():
    async def test(hunter, fakes):
        assert await hunter.telegram_answers(wait=0) is False
        await hunter.round()
        assert await hunter.telegram_answers(wait=0) is False  # asking is switched off
    run(test, TELEGRAM_BOT_TOKEN="TESTTOKEN", TELEGRAM_CHAT_ID="42")


def test_dlc_pack_does_not_ask_while_the_dlc_itself_is_on_its_way():
    async def test(hunter, fakes):
        await hunter.round()
        pack = hunter.state["items"][ALAN + ":pack"]
        assert pack["candidates"] and hunter.awaits(pack)
        await hunter.grab(ALAN_DLC, hunter.state["items"][ALAN_DLC]["candidates"][0]["guid"])
        assert not hunter.awaits(pack)
        shown = {i["key"]: i["status"] for i in hunter.view()["items"]}
        assert (shown[ALAN_DLC], shown[ALAN + ":pack"]) == ("sent", "covered")
    run(test, INCLUDE_DLC=True)
