"""The settings: saving, validating, the lists of providers, and never handing a secret back."""
import asyncio
import json
import os
import shutil
import stat
import zipfile

import aiohttp
import pytest
from aiohttp.test_utils import TestClient, TestServer

import auth
import config
import main

LISTS = ("INDEXERS", "DOWNLOAD_CLIENTS", "CONNECTIONS", "INITIAL_PASSWORD")
LOGIN = {"user": "hunter", "password": "correct horse"}


@pytest.fixture(autouse=True)
def clean_settings():
    before = {name: getattr(config, name) for name in (*config.EDITABLE, *LISTS)}
    yield
    for name, value in before.items():
        setattr(config, name, value)
    for path in (config.SETTINGS_FILE, config.STATE_FILE, config.SESSIONS_FILE, config.INITIAL_PASSWORD_FILE):
        if os.path.exists(path):
            os.remove(path)
    shutil.rmtree(os.path.join(config.DATA_DIR, "backups"), ignore_errors=True)
    auth.sessions.clear()
    auth.failures.clear()


def api(test, login=True):
    """Run `test(client)` against the panel; with `login` the client is logged in as hunter."""
    async def body():
        config.PANEL_USER, config.PANEL_PASSWORD = "hunter", config.hash_password("correct horse")
        config.INITIAL_PASSWORD, config.BACKUP_FOLDER = None, "backups"
        # The test server is an IP address: a browser keeps its cookies, this client must be told to.
        jar = aiohttp.CookieJar(unsafe=True)
        async with TestClient(TestServer(main.make_app()), cookie_jar=jar) as client:
            if login:
                assert (await client.post("/api/login", json=LOGIN)).status == 200
            await test(client)
    asyncio.run(body())


# ---------------------------------------------------------------- single settings


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


def test_empty_secret_keeps_the_old_one_and_clear_removes_it():
    config.update({"SLM_API_KEY": "geheim"})
    config.update({"SLM_API_KEY": "", "PANEL_USER": "hunter"})
    assert (config.SLM_API_KEY, config.PANEL_USER) == ("geheim", "hunter")
    config.update({}, clear=["SLM_API_KEY"])
    assert config.SLM_API_KEY == ""


@pytest.mark.parametrize("values", [
    {"SLM_URL": "nas:3000"},                 # no http://
    {"AUTO_DOWNLOAD": "altijd"},
    {"PANEL_USER": "a:b"},
    {"PANEL_USER": ""},
    {"SEARCH_INTERVAL_HOURS": "7"},          # only 6, 12, 24 and 48
    {"AUTO_DOWNLOAD": "11"},
    {"TZ": "UTC"},                           # not a setting of the panel
    {"PROWLARR_URL": "http://nas:9696"},     # an indexer is an entry of a list now
    {"PANEL_PASSWORD": "short"},             # at least 8 characters
    {"PANEL_HOSTS": "http://nas.example"},   # names only
    {"LOG_LEVEL": "loud"},
    {"LOG_SIZE_MB": "3"},
    {"BACKUP_INTERVAL_DAYS": "0"},
    {"BACKUP_RETENTION_DAYS": "400"},
    {"BACKUP_FOLDER": "../elsewhere"},
    {"BACKUP_FOLDER": ""},
    {"UI_THEME": "pink"},
    {"SLM_URL": "http://ok", "AUTO_DOWNLOAD": "nee"},
])
def test_wrong_values_change_nothing(values):
    before = config.SLM_URL
    with pytest.raises(ValueError):
        config.update(values)
    assert config.SLM_URL == before and not os.path.exists(config.SETTINGS_FILE)


def test_numbers_and_choices_of_the_new_pages():
    config.update({"SEARCH_INTERVAL_HOURS": "48", "LOG_LEVEL": "Trace", "LOG_SIZE_MB": "5", "BACKUP_FOLDER": "/backup",
                   "BACKUP_INTERVAL_DAYS": "3", "BACKUP_RETENTION_DAYS": 60, "UI_THEME": "dark",
                   "UI_DATE_FORMAT": "iso", "UI_TIME_FORMAT": "24", "UI_RELATIVE_DATES": False})
    shown = config.editable()["values"]
    assert (shown["SEARCH_INTERVAL_HOURS"], shown["LOG_LEVEL"], shown["LOG_SIZE_MB"]) == (48, "trace", 5)
    assert (shown["BACKUP_INTERVAL_DAYS"], shown["BACKUP_RETENTION_DAYS"], shown["UI_RELATIVE_DATES"]) == (3, 60, False)


