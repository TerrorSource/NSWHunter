"""Putting a finished download in the library, as Completed Download Handling does in Sonarr
and Radarr.

The download client says where a finished download is. The Switch files in it are moved to the
folder of their game in the library: next to the updates (or DLC) the game already has, or else
next to the game itself. A torrent is linked or copied instead, so it can go on seeding.

Both folders have to be volumes of this container. The library is named by its root folders
(Settings > Media Management); nothing is ever written outside one, and nothing is overwritten."""
import os
import re
import shutil

import config

EXTENSIONS = (".nsp", ".nsz", ".xci", ".xcz")
TITLE_ID = re.compile(r"(?<![0-9A-Fa-f])(0[0-9A-Fa-f]{15})(?![0-9A-Fa-f])")
PART = ".nswhunter-part"  # a file that is still being copied; the library does not read this


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


def switch_files(path):
    """The Switch files of a download: the file itself, or everything in its folder."""
    if os.path.isfile(path):
        return [path] if path.lower().endswith(EXTENSIONS) else []
    found = []
    for folder, _, names in os.walk(path):
        found += [os.path.join(folder, n) for n in sorted(names) if n.lower().endswith(EXTENSIONS) and not n.startswith(".")]
    return found


def put(source, folder, keep):
    """Bring one file into a folder; `keep` leaves the original where it is (a torrent that goes
    on seeding). Returns (the new file, how it got there). Nothing is overwritten."""
    target = os.path.join(folder, os.path.basename(source))
    if os.path.lexists(target):
        if os.path.isfile(target) and os.path.getsize(target) == os.path.getsize(source):
            return target, "was there already"
        raise ImportProblem(f"{target} is there already, with another size")
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


def bring(client, reported, game_files, wanted, protocol):
    """Put the Switch files of one finished download in the library.

    client: the download client entry. reported: where the client says the download is.
    game_files: [{"type", "path", "version"}] of the game as the library has it. wanted: "UPD"
    or "DLC", what the download was sent for. Returns ([{"file", "folder", "how"}] of what
    was brought in, [files that were left where they are]). ImportProblem says why not."""
    if not config.ROOT_FOLDERS:
        raise ImportProblem("there is no root folder yet (Settings > Media Management > Root Folders)")
    if not reported:
        raise ImportProblem(f"{client['name']} does not say where the download is")
    if not game_files:
        raise ImportProblem("the library has not been read yet, or does not say where the files of this game are")
    source = local_download(client, str(reported))
    try:
        if not os.path.exists(source):
            raise ImportProblem(
                f"{source} is not there in this container. Make the download folder a volume of the container, under "
                f"the same path as in {client['name']}; or give the download client a Remote Path and a Local Path.")
        files = switch_files(source)
        if not files:
            raise ImportProblem(f"there are no Switch files (NSP, NSZ, XCI, XCZ) in {source}. Is the download still packed?")
        done, left = [], []
        for file in files:
            kind = kind_of(os.path.basename(file), wanted)
            if kind == "BASE":
                left.append(file)  # the game itself, from a bundle: the library has it already
                continue
            folder, root = local_library(folder_for(game_files, kind))
            # Whatever the library says: nothing is written outside a root folder.
            if not under(os.path.realpath(folder), os.path.realpath(root)):
                raise ImportProblem(f"{folder} is not inside the root folder {root}")
            target, how = put(file, folder, keep=protocol == "torrent")
            done.append({"file": os.path.basename(target), "folder": folder, "how": how})
    except PermissionError as e:
        raise ImportProblem(f"NSWHunter may not write {e.filename or 'there'}. The user of the container has to own "
                            "the library and the download folder, or be in their group.") from e
    except OSError as e:
        raise ImportProblem(f"{e.filename or source}: {e.strerror or e}") from e
    if not done:
        raise ImportProblem("the download only holds the game itself, which the library has already")
    return done, left


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
