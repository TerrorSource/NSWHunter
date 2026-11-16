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
            "SEARCH_BY_TITLE_ID": False, **settings}
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
        assert titles(hunter, ALAN) == [
            "Alan Wake Remastered [0100623017A58800][v196608].nsz",
            "[NSW] Alan Wake Remastered (Update v131072) (EUR)",
            "Alan_Wake_Remastered_Update_v1.0.3_NSW-VENOM",
            "Alan Wake Remastered [NSP] [Base + Update 1.0.3 + DLC]",
        ]
        assert titles(hunter, HADES) == ["Hades_Update_v1.0.2_NSW-GRP"]
        assert hunter.state["items"][HADES]["candidates"][0]["confidence"] == "likely"
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
        assert [name for name, _, _ in fakes["sent"]] == [
            "Alan Wake Remastered [0100623017A58800][v196608].nsz.nzb"]
        assert hunter.state["items"][ALAN]["grab"]["auto"] is True
        assert hunter.state["items"][HADES]["grab"] is None
        # A second round does not send it again.
        await hunter.round()
        assert len(fakes["sent"]) == 1
    run(test, AUTO_DOWNLOAD="sure")


def test_auto_likely_also_sends_display_versions_posted_after_the_latest_update():
    async def test(hunter, fakes):
        await hunter.round()
        assert sorted(name for name, _, _ in fakes["sent"]) == [
            "Alan Wake Remastered [0100623017A58800][v196608].nsz.nzb",
            "Hades_Update_v1.0.2_NSW-GRP.nzb",
            "NARUTO X BORUTO Ultimate Ninja STORM CONNECTIONS Update v1.7.1 NSW-SUXXORS.nzb",
            "Pokemon.Scarlet.Update.v3.0.1.NSW-BigBlueBox.nzb"]
    run(test, AUTO_DOWNLOAD="likely")


def test_display_version_is_matched_to_the_update_by_its_posting_date():
    """The user's real case: releases say v1.7.1, the library says update 11 (v720896)."""
    async def test(hunter, fakes):
        await hunter.round()
        found = hunter.state["items"][NARUTO]["candidates"]
        # v1.7.0 is what the library has; only the three v1.7.1 variants remain, most grabbed first.
        assert [c["title"] for c in found] == [
            "NARUTO X BORUTO Ultimate Ninja STORM CONNECTIONS Update v1.7.1 NSW-SUXXORS",
            "NARUTO X BORUTO Ultimate Ninja STORM CONNECTIONS Update v1.7.1 MULTI4 NSW-SUXXORS",
            "NARUTO X BORUTO ULTIMATE NINJA STORM CONNECTIONS Update v1.7.1 MULTI6 NSW-SUXXORS"]
        assert {(c["confidence"], c["is_latest"], c["estimated_version"]) for c in found} == {
            ("likely", True, 720896)}
        assert any("update 11" in reason for reason in found[0]["reasons"])
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
        assert await hunter.test("slm", good) == "6 games in de bibliotheek"
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


def test_dlc_is_its_own_item():
    async def test(hunter, fakes):
        await hunter.round()
        item = hunter.state["items"][ALAN_DLC]
        assert item["type"] == "dlc" and item["game_id"] == ALAN
        assert titles(hunter, ALAN_DLC)[0] == "Alan Wake Remastered [0100623017A59001][v0] DLC"
        assert item["candidates"][0]["confidence"] == "sure"
        # The DLC release is not offered as the update.
        assert "Alan Wake Remastered [0100623017A59001][v0] DLC" not in titles(hunter, ALAN)
    run(test, INCLUDE_DLC=True)


def test_grab_through_prowlarr():
    async def test(hunter, fakes):
        await hunter.round()
        await hunter.grab(HADES, hunter.state["items"][HADES]["candidates"][0]["guid"])
        assert fakes["grabbed"] == [{"guid": "guid-6", "indexerId": 1}]
        assert fakes["sent"] == []
    run(test, DOWNLOAD_CLIENT="prowlarr")


def test_release_that_never_arrives_is_skipped_next_time():
    async def test(hunter, fakes):
        await hunter.round()
        first = hunter.state["items"][ALAN]["candidates"][0]["guid"]
        await hunter.grab(ALAN, first)
        hunter.state["items"][ALAN]["grab"]["at"] = time.time() - 72 * 3600
        hunter.state["searched"].clear()
        await hunter.round()
        item = hunter.state["items"][ALAN]
        assert item["grab"] is None and first in item["blocked"]
        assert first not in [c["guid"] for c in item["candidates"]]
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
