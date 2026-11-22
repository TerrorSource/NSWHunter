"""Putting a finished download in the library, as Completed Download Handling does in Sonarr
and Radarr.

The download client says where a finished download is. The Switch files in it are moved to the
folder of their game in a root folder. That folder is named by the folder name template, as
Organize of Switch-library-manager-web names it; a folder that already has the title ID of the
game in its name is used as it is. Without a template a file goes next to the updates (or DLC)
the game already has, or else next to the game itself. A torrent is linked or copied instead of
moved, so it can go on seeding.

Both folders have to be volumes of this container. The library is named by its root folders
(Settings > Media Management); nothing is ever written outside one, and nothing is overwritten."""
import os
import re
import shutil
import time

import config

EXTENSIONS = (".nsp", ".nsz", ".xci", ".xcz")
TITLE_ID = re.compile(r"(?<![0-9A-Fa-f])(0[0-9A-Fa-f]{15})(?![0-9A-Fa-f])")
PART = ".nswhunter-part"  # a file that is still being copied; the library does not read this
# What Switch-library-manager-web leaves out of a name: what a disk refuses or a path splits on.
ILLEGAL = re.compile(r'[/\\?%*:;=|"<>]')


class ImportProblem(Exception):
    """Why a download could not be put in the library, in words for the user."""


def under(path, folder):
    """Is this path the folder itself or something in it?"""
    folder = folder.rstrip("/") or "/"
    return path == folder or path.startswith(folder.rstrip("/") + "/")


def local_download(client, path):
    """The path of a download as this container sees it: what the download client says, with
    its Remote Path replaced by its Local Path if the client has that pair."""
    remote, local = (client.get("remote_path") or "").rstrip("/"), (client.get("local_path") or "").rstrip("/")
    if remote and local and under(path, remote):
        return local + path[len(remote):]
    return path


def local_library(path):
    """A path of the library as this container sees it, and the root folder that holds it."""
    for root in sorted(config.ROOT_FOLDERS, key=lambda r: -len(r["library_path"])):
        theirs = root["library_path"].rstrip("/")
        if under(path, theirs):
            return root["path"].rstrip("/") + path[len(theirs):], root["path"]
    raise ImportProblem(f"{path} is not in a root folder. Add the folder of your library under "
                        "Settings > Media Management > Root Folders.")


def kind_of(name, fallback):
    """What a file is, by the title ID in its name: "BASE", "UPD" or "DLC". Without one it is
    what was asked for."""
    found = TITLE_ID.search(name)
    if not found:
        return fallback
    end = found.group(1)[-3:].upper()
    return "BASE" if end == "000" else "UPD" if end == "800" else "DLC"


def folder_for(files, kind):
    """The folder a file of this kind belongs in for a game, as the library names it: next to
    the newest file of that kind the game has, or else next to the game itself."""
    same = [f for f in files if f["type"] == kind]
    base = [f for f in files if f["type"] not in ("UPD", "DLC")]
    for group in (same, base, files):
        if group:
            return os.path.dirname(max(group, key=lambda f: f.get("version") or 0)["path"])
    raise ImportProblem("the library does not say where the files of this game are")


def piece(name):
    """A name as a part of the name of a folder, as Switch-library-manager-web writes it:
    without the characters a disk refuses, its spaces one by one, nothing loose at its ends."""
    return " ".join(ILLEGAL.sub("", name).split()).strip(" -_.")


def folder_name(game_id, name):
    """The name of the folder of a game by the folder name template."""
    result = config.FOLDER_TEMPLATE.replace("{TITLE_NAME}", piece(name)).replace("{TITLE_ID}", game_id.upper())
    for empty in ("[]", "()", "<>"):
        result = result.replace(empty, "")
    result = ILLEGAL.sub("", " ".join(result.split())).strip(". ")
    return result or "_"


def game_folder(game_id, name):
    """(the folder of a game, its root folder) by the folder name template. A folder in a root
    folder that already has the title ID in its name is the folder of the game, whatever name
    is around it: the library may write the name a little differently. Else it is a new folder
    in the first root folder."""
    wanted, by_id = folder_name(game_id, name), "{TITLE_ID}" in config.FOLDER_TEMPLATE
    for root in config.ROOT_FOLDERS:
        try:
            folders = sorted(entry.name for entry in os.scandir(root["path"]) if entry.is_dir())
        except OSError:
            continue
        found = [f for f in folders if f == wanted] or [f for f in folders if by_id and game_id.upper() in f.upper()]
        if found:
            return os.path.join(root["path"], found[0]), root["path"]
    root = config.ROOT_FOLDERS[0]["path"]
    return os.path.join(root, wanted), root