def test_panel_password_is_kept_as_a_hash_and_cannot_be_removed():
    config.update({"PANEL_PASSWORD": "hunter2hunter2"})
    assert config.PANEL_PASSWORD.startswith("scrypt$") and "hunter2" not in open(config.SETTINGS_FILE).read()
    assert config.check_password("hunter2hunter2") and not config.check_password("hunter3hunter3")
    with pytest.raises(ValueError):
        config.update({}, clear=["PANEL_PASSWORD"])
    assert config.check_password("hunter2hunter2")


def test_password_saved_by_an_older_version_is_hashed_at_start():
    config.write({"PANEL_USER": "hunter", "PANEL_PASSWORD": "plain-old"})
    config.load_saved()
    assert config.check_password("plain-old")
    assert "plain-old" not in open(config.SETTINGS_FILE).read()


def test_a_saved_library_key_is_only_sent_to_its_own_address():
    config.update({"SLM_URL": "http://nas:3000", "SLM_API_KEY": "slm_key"})
    for elsewhere in ("http://evil.example:3000", "http://nas:3001", "https://nas:3000"):
        with pytest.raises(ValueError, match="SLM_API_KEY: fill it in again"):
            config.overlay({"SLM_URL": elsewhere, "SLM_API_KEY": ""})
        with pytest.raises(ValueError, match="SLM_API_KEY: fill it in again"):
            config.update({"SLM_URL": elsewhere})
    assert config.SLM_URL == "http://nas:3000"
    # The key typed again, the key emptied, the same server, or no address at all: fine.
    assert config.overlay({"SLM_URL": "http://other:3000", "SLM_API_KEY": "new"}).SLM_API_KEY == "new"
    assert config.overlay({"SLM_URL": "http://other:3000"}, clear=["SLM_API_KEY"]).SLM_API_KEY == ""
    assert config.overlay({"SLM_URL": "http://NAS:3000/slm/"}).SLM_API_KEY == "slm_key"
    assert config.overlay({"SLM_URL": ""}).SLM_URL == ""


# ---------------------------------------------------------------- the made-up password of the first start


def test_first_start_makes_up_a_password_and_shows_it_until_it_is_changed():
    config.PANEL_USER, config.PANEL_PASSWORD = "admin", ""
    first = config.first_login()
    assert first and len(first) >= 12 and config.check_password(first) and config.must_change_password()
    assert stat.S_IMODE(os.stat(config.INITIAL_PASSWORD_FILE).st_mode) == 0o600
    # The settings file holds the hash only; the readable password is in a file of its own.
    assert first not in open(config.SETTINGS_FILE).read()
    # A restart before it was changed: the same password again.
    config.PANEL_PASSWORD, config.INITIAL_PASSWORD = "", None
    config.load_saved()
    assert config.first_login() == first and config.must_change_password()
    # The user chooses one: the made-up one is gone and is not shown again.
    config.update({"PANEL_USER": "hunter", "PANEL_PASSWORD": "a password of my own"})
    assert not config.must_change_password() and not os.path.exists(config.INITIAL_PASSWORD_FILE)
    config.PANEL_PASSWORD, config.INITIAL_PASSWORD = "", None
    config.load_saved()
    assert config.first_login() is None and config.PANEL_USER == "hunter" and config.check_password("a password of my own")


def test_a_password_set_another_way_is_not_made_up_again():
    config.PANEL_PASSWORD = config.hash_password("from the compose file")
    assert config.first_login() is None and not config.must_change_password()
    assert not os.path.exists(config.INITIAL_PASSWORD_FILE)
    # A file left behind by an earlier made-up password does not bring that password back.
    with open(config.INITIAL_PASSWORD_FILE, "w") as f:
        f.write("an-old-made-up-one")
    assert config.first_login() is None and not config.must_change_password()


# ---------------------------------------------------------------- indexers, download clients, connections

PROWLARR = {"type": "prowlarr", "name": "My Prowlarr", "url": "http://nas:9696/", "api_key": "key123", "categories": "1000, 4050"}


