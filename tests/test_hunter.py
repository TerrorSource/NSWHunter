"""A whole round against stand-ins for the library, Prowlarr and NZBGet."""
import asyncio
import os
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


def run(test, **settings):
    """Start the fake services, point the config at them, and run `test(hunter, fakes)`."""
    async def body():
        fakes = make_fakes()
        server = TestServer(fakes)
        await server.start_server()
        base = str(server.make_url("")).rstrip("/")
        values = {
            "SLM_URL": base, "SLM_API_KEY": "slm_test", "PROWLARR_URL": base,
            "PROWLARR_API_KEY": "prowlarr_test", "NZBGET_URL": base, "NZBGET_USER": "nzbget", "NZBGET_PASSWORD": "tegen",
            "DOWNLOAD_CLIENT": "nzbget",
            "DOWNLOAD_CATEGORY": "games", "TITLEDB_VERSIONS_URL": base + "/versions.json",
            "AUTO_DOWNLOAD": "off", "AUTO_BUNDLES": False, "INCLUDE_DLC": False,
            "SEARCH_DELAY_SECONDS": 0, "BACKLOG_PER_RUN": 0, "SEARCH_INTERVAL_HOURS": 24,
            "SEARCH_BY_TITLE_ID": False, "GRAB_WAIT_MINUTES": 60, "WATCH_SECONDS": 120,
            "TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": "", "TELEGRAM_API_URL": base, **settings}
        saved = {k: getattr(config, k) for k in values}
        for path in (config.STATE_FILE, config.VERSIONS_FILE):
            if os.path.exists(path):
                os.remove(path)
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
        assert any(e["text"].startswith("Binnen: Alan Wake Remastered") for e in hunter.state["events"])
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
        good = config.overlay({})
        assert await hunter.test("slm", good) == "8 games in de bibliotheek"
        assert await hunter.test("prowlarr", good) == "Prowlarr 2.0.0, 1 usenet-indexer"
        assert await hunter.test("downloader", good) == "NZBGet 24.5"
        assert await hunter.test("downloader", config.overlay({"DOWNLOAD_CLIENT": "prowlarr"})) == "via Prowlarr: NZBGet"
        for service, values in (("slm", {"SLM_API_KEY": "slm_wrong"}), ("prowlarr", {"PROWLARR_API_KEY": "x"}),
                                ("downloader", {"NZBGET_PASSWORD": "x"}), ("slm", {"SLM_URL": ""})):
            with pytest.raises(hunter_module.clients.ServiceError):
                await hunter.test(service, config.overlay(values))
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
        hunter.priorities = {1: 10, 7: 3, 8: 40}
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
        assert found["score"] == 8 and found["reasons"] == ["naam komt overeen", "naam van de DLC staat in de titel"]
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
        assert any("Er is nog een nieuwere update" in e["text"] for e in hunter.state["events"])
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
        assert any(e["text"].startswith("Niet aangekomen na 60 minuten") for e in hunter.state["events"])
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
        # The first message is from the round: "4 updates of DLC wachten op je keuze".
        assert fakes["telegram"][1].startswith("NSWHunter\nDownload mislukt: Alan Wake Remastered [0100623017A58800]")
        assert any("Vanzelf verstuurd: Alan_Wake" in text for text in fakes["telegram"])
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
        assert fakes["telegram"][1:] == ["NSWHunter\nBinnen: Alan Wake Remastered (update) staat nu in de bibliotheek"]
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
        assert "niet in je bibliotheek" in fakes["telegram"][-1]
        await hunter.watch()
        assert sum("niet in je bibliotheek" in text for text in fakes["telegram"]) == 1  # told once
    run(test, TELEGRAM_BOT_TOKEN="TESTTOKEN", TELEGRAM_CHAT_ID="42")


def test_what_fell_off_is_kept_with_the_reason_and_can_still_be_sent():
    async def test(hunter, fakes):
        await hunter.round()
        fell = {r["title"]: r["reason"] for r in hunter.state["items"][NARUTO]["rejected"]}
        assert fell["NARUTO X BORUTO Ultimate Ninja STORM CONNECTIONS Update v1.7.0 NSW-SUXXORS"] == \
            "v1.7.0 is niet nieuwer dan je eigen versie"
        hades = hunter.state["items"][HADES]["rejected"]
        assert [r["reason"] for r in hades] == ["voor een ander platform (PS4), niet voor de Switch"]
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
        good = config.overlay({"TELEGRAM_BOT_TOKEN": "TESTTOKEN", "TELEGRAM_CHAT_ID": "42"})
        assert await hunter.test("telegram", good) == "Testbericht verstuurd"
        assert fakes["telegram"] == ["NSWHunter\nDit is een testbericht."]
        for values, expected in (({"TELEGRAM_BOT_TOKEN": "WRONGTOKEN", "TELEGRAM_CHAT_ID": "42"}, "bot-token klopt niet"),
                                 ({"TELEGRAM_BOT_TOKEN": "TESTTOKEN", "TELEGRAM_CHAT_ID": "7"}, "chat not found"),
                                 ({"TELEGRAM_BOT_TOKEN": "TESTTOKEN"}, "vul het bot-token en het chat-ID in")):
            with pytest.raises(hunter_module.clients.ServiceError) as error:
                await hunter.test("telegram", config.overlay(values))
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
    saved = config.PROWLARR_API_KEY, config.SLM_URL
    try:
        config.PROWLARR_API_KEY, config.SLM_URL = "", ""
        assert len(config.problems()) >= 2
    finally:
        config.PROWLARR_API_KEY, config.SLM_URL = saved