def switch_files(path):
    """The Switch files of a download: the file itself, or everything in its folder."""
    if os.path.isfile(path):
        return [path] if path.lower().endswith(EXTENSIONS) else []
    found = []
    for folder, _, names in os.walk(path):
        found += [os.path.join(folder, n) for n in sorted(names) if n.lower().endswith(EXTENSIONS) and not n.startswith(".")]
    return found


PACKED = (".rar", ".zip", ".7z", ".001", ".par2")


def holds(path):
    """What is in a folder without Switch files, in words: so it need not be looked up on the
    server. Counted by the ending of the names."""
    if os.path.isfile(path):
        return f"it is one file, {os.path.basename(path)}", os.path.splitext(path)[1].lower() in PACKED
    count, endings = 0, {}
    for _, _, names in os.walk(path):
        for name in names:
            ending = os.path.splitext(name)[1].lower() or "(no ending)"
            ending = ".r00-.r99" if re.fullmatch(r"\.[r-z]\d\d", ending) else ending
            endings[ending] = endings.get(ending, 0) + 1
            count += 1
    if not count:
        return "the folder is empty", False
    most = sorted(endings.items(), key=lambda e: (-e[1], e[0]))
    listed = ", ".join(f"{n} {ending}" for ending, n in most[:6]) + (" and more" if len(most) > 6 else "")
    return f"it holds {count} file(s): {listed}", any(e in PACKED or e == ".r00-.r99" for e in endings)


def put(source, folder, keep, dry=False):
    """Bring one file into a folder; `keep` leaves the original where it is (a torrent that goes
    on seeding). Returns (the new file, how it got there). Nothing is overwritten. `dry`: only
    say what would be done."""
    target = os.path.join(folder, os.path.basename(source))
    if os.path.lexists(target):
        if os.path.isfile(target) and os.path.getsize(target) == os.path.getsize(source):
            return target, "was there already"
        raise ImportProblem(f"{target} is there already, with another size")
    if dry:
        return target, "linked" if keep else "moved"
    os.makedirs(folder, exist_ok=True)
    part = target + PART
    if keep:
        try:
            os.link(source, target)  # one file in two places, if both are on the same disk
            return target, "linked"
        except OSError:
            shutil.copyfile(source, part)
            os.replace(part, target)
            return target, "copied"
    try:
        os.rename(source, target)  # on the same disk this takes no time
    except OSError:
        shutil.copyfile(source, part)
        os.replace(part, target)
        os.remove(source)
    return target, "moved"


def bring(client, reported, game_files, wanted, protocol, game=None):
    """Put the Switch files of one finished download in the library.

    client: the download client entry. reported: where the client says the download is.
    game_files: [{"type", "path", "version"}] of the game as the library has it. wanted: "UPD",
    "DLC" or "BASE" (a game that is not in the library yet), what the download was sent for. game: (title ID, name) of the game; with it and
    a folder name template, the folder comes from the template and not from the files the game
    has. Returns ([{"file", "folder", "how"}] of what was brought in, [files that were left
    where they are]). ImportProblem says why not."""
    ready(game_files, game, wanted)
    if not reported:
        raise ImportProblem(f"{client['name']} no longer has this download in its list, so it does not say where the files are, "
                            "and no folder named after the release was found where its other downloads are")
    source = local_download(client, str(reported))
    if not os.path.exists(source):
        raise ImportProblem(
            f"{source} is not there in this container. Make the download folder a volume of the container, under "
            f"the same path as in {client['name']}; or give the download client a Remote Path and a Local Path.")
    return place(source, game_files, wanted, protocol == "torrent", game)


def ready(game_files, game, wanted=None):
    """What importing needs before a file is looked at; ImportProblem says what is missing."""
    if not config.ROOT_FOLDERS:
        raise ImportProblem("there is no root folder yet (Settings > Media Management > Root Folders)")
    if wanted == "BASE" and not game_files and not config.FOLDER_TEMPLATE:
        raise ImportProblem("a game that is not in the library yet needs a Folder Name Template "
                            "(Settings > Media Management) to get a folder of its own")
    if not (game and config.FOLDER_TEMPLATE) and not game_files:
        raise ImportProblem("the library has not been read yet, or does not say where the files of this game are")