def test_an_entry_is_saved_in_the_shape_the_app_uses():
    saved = config.save_provider("INDEXERS", PROWLARR)
    assert saved == {"id": saved["id"], "type": "prowlarr", "name": "My Prowlarr", "enabled": True,
                     "url": "http://nas:9696", "api_key": "key123", "categories": ["1000", "4050"]}
    assert config.indexers() == [saved] and json.load(open(config.SETTINGS_FILE))["INDEXERS"] == [saved]
    # Changing it keeps its id and its place; an empty key keeps the saved one.
    again = config.save_provider("INDEXERS", {**saved, "name": "Prowlarr", "api_key": "", "enabled": False})
    assert again["id"] == saved["id"] and again["api_key"] == "key123" and config.providers("INDEXERS") == [again]
    assert config.indexers() == []  # switched off
    cleared = config.save_provider("INDEXERS", {**again, "api_key": "", "clear": ["api_key"]})
    assert cleared["api_key"] == ""
    config.delete_provider("INDEXERS", saved["id"])
    assert config.providers("INDEXERS") == []


def test_the_panel_never_gets_a_secret_of_an_entry():
    config.save_provider("INDEXERS", PROWLARR)
    config.save_provider("CONNECTIONS", {"type": "discord", "webhook": "https://discord.com/api/webhooks/1/secret-part"})
    config.save_provider("CONNECTIONS", {"type": "telegram", "bot_token": "", "chat_id": "42"})
    shown = config.editable()
    assert "key123" not in str(shown) and "secret-part" not in str(shown)
    assert shown["providers"]["INDEXERS"][0]["secrets"] == {"api_key": True}
    assert [c["secrets"] for c in shown["providers"]["CONNECTIONS"]] == [{"webhook": True}, {"bot_token": False}]
    assert shown["schema"]["DOWNLOAD_CLIENTS"]["qbittorrent"]["protocol"] == "torrent"


@pytest.mark.parametrize("kind, entry, why", [
    ("INDEXERS", {"type": "jackett", "url": "http://nas"}, "Unknown type"),
    ("INDEXERS", {"type": "prowlarr", "url": ""}, "fill in the address"),
    ("INDEXERS", {"type": "prowlarr", "url": "nas:9696"}, "http://"),
    ("INDEXERS", {"type": "newznab", "url": "http://indexer", "categories": "console"}, "numbers"),
    ("INDEXERS", {"type": "newznab", "url": "http://indexer", "priority": "0"}, "1 to 50"),
    ("DOWNLOAD_CLIENTS", {"type": "deluge", "url": "http://nas"}, "Unknown type"),
    ("CONNECTIONS", {"type": "discord", "webhook": "http://discord.com/api/webhooks/1/x"}, "https://"),
    ("CONNECTIONS", {"type": "telegram", "chat_id": "my chat"}, "chat ID"),
    ("PLUGINS", {"type": "x"}, "Invalid request"),
])
def test_a_wrong_entry_is_refused(kind, entry, why):
    with pytest.raises(ValueError, match=why):
        config.save_provider(kind, entry)
    assert not os.path.exists(config.SETTINGS_FILE)


def test_a_saved_key_of_an_entry_is_only_sent_to_its_own_address():
    saved = config.save_provider("INDEXERS", PROWLARR)
    nzbget = config.save_provider("DOWNLOAD_CLIENTS", {"type": "nzbget", "url": "http://nas:6789", "username": "u", "password": "geheim"})
    with pytest.raises(ValueError, match="fill in the api key again"):
        config.normalize_entry("INDEXERS", {**saved, "url": "http://evil.example:9696", "api_key": ""})
    with pytest.raises(ValueError, match="fill in the password again"):
        config.save_provider("DOWNLOAD_CLIENTS", {**nzbget, "url": "http://evil.example", "password": ""})
    assert config.DOWNLOAD_CLIENTS[0]["url"] == "http://nas:6789"
    # Typed again, the same server, or without a saved key: fine.
    assert config.normalize_entry("INDEXERS", {**saved, "url": "http://other:9696", "api_key": "new"})["api_key"] == "new"
    assert config.normalize_entry("INDEXERS", {**saved, "url": "http://nas:9696/prowlarr", "api_key": ""})["api_key"] == "key123"
    # A new entry cannot borrow the key of another by naming its id with another type.
    with pytest.raises(ValueError, match="type"):
        config.normalize_entry("INDEXERS", {**saved, "type": "newznab", "url": "http://evil.example", "api_key": ""})


