"""The Configuratie tab: saving, validating and never handing a secret back."""
import asyncio
import base64
import os
import stat

import pytest
from aiohttp.test_utils import TestClient, TestServer

import config
import main


@pytest.fixture(autouse=True)
def clean_settings():
    before = {name: getattr(config, name) for name in config.EDITABLE}
    yield
    for name, value in before.items():
        setattr(config, name, value)
    for path in (config.SETTINGS_FILE, config.STATE_FILE):
        if os.path.exists(path):
            os.remove(path)


def test_update_saves_and_applies():
    changed = config.update({"SLM_URL": "http://nas:3000/", "AUTO_DOWNLOAD": "SURE", "INCLUDE_DLC": True,
                             "SLM_API_KEY": "slm_abc"})
    assert changed == ["AUTO_DOWNLOAD", "INCLUDE_DLC", "SLM_API_KEY", "SLM_URL"]
    # Saving the same form again changes nothing.
    assert config.update({"SLM_URL": "http://nas:3000", "AUTO_DOWNLOAD": "sure", "SLM_API_KEY": ""}) == []
    assert (config.SLM_URL, config.AUTO_DOWNLOAD, config.INCLUDE_DLC) == ("http://nas:3000", "sure", True)
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
    {"TZ": "UTC"},                           # not a setting of the Configuratie tab
    {"SLM_URL": "http://ok", "AUTO_DOWNLOAD": "nee"},
])
def test_wrong_values_change_nothing(values):
    before = config.SLM_URL
    with pytest.raises(ValueError):
        config.update(values)
    assert config.SLM_URL == before and not os.path.exists(config.SETTINGS_FILE)


def test_search_interval_is_a_number_of_hours():
    config.update({"SEARCH_INTERVAL_HOURS": "48"})
    assert config.SEARCH_INTERVAL_HOURS == 48 and config.editable()["values"]["SEARCH_INTERVAL_HOURS"] == 48


def test_api_test_button_reports_instead_of_failing():
    async def test(client):
        r = await client.post("/api/test", json={"service": "prowlarr", "values": {"PROWLARR_URL": ""}})
        data = await r.json()
        assert r.status == 200 and data["ok"] is False and "adres" in data["text"]
        r = await client.post("/api/test", json={"service": "slm", "values": {"SLM_URL": "geen-adres"}})
        assert (await r.json())["ok"] is False
    api(test)


def test_secrets_never_leave():
    config.update({"SLM_API_KEY": "slm_abc", "PANEL_PASSWORD": "pw"})
    shown = config.editable()
    assert "slm_abc" not in str(shown) and "pw" not in str(shown["values"])
    assert shown["secrets"]["SLM_API_KEY"] is True and shown["secrets"]["NZBGET_PASSWORD"] is False


def api(test):
    async def body():
        async with TestClient(TestServer(main.make_app())) as client:
            await test(client)
    asyncio.run(body())


def test_api_saves_and_reports_without_secrets():
    async def test(client):
        r = await client.post("/api/settings", json={
            "values": {"AUTO_DOWNLOAD": "likely", "SLM_API_KEY": "slm_abc", "PROWLARR_API_KEY": ""}})
        text = await r.text()
        data = await r.json()
        assert r.status == 200 and data["ok"] and "slm_abc" not in text
        assert data["values"]["AUTO_DOWNLOAD"] == "likely" and data["secrets"]["SLM_API_KEY"] is True
        assert config.AUTO_DOWNLOAD == "likely"
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


def test_panel_password_works_at_once_and_can_be_removed():
    async def test(client):
        r = await client.post("/api/settings", json={"values": {"PANEL_USER": "hunter", "PANEL_PASSWORD": "pw"}})
        assert r.status == 200
        assert (await client.get("/api/settings")).status == 401
        assert (await client.get("/health")).status == 200
        login = {"Authorization": "Basic " + base64.b64encode(b"hunter:pw").decode()}
        assert (await client.get("/api/settings", headers=login)).status == 200
        wrong = {"Authorization": "Basic " + base64.b64encode(b"hunter:fout").decode()}
        assert (await client.get("/api/settings", headers=wrong)).status == 401
        r = await client.post("/api/settings", json={"values": {}, "clear": ["PANEL_PASSWORD"]}, headers=login)
        assert r.status == 200 and (await client.get("/api/settings")).status == 200
    api(test)