def manual(path, game_files, wanted, game, dry=False):
    """Manual Import: the Switch files of a folder or a file the user chose, moved to the
    folder of a game. A file that has the title ID of another game in its name is left where
    it is. `dry`: only say what would be done. Returns what bring() returns."""
    ready(game_files, game, wanted)
    source = os.path.normpath("/" + str(path or "").strip().lstrip("/"))
    if not os.path.exists(source):
        raise ImportProblem(f"{source} is not there in this container")
    real = os.path.realpath(source)
    for root in config.ROOT_FOLDERS:
        inside = os.path.realpath(root["path"])
        if under(real, inside):
            raise ImportProblem(f"{source} is in your library already (the root folder {root['path']})")
        if under(inside, real):
            raise ImportProblem(f"{source} holds your library (the root folder {root['path']}): choose the folder of the download itself")
    return place(source, game_files, wanted, False, game, dry=dry, only=game[0])


def family(title_id):
    """Base game, update and DLC of one game share everything but the last 13 bits."""
    return int(title_id, 16) & ~0x1FFF


def place(source, game_files, wanted, keep, game=None, dry=False, only=None):
    """Put the Switch files of a folder or a file of this container in the library (see bring).
    keep: leave the originals where they are. only: the title ID of the game; files named with
    the title ID of another game are left."""
    templated = bool(game and config.FOLDER_TEMPLATE)
    try:
        files = switch_files(source)
        if not files:
            what, packed = holds(source)
            advice = ("The download is still packed: let your download client unpack, or unpack it by hand and try again."
                      if packed else "Were its files moved by hand?" if what == "the folder is empty"
                      else "Nothing in it is a file for the Switch.")
            raise ImportProblem(f"there are no Switch files (NSP, NSZ, XCI, XCZ) in {source}: {what}. {advice}")
        done, left, others = [], [], []
        for file in files:
            named = TITLE_ID.search(os.path.basename(file))
            if only and named and family(named.group(1)) != family(only):
                others.append(file)  # of another game: not for the folder of this one
                continue
            kind = kind_of(os.path.basename(file), wanted)
            if kind == "BASE" and wanted != "BASE":
                left.append(file)  # the game itself, from a bundle: the library has it already
                continue
            folder, root = game_folder(*game) if templated else local_library(folder_for(game_files, kind))
            # Whatever the library says: nothing is written outside a root folder.
            if not under(os.path.realpath(folder), os.path.realpath(root)):
                raise ImportProblem(f"{folder} is not inside the root folder {root}")
            target, how = put(file, folder, keep, dry)
            done.append({"file": os.path.basename(target), "folder": folder, "how": how})
    except PermissionError as e:
        raise ImportProblem(f"NSWHunter may not write {e.filename or 'there'}. The user of the container has to own "
                            "the library and the download folder, or be in their group.") from e
    except OSError as e:
        raise ImportProblem(f"{e.filename or source}: {e.strerror or e}") from e
    if not done and others:
        names = ", ".join(os.path.basename(f) for f in others[:3]) + (" and more" if len(others) > 3 else "")
        raise ImportProblem(f"the Switch files in {source} have the title ID of another game: {names}")
    if not done:
        raise ImportProblem("the download only holds the game itself, which the library has already")
    return done, left + others


def tidy(client, reported, spare=()):
    """Remove the folder of a download if nothing is left in it, with the empty folders inside
    it. Only a folder without a single file goes: one leftover (an .nfo, a sample, the game
    itself from a bundle) and it stays as it is, with every folder that leads to that file.
    Never a root folder or a folder one is in, never a volume, never a folder in `spare`
    (where the other downloads of the client are). Returns the folder if it is gone."""
    source = local_download(client, str(reported or ""))
    if not reported or os.path.islink(source) or not os.path.isdir(source):
        return None
    real = os.path.realpath(source)
    kept = [os.path.realpath(r["path"]) for r in config.ROOT_FOLDERS]
    kept += [os.path.realpath(local_download(client, str(s))) for s in spare if s]
    if os.path.ismount(source) or any(under(k, real) for k in kept):
        return None
    for folder, _, _ in os.walk(source, topdown=False):  # the deepest first; a link is not followed
        try:
            os.rmdir(folder)  # refuses a folder that holds anything, so nothing is lost
        except OSError:
            pass
    return None if os.path.lexists(source) else source