def test_which_download_client_takes_a_release():
    def client(type_, **more):
        return config.save_provider("DOWNLOAD_CLIENTS", {"type": type_, "url": "http://nas", **more})
    assert config.client_for("usenet") is None and not config.wants_torrents()
    own = config.save_provider("DOWNLOAD_CLIENTS", {"type": "prowlarr"})
    # The download client of Prowlarr only takes usenet releases that a Prowlarr found.
    assert config.client_for("usenet", "prowlarr") == own and config.client_for("usenet", "newznab") is None
    assert config.client_for("torrent", "prowlarr") is None and not config.wants_torrents()
    sab, off, qbt = client("sabnzbd"), client("nzbget", enabled=False), client("qbittorrent")
    client("transmission")
    assert config.client_for("usenet", "newznab") == sab and config.client_for("torrent") == qbt
    assert config.wants_torrents() and off not in config.download_clients()


OLD_SETTINGS = {
    "SLM_URL": "http://nas:3000", "SLM_API_KEY": "slm_key", "PROWLARR_URL": "http://nas:9696", "PROWLARR_API_KEY": "pkey",
    "PROWLARR_CATEGORIES": ["1000", "1090"], "DOWNLOAD_CLIENT": "sabnzbd", "DOWNLOAD_CATEGORY": "switch",
    "NZBGET_URL": "http://nas:6789", "NZBGET_USER": "nzbget", "NZBGET_PASSWORD": "npass",
    "SABNZBD_URL": "http://nas:8080", "SABNZBD_API_KEY": "skey", "AUTO_DOWNLOAD": "9",
    "TELEGRAM_BOT_TOKEN": "123:token", "TELEGRAM_CHAT_ID": "42", "TELEGRAM_ASK": True, "PANEL_USER": "hunter",
}


def test_settings_of_a_version_with_one_of_each_become_entries():
    with open(config.SETTINGS_FILE, "w") as f:
        json.dump(OLD_SETTINGS, f)
    config.load_saved()
    assert [(i["type"], i["url"], i["api_key"], i["categories"]) for i in config.INDEXERS] == [
        ("prowlarr", "http://nas:9696", "pkey", ["1000", "1090"])]
    # Both clients are kept; the one that was chosen is the one that is switched on.
    assert [(c["type"], c["enabled"], c["category"]) for c in config.DOWNLOAD_CLIENTS] == [
        ("nzbget", False, "switch"), ("sabnzbd", True, "switch")]
    assert config.DOWNLOAD_CLIENTS[0]["password"] == "npass" and config.DOWNLOAD_CLIENTS[1]["api_key"] == "skey"
    assert [(c["type"], c["bot_token"], c["chat_id"], c["ask"]) for c in config.CONNECTIONS] == [
        ("telegram", "123:token", "42", True)]
    assert (config.SLM_URL, config.AUTO_DOWNLOAD, config.PANEL_USER) == ("http://nas:3000", "9", "hunter")
    kept = json.load(open(config.SETTINGS_FILE))
    assert "PROWLARR_URL" not in kept and "NZBGET_PASSWORD" not in kept and len(kept["DOWNLOAD_CLIENTS"]) == 2
    # The next start reads the lists as they are: the same ids, nothing made twice.
    ids = [e["id"] for kind in config.KINDS for e in getattr(config, kind)]
    config.load_saved()
    assert [e["id"] for kind in config.KINDS for e in getattr(config, kind)] == ids


def test_environment_variables_of_an_older_compose_file_become_entries(monkeypatch):
    monkeypatch.setenv("PROWLARR_URL", "http://nas:9696/")
    monkeypatch.setenv("PROWLARR_API_KEY", "from-env")
    monkeypatch.setenv("DOWNLOAD_CLIENT", "prowlarr")
    monkeypatch.setenv("NOTIFY_URLS", "ntfy://ntfy.sh/topic")
    config.load_saved()
    assert [(i["type"], i["url"], i["api_key"]) for i in config.INDEXERS] == [("prowlarr", "http://nas:9696", "from-env")]
    assert [c["type"] for c in config.DOWNLOAD_CLIENTS] == ["prowlarr"]
    assert [(c["type"], c["urls"]) for c in config.CONNECTIONS] == [("apprise", "ntfy://ntfy.sh/topic")]
    # Once the lists exist, the environment no longer adds to them.
    config.delete_provider("INDEXERS", config.INDEXERS[0]["id"])
    config.load_saved()
    assert config.INDEXERS == []


