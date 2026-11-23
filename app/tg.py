"""A chat source of torrents: a bot that answers a query with a list of releases, and sends the
.torrent of one when asked. A bot cannot talk to another bot, so this is a Telegram account of
the user (Telethon), logged in once with a code. Set up on the page /telegrambot."""
import asyncio
import logging
import re
import time

from telethon import TelegramClient, errors
from telethon.sessions import StringSession

import config
import logs
from clients import ServiceError

SOURCE = "tg"  # the "source" of its releases, where an indexer has its id
NAME = "Telegram"
GAP = 4  # seconds between two messages to the bot, so it does not limit us
ANSWER = 30  # seconds the bot gets to answer
# "Some Game - Subtitle\nSize: 6.01 GB\nDownload: /download3573 /cover3573"
RESULT = re.compile(r"^[ \t]*(?P<title>\S[^\n]*?)[ \t]*\n[ \t]*Size:[ \t]*(?P<size>[\d.,]+)[ \t]*(?P<unit>[KMGT]?i?B)\b[^\n]*\n"
                    r"[ \t]*Download:[ \t]*/download(?P<id>\d+)", re.M | re.I)
UNITS = {"b": 1, "kb": 2**10, "mb": 2**20, "gb": 2**30, "tb": 2**40}
TITLE_ID = re.compile(r"[0-9a-fA-F]{16}")

logging.getLogger("telethon").setLevel(logging.WARNING)
state = {"client": None, "key": None, "pending": None, "last": 0.0, "paused_until": 0.0, "error": "", "error_at": 0}
lock = asyncio.Lock()


def ready():
    s = config.TG
    return bool(s.get("enabled") and s.get("session") and s.get("bot") and s.get("api_id") and s.get("api_hash"))


def shown():
    """What the page gets: no hash and no session, only whether they are there."""
    s = config.TG
    return {"api_id": s.get("api_id", ""), "api_hash": bool(s.get("api_hash")), "bot": s.get("bot", ""),
            "enabled": bool(s.get("enabled")), "account": s.get("account", "") if s.get("session") else "",
            "logged_in": bool(s.get("session")), "waiting": bool(state["pending"]),
            "last_error": state["error"], "last_error_at": state["error_at"], "torrents": config.wants_torrents()}


async def close():
    old, state["client"], state["key"] = state["client"], None, None
    if old is not None:
        try:
            await old.disconnect()
        except Exception:  # noqa: BLE001  (it goes either way)
            pass


async def client(session=None):
    """The connected client of the settings; `session` "" for a new login."""
    s = config.TG
    if not (s.get("api_id") and s.get("api_hash")):
        raise ServiceError("Fill in the API ID and the API hash first")
    key = (s["api_id"], s["api_hash"], s.get("session", "") if session is None else session)
    if state["client"] is not None and state["key"] == key and state["client"].is_connected():
        return state["client"]
    await close()
    made = TelegramClient(StringSession(key[2] or None), int(key[0]), key[1], flood_sleep_threshold=0,
                          device_model="NSWHunter", app_version="1", receive_updates=True)
    try:
        await made.connect()
    except (OSError, ConnectionError) as e:
        raise ServiceError(f"Telegram cannot be reached: {e}") from e
    state.update(client=made, key=key)
    return made


def problem(e):
    """A Telethon error as a text for the user."""
    if isinstance(e, errors.FloodWaitError):
        state["paused_until"] = time.time() + e.seconds
        return f"Telegram asks to wait {e.seconds} seconds before the next message"
    texts = {errors.PhoneNumberInvalidError: "That phone number is not right: fill it in with the country code, like +31612345678",
             errors.PhoneCodeInvalidError: "That code is not right",
             errors.PhoneCodeExpiredError: "That code has expired: ask for a new one",
             errors.PasswordHashInvalidError: "That password is not right",
             errors.ApiIdInvalidError: "The API ID and the API hash do not belong together",
             errors.UsernameInvalidError: "There is no bot with that name",
             errors.UsernameNotOccupiedError: "There is no bot with that name"}
    return next((t for kind, t in texts.items() if isinstance(e, kind)), f"Telegram: {e}")


async def send_code(phone):
    phone = re.sub(r"[\s()-]", "", str(phone or ""))
    if not re.fullmatch(r"\+?\d{6,16}", phone):
        raise ValueError("Fill in the phone number with the country code, like +31612345678")
    made = await client("")
    try:
        sent = await made.send_code_request(phone)
    except errors.RPCError as e:
        raise ServiceError(problem(e)) from e
    state["pending"] = {"phone": phone, "hash": sent.phone_code_hash}


