"""The second step of the login: a code from an authenticator app (TOTP, RFC 6238).

The app and NSWHunter share a secret; both turn it and the time into the same six digits,
which change every thirty seconds. Optional: without a secret the login is the password alone."""
import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

STEP = 30  # seconds one code lasts
DIGITS = 6


def new_secret():
    """A new secret, in the letters and digits an authenticator app takes."""
    return base64.b32encode(secrets.token_bytes(20)).decode()


def code(secret, step):
    """The code of one step of time."""
    key = base64.b32decode(secret, casefold=True)
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    at = digest[-1] & 15
    number = struct.unpack(">I", digest[at:at + 4])[0] & 0x7FFFFFFF
    return str(number % 10 ** DIGITS).zfill(DIGITS)


def verify(secret, given, after=0, now=None):
    """The step of time a code belongs to, or None if it is wrong. The step before and the one
    after count too, for a clock that is a little off. `after`: the step of the last code that
    was used; that one and older ones are refused, so a code that was seen cannot be used again."""
    given = "".join(str(given).split())
    if not secret or len(given) != DIGITS or not given.isdigit():
        return None
    current = int((time.time() if now is None else now) // STEP)
    for step in (current, current - 1, current + 1):
        try:
            right = hmac.compare_digest(code(secret, step), given)
        except (ValueError, TypeError):  # a secret that is no base32: nothing can match it
            return None
        if right and step > after:
            return step
    return None


def uri(secret, user):
    """What the QR code holds: the address an authenticator app reads the secret from."""
    return f"otpauth://totp/NSWHunter:{quote(user)}?secret={secret}&issuer=NSWHunter&digits={DIGITS}&period={STEP}"


def qr(text):
    """The QR code of a text as rows of "1" (dark) and "0", or [] if it cannot be made. The
    panel draws it itself: the secret never goes into the address of a picture."""
    try:
        import segno
        return ["".join("1" if dark else "0" for dark in row) for row in segno.make(text, error="m").matrix]
    except Exception:  # noqa: BLE001
        return []
