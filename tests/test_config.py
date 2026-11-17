"""The Configuration tab: saving, validating and never handing a secret back."""
import asyncio
import os
import stat

import aiohttp
import pytest
from aiohttp.test_utils import TestClient, TestServer

import auth
import config
import main


@pytest.fixture(autouse=True)
def clean_settings():
    before = {name: getattr(config, name) for name in config.EDITABLE}
    yield
    for name, value in before.items():
        setattr(config, name, value)
    for path in (config.SETTINGS_FILE, config.STATE_FILE, config.SESSIONS_FILE):
        if os.path.exists(path):
            os.remove(path)
    auth.sessions.clear()
    auth.failures.clear()


def test_update_saves_and_applies():
    changed = config.update({"SLM_URL": "http://nas:3000/", "AUTO_DOWNLOAD": "SURE", "INCLUDE_DLC": True,
                             "SLM_API_KEY": "slm_abc"})
    assert changed == ["AUTO_DOWNLOAD", "INCLUDE_DLC", "SLM_API_KEY", "SLM_URL"]
    # Saving the same form again changes nothing.
    assert config.update({"SLM_URL": "http://nas:3000", "AUTO_DOWNLOAD": "sure", "SLM_API_KEY": ""}) == []
    # "sure" and "likely" are the names from before the scores: 9 and 7.
    assert (config.SLM_URL, config.AUTO_DOWNLOAD, config.INCLUDE_DLC) == ("http://nas:3000", "9", True)
    assert config.auto_min_score() == 9
    # Only the app user can read the file with keys.
    assert stat.S_IMODE(os.stat(config.SETTINGS_FILE).st_mode) == 0o600


def test_saved_settings_come_back_after_a_restart():
    config.update({"PROWLARR_URL": "http://nas:9696", "PROWLARR_API_KEY": "key123", "DOWNLOAD_CLIENT": "sabnzbd"})
    config.PROWLARR_URL, config.PROWLARR_API_KEY, config.DOWNLOAD_CLIENT = "", "", "nzbget"
    config.load_saved()
    assert (config.PROWLARR_URL, config.PROWLARR_API_KEY, config.DOWNLOAD_CLIENT) == (
        "http://nas:9696", "key123", "sabnzbd")


def test_empty_secret_keeps_the_old_one_and_clear_removes_it():
    config.update({"NZBGET_PASSWORD": "geheim"})
    config.update({"NZBGET_PASSWORD": "", "NZBGET_USER": "hunter"})
    assert (config.NZBGET_PASSWORD, config.NZBGET_USER) == ("geheim", "hunter")
    config.update({}, clear=["NZBGET_PASSWORD"])
    assert config.NZBGET_PASSWORD == ""


@pytest.mark.parametrize("values", [
    {"SLM_URL": "nas:3000"},                 # no http://
    {"AUTO_DOWNLOAD": "altijd"},
    {"DOWNLOAD_CLIENT": "transmission"},
    {"PANEL_USER": "a:b"},
    {"PANEL_USER": ""},
    {"SEARCH_INTERVAL_HOURS": "7"},          # only 6, 12, 24 and 48
    {"PROWLARR_CATEGORIES": "console"},      # numbers only
    {"PROWLARR_CATEGORIES": ""},
    {"AUTO_DOWNLOAD": "11"},
    {"TZ": "UTC"},                           # not a setting of the Configuration tab
    {"PANEL_PASSWORD": "short"},             # at least 8 characters
    {"PANEL_HOSTS": "http://nas.example"},   # names only
    {"SLM_URL": "http://ok", "AUTO_DOWNLOAD": "nee"},
])
def test_wrong_values_change_nothing(values):
    before = config.SLM_URL
    with pytest.raises(ValueError):
        config.update(values)
    assert config.SLM_URL == before and not os.path.exists(config.SETTINGS_FILE)


def test_categories_are_a_list_of_numbers():
    import clients
    config.update({"PROWLARR_CATEGORIES": "1000, 4050"})
    assert config.PROWLARR_CATEGORIES == ["1000", "4050"]
    assert config.editable()["values"]["PROWLARR_CATEGORIES"] == "1000,4050"
    # A main category covers its subcategories; a subcategory only itself.
    assert [clients.in_categories(c) for c in (1000, 1090, 1990, 2000, 4050, 4000, 100123)] == [
        True, True, True, False, True, False, False]


def test_search_interval_is_a_number_of_hours():
    config.update({"SEARCH_INTERVAL_HOURS": "48"})
    assert config.SEARCH_INTERVAL_HOURS == 48 and config.editable()["values"]["SEARCH_INTERVAL_HOURS"] == 48


def test_api_test_button_reports_instead_of_failing():
    async def test(client):
        r = await client.post("/api/test", json={"service": "prowlarr", "values": {"PROWLARR_URL": ""}})
        data = await r.json()
        assert r.status == 200 and data["ok"] is False and "address" in data["text"]
        r = await client.post("/api/test", json={"service": "slm", "values": {"SLM_URL": "no-address"}})
        assert (await r.json())["ok"] is False
    api(test)


def test_secrets_never_leave():
    config.update({"SLM_API_KEY": "slm_abc", "PANEL_PASSWORD": "correct horse"})
    shown = config.editable()
    assert "slm_abc" not in str(shown) and "correct horse" not in str(shown)
    assert shown["secrets"]["SLM_API_KEY"] is True and shown["secrets"]["NZBGET_PASSWORD"] is False