EMPTY_AGE = 600  # seconds a folder has to be left alone before the sweep takes it for left behind


def sweep(client, folder, age=EMPTY_AGE):
    """Remove the folders in the folder of finished downloads of a client that hold no file at
    all: what earlier downloads left when their files went to the library. A folder with a file
    anywhere in it is not touched, nor one that changed in the last minutes (a download that
    is just starting). Returns the folders that are gone."""
    top = local_download(client, str(folder or ""))
    try:
        found = sorted(e.path for e in os.scandir(top) if e.is_dir(follow_symlinks=False))
    except OSError:
        return []
    gone, now = [], time.time()
    for path in found:
        try:
            walked = list(os.walk(path))
            if any(names for _, _, names in walked) or now - max(os.stat(f).st_mtime for f, _, _ in walked) < age:
                continue
        except (OSError, ValueError):
            continue
        if tidy({}, path):
            gone.append(path)
    return gone


def root_folders():
    """The root folders for the panel: their paths, whether they are there, and the free space."""
    listed = []
    for root in config.ROOT_FOLDERS:
        entry = {**root, "ok": os.path.isdir(root["path"]) and os.access(root["path"], os.W_OK), "free": None, "total": None}
        try:
            usage = shutil.disk_usage(root["path"])
            entry.update(free=usage.free, total=usage.total)
        except OSError:
            pass
        listed.append(entry)
    return listed


LOW_LIBRARY = 5 * 2**30  # less free than this where the library or the downloads are: a warning
LOW_CONFIG = 100 * 2**20  # and where only the settings are


def disks(places):
    """The disks a list of (what, path) is on, each once: [{"places": [{"what", "path"}],
    "free", "total", "low"}]. Two folders on one disk share its space, so they are one row.
    low: there is so little left that a download or the settings may no longer fit. A folder
    that is not there or cannot be read is left out."""
    found = {}
    for what, path in places:
        try:
            device, usage = os.stat(path).st_dev, shutil.disk_usage(path)
        except OSError:
            continue
        disk = found.setdefault(device, {"places": [], "free": usage.free, "total": usage.total, "low": False})
        if {"what": what, "path": path} not in disk["places"]:
            disk["places"].append({"what": what, "path": path})
    for disk in found.values():
        only_config = all(p["what"] == "Config folder" for p in disk["places"])
        disk["low"] = disk["free"] < (LOW_CONFIG if only_config else LOW_LIBRARY)
    return list(found.values())


MAX_LISTED = 1000


def browse(path, files=False):
    """What the File Browser of the panel shows for a path in this container: the folders in
    it (and the files, if asked), and the folder above it. A path that is not a folder is a
    name being typed: its folder is listed, with the names that start like it.

    Returns {"folder", "parent", "entries": [{"name", "path", "folder"}], "error"}. Only names:
    nothing of what is inside a file."""
    # A whole path, without "..". One slash in front: two would be a path of its own kind.
    path = os.path.normpath("/" + str(path or "").strip().lstrip("/"))
    start = ""
    folder = path
    if not os.path.isdir(folder):
        start, folder = os.path.basename(folder).lower(), os.path.dirname(folder)
        while not os.path.isdir(folder):
            start, folder = "", os.path.dirname(folder)  # typed further than what is there
    entries, error = [], ""
    try:
        with os.scandir(folder) as found:
            for entry in found:
                try:
                    is_folder = entry.is_dir()
                    wanted = is_folder or (files and entry.is_file())
                except OSError:
                    continue
                if wanted and not entry.name.startswith(".") and entry.name.lower().startswith(start):
                    entries.append({"name": entry.name, "path": os.path.join(folder, entry.name), "folder": is_folder})
    except OSError as e:
        error = f"{folder} cannot be read: {e.strerror or e}"
    entries.sort(key=lambda e: (not e["folder"], e["name"].casefold()))
    return {"folder": folder, "parent": None if folder == "/" else os.path.dirname(folder),
            "entries": entries[:MAX_LISTED], "error": error}
