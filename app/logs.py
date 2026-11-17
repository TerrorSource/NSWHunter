"""The log of NSWHunter: to the output of the container and to a file per day in /data/logs,
named nswhunter_2026-03-25.txt.

Three levels, chosen in the settings: info says what happens; debug also every search and
every talk with a service; trace also every release that was judged, with the verdict."""
import datetime
import os
import re

import config

LEVELS = {"info": 0, "debug": 1, "trace": 2}
NAME = re.compile(r"nswhunter_(\d{4}-\d{2}-\d{2})\.txt")
OLD_NAME = re.compile(r"nswhunter\.txt(\.\d)?")  # the files of a version that named them by number
_file = {"handle": None, "path": None}


def path_for(day):
    return os.path.join(config.LOG_DIR, f"nswhunter_{day.isoformat()}.txt")


def prune(today=None):
    """Remove the log files that are older than the settings keep them."""
    today = today or datetime.date.today()
    oldest = today - datetime.timedelta(days=config.LOG_KEEP_DAYS)
    try:
        names = os.listdir(config.LOG_DIR)
    except OSError:
        return
    for name in names:
        full = os.path.join(config.LOG_DIR, name)
        match = NAME.fullmatch(name)
        try:
            if match:
                day = datetime.date.fromisoformat(match.group(1))
            elif OLD_NAME.fullmatch(name):
                day = datetime.date.fromtimestamp(os.path.getmtime(full))
            else:
                continue
            if day < oldest:
                os.remove(full)
        except (OSError, ValueError):
            continue


def setup():
    """Called at start and after the settings changed: the file of today is opened again at
    the next line, and what is too old is removed."""
    if _file["handle"] is not None:
        _file["handle"].close()
    _file.update(handle=None, path=None)
    prune()


def _handle(day):
    """The open file of this day; a new day starts a new file. None without a folder to write in:
    the output of the container is then all there is."""
    path = path_for(day)
    if _file["path"] != path:
        if _file["handle"] is not None:
            _file["handle"].close()
        _file.update(handle=None, path=path)
        try:
            os.makedirs(config.LOG_DIR, exist_ok=True)
            _file["handle"] = open(path, "a", encoding="utf-8")
        except OSError:
            return None
        prune(day)
    return _file["handle"]


def _write(level, args):
    if LEVELS[level] > LEVELS.get(config.LOG_LEVEL, 0):
        return
    now = datetime.datetime.now()
    line = " ".join([now.strftime("%Y-%m-%d %H:%M:%S"), f"[{level}]" if level != "info" else ""]
                    + [str(a) for a in args]).replace("  ", " ")
    print(line, flush=True)
    handle = _handle(now.date())
    if handle is not None:
        try:
            handle.write(line + "\n")
            handle.flush()
        except OSError:
            pass


def info(*args):
    _write("info", args)


def debug(*args):
    _write("debug", args)


def trace(*args):
    _write("trace", args)


def console(*args):
    """Only to the output of the container, never to a file: for the made-up password."""
    print(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), *args, flush=True)