def test_a_broken_entry_in_the_file_does_not_cost_the_others():
    config.write({"INDEXERS": [{"type": "prowlarr", "url": "not an address"}, {"id": "ok1", **PROWLARR}, "nonsense"]})
    config.load_saved()
    assert [i["id"] for i in config.INDEXERS] == ["ok1"]


# ---------------------------------------------------------------- through the panel


def test_api_saves_and_reports_without_secrets():
    async def test(client):
        r = await client.post("/api/settings", json={"values": {"AUTO_DOWNLOAD": "likely", "SLM_API_KEY": "slm_abc"}})
        text = await r.text()
        data = await r.json()
        assert r.status == 200 and data["ok"] and "slm_abc" not in text
        assert data["values"]["AUTO_DOWNLOAD"] == "7" and data["secrets"]["SLM_API_KEY"] is True
        assert config.AUTO_DOWNLOAD == "7"
        assert "slm_abc" not in await (await client.get("/api/settings")).text()
        state = await (await client.get("/api/state")).json()
        assert "slm_abc" not in str(state) and state["configured"] is False and len(state["missing"]) == 3
    api(test)


def test_api_refuses_a_wrong_value():
    async def test(client):
        r = await client.post("/api/settings", json={"values": {"SLM_URL": "ftp://x"}})
        assert r.status == 400 and "http://" in (await r.json())["error"]
        assert config.SLM_URL == ""
    api(test)


def test_api_test_buttons_report_instead_of_failing():
    async def test(client):
        r = await client.post("/api/test", json={"values": {"SLM_URL": ""}})
        data = await r.json()
        assert r.status == 200 and data["ok"] is False and "address" in data["text"]
        r = await client.post("/api/provider/test", json={"kind": "INDEXERS", "entry": {"type": "prowlarr", "url": "x"}})
        assert (await r.json())["ok"] is False
        # A saved key is not tested against another address.
        config.save_provider("INDEXERS", {"id": "ignored", **PROWLARR})
        saved = config.INDEXERS[0]
        r = await client.post("/api/provider/test", json={"kind": "INDEXERS", "entry": {
            **saved, "url": str(client.make_url("")).rstrip("/"), "api_key": ""}})
        data = await r.json()
        assert data["ok"] is False and "fill in the api key again" in data["text"]
    api(test)


def test_api_adds_changes_and_removes_an_entry():
    async def test(client):
        r = await client.post("/api/provider", json={"kind": "DOWNLOAD_CLIENTS", "entry": {
            "type": "nzbget", "name": "NZBGet", "url": "http://127.0.0.1:1", "username": "u", "password": "geheim"}})
        text, data = await r.text(), await r.json()
        # Saved, tested at once, and the test said it does not answer.
        assert r.status == 200 and data["tested"] is False and "geheim" not in text
        entry = data["providers"]["DOWNLOAD_CLIENTS"][0]
        assert entry["secrets"] == {"password": True} and config.DOWNLOAD_CLIENTS[0]["password"] == "geheim"
        state = await (await client.get("/api/state")).json()
        assert state["services"]["DOWNLOAD_CLIENTS:" + entry["id"]]["ok"] is False and "geheim" not in str(state)
        r = await client.post("/api/provider", json={"kind": "DOWNLOAD_CLIENTS", "entry": {**entry, "enabled": False}})
        assert (await r.json())["tested"] is None and config.DOWNLOAD_CLIENTS[0]["password"] == "geheim"
        state = await (await client.get("/api/state")).json()
        assert "DOWNLOAD_CLIENTS:" + entry["id"] not in state["services"]  # switched off: nothing to say
        r = await client.post("/api/provider", json={"kind": "DOWNLOAD_CLIENTS", "entry": {"type": "nzbget", "url": ""}})
        assert r.status == 400 and "address" in (await r.json())["error"]
        r = await client.post("/api/provider/delete", json={"kind": "DOWNLOAD_CLIENTS", "id": entry["id"]})
        assert (await r.json())["providers"]["DOWNLOAD_CLIENTS"] == [] and config.DOWNLOAD_CLIENTS == []
    api(test)