async def sign_in(code="", password=""):
    """Returns "password" when the account has a second step, else the name of the account."""
    made, pending = state["client"], state["pending"]
    if made is None or pending is None:
        raise ValueError("Ask for a code first")
    try:
        if password:
            await made.sign_in(password=password)
        else:
            await made.sign_in(phone=pending["phone"], code=re.sub(r"\D", "", str(code)), phone_code_hash=pending["hash"])
    except errors.SessionPasswordNeededError:
        return "password"
    except errors.RPCError as e:
        raise ServiceError(problem(e)) from e
    me = await made.get_me()
    account = " ".join(p for p in (me.first_name, me.last_name) if p) or me.username or str(me.id)
    session = made.session.save()
    config.set_tg({**config.TG, "session": session, "account": account})
    state.update(key=(config.TG["api_id"], config.TG["api_hash"], session), pending=None, error="")
    return account


async def log_out():
    if config.TG.get("session"):
        try:
            await (await client()).log_out()
        except (ServiceError, errors.RPCError, OSError):
            pass  # the session is forgotten here either way
    await close()
    state["pending"] = None
    config.set_tg({k: v for k, v in config.TG.items() if k not in ("session", "account")})


async def ask(text, done, wait=ANSWER, most=4):
    """Send `text` to the bot and gather its answers until `done(answers)` or the time is over."""
    if time.time() < state["paused_until"]:
        raise ServiceError(f"Telegram asked to wait until {time.strftime('%H:%M', time.localtime(state['paused_until']))}")
    async with lock:
        pause = GAP - (time.monotonic() - state["last"])
        if pause > 0:
            await asyncio.sleep(pause)
        try:
            made = await client()
            if not await made.is_user_authorized():
                raise ServiceError("The Telegram account is no longer logged in: log in again on /telegrambot")
            answers = []
            async with made.conversation(config.TG["bot"], timeout=wait, exclusive=True) as talk:
                await talk.send_message(text)
                while len(answers) < most and not done(answers):
                    try:
                        answers.append(await talk.get_response(timeout=wait if not answers else 5))
                    except asyncio.TimeoutError:
                        break
            if not answers:
                raise ServiceError(f"The bot {config.TG['bot']} did not answer")
            return answers
        except errors.RPCError as e:
            raise ServiceError(problem(e)) from e
        except ValueError as e:  # an unknown bot name
            raise ServiceError(f"Telegram: {e}") from e
        finally:
            state["last"] = time.monotonic()


def results(text):
    """The releases in one answer of the bot."""
    found = []
    for m in RESULT.finditer(text or ""):
        try:
            size = int(float(m.group("size").replace(",", ".")) * UNITS.get(m.group("unit").lower().replace("i", ""), 1))
        except ValueError:
            size = 0
        found.append({"id": m.group("id"), "title": m.group("title").strip(" *_"), "size": size})
    return found


async def search(query):
    """Releases for a query, in the shape of those of an indexer. Not for a title ID or nothing:
    the bot knows names only."""
    query = str(query or "").strip()
    if not query or TITLE_ID.fullmatch(query):
        return []
    try:
        answers = await ask(query, lambda got: any("/download" in (a.raw_text or "") for a in got) or len(got) >= 2)
    except ServiceError as e:
        state.update(error=str(e), error_at=int(time.time()))
        raise
    state["error"] = ""
    found = [r for a in answers for r in results(a.raw_text)]
    logs.debug(f"{NAME}: {query!r} gave {len(found)} release(s)")
    return [{
        # The bot sells only Switch games, and says so nowhere in a title: the matcher wants to know.
        "guid": f"{SOURCE}:{r['id']}", "title": f"{r['title']} NSW", "size": r["size"], "indexer": NAME,
        "indexerId": None, "source": SOURCE, "protocol": "torrent", "seeders": None, "published": "",
        "downloadUrl": f"{SOURCE}:{r['id']}", "infoUrl": "", "grabs": 0, "priority": 50,
    } for r in found]


async def fetch(release):
    """("file", the .torrent) of a release the bot listed."""
    number = str(release.get("downloadUrl") or "").removeprefix(f"{SOURCE}:")
    if not number.isdigit():
        raise ServiceError("This release has no number the bot knows")
    answers = await ask(f"/download{number}", lambda got: any(a.file for a in got), wait=60)
    sent = next((a for a in answers if a.file), None)
    if sent is None:
        raise ServiceError(f"The bot sent no torrent for this release: {(answers[-1].raw_text or '')[:200]}")
    data = await sent.download_media(file=bytes)
    if not data or data[:1] != b"d":
        raise ServiceError("What the bot sent is not a torrent file")
    return "file", data
