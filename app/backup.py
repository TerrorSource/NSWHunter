"""Backups of the settings and the state: a zip per backup in the backup folder.

A scheduled backup is made every BACKUP_INTERVAL_DAYS and removed after BACKUP_RETENTION_DAYS.
A backup made by hand stays until it is removed by hand. A backup holds the keys and
passwords of the settings, so its file is for the app user only; with a backup password in the
settings it is encrypted as well (AES-256-GCM, the key made from the password with scrypt)."""
import datetime
import hashlib
import io
import os
import re
import time
import zipfile

import config
from version import __version__

NAME_RE = re.compile(r"nswhunter_backup_(scheduled|manual)_v[0-9.]+_\d{4}\.\d{2}\.\d{2}_\d{2}\.\d{2}\.\d{2}\.zip(\.enc)?")
ENCRYPTED = ".enc"
MAGIC = b"NSWHUNTER-BACKUP-1\n"  # what an encrypted backup starts with; then the salt, the nonce, the rest
MAX_BACKUP = 512 * 2**20
MEMBERS = ("settings.json", "state.json")
MAX_MEMBER = 256 * 2**20  # nothing in a backup is bigger: a zip that claims so is not one of ours


class BackupError(Exception):
    pass


class WrongPassword(BackupError):
    """An encrypted backup that the password does not open."""


def _key(password, salt):
    return hashlib.scrypt(password.encode(), salt=salt, n=2**15, r=8, p=1, maxmem=128 * 2**20, dklen=32)


def encrypt(data, password):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    salt, nonce = os.urandom(16), os.urandom(12)
    return MAGIC + salt + nonce + AESGCM(_key(password, salt)).encrypt(nonce, data, MAGIC)


def decrypt(data, password):
    """The zip inside an encrypted backup. WrongPassword if the password does not open it."""
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    start = len(MAGIC)
    if not data.startswith(MAGIC) or len(data) < start + 28 + 16:
        raise BackupError("That backup is not one NSWHunter made")
    if not password:
        raise WrongPassword("This backup is encrypted: fill in the backup password it was made with")
    salt, nonce = data[start:start + 16], data[start + 16:start + 28]
    try:
        return AESGCM(_key(password, salt)).decrypt(nonce, data[start + 28:], MAGIC)
    except InvalidTag:
        raise WrongPassword("That is not the password this backup was made with") from None


def folder():
    """Where the backups are kept: by default "backups" in the config folder. A relative folder
    is under the config folder; "/backup" without that volume is the default too (see config)."""
    return os.path.join(config.DATA_DIR, config.backup_folder(config.BACKUP_FOLDER))  # an absolute folder stays as it is


def listing():
    """[{"name", "kind", "size", "at"}] of the backups in the folder, newest first."""
    try:
        names = os.listdir(folder())
    except OSError:
        return []
    found = []
    for name in names:
        match = NAME_RE.fullmatch(name)
        if match:
            info = os.stat(os.path.join(folder(), name))
            found.append({"name": name, "kind": match.group(1), "size": info.st_size, "at": int(info.st_mtime),
                          "encrypted": name.endswith(ENCRYPTED)})
    return sorted(found, key=lambda b: (b["at"], b["name"]), reverse=True)


def path(name):
    """The file of a backup. Only a name this module made is accepted: nothing outside the
    folder can be reached through a name."""
    if not NAME_RE.fullmatch(str(name)):
        raise BackupError("That is not the name of a backup")
    full = os.path.join(folder(), name)
    if not os.path.isfile(full):
        raise BackupError("That backup is no longer there")
    return full


def create(kind="manual"):
    """Make a backup now: encrypted if the settings have a backup password. Returns its name."""
    stamp = datetime.datetime.now().strftime("%Y.%m.%d_%H.%M.%S")
    password = config.BACKUP_PASSWORD
    name = f"nswhunter_backup_{kind}_v{__version__}_{stamp}.zip" + (ENCRYPTED if password else "")
    target = os.path.join(folder(), name)
    try:
        packed = io.BytesIO()
        with zipfile.ZipFile(packed, "w", zipfile.ZIP_DEFLATED) as archive:
            for member in MEMBERS:
                source = os.path.join(config.DATA_DIR, member)
                if os.path.isfile(source):
                    archive.write(source, member)
        data = encrypt(packed.getvalue(), password) if password else packed.getvalue()
        os.makedirs(folder(), exist_ok=True)
        tmp = target + ".tmp"
        with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "wb") as f:
            f.write(data)
        os.replace(tmp, target)
    except OSError as e:
        raise BackupError(f"Cannot write in the backup folder {folder()}: {e.strerror or e}. "
                          "Is it a volume of the container?") from e
    return name


def delete(name):
    os.remove(path(name))


def restore(name, password=None):
    """Put the settings and the state of a backup back. The caller reads them in again. An
    encrypted backup is opened with `password`, or else with the backup password of the settings;
    WrongPassword if neither opens it."""
    try:
        full = path(name)
        if os.path.getsize(full) > MAX_BACKUP:
            raise BackupError("That backup is not one NSWHunter made")
        with open(full, "rb") as f:
            data = f.read()
        if name.endswith(ENCRYPTED):
            data = decrypt(data, password or config.BACKUP_PASSWORD)
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members = [m for m in archive.infolist() if m.filename in MEMBERS]
            if not members:
                raise BackupError("That backup holds no settings and no state")
            for member in members:
                if member.file_size > MAX_MEMBER:
                    raise BackupError("That backup is not one NSWHunter made")
                target = os.path.join(config.DATA_DIR, member.filename)
                with os.fdopen(os.open(target + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "wb") as f:
                    f.write(archive.read(member))
                os.replace(target + ".tmp", target)
    except (zipfile.BadZipFile, OSError) as e:
        raise BackupError(f"That backup cannot be read: {e}") from e


def due(now=None):
    """Is it time for a scheduled backup?"""
    scheduled = [b["at"] for b in listing() if b["kind"] == "scheduled"]
    return not scheduled or (now or time.time()) - max(scheduled) >= config.BACKUP_INTERVAL_DAYS * 86400


def prune(now=None):
    """Remove the scheduled backups that are older than the retention. Returns how many."""
    limit = (now or time.time()) - config.BACKUP_RETENTION_DAYS * 86400
    old = [b["name"] for b in listing() if b["kind"] == "scheduled" and b["at"] < limit]
    for name in old:
        os.remove(os.path.join(folder(), name))
    return len(old)
