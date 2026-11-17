"""The log of NSWHunter: to the output of the container and to files in /data/logs.

Three levels, chosen in the settings: info says what happens; debug also every search and
every talk with a service; trace also every release that was judged, with the verdict."""
import datetime
import logging
import logging.handlers
import os

import config

LEVELS = {"info": 0, "debug": 1, "trace": 2}
FILES_KEPT = 5
_file = {"handler": None, "opened": None}  # opened: (path, size) of the file that is open
_logger = logging.getLogger("nswhunter")
_logger.setLevel(logging.INFO)
_logger.propagate = False


def setup():
    """Open the log file with the size from the settings. Called at start and after the
    settings changed. Without a folder to write in, the output of the container is all there is."""
    size, path = config.LOG_SIZE_MB, os.path.join(config.LOG_DIR, "nswhunter.txt")
    if _file["handler"] is not None and _file["opened"] == (path, size):
        return
    if _file["handler"] is not None:
        _logger.removeHandler(_file["handler"])
        _file["handler"].close()
        _file["handler"] = None
    try:
        os.makedirs(config.LOG_DIR, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            path, maxBytes=size * 2**20, backupCount=FILES_KEPT, encoding="utf-8")
    except OSError:
        return
    handler.setFormatter(logging.Formatter("%(message)s"))
    _logger.addHandler(handler)
    _file.update(handler=handler, opened=(path, size))


def _write(level, args):
    if LEVELS[level] > LEVELS.get(config.LOG_LEVEL, 0):
        return
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = " ".join([stamp, f"[{level}]" if level != "info" else ""] + [str(a) for a in args]).replace("  ", " ")
    print(line, flush=True)
    if _file["handler"] is not None:
        _logger.info(line)


def info(*args):
    _write("info", args)


def debug(*args):
    _write("debug", args)


def trace(*args):
    _write("trace", args)


def console(*args):
    """Only to the output of the container, never to a file: for the made-up password."""
    print(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), *args, flush=True)