def test_api_backups_are_made_listed_downloaded_put_back_and_removed():
    async def test(client):
        config.update({"AUTO_DOWNLOAD": "9"})
        data = await (await client.post("/api/backup", json={"action": "create"})).json()
        assert data["ok"] and len(data["backups"]) == 1 and data["backups"][0]["kind"] == "manual"
        name = data["backups"][0]["name"]
        r = await client.get("/api/backup/download", params={"name": name})
        assert r.status == 200 and r.headers["Content-Type"] == "application/zip"
        with open(os.path.join(config.DATA_DIR, "downloaded.zip"), "wb") as f:
            f.write(await r.read())
        assert "settings.json" in zipfile.ZipFile(os.path.join(config.DATA_DIR, "downloaded.zip")).namelist()
        os.remove(os.path.join(config.DATA_DIR, "downloaded.zip"))
        # Something changes; putting the backup back undoes it, at once.
        config.update({"AUTO_DOWNLOAD": "off"})
        data = await (await client.post("/api/backup", json={"action": "restore", "name": name})).json()
        assert data["ok"] and config.AUTO_DOWNLOAD == "9"
        assert (await client.get("/api/state")).status == 200  # still logged in
        for wrong in ("../settings.json", "nswhunter_backup_manual_v1.0.0_2026.01.01_00.00.00.zip", ""):
            r = await client.post("/api/backup", json={"action": "restore", "name": wrong})
            assert r.status == 400
            assert (await client.get("/api/backup/download", params={"name": wrong})).status == 404
        data = await (await client.post("/api/backup", json={"action": "delete", "name": name})).json()
        assert data["backups"] == []
    api(test)


def test_api_lists_the_games_of_the_library():
    async def test(client):
        hunter = client.server.app["hunter"]
        hunter.state["games"] = [{"id": "0100AAAA0000A000", "name": "Hades", "update_missing": True}]
        assert (await (await client.get("/api/games")).json())["games"][0]["name"] == "Hades"
    api(test)


def test_a_connection_has_triggers_that_are_on_unless_switched_off():
    saved = config.save_provider("CONNECTIONS", {"type": "telegram", "bot_token": "t", "chat_id": "42", "on_fail": False})
    assert [saved[t] for t in config.TRIGGERS] == [True, True, False, True, True]
    # An entry of an older version has no triggers: at the next start it gets them, all on.
    config.write({"CONNECTIONS": [{"id": "old1", "type": "discord", "webhook": "https://discord.com/api/webhooks/1/x"}]})
    config.load_saved()
    assert all(config.CONNECTIONS[0][t] is True for t in config.TRIGGERS) and config.CONNECTIONS[0]["id"] == "old1"


def test_api_history_search_all_test_all_and_log_files():
    async def test(client):
        hunter = client.server.app["hunter"]
        hunter.state["history"] = [{"at": 1, "kind": "grabbed", "name": "Hades", "what": "update", "title": "Hades Update"}]
        assert (await (await client.get("/api/history")).json())["history"][0]["title"] == "Hades Update"
        hunter.state["searched"] = {"0100AAAA0000A000": 5}
        assert (await (await client.post("/api/search-all", json={})).json())["ok"] and hunter.state["searched"] == {}
        assert (await (await client.post("/api/test-all", json={})).json())["ok"]
        # The log files: listed, downloaded by name, and nothing else reached through a name.
        saved = config.LOG_DIR
        config.LOG_DIR = os.path.join(config.DATA_DIR, "logs-api")
        os.makedirs(config.LOG_DIR, exist_ok=True)
        try:
            for name, text in (("nswhunter.txt", "newest"), ("nswhunter.txt.1", "older"), ("notes.txt", "not a log")):
                with open(os.path.join(config.LOG_DIR, name), "w") as f:
                    f.write(text)
            data = await (await client.get("/api/logfiles")).json()
            assert [f["name"] for f in data["files"]] == ["nswhunter.txt", "nswhunter.txt.1"] and data["files"][0]["size"] == 6
            r = await client.get("/api/logfile", params={"name": "nswhunter.txt.1"})
            assert r.status == 200 and await r.text() == "older" and "attachment" in r.headers["Content-Disposition"]
            for wrong in ("notes.txt", "../settings.json", "nswhunter.txt.22", ""):
                assert (await client.get("/api/logfile", params={"name": wrong})).status == 404
        finally:
            shutil.rmtree(config.LOG_DIR, ignore_errors=True)
            config.LOG_DIR = saved
    api(test)