def api(test, login=True):
    """Run `test(client)` against the panel; with `login` the client has made a login first."""
    async def body():
        # The test server is an IP address: a browser keeps its cookies, this client must be told to.
        jar = aiohttp.CookieJar(unsafe=True)
        async with TestClient(TestServer(main.make_app()), cookie_jar=jar) as client:
            if login:
                r = await client.post("/api/setup", json={"user": "hunter", "password": "correct horse"})
                assert r.status == 200
            await test(client)
    asyncio.run(body())


def test_api_saves_and_reports_without_secrets():
    async def test(client):
        r = await client.post("/api/settings", json={
            "values": {"AUTO_DOWNLOAD": "likely", "SLM_API_KEY": "slm_abc", "PROWLARR_API_KEY": ""}})
        text = await r.text()
        data = await r.json()
        assert r.status == 200 and data["ok"] and "slm_abc" not in text
        assert data["values"]["AUTO_DOWNLOAD"] == "7" and data["secrets"]["SLM_API_KEY"] is True
        assert config.AUTO_DOWNLOAD == "7"
        # Still incomplete: said so, and nothing was contacted.
        assert data["services"]["config"]["ok"] is False
        assert "slm_abc" not in await (await client.get("/api/settings")).text()
        assert "slm_abc" not in await (await client.get("/api/state")).text()
    api(test)


def test_api_refuses_a_wrong_value():
    async def test(client):
        r = await client.post("/api/settings", json={"values": {"PROWLARR_URL": "ftp://x"}})
        assert r.status == 400 and "http://" in (await r.json())["error"]
        assert config.PROWLARR_URL == ""
    api(test)


def test_panel_password_is_kept_as_a_hash_and_cannot_be_removed():
    config.update({"PANEL_PASSWORD": "hunter2hunter2"})
    assert config.PANEL_PASSWORD.startswith("scrypt$") and "hunter2" not in open(config.SETTINGS_FILE).read()
    assert config.check_password("hunter2hunter2") and not config.check_password("hunter3hunter3")
    with pytest.raises(ValueError):
        config.update({}, clear=["PANEL_PASSWORD"])
    assert config.check_password("hunter2hunter2")


def test_a_saved_key_is_only_sent_to_its_own_address():
    config.update({"PROWLARR_URL": "http://nas:9696", "PROWLARR_API_KEY": "key123",
                   "NZBGET_URL": "http://nas:6789", "NZBGET_PASSWORD": "geheim"})
    # Another host, port or scheme with the saved key: refused, for testing and for saving.
    for elsewhere in ("http://evil.example:9696", "http://nas:9697", "https://nas:9696"):
        with pytest.raises(ValueError, match="PROWLARR_API_KEY: fill it in again"):
            config.overlay({"PROWLARR_URL": elsewhere, "PROWLARR_API_KEY": ""})
        with pytest.raises(ValueError, match="PROWLARR_API_KEY: fill it in again"):
            config.update({"PROWLARR_URL": elsewhere})
    assert config.PROWLARR_URL == "http://nas:9696"
    with pytest.raises(ValueError, match="NZBGET_PASSWORD"):
        config.overlay({"NZBGET_URL": "http://evil.example"})
    # The key typed again, the key emptied, the same server, or no address at all: fine.
    assert config.overlay({"PROWLARR_URL": "http://other:9696", "PROWLARR_API_KEY": "new"}).PROWLARR_API_KEY == "new"
    assert config.overlay({"PROWLARR_URL": "http://other:9696"}, clear=["PROWLARR_API_KEY"]).PROWLARR_API_KEY == ""
    assert config.overlay({"PROWLARR_URL": "http://NAS:9696/prowlarr/"}).PROWLARR_API_KEY == "key123"
    assert config.overlay({"PROWLARR_URL": ""}).PROWLARR_URL == ""
    # An address without a saved key has nothing to give away.
    assert config.overlay({"SLM_URL": "http://anywhere:3000"}).SLM_URL == "http://anywhere:3000"


def test_the_test_button_does_not_send_a_saved_key_elsewhere():
    async def test(client):
        await client.post("/api/settings", json={"values": {"PROWLARR_URL": "http://nas:9696", "PROWLARR_API_KEY": "key123"}})
        r = await client.post("/api/test", json={"service": "prowlarr", "values": {
            "PROWLARR_URL": str(client.make_url("")).rstrip("/"), "PROWLARR_API_KEY": ""}})
        data = await r.json()
        assert data["ok"] is False and "fill it in again" in data["text"]
    api(test)


def test_password_saved_by_an_older_version_is_hashed_at_start():
    config.write({"PANEL_USER": "hunter", "PANEL_PASSWORD": "plain-old"})
    config.load_saved()
    assert config.check_password("plain-old")
    assert "plain-old" not in open(config.SETTINGS_FILE).read()


def test_telegram_and_wait_settings():
    config.update({"TELEGRAM_BOT_TOKEN": "TESTTOKEN", "TELEGRAM_CHAT_ID": "-100123", "GRAB_WAIT_MINUTES": "120"})
    assert (config.TELEGRAM_CHAT_ID, config.GRAB_WAIT_MINUTES) == ("-100123", 120)
    shown = config.editable()
    assert shown["secrets"]["TELEGRAM_BOT_TOKEN"] is True and "TESTTOKEN" not in str(shown)
    for wrong in ({"TELEGRAM_CHAT_ID": "mijn chat"}, {"GRAB_WAIT_MINUTES": "45"}):
        with pytest.raises(ValueError):
            config.update(wrong)
