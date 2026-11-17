"""The optional locks of the panel: the second step of the login, the list of sessions, HTTPS and
encrypted backups."""
import asyncio
import json
import os
import shutil
import socket
import ssl
import stat
import time
import zipfile

import aiohttp
import pytest
from aiohttp import web

import auth
import backup
import config
import main
import tls
import totp
from test_config import LOGIN, api, clean_settings  # noqa: F401  (the fixture puts the settings back)

# The secret of the examples in RFC 6238 ("12345678901234567890"), as an authenticator app gets it.
RFC_SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"


@pytest.fixture(autouse=True)
def clean_locks():
    yield
    config.TOTP_SECRET = ""
    auth.used_step = 0
    main.pending_totp.clear()
    main.listening.update(runner=None, tls=None)
    shutil.rmtree(tls.CERT_DIR, ignore_errors=True)


def code_now(secret, shift=0):
    return totp.code(secret, int(time.time() // totp.STEP) + shift)


# ---------------------------------------------------------------- the second step of the login


def test_codes_are_the_ones_of_the_standard():
    # RFC 6238, appendix B: the last six digits of its SHA-1 examples.
    for moment, code in ((59, "287082"), (1111111109, "081804"), (1234567890, "005924"), (2000000000, "279037")):
        assert totp.code(RFC_SECRET, moment // 30) == code
        assert totp.verify(RFC_SECRET, code, now=moment) == moment // 30


def test_a_code_counts_one_step_around_now_and_only_once():
    now = 1_700_000_000
    step = now // 30
    for shift in (-1, 0, 1):
        assert totp.verify(RFC_SECRET, totp.code(RFC_SECRET, step + shift), now=now) == step + shift
    assert totp.verify(RFC_SECRET, totp.code(RFC_SECRET, step + 2), now=now) is None
    assert totp.verify(RFC_SECRET, totp.code(RFC_SECRET, step - 2), now=now) is None
    # A code that was used, and every older one, is worth nothing any more.
    assert totp.verify(RFC_SECRET, totp.code(RFC_SECRET, step), after=step, now=now) is None
    assert totp.verify(RFC_SECRET, totp.code(RFC_SECRET, step + 1), after=step, now=now) == step + 1
    # Typed with a space in the middle, as the apps show it.
    code = totp.code(RFC_SECRET, step)
    assert totp.verify(RFC_SECRET, code[:3] + " " + code[3:], now=now) == step


@pytest.mark.parametrize("given", ["", "12345", "1234567", "abcdef", "12 34", None, "000000 000000"])
def test_what_is_no_code_is_refused(given):
    assert totp.verify(RFC_SECRET, given, now=59) is None


def test_no_secret_or_a_broken_one_matches_nothing():
    assert totp.verify("", "287082", now=59) is None
    assert totp.verify("not base32 !!", "287082", now=59) is None


def test_a_new_secret_and_its_qr_code():
    first, second = totp.new_secret(), totp.new_secret()
    assert first != second and len(first) == 32 and first.isalnum()
    address = totp.uri(first, "hunter name")
    assert address.startswith("otpauth://totp/NSWHunter:hunter%20name?secret=" + first) and "issuer=NSWHunter" in address
    rows = totp.qr(address)
    assert len(rows) > 20 and all(len(row) == len(rows) and set(row) <= {"0", "1"} for row in rows)


def test_two_step_login_from_setting_up_to_switching_off():
    async def test(client):
        assert (await (await client.get("/api/settings")).json())["totp"] is False
        # Without beginning there is nothing to switch on.
        assert (await client.post("/api/totp", json={"action": "enable", "code": "123456"})).status == 400
        begun = await (await client.post("/api/totp", json={"action": "begin"})).json()
        secret = begun["secret"]
        assert begun["uri"] == totp.uri(secret, "hunter") and begun["qr"] and not config.TOTP_SECRET
        # Only a code of the app proves that the app has the secret.
        r = await client.post("/api/totp", json={"action": "enable", "code": "000000" if code_now(secret) != "000000" else "111111"})
        assert r.status == 400 and not config.TOTP_SECRET
        assert (await client.post("/api/totp", json={"action": "enable", "code": code_now(secret)})).status == 200
        assert config.TOTP_SECRET == secret
        # It is in the settings file, and a form of the settings cannot touch it.
        with open(config.SETTINGS_FILE) as f:
            assert json.load(f)["TOTP_SECRET"] == secret
        r = await client.post("/api/settings", json={"values": {"TOTP_SECRET": ""}})
        assert r.status == 400 and config.TOTP_SECRET == secret
        assert (await client.post("/api/settings", json={"values": {"PANEL_HOSTS": "nas.example"}})).status == 200
        config.load_saved()
        assert config.TOTP_SECRET == secret and (await (await client.get("/api/settings")).json())["totp"] is True
        assert (await client.post("/api/totp", json={"action": "begin"})).status == 400  # it is on already

        await client.post("/api/logout", json={})
        # The password alone is no longer enough, and says so without counting as a wrong login.
        r = await client.post("/api/login", json=LOGIN)
        assert r.status == 401 and (await r.json())["totp"] is True and not auth.failures
        # A wrong password never gets as far as the code.
        r = await client.post("/api/login", json={"user": "hunter", "password": "wrong", "code": code_now(secret, 1)})
        assert r.status == 401 and "totp" not in await r.json()
        auth.failures.clear()
        r = await client.post("/api/login", json={**LOGIN, "code": "000000" if code_now(secret, 1) != "000000" else "111111"})
        assert r.status == 401 and (await r.json())["totp"] is True and auth.failures
        # The code that switched it on was used: it does not log in. The next one does.
        assert (await client.post("/api/login", json={**LOGIN, "code": code_now(secret)})).status == 401
        assert (await client.post("/api/login", json={**LOGIN, "code": code_now(secret, 1)})).status == 200
        assert (await client.get("/api/state")).status == 200

        # Switching it off takes a code too.
        assert (await client.post("/api/totp", json={"action": "disable", "code": ""})).status == 400
        auth.used_step = 0  # as if time went on
        auth.failures.clear()
        assert (await client.post("/api/totp", json={"action": "disable", "code": code_now(secret)})).status == 200
        assert config.TOTP_SECRET == ""
        with open(config.SETTINGS_FILE) as f:
            assert "TOTP_SECRET" not in json.load(f)
        await client.post("/api/logout", json={})
        assert (await client.post("/api/login", json=LOGIN)).status == 200
    api(test)


def test_wrong_codes_have_to_wait_like_wrong_passwords():
    async def test(client):
        config.TOTP_SECRET = totp.new_secret()
        for _ in range(auth.FREE_TRIES):
            r = await client.post("/api/login", json={**LOGIN, "code": "12345"})
            assert r.status == 401
        r = await client.post("/api/login", json={**LOGIN, "code": code_now(config.TOTP_SECRET)})
        assert r.status == 429 and "Too many" in (await r.json())["error"]
    api(test, login=False)


# ---------------------------------------------------------------- sessions


def test_sessions_are_listed_and_can_be_ended_one_by_one():
    async def test(client):
        phone = auth.start("192.168.1.20", "Mozilla/5.0 (iPhone)")
        laptop = auth.start("192.168.1.30", "Mozilla/5.0 (Windows NT 10.0)")
        listed = (await (await client.get("/api/sessions")).json())["sessions"]
        assert len(listed) == 3 and [s["current"] for s in listed].count(True) == 1
        assert {s["address"] for s in listed} >= {"192.168.1.20", "192.168.1.30"}
        # What the panel gets cannot be used to log in: no token, and only a piece of its hash.
        assert all(len(s["id"]) == 16 and s["id"] not in (phone, laptop) for s in listed)
        one = next(s for s in listed if s["address"] == "192.168.1.20")
        r = await (await client.post("/api/sessions", json={"id": one["id"]})).json()
        assert r["ended"] == 1 and len(r["sessions"]) == 2 and not auth.valid(phone) and auth.valid(laptop)
        assert (await (await client.post("/api/sessions", json={"id": one["id"]})).json())["ended"] == 0
        assert (await (await client.post("/api/sessions", json={"id": ""})).json())["ended"] == 0
        r = await (await client.post("/api/sessions", json={"others": True})).json()
        assert r["ended"] == 1 and not auth.valid(laptop) and [s["current"] for s in r["sessions"]] == [True]
        assert (await client.get("/api/state")).status == 200  # this browser stays logged in
        assert (await client.post("/api/sessions", json={})).status == 400
    api(test)


def test_sessions_of_an_older_version_stay_logged_in():
    token = auth.start()
    key = auth._key(token)
    os.makedirs(config.DATA_DIR, exist_ok=True)
    with open(config.SESSIONS_FILE, "w") as f:
        json.dump({key: int(time.time()) + 3600, "old": int(time.time()) - 5, "odd": "text"}, f)
    auth.load()
    assert list(auth.sessions) == [key] and auth.valid(token)
    assert auth.listing(token)[0]["current"] and auth.listing("")[0]["current"] is False
    # Using a login is remembered, but not written to the file at every call.
    auth.sessions[key]["seen"] = 0
    assert auth.valid(token) and auth.sessions[key]["seen"] > 0
    with open(config.SESSIONS_FILE) as f:
        assert json.load(f)[key]["seen"] > 0
    assert stat.S_IMODE(os.stat(config.SESSIONS_FILE).st_mode) == 0o600


# ---------------------------------------------------------------- encrypted backups


def with_data(test):
    """Run `test()` with settings and a state to make a backup of."""
    config.BACKUP_FOLDER = "backups"
    config.write({"SLM_URL": "http://library.example", "SLM_API_KEY": "slm_key_in_the_backup"})
    with open(config.STATE_FILE, "w") as f:
        json.dump({"items": {}}, f)
    test()


def test_backups_are_encrypted_with_the_backup_password():
    def test():
        plain = backup.create("manual")
        config.BACKUP_PASSWORD = "open sesame"
        name = backup.create("manual")
        assert plain.endswith(".zip") and name.endswith(".zip.enc")
        listed = {b["name"]: b["encrypted"] for b in backup.listing()}
        assert listed == {plain: False, name: True}
        with open(backup.path(name), "rb") as f:
            data = f.read()
        # Nothing of what is inside can be read from the file.
        assert data.startswith(backup.MAGIC) and b"slm_key_in_the_backup" not in data and b"settings.json" not in data
        assert not zipfile.is_zipfile(backup.path(name)) and zipfile.is_zipfile(backup.path(plain))
        assert stat.S_IMODE(os.stat(backup.path(name)).st_mode) == 0o600
        # The same content twice is not the same file: the salt and the nonce are new every time.
        assert backup.encrypt(b"same", "open sesame") != backup.encrypt(b"same", "open sesame")

        os.remove(config.SETTINGS_FILE)
        backup.restore(name)  # with the password of the settings
        with open(config.SETTINGS_FILE) as f:
            assert json.load(f)["SLM_API_KEY"] == "slm_key_in_the_backup"
        # Another password in the settings since: the one the backup was made with has to be given.
        config.BACKUP_PASSWORD = "another one"
        with pytest.raises(backup.WrongPassword, match="not the password"):
            backup.restore(name)
        with pytest.raises(backup.WrongPassword):
            backup.restore(name, "guess")
        backup.restore(name, "open sesame")
        config.BACKUP_PASSWORD = ""
        with pytest.raises(backup.WrongPassword, match="is encrypted"):
            backup.restore(name)
        backup.restore(plain)  # one that is not encrypted needs none
        # A file that only looks like an encrypted backup, or was changed, opens nothing.
        with open(backup.path(name), "wb") as f:
            f.write(data[:-1] + bytes([data[-1] ^ 1]))
        with pytest.raises(backup.WrongPassword):
            backup.restore(name, "open sesame")
        with open(backup.path(name), "wb") as f:
            f.write(b"PK not ours")
        with pytest.raises(backup.BackupError, match="not one NSWHunter made"):
            backup.restore(name, "open sesame")
    with_data(test)


def test_the_panel_asks_for_the_password_of_an_encrypted_backup():
    async def test(client):
        assert (await client.post("/api/settings", json={"values": {"BACKUP_PASSWORD": "open sesame"}})).status == 200
        settings = await (await client.get("/api/settings")).json()
        assert settings["secrets"]["BACKUP_PASSWORD"] is True and "BACKUP_PASSWORD" not in settings["values"]
        made = await (await client.post("/api/backup", json={"action": "create"})).json()
        name = made["backups"][0]["name"]
        assert made["encrypting"] is True and made["backups"][0]["encrypted"] and name.endswith(".enc")
        r = await client.get("/api/backup/download", params={"name": name})
        assert r.status == 200 and r.headers["Content-Type"] == "application/octet-stream"
        # The password goes out of the settings: the backup stays what it is.
        assert (await client.post("/api/settings", json={"values": {}, "clear": ["BACKUP_PASSWORD"]})).status == 200
        r = await client.post("/api/backup", json={"action": "restore", "name": name})
        assert r.status == 400 and (await r.json())["password"] is True
        r = await client.post("/api/backup", json={"action": "restore", "name": name, "password": "wrong"})
        assert r.status == 400 and (await r.json())["password"] is True
        r = await client.post("/api/backup", json={"action": "restore", "name": name, "password": "open sesame"})
        assert r.status == 200 and config.BACKUP_PASSWORD == "open sesame"  # as it was when the backup was made
    api(test)


# ---------------------------------------------------------------- HTTPS


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_a_certificate_of_its_own_is_made_once_and_kept():
    config.PANEL_HOSTS = "nswhunter.example"
    assert tls.self_made() is True and tls.self_made() is False
    assert stat.S_IMODE(os.stat(tls.OWN_KEY).st_mode) == 0o600
    from cryptography import x509
    with open(tls.OWN_CERT, "rb") as f:
        certificate = x509.load_pem_x509_certificate(f.read())
    names = certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert "nswhunter.example" in names.get_values_for_type(x509.DNSName)
    days = (certificate.not_valid_after_utc - certificate.not_valid_before_utc).days
    assert 700 < days < 830
    # One that ends within a month is replaced.
    import datetime
    late = certificate.not_valid_after_utc - datetime.timedelta(days=5)
    assert tls.self_made(now=late) is True
    assert isinstance(tls.context(), ssl.SSLContext)


def test_a_certificate_that_cannot_be_used_says_why():
    config.SSL_CERT_PATH = "/nowhere/panel.pem"
    with pytest.raises(tls.TlsError, match="is not there"):
        tls.context()
    os.makedirs(tls.CERT_DIR, exist_ok=True)
    broken = os.path.join(tls.CERT_DIR, "broken.pem")
    with open(broken, "w") as f:
        f.write("this is no certificate")
    config.SSL_CERT_PATH = broken
    with pytest.raises(tls.TlsError, match="cannot be used"):
        tls.context()
    # A certificate of your own with its key: here the self-made pair, by its paths.
    tls.self_made()
    config.SSL_CERT_PATH, config.SSL_KEY_PATH = tls.OWN_CERT, tls.OWN_KEY
    assert tls.files() == (tls.OWN_CERT, tls.OWN_KEY, False) and isinstance(tls.context(), ssl.SSLContext)
    config.SSL_KEY_PATH = ""  # without a key of its own the key has to be in the same file
    with pytest.raises(tls.TlsError):
        tls.context()


def test_https_is_only_switched_on_with_a_certificate_that_works():
    async def test(client):
        r = await client.post("/api/settings", json={"values": {"SSL_ENABLED": True, "SSL_CERT_PATH": "/nowhere/panel.pem"}})
        assert r.status == 400 and "HTTPS" in (await r.json())["error"] and config.SSL_ENABLED is False
        r = await client.post("/api/settings", json={"values": {"SSL_CERT_PATH": "certs/panel.pem"}})
        assert r.status == 400 and "whole path" in (await r.json())["error"]
        r = await client.post("/api/settings", json={"values": {"SSL_ENABLED": True, "SSL_PORT": config.PORT}})
        assert r.status == 400 and "HTTP" in (await r.json())["error"]
        for port in (0, 70000, "many"):
            assert (await client.post("/api/settings", json={"values": {"SSL_PORT": port}})).status == 400
        # Without a certificate of your own NSWHunter makes one.
        r = await client.post("/api/settings", json={"values": {"SSL_ENABLED": True, "SSL_PORT": 3443}})
        assert r.status == 200 and config.SSL_ENABLED is True and os.path.isfile(tls.OWN_CERT)
    api(test)


def test_the_https_side_starts_moves_and_stops_with_the_settings():
    async def test():
        config.PANEL_USER, config.PANEL_PASSWORD, config.INITIAL_PASSWORD = "hunter", config.hash_password("correct horse"), None
        app = main.make_app()
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        main.listening["runner"] = runner
        hunter = app["hunter"]
        # A self-made certificate: nobody vouches for it. And a new connection for every call: one
        # that is still open keeps working after the port it came in by was closed.
        open_to_any = aiohttp.TCPConnector(ssl=False, force_close=True)
        try:
            async with aiohttp.ClientSession(connector=open_to_any) as session:
                async def answers(port):
                    try:
                        async with session.get(f"https://127.0.0.1:{port}/health", timeout=aiohttp.ClientTimeout(total=5)) as r:
                            return r.status == 200
                    except aiohttp.ClientError:
                        return False
                first, second = free_port(), free_port()
                config.SSL_ENABLED, config.SSL_PORT = True, first
                await main.secure(hunter)
                assert await answers(first) and hunter.state["services"]["ssl"]["ok"]
                assert "made itself" in hunter.state["services"]["ssl"]["text"]
                # The login cookie over HTTPS is only ever sent over HTTPS.
                async with session.post(f"https://127.0.0.1:{first}/api/login", json=LOGIN) as r:
                    assert r.status == 200 and "Secure" in r.headers["Set-Cookie"]
                config.SSL_PORT = second
                await main.secure(hunter)
                assert await answers(second) and not await answers(first)
                # A certificate that broke: HTTPS goes off and the Status page says why.
                config.SSL_CERT_PATH = "/nowhere/panel.pem"
                await main.secure(hunter)
                assert not await answers(second) and not hunter.state["services"]["ssl"]["ok"]
                assert "is not there" in hunter.state["services"]["ssl"]["text"]
                config.SSL_CERT_PATH, config.SSL_ENABLED = "", False
                await main.secure(hunter)
                assert not await answers(second) and "ssl" not in hunter.state["services"]
        finally:
            await runner.cleanup()
    asyncio.run(test())
