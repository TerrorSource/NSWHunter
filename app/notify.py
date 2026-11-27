"""Telling the user something: through Telegram, Discord or Apprise. Each is an entry of the
connections in the settings."""
import asyncio
import json

import aiohttp

import config
from clients import SHORT, ServiceError, _read

RETRY_SECONDS = 3


async def telegram_call(session, connection, method, body, wait=0):
    """One call to the Bot API of Telegram with the user's own bot. Returns its result.
    wait: seconds the call itself may stay open (getUpdates waits for news)."""
    if not connection.get("bot_token") or not connection.get("chat_id"):
        raise ServiceError("Telegram: fill in the bot token and the chat ID")
    # The address holds the token: no error may ever show it.
    address = f"{config.TELEGRAM_API_URL}/bot{connection['bot_token']}/{method}"
    for attempt in (1, 2):
        try:
            async with session.post(address, json=body, timeout=aiohttp.ClientTimeout(total=wait + 30)) as r:
                status = r.status
                try:
                    answer = json.loads(await _read(r))
                except ValueError:
                    answer = None
            break
        except aiohttp.ClientConnectorError as e:
            # Nothing reached Telegram yet, so trying once more cannot send a message twice.
            if attempt == 1:
                await asyncio.sleep(RETRY_SECONDS)
                continue
            raise ServiceError(f"Telegram: no connection to Telegram ({type(e).__name__})") from e
        except TimeoutError as e:
            raise ServiceError("Telegram: no answer from Telegram (timeout)") from e
        except Exception as e:  # noqa: BLE001  (only the kind of error: its text may hold the address, and so the token)
            raise ServiceError(f"Telegram: no connection to Telegram ({type(e).__name__})") from e
    if status in (401, 404):
        raise ServiceError("Telegram: the bot token is wrong")
    if status == 409:
        raise ServiceError("Telegram: another program reads the messages of this bot. Choosing from Telegram "
                           "needs a bot of its own for NSWHunter.")
    if status != 200 or not isinstance(answer, dict):
        why = str((answer if isinstance(answer, dict) else {}).get("description", f"HTTP {status}"))[:120]
        if method == "sendMessage":
            raise ServiceError(f"Telegram refuses the message: {why}. Is the chat ID right, and did you send the bot a message yet?")
        raise ServiceError(f"Telegram: {why}")
    return answer.get("result")


async def _telegram(session, connection, text, buttons):
    body = {"chat_id": connection.get("chat_id"), "text": text[:3900], "disable_web_page_preview": True}
    if buttons:
        body["reply_markup"] = {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in buttons]]}
    result = await telegram_call(session, connection, "sendMessage", body)
    return result.get("message_id") if isinstance(result, dict) else None


async def _discord(session, connection, text):
    """Post to a Discord webhook. The address of the webhook is the secret: never shown."""
    if not connection.get("webhook"):
        raise ServiceError("Discord: fill in the webhook")
    try:
        async with session.post(connection["webhook"], json={"content": text[:1900], "username": "NSWHunter"},
                                timeout=SHORT) as r:
            status = r.status
    except Exception as e:  # noqa: BLE001
        raise ServiceError("Discord: no connection to Discord") from e
    if status in (401, 403, 404):
        raise ServiceError("Discord: the webhook is wrong or was removed")
    if status >= 300:
        raise ServiceError(f"Discord refuses the message (HTTP {status})")


async def _apprise(connection, text):
    """Apprise knows a hundred services; its URLs say which (comma separated)."""
    if not connection.get("urls"):
        raise ServiceError("Apprise: fill in at least one URL")
    try:
        import apprise
        sender = apprise.Apprise()
        added = [sender.add(target.strip()) for target in connection["urls"].split(",") if target.strip()]
        if not all(added):
            raise ServiceError("Apprise: one of the URLs is not one Apprise knows")
        sent = await sender.async_notify(title="NSWHunter", body=text)
    except ServiceError:
        raise
    except Exception as e:  # noqa: BLE001
        raise ServiceError(f"Apprise: {type(e).__name__}") from e  # the text of the error can hold a URL
    if not sent:
        raise ServiceError("Apprise could not deliver the message")


async def send(session, connection, text, buttons=None):
    """Send one message through one connection. buttons: [(text, data)] under the message,
    for Telegram only. Returns the id of the message where the service gives one."""
    if connection["type"] == "telegram":
        return await _telegram(session, connection, "NSWHunter\n" + text, buttons)
    if connection["type"] == "discord":
        return await _discord(session, connection, text)
    return await _apprise(connection, text)
