"""The login of the panel, its sessions, and what the panel refuses to answer."""
import asyncio
import os
import time

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

import auth
import clients
import config
import indexers
import main
from test_config import LOGIN, api, clean_settings  # noqa: F401  (the fixture puts the settings back)


def test_first_login_with_the_made_up_password_can_only_choose_a_new_one():
    async def test(client):
        config.PANEL_USER, config.PANEL_PASSWORD = "admin", ""
        made_up = config.first_login()
        r = await client.get("/api/state")
        assert r.status == 401 and await r.json() == {"ok": False, "error": "Login required", "login": True}
        # The page itself holds no data and is needed to show the login screen.
        page = await client.get("/")
        assert page.status == 200 and "authform" in await page.text() and made_up not in await page.text()
        assert (await client.post("/api/login", json={"user": "admin", "password": made_up})).status == 200
        assert (await (await client.get("/api/session")).json())["change"] is True
        # Logged in, and still nothing works but choosing a password.
        for path in ("/api/state", "/api/settings", "/api/log", "/api/games", "/api/backups"):
            r = await client.get(path)
            assert r.status == 403 and (await r.json())["change"] is True
        assert (await client.post("/api/sync", json={})).status == 403
        for wrong, why in (({"user": "hunter", "password": "short"}, "at least 8"),
                           ({"user": "", "password": "correct horse"}, "name"),
                           ({"user": "hunter", "password": ""}, "password"),
                           ({"user": "hunter", "password": made_up}, "another password")):
            r = await client.post("/api/password", json=wrong)
            assert r.status == 400 and why in (await r.json())["error"]
        assert config.must_change_password()
        assert (await client.post("/api/password", json=LOGIN)).status == 200
        assert (await client.get("/api/state")).status == 200 and not config.must_change_password()
        # The name was changed too, and the made-up password is worth nothing now.
        assert config.PANEL_USER == "hunter" and not os.path.exists(config.INITIAL_PASSWORD_FILE)
        await client.post("/api/logout", json={})
        assert (await client.post("/api/login", json={"user": "admin", "password": made_up})).status == 401
        assert (await client.post("/api/login", json=LOGIN)).status == 200
    api(test, login=False)


def test_choosing_a_password_needs_a_login():
    async def test(client):
        r = await client.post("/api/password", json={"user": "eve", "password": "taken over now"})
        assert r.status == 401 and config.PANEL_USER == "hunter"
    api(test, login=False)


def test_login_and_logout():
    async def test(client):
        await client.post("/api/logout", json={})
        assert (await client.get("/api/state")).status == 401
        for wrong in ({"user": "hunter", "password": "wrong horse"}, {"user": "eve", "password": "correct horse"}):
            r = await client.post("/api/login", json=wrong)
            assert r.status == 401 and (await r.json())["error"] == "Wrong username or password"
        r = await client.post("/api/login", json=LOGIN)
        assert r.status == 200
        cookie = r.cookies[auth.COOKIE]
        assert cookie["httponly"] and cookie["samesite"] == "Strict" and cookie["path"] == "/"
        assert (await client.get("/api/state")).status == 200
        # No pop-up of the browser: the panel never asks for Basic authentication.
        assert "WWW-Authenticate" not in (await client.get("/api/state")).headers
    api(test)


def test_wrong_logins_have_to_wait():
    async def test(client):
        await client.post("/api/logout", json={})
        for _ in range(auth.FREE_TRIES):
            assert (await client.post("/api/login", json={"user": "hunter", "password": "guess"})).status == 401
        # Now even the right password has to wait.
        r = await client.post("/api/login", json=LOGIN)
        assert r.status == 429 and 0 < (await r.json())["wait"] <= 30
        address = next(iter(auth.failures))
        auth.failures[address] = (auth.FREE_TRIES, time.time() - 31)
        assert (await client.post("/api/login", json={"user": "hunter", "password": "guess"})).status == 401
        assert 30 < auth.wait_for(address) <= 60  # every next wrong login doubles the wait
        auth.failures[address] = (auth.FREE_TRIES + 1, time.time() - 61)
        assert (await client.post("/api/login", json=LOGIN)).status == 200 and auth.failures == {}
    api(test)


def test_a_new_password_logs_the_other_browsers_out():
    async def test(client):
        other = auth.start()
        r = await client.post("/api/settings", json={"values": {"PANEL_PASSWORD": "a better horse"}})
        assert r.status == 200 and not auth.valid(other)
        assert (await client.get("/api/state")).status == 200  # this browser stays logged in
        assert config.check_password("a better horse")
    api(test)


def test_sessions_survive_a_restart_as_hashes():
    token = auth.start()
    assert token not in open(config.SESSIONS_FILE).read()
    auth.sessions.clear()
    auth.load()
    assert auth.valid(token) and not auth.valid("something else") and not auth.valid("")
    auth.end(token)
    auth.load()
    assert not auth.valid(token)


@pytest.mark.parametrize("host, allowed", [
    ("192.168.1.10:3033", True), ("127.0.0.1", True), ("[::1]:3033", True), ("localhost:3033", True),
    ("nas:3033", True), ("server.local", True), ("nas.lan:3033", True), ("NAS.home.arpa", True),
    ("evil.example.com:3033", False), ("rebind.attacker.net", False), ("local.attacker.net", False), ("", False),
    ("panel.example.com", True), ("PANEL.example.com:443", True),  # named in PANEL_HOSTS
])
def test_which_host_names_the_panel_answers_to(host, allowed):
    config.PANEL_HOSTS = "panel.example.com"
    assert auth.host_allowed(host) is allowed


def test_panel_refuses_foreign_host_names_and_other_sites():
    async def test(client):
        r = await client.get("/api/state", headers={"Host": "rebind.attacker.net:3033"})
        assert r.status == 403 and "rebind.attacker.net" in await r.text()
        assert (await client.get("/", headers={"Host": "rebind.attacker.net"})).status == 403
        assert (await client.get("/health", headers={"Host": "anything.example"})).status == 200
        # A page of another site that lets the browser post here: the browser says where it comes from.
        r = await client.post("/api/sync", json={}, headers={"Origin": "http://evil.example"})
        assert r.status == 403
        own = str(client.make_url("")).rstrip("/")
        assert (await client.post("/api/sync", json={}, headers={"Origin": own})).status == 200
        # And a form of another site cannot send JSON at all.
        assert (await client.post("/api/sync", data={"a": "b"})).status == 415
    api(test)


def test_every_answer_has_the_security_headers():
    async def test(client):
        for path in ("/", "/api/state", "/api/session"):
            headers = (await client.get(path)).headers
            policy = headers["Content-Security-Policy"]
            assert "default-src 'none'" in policy and "frame-ancestors 'none'" in policy and "unsafe" not in policy
            assert headers["X-Frame-Options"] == "DENY" and headers["X-Content-Type-Options"] == "nosniff"
            assert headers["Referrer-Policy"] == "no-referrer" and headers["Cache-Control"] == "no-store"
        # The page has no script or style that the policy does not name, and loads nothing from elsewhere.
        page = main.PANEL
        assert page.count("<script") == 1 and page.count("<style") == 1 and " style=" not in page
        assert "onclick=" not in page and "src=" not in page
    api(test)


def test_health_turns_red_when_a_round_broke():
    async def test(client):
        hunter = client.server.app["hunter"]
        assert (await client.get("/health")).status == 200
        hunter.status["error"] = {"text": "Round failed: TypeError('boom')", "at": 1}
        r = await client.get("/health")
        assert r.status == 503 and (await r.json())["ok"] is False
    api(test, login=False)


def test_an_answer_that_is_too_big_is_refused():
    async def test():
        async def endless(request):
            return web.Response(body=b"[" + b"1," * (2 * 2**20) + b"1]", content_type="application/json")
        app = web.Application()
        app.add_routes([web.get("/api/v1/system/status", endless)])
        server = TestServer(app)
        await server.start_server()
        prowlarr = {"id": "px", "type": "prowlarr", "name": "Prowlarr", "url": str(server.make_url("")).rstrip("/"),
                    "api_key": "x", "categories": ["1000"]}
        try:
            async with aiohttp.ClientSession() as session:
                with pytest.raises(clients.ServiceError, match="Prowlarr: the answer is bigger than 2 MB"):
                    await indexers.status(session, prowlarr)
        finally:
            await server.close()
    asyncio.run(test())


def test_settings_file_and_sessions_file_are_for_the_app_user_only():
    config.update({"PANEL_PASSWORD": "correct horse"})
    auth.start()
    for path in (config.SETTINGS_FILE, config.SESSIONS_FILE):
        assert os.stat(path).st_mode & 0o077 == 0
