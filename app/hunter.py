"""What NSWHunter does each round: read the library, look for releases, judge them, send them."""
import asyncio
import datetime
import hashlib
import json
import os
import re
import secrets
import time
import unicodedata

import backup
import clients
import config
import downloads
import importer
import indexers
import logs
import matcher
import notify

MAX_CANDIDATES = 15
MAX_REJECTED = 25
MAX_FAILED = 10  # failed downloads kept per item, for the panel
# What the panel needs of a release that fell off; the judgement is made again when it counts.
RELEASE_FIELDS = ("guid", "title", "size", "indexer", "indexerId", "published", "downloadUrl",
                  "infoUrl", "grabs", "priority", "source", "protocol", "seeders")
# A release that belongs under another item of the same game did not fall off: it is there.
ELSEWHERE = ("is another DLC", "names no DLC", "names one DLC", "has the title ID of one DLC",
             "not DLC", "DLC only", "title ID of another part")
MAX_EVENTS = 1000
COVER_ID = re.compile(r"[0-9A-F]{16}")
# What a round is made of, as the Tasks page lists it: name -> how it is called there.
TASKS = {"health": "Check Health", "library": "Library Sync", "rss": "Rss Sync", "search": "Search Missing",
         "downloads": "Refresh Monitored Downloads", "import": "Rescan Download Folder",
         "versions": "Refresh Version List", "backup": "Backup"}
MAX_HISTORY = 500  # what was sent, arrived or failed, for the History page
MAX_TURNED_DOWN = 25  # releases the user rejected, kept per item so they can be restored
ARRIVED_DAYS = 30  # how long the panel shows what arrived
MAX_LOOKUP = 10  # Add Game: the games a search by name offers at most
MAX_LIST = 50  # Add Game: the lines of a pasted list
# Words that make another edition of the same game, not another game.
EDITION_WORDS = {"edition", "complete", "deluxe", "special", "ultimate", "definitive", "gold", "goty", "game",
                 "of", "the", "year", "plus", "remastered", "hd", "digital", "standard", "nintendo", "switch", "and", "version"}
TITLES_DAYS = 7  # how often the names of all games are fetched anew
DISK_SECONDS = 60  # how long the free space of the disks is taken as known
SCAN_WAIT = 900  # Rescan Folder: the longest wait for the library to finish its scan
SCAN_LOOK = 3  # seconds between two looks whether it is done
MAX_ASKS = 10  # questions in Telegram per round
ASK_DELAY = 1.1  # seconds between two messages: Telegram allows about one per second to a chat
DEFAULT_PRIORITY = 25  # what Prowlarr gives an indexer that has none set


log = logs.info


def published_date(release):
    try:
        return datetime.date.fromisoformat(release.get("published", "")[:10])
    except ValueError:
        return None


def best_first(candidate):
    """Sort key: the highest score first, then the newest post, then the indexer with the
    highest priority in Prowlarr (the lowest number), then the one most people took."""
    return (-candidate.get("score", 0), -published_ordinal(candidate),
            priority_of(candidate), -(candidate.get("grabs") or 0))


def priority_of(release):
    """The priority in Prowlarr of the indexer a release came from. A release kept by an
    older version has none, and one without a number cannot be sorted."""
    value = release.get("priority")
    return value if isinstance(value, int) else DEFAULT_PRIORITY


def published_ordinal(release):
    day = published_date(release)
    return day.toordinal() if day else 0



def words_of(name):
    """The words of a name, to hold names against each other: without case, accents, marks
    like ™ and punctuation. "Assassin's Creed®" and "assassins creed" are the same."""
    text = unicodedata.normalize("NFKD", re.sub("[™®©℠]", " ", str(name)))  # NFKD would make ™ "TM"
    text = "".join(c for c in text if not unicodedata.combining(c)).casefold()
    return tuple(re.sub(r"[^\w]+", " ", re.sub(r"['’`]", "", text)).split())


class Hunter:
    def __init__(self, session):
        self.session = session
        self.lock = asyncio.Lock()  # one round or search at a time
        self.tell_later, self.dropped, self.finished = [], False, False  # of follow_grabs
        self.games = {}  # game id -> matcher.Game, only games that miss something
        self.files = {}  # game id -> where its files are, as the library names them; of every game
        self.disks = (0, [])  # (when it was looked at, the free space of the folders that matter)
        self.versions = {}  # titledb: lower-case title id -> {"65536": "2021-10-05"}
        self.titles = {}  # titledb: base title ID -> [name, picture address, YYYYMMDD], for Add Game
        self.titles_gate = asyncio.Lock()
        self.background = set()  # tasks that run on their own, kept until they are done
        self.newly_owned = []  # games of the wishlist the last library sync found in the library
        # (id of a Prowlarr in the settings, id that Prowlarr has for an indexer) -> priority
        self.priorities = {}
        self.status = {"running": False, "phase": None, "last_run": None, "next_run": None,
                       "error": None,  # {"text", "at"} of the last round, if it broke
                       "skipped": 0}  # games and releases the last round had to leave out
        self.troubles = set()  # what was already written to the log about those
        self.cover_gate = asyncio.Semaphore(4)  # pictures fetched at the same time
        self.failed = []  # the downloads that failed in this look at the download clients (see follow_grabs)
        self.no_cover = {}  # picture -> when fetching it last failed
        self.state = {
            "items": {},  # key -> one missing update or DLC, with its candidates
            "searched": {},  # game id -> time of the last search by name
            "vermap": {},  # game id -> {"1.0.4": 262144}
            "seen": {},  # game id -> {"1.7.1": "2026-09-30"}: display versions and their first post
            "versions_source": "",
            "events": [],
            "library": {"fetched": None, "games": 0, "updates": 0, "dlc": 0},
            "services": {},  # name -> {"ok": bool, "text": str}
            "versions_fetched": 0,
            "arrived": [],  # what was sent and is now in the library, newest first
            "games": [],  # every game of the library, for the Games page
            "history": [],  # what was sent, arrived and failed, newest first
            "covers": {},  # title ID -> where the small picture of the game is
            "covers_fetched": 0,
            "tasks": {},  # name -> {"last": when it last ran, "duration": seconds}
            "telegram_offset": 0,  # the next update to ask Telegram for
            "new_games": [],  # the wishlist: games that are not in the library yet: {"id", "name", "added", "released"}
            "titles_fetched": 0,
        }
        self.load()

    # ------------------------------------------------------------ state file

    def load(self):
        try:
            with open(config.STATE_FILE) as f:
                saved = json.load(f)
            self.state.update(saved)
            for item in self.state["items"].values():
                for candidate in item.get("candidates", []):
                    candidate.setdefault("score", 0)  # judged again in the first round
            if "seen" not in saved:
                # State from before the version ladder: search every game once more, so the
                # display versions in the release names are noticed.
                self.state["searched"] = {}
        except (FileNotFoundError, ValueError):
            pass
        try:
            with open(config.VERSIONS_FILE) as f:
                self.versions = json.load(f)
        except (FileNotFoundError, ValueError):
            self.state["versions_fetched"] = 0
        try:
            with open(config.TITLES_FILE) as f:
                self.titles = json.load(f)
        except (FileNotFoundError, ValueError):
            self.state["titles_fetched"] = 0

    def save(self):
        os.makedirs(config.DATA_DIR, exist_ok=True)
        tmp = config.STATE_FILE + ".tmp"
        # Only for the owner: the download links in it hold the API key of Prowlarr.
        with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
            json.dump(self.state, f)
        os.chmod(tmp, 0o600)  # a .tmp left behind keeps the mode it was made with
        os.replace(tmp, config.STATE_FILE)

    def log(self):
        """The whole log, for the Log page."""
        return self.state["events"]

    def library(self):
        """Every game of the library, for the Games page."""
        return self.state.get("games", [])

    def history(self):
        """What was sent, arrived and failed, for the History page."""
        return self.state.get("history", [])

    def tasks(self):
        """What runs by itself, for the Tasks page: how often, when last, how long, when next."""
        done, next_round = self.state.get("tasks", {}), self.status.get("next_run")
        every_round = config.SYNC_INTERVAL_MINUTES * 60
        hours, days = config.SEARCH_INTERVAL_HOURS * 3600, config.BACKUP_INTERVAL_DAYS * 86400
        searched = self.state["searched"]
        open_games = [g for g in self.games if any(not i["ignored"] and not i["grab"] for i in self.items_of(g))]
        oldest = min((searched.get(g, 0) for g in open_games), default=None)
        queued = any(i.get("grab") for i in self.state["items"].values())
        unplaced = config.IMPORT_COMPLETED and bool(self.unplaced())
        watched = (done.get("downloads", {}).get("last", 0) + config.WATCH_SECONDS)
        scheduled = [b["at"] for b in backup.listing() if b["kind"] == "scheduled"]
        fetched = self.state.get("versions_fetched") or 0

        def after(moment):
            """The first round at or after a moment: these tasks run as part of a round."""
            return max(moment, next_round or 0) or None

        rows = {
            "health": (every_round, next_round, "The library, every indexer and every download client"),
            "library": (every_round, next_round, "What your library has and misses"),
            "rss": (every_round, next_round, "The newest posts of your indexers, held against what is missing"),
            "search": (hours, None if oldest is None else after(oldest + hours),
                       "Every game that misses something, by name; a game is searched when its turn comes"),
            "downloads": (config.WATCH_SECONDS, watched if queued else None, "Only while something is in the queue"),
            "import": (config.WATCH_SECONDS, watched if unplaced else None,
                       "Finished downloads that are not in the folder of their game yet: their folders are looked at again, "
                       "as after unpacking one by hand. Only while Import Completed Downloads is on"),
            "versions": (86400, after(fetched + 86400), "Every update of every game with its date; once a week also "
                         "the names of all games, for Add Game"),
            "backup": (days, after(max(scheduled) + days) if scheduled else next_round, "The settings and the state"),
        }
        result = []
        for name, (interval, upcoming, about) in rows.items():
            last = done.get(name, {})
            result.append({"name": name, "text": TASKS[name], "about": about, "interval": int(interval),
                           # Not run since this version started counting: what is known another way.
                           "last": last.get("last") or (max(scheduled) if name == "backup" and scheduled else None)
                           or (fetched if name == "versions" and fetched else None)
                           or (max(searched.values()) if name == "search" and searched else None),
                           "duration": last.get("duration"), "next": int(upcoming) if upcoming else None})
        return result

    async def run_task(self, name):
        """The button of a task: run it now. Returns True if a round has to start for it."""
        if name not in TASKS:
            raise clients.ServiceError("Unknown task")
        if config.problems():
            raise clients.ServiceError("NSWHunter is not set up yet")
        if name == "search":
            self.search_all()
            return True  # the round that starts now searches every game
        if self.lock.locked():
            raise clients.ServiceError("A round is running. Try again when it is done.")
        async with self.lock:
            if name == "health":
                await self.task("health", self.check_services())
            elif name == "library":
                await self.task("library", self.sync_library())
            elif name == "rss":
                if not self.games:
                    await self.sync_library()
                await self.task("rss", self.feed())
            elif name == "downloads":
                await self.task("downloads", self.follow_grabs())
            elif name == "import":
                await self.task("import", self.rescan_downloads())
            elif name == "versions":
                self.state["versions_fetched"] = self.state["titles_fetched"] = 0
                await self.task("versions", self.refresh_versions())
                await self.refresh_titles()
                await self.sync_library()  # the dates of the updates are used when the library is read
            elif name == "backup":
                self.backups(now=True)
                if "backup" in self.state["services"]:
                    raise clients.ServiceError(self.state["services"]["backup"]["text"])
            self.save()
        return False

    def search_all(self):
        """The button "Search All": every game is searched by name in the next round, not only
        the ones whose turn it is. Returns how many games that are."""
        self.state["searched"] = {}
        return len(self.games)

    def search_wishlist(self):
        """The button "Search All" on the Wishlist: only the games of the wishlist, at once.
        Returns how many games that are."""
        ids = sorted({i["game_id"] for i in self.state["items"].values() if i["type"] == "game"})
        if ids:
            self.later(self.search_games(ids))
        return len(ids)

    def event(self, text, level="info"):
        log(text)
        self.state["events"].insert(0, {"at": int(time.time()), "text": text, "level": level})
        del self.state["events"][MAX_EVENTS:]

    def service(self, name, ok, text):
        self.state["services"][name] = {"ok": ok, "text": text, "at": int(time.time())}

    def did(self, name, start):
        """Remember when a task ran and how long it took, for the Tasks page: per task the last
        time, and the last twenty runs of any task."""
        duration = round(time.time() - start, 2)
        self.state.setdefault("tasks", {})[name] = {"last": int(start), "duration": duration}
        run = {"name": name, "text": TASKS[name], "started": int(start), "ended": int(time.time()), "duration": duration}
        self.state["task_runs"] = [run] + self.state.get("task_runs", [])[:19]

    async def task(self, name, work):
        start = time.time()
        try:
            return await work
        finally:
            self.did(name, start)

    def provider(self, kind, entry, ok, text):
        """What an indexer, download client or connection last said."""
        self.state["services"][f"{kind}:{entry['id']}"] = {
            "ok": ok, "text": text, "at": int(time.time()), "name": entry["name"], "kind": kind}
        logs.debug(f"{entry['name']}:", "ok" if ok else "FAILED", "-", text)

    def working(self, kind):
        """Does at least one enabled entry of this kind answer?"""
        services = self.state["services"]
        return any(services.get(f"{kind}:{e['id']}", {}).get("ok") for e in config.providers(kind, enabled=True))

    def forget_services(self):
        """Drop what was said by entries that are gone or switched off."""
        live = {f"{kind}:{e['id']}" for kind in config.KINDS for e in config.providers(kind, enabled=True)}
        for name in [n for n in self.state["services"] if n not in live and n not in ("slm", "titledb", "config", "backup", "ssl")]:
            del self.state["services"][name]

    def legacy_source(self):
        """A release kept by a version that knew one Prowlarr only: it came from that one."""
        return next((i["id"] for i in config.providers("INDEXERS") if i["type"] == "prowlarr"), "")

    def skip(self, what, error, count=True):
        """Leave out one game or release that cannot be handled, so the rest goes on. Written
        to the log once; the panel says how many the last round left out."""
        self.status["skipped"] += 1 if count else 0
        text = f"Skipped {what}: {error!r}"
        if text not in self.troubles:
            self.troubles.add(text)
            self.event(text, "error")

    # ------------------------------------------------------------ library

    def dates_for(self, game_id):
        dates = {}
        for version, day in (self.versions.get(game_id.lower()) or {}).items():
            try:
                dates[int(version)] = datetime.date.fromisoformat(str(day)[:10])
            except ValueError:
                continue
        return dates

    async def refresh_versions(self):
        """Every update of every game with its date. Once a day is plenty."""
        source = config.TITLEDB_VERSIONS_URL
        fresh = time.time() - self.state["versions_fetched"] < 86400
        if not source or (fresh and self.state.get("versions_source") == source):
            return
        try:
            text = await clients.titledb_versions(self.session)
            versions = json.loads(text)
            if not isinstance(versions, dict):
                raise clients.ServiceError("Version list: unexpected answer")
        except (clients.ServiceError, ValueError) as e:
            self.service("titledb", False, str(e))
            return
        self.versions = {str(k).lower(): v for k, v in versions.items() if isinstance(v, dict)}
        os.makedirs(config.DATA_DIR, exist_ok=True)
        with open(config.VERSIONS_FILE, "w") as f:
            json.dump(self.versions, f)
        self.state["versions_fetched"] = int(time.time())
        self.state["versions_source"] = source
        self.service("titledb", True, f"{len(self.versions)} games")

    def versions_due(self):
        source = config.TITLEDB_VERSIONS_URL
        fresh = time.time() - self.state["versions_fetched"] < 86400
        return bool(source) and not (fresh and self.state.get("versions_source") == source)

    def titles_due(self):
        return bool(config.TITLEDB_TITLES_URL) and time.time() - self.state.get("titles_fetched", 0) > TITLES_DAYS * 86400

    async def refresh_titles(self):
        """The name, picture and release date of every game, for Add Game. Once a week: it is a
        download of over 20 MB. Without it Add Game searches the indexers by name."""
        async with self.titles_gate:  # Add Game may ask for it while a round fetches it
            if self.titles_due():
                await self.fetch_titles()

    async def fetch_titles(self):
        try:
            data = await clients.titledb_titles(self.session)
            titles = await asyncio.to_thread(clients.title_list, data)
        except Exception as e:  # noqa: BLE001 - a broken download (zstd, JSON) must not break the round
            self.event(f"The list of all games for Add Game could not be fetched: {e}", "warn")
            self.state["titles_fetched"] = int(time.time()) - (TITLES_DAYS - 1) * 86400  # again in a day
            return
        self.titles = titles
        os.makedirs(config.DATA_DIR, exist_ok=True)
        with open(config.TITLES_FILE + ".tmp", "w") as f:
            json.dump(titles, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(config.TITLES_FILE + ".tmp", config.TITLES_FILE)
        self.state["titles_fetched"] = int(time.time())
        logs.debug(f"Title list: {len(titles)} games")

    def cover_address(self, game_id):
        """Where the picture of a game is: the library first, then the list of all games."""
        return self.state.get("covers", {}).get(game_id) or (self.titles.get(game_id) or ["", ""])[1]

    async def refresh_covers(self):
        """Where the small pictures of the games are, as switch-library-manager-web says. Asked
        once a day. Without them the games are listed without a picture: nothing else needs them."""
        if time.time() - self.state.get("covers_fetched", 0) < 86400:
            return
        try:
            self.state["covers"] = await clients.cover_addresses(self.session)
            self.state["covers_fetched"] = int(time.time())
            logs.debug(f"Covers: {len(self.state['covers'])} games have a picture")
        except clients.ServiceError as e:
            logs.debug("No covers:", e)
            self.state["covers_fetched"] = int(time.time()) - 86400 + 3600  # again in an hour

    async def cover(self, game_id):
        """(content type, bytes) of the small picture of a game, or None if there is none. A
        picture is fetched once and then kept in the folder covers of the config folder."""
        address = self.cover_address(game_id) if COVER_ID.fullmatch(game_id) else ""
        if not address:
            return None
        # The address is part of the name: a new picture in the library is fetched anew.
        stem = f"{game_id}_{hashlib.sha256(address.encode()).hexdigest()[:8]}"
        for kind, extension in clients.IMAGES.items():
            path = os.path.join(config.COVER_DIR, f"{stem}.{extension}")
            if os.path.isfile(path):
                with open(path, "rb") as f:
                    return kind, f.read()
        if self.no_cover.get(stem, 0) > time.time() - 3600:
            return None
        async with self.cover_gate:
            try:
                kind, data = await clients.cover(self.session, address)
            except clients.ServiceError as e:
                self.no_cover[stem] = time.time()
                logs.debug(f"No picture of {game_id}:", e)
                return None
        try:
            os.makedirs(config.COVER_DIR, exist_ok=True)
            for old in os.listdir(config.COVER_DIR):
                if old.startswith(game_id + "_"):
                    os.remove(os.path.join(config.COVER_DIR, old))
            path = os.path.join(config.COVER_DIR, f"{stem}.{clients.IMAGES[kind]}")
            with open(path + ".tmp", "wb") as f:
                f.write(data)
            os.replace(path + ".tmp", path)
        except OSError:
            pass  # not kept: it is fetched again the next time
        return kind, data

    async def sync_library(self):
        """Read the export and keep one item per missing update (and per missing DLC)."""
        try:
            titles = await clients.library(self.session)
        except clients.ServiceError as e:
            self.service("slm", False, str(e))
            return False
        await self.refresh_covers()
        games, wanted, broken, listed = {}, {}, set(), []
        for title in titles:
            try:
                self.read_title(title, games, wanted, listed)
            except Exception as e:  # noqa: BLE001
                game_id = str(title.get("id", "")).upper() if isinstance(title, dict) else ""
                broken.add(game_id)  # what is known about it is kept as it is
                self.skip(f"{game_id or 'a game'} of the library", e)
        added = self.want_new_games(games, wanted, {g["id"] for g in listed} | broken)
        items = self.state["items"]
        arrived = []
        for key in [k for k in items if k not in wanted and items[k]["game_id"] not in broken]:
            gone = items.pop(key)
            if gone["type"] == "game":
                self.arrive(gone, gone.get("grab") or {"title": gone["name"]}, "it leaves the wishlist")
            elif gone.get("grab") and gone["type"] != "dlcpack":
                arrived.append(f"Arrived: {self.label(gone)} is now in the library")
                self.arrive(gone, gone["grab"])
        for key, facts in wanted.items():
            item = items.setdefault(key, {
                "key": key, "candidates": [], "blocked": [], "ignored": False,
                "grab": None, "first_seen": int(time.time())})
            grab = item.get("grab")
            if grab and facts.get("local_version", 0) > grab.get("local_version", facts.get("local_version", 0)):
                # What was sent arrived, but it was not the newest update: choose again.
                arrived.append(f"Arrived: {grab['title']}. There is a newer update still.")
                self.arrive(item, grab, "a newer update is still missing")
                item["grab"] = None
            elif grab and facts.get("dlc_missing", 0) < grab.get("dlc_missing", 0):
                arrived.append(f"Arrived: {grab['title']}. {facts['dlc_missing']} DLC are still missing.")
                self.arrive(item, grab, f"{facts['dlc_missing']} DLC are still missing")
                item["grab"] = None
            item.update(facts)
        self.games = games
        self.state["games"] = sorted(listed, key=lambda g: g["name"].lower())
        logs.debug(f"Library: {len(listed)} games, {len(wanted)} things to look for")
        self.state["library"] = {
            "fetched": int(time.time()), "games": len(titles),
            "updates": sum(1 for i in items.values() if i["type"] == "update"),
            "dlc": sum(1 for i in items.values() if i["type"] == "dlc"),
        }
        self.service("slm", True, f"{len(titles)} games")
        self.reevaluate()
        for text in arrived:
            self.event(text, "grab")
            await self.tell(text, "arrive")
        self.newly_owned = [game["id"] for game in added]
        for game in added:
            # Its updates and DLC are searched at once, not when the turn of the game comes.
            self.state["searched"].pop(game["id"], None)
            text = f"Arrived: {game['name']} is in your library now and leaves the wishlist"
            self.event(text, "grab")
            await self.tell(text + ". NSWHunter looks for its updates and DLC now.", "arrive")
        return True

    def want_new_games(self, games, wanted, owned):
        """The games of Add Game as items to look for. One that is in the library now leaves the
        list; the games of the library are `owned`. Returns the ones that left."""
        left = [g for g in self.state["new_games"] if g["id"] in owned]
        self.state["new_games"] = [g for g in self.state["new_games"] if g["id"] not in owned]
        for new in self.state["new_games"]:
            games[new["id"]] = matcher.Game(id=new["id"], name=new["name"])
            wanted[new["id"] + ":game"] = {"type": "game", "game_id": new["id"], "name": new["name"],
                                           "released": new.get("released") or 0}
        return left

    def read_title(self, title, games, wanted, listed):
        """One game of the export: a line for the Games page, and what it misses as items to
        look for."""
        game_id = str(title.get("id", "")).upper()
        # 04...: a Switch 2 title. Left alone on purpose: only the first Switch.
        if len(game_id) != 16 or game_id.startswith("04"):
            return
        name = title.get("name") or ""
        if name == "Unknown title":
            name = ""  # nothing to match on; only a title ID can identify it
        update = bool(title.get("updateMissing")) and not title.get("updatesIgnored")
        all_dlc = [{"id": str(d.get("id", "")).upper(), "name": d.get("name") or "",
                    "status": d.get("status")} for d in title.get("dlc") or [] if isinstance(d, dict)]
        missing_dlc = [d for d in all_dlc if d["status"] == "missing"] if config.INCLUDE_DLC else []
        listed.append({
            "id": game_id, "name": name or game_id, "version": title.get("version") or "",
            "cover": game_id in self.state.get("covers", {}),
            "local": int(title.get("localUpdate") or 0), "latest": int(title.get("latestUpdate") or 0),
            "update_missing": update, "updates_ignored": bool(title.get("updatesIgnored")),
            "dlc_missing": sum(1 for d in all_dlc if d["status"] == "missing"),
            "dlc_owned": sum(1 for d in all_dlc if d["status"] == "owned"),
            "size": sum(int(f.get("size") or 0) for f in title.get("files") or [] if isinstance(f, dict))})
        # Where the files of the game are, as the library names them: a download is put next to
        # them. Of every game, so one that misses nothing can take a manual import too.
        self.files[game_id] = [{"type": str(f.get("type") or ""), "path": f["path"], "version": int(f.get("version") or 0)}
                               for f in title.get("files") or [] if isinstance(f, dict) and isinstance(f.get("path"), str)]
        if not update and not missing_dlc:
            return
        game = matcher.Game(
            id=game_id, name=name,
            local_version=int(title.get("localUpdate") or 0),
            latest_version=int(title.get("latestUpdate") or 0),
            local_display=title.get("version") or None,
            dates=self.dates_for(game_id), missing_dlc=missing_dlc, dlc=all_dlc,
            **self.sizes(title))
        games[game_id] = game
        shown = name or game_id
        if update:
            wanted[game_id] = {
                "type": "update", "game_id": game_id, "name": shown,
                "local_version": game.local_version, "latest_version": game.latest_version,
                "local_display": game.local_display,
                "latest_date": str(game.dates.get(game.latest_version) or ""),
            }
        for dlc in missing_dlc:
            wanted[dlc["id"]] = {
                "type": "dlc", "game_id": game_id, "name": shown,
                "dlc_id": dlc["id"], "dlc_name": dlc["name"],
            }
        if missing_dlc:
            # "DLC Unlocker", "DLC Pack": releases that name no DLC, once per game.
            wanted[game_id + ":pack"] = {
                "type": "dlcpack", "game_id": game_id, "name": shown, "dlc_missing": len(missing_dlc)}

    @staticmethod
    def sizes(title):
        """The size of the game and of the newest update in the library, to weigh a release by."""
        files = [f for f in title.get("files") or [] if isinstance(f, dict)]
        updates = [f for f in files if f.get("type") == "UPD"]
        base = [f for f in files if f.get("type") not in ("UPD", "DLC")]
        newest = max(updates, key=lambda f: f.get("version") or 0, default={})
        return {"update_size": int(newest.get("size") or 0),
                "base_size": int(base[0].get("size") or 0) if base else 0}

    @staticmethod
    def what(item):
        return ("DLC: " + (item.get("dlc_name") or item["key"]) if item["type"] == "dlc"
                else "DLC pack" if item["type"] == "dlcpack" else "game" if item["type"] == "game" else "update")

    def record(self, kind, item, title, **more):
        """One line of the History page. kind: "grabbed", "imported", "arrived", "unseen" or "failed"."""
        entry = {"at": int(time.time()), "kind": kind, "game_id": item["game_id"], "name": item["name"],
                 "what": self.what(item), "title": title, **more}
        self.state["history"] = [entry] + self.state.get("history", [])[:MAX_HISTORY - 1]

    def arrive(self, item, grab, note=""):
        """Remember that what was sent is now in the library, for the panel."""
        now = int(time.time())
        what = self.what(item)
        self.record("arrived", item, grab["title"], note=note, client=grab.get("client_name", ""))
        arrived = [a for a in self.state.setdefault("arrived", []) if a["at"] > now - ARRIVED_DAYS * 86400]
        self.state["arrived"] = [{
            "at": now, "game_id": item["game_id"], "name": item["name"], "what": what,
            "title": grab["title"], "auto": bool(grab.get("auto")), "note": note}] + arrived[:299]

    @staticmethod
    def label(item):
        if item["type"] == "dlc":
            return f"{item['name']} (DLC: {item.get('dlc_name') or item['key']})"
        if item["type"] == "dlcpack":
            return f"{item['name']} (DLC pack)"
        if item["type"] == "game":
            return f"{item['name']} (wishlist)"
        return f"{item['name']} (update)"

    def items_of(self, game_id):
        return [i for i in self.state["items"].values() if i["game_id"] == game_id]

    def untried(self, item):
        """The releases of an item that were never sent, the best first. One that was sent and
        is in the queue no more (downloaded but never seen in the library, or taken out of the
        queue) stays in the list with the label "sent", but is no choice to make again."""
        sent = set(item.get("sent") or [])
        return [c for c in item["candidates"] if c["guid"] not in sent]

    def awaits(self, item):
        """Does this item wait for a choice? Not if every release it has was sent before. A
        DLC pack does not while every missing DLC of its game is already on its way: the pack
        would bring the same."""
        if item["ignored"] or item["grab"] or not self.untried(item):
            return False
        if item["type"] == "dlcpack":
            dlc = [i for i in self.items_of(item["game_id"]) if i["type"] == "dlc"]
            return not dlc or not all(i["grab"] for i in dlc)
        return True

    # ------------------------------------------------------------ judging

    def judge(self, item, release):
        """A candidate (dict), or the matcher.Rejection that says why not."""
        game = self.games.get(item["game_id"])
        if game is None:
            return matcher.Rejection("game is no longer in the list")
        dlc = {"id": item.get("dlc_id", ""), "name": item.get("dlc_name", "")}
        vermap = self.state["vermap"].setdefault(game.id, {})
        result = matcher.evaluate(game, release["title"], published_date(release), vermap,
                                  want=item["type"], dlc=dlc, seen=self.seen(game.id),
                                  size=int(release.get("size") or 0), min_game=config.MIN_GAME_MB * 2**20)
        if not self.state["vermap"][game.id]:
            del self.state["vermap"][game.id]
        if isinstance(result, matcher.Rejection):
            return result
        if item["type"] == "game" and result.name_match != "tid":
            other = self.other_title(game.name, release["title"])
            if other:
                return matcher.Rejection(f"another game: {other}")
        return {**{k: release.get(k) for k in RELEASE_FIELDS}, **result.to_dict()}

    def other_title(self, name, title):
        """For a game of the wishlist: another game of the list of all games whose whole name is
        in the release title and longer than this one ("Double Dragon Gaiden" for "Double Dragon").
        Another edition of the same game does not count ("... Special Edition")."""
        if not self.titles:
            return None
        if getattr(self, "title_index", None) is None or self.title_index[0] != len(self.titles):
            index = {}
            for entry in self.titles.values():
                words = tuple(matcher.search_term(entry[0]).split())
                if words:
                    index.setdefault(words[0], []).append((words, entry[0]))
            self.title_index = (len(self.titles), index)
        own = matcher.search_term(name).split()
        toks = matcher.search_term(title).split()
        for i, token in enumerate(toks):
            for words, other in self.title_index[1].get(token, ()):
                if len(words) > len(own) and tuple(toks[i:i + len(words)]) == words \
                        and not set(words) - set(own) <= EDITION_WORDS:
                    return other
        return None

    def seen(self, game_id):
        """{display version: date first posted} of everything seen for a game."""
        result = {}
        for display, day in self.state["seen"].get(game_id, {}).items():
            try:
                result[display] = datetime.date.fromisoformat(day) if day else None
            except ValueError:
                result[display] = None
        return result

    def notice(self, game_id, release):
        """Remember the display version of a release of this game. True if that changed what is
        known: a new version, or an earlier first post."""
        display = matcher.observe(self.games[game_id], release["title"])
        if not display:
            return False
        seen = self.state["seen"].setdefault(game_id, {})
        day = str(published_date(release) or "")
        if display in seen and (not day or (seen[display] and seen[display] <= day)):
            return False
        seen[display] = day
        return True

    def offer(self, item, release):
        """Judge a release for an item and file it: with the candidates, or with what fell off.
        True if it is a new candidate."""
        if release["guid"] in item["blocked"]:
            return False
        if any(c["guid"] == release["guid"] for c in item["candidates"]):
            return False
        if self.failed_before(item, release):
            return False
        return self.place(item, release)

    def place(self, item, release):
        # The priority as Prowlarr has it now; else the one the release was found with.
        source = release.get("source") or self.legacy_source()
        release = {**release, "source": source, "protocol": release.get("protocol") or "usenet",
                   "priority": self.priorities.get((source, release.get("indexerId")), priority_of(release))}
        same = matcher.same_release(release["title"])
        rejected = item.setdefault("rejected", [])
        result = self.judge(item, release)
        logs.trace(f"{self.label(item)} <- {release['title']}:", f"ruled out, {result.reason}" if isinstance(
            result, matcher.Rejection) else f"score {result.get('score')}, {'; '.join(result.get('reasons') or [])}")
        if isinstance(result, matcher.Rejection):
            # Shown in the panel, so a wrong rejection can be seen and overruled. Not what is of
            # another game, and not what simply belongs under another item of this game.
            if result.known and not result.reason.startswith(ELSEWHERE) \
                    and not any(matcher.same_release(r["title"]) == same for r in rejected):
                rejected.append({**{k: release.get(k) for k in RELEASE_FIELDS}, "reason": result.reason})
                rejected.sort(key=published_ordinal, reverse=True)
                del rejected[MAX_REJECTED:]
            return False
        # The same release on several indexers: keep the one from the indexer that goes first.
        twin = next((c for c in item["candidates"] if matcher.same_release(c["title"]) == same), None)
        if twin and priority_of(twin) <= priority_of(result):
            return False
        if twin:
            item["candidates"].remove(twin)
        rejected[:] = [r for r in rejected if matcher.same_release(r["title"]) != same]
        item["candidates"].append(result)
        item["candidates"].sort(key=best_first)
        del item["candidates"][MAX_CANDIDATES:]
        return result in item["candidates"] and not twin

    def reevaluate(self):
        """The library changed (new local version, newer update out) or more became known about
        the versions: judge everything again, also what fell off before."""
        for item in self.state["items"].values():
            pool = item["candidates"] + item.get("rejected", [])
            item["candidates"], item["rejected"] = [], []
            for release in sorted(pool, key=priority_of):
                if release["guid"] in item["blocked"]:
                    continue
                try:
                    self.place(item, release)
                except Exception as e:  # noqa: BLE001
                    self.skip(f"a release of {item['name']}", e)

    def ladder_text(self, game_id):
        """For the panel: which display version is which update, from the library's own up."""
        game = self.games.get(game_id)
        seen = self.seen(game_id)
        if game is None or not seen:
            return []
        steps = matcher.ladder(game, seen, self.state["vermap"].get(game_id))
        rows = []
        for display in sorted(steps, key=matcher.version_tuple):
            step = steps[display]
            if step.version is not None and step.version < game.local_version:
                continue
            name = matcher.update_name(step.version) if step.version else (
                "base game" if step.version == 0 else "newer than " + matcher.update_name(game.latest_version))
            rows.append({"display": display, "update": name, "how": step.how, "solid": step.solid})
        return rows

    def process(self, releases, game_ids):
        """Hold releases against the items of these games. Returns how many new candidates."""
        by_game = {}
        for item in self.state["items"].values():
            if item["game_id"] in game_ids:
                by_game.setdefault(item["game_id"], []).append(item)
        names = {g: {t for t, _, _ in matcher.tokens(matcher.clean(self.games[g].name))} for g in by_game}
        relevant = []
        learned = False
        for release in releases:
            text = matcher.clean(release["title"])
            words = {t for t, _, _ in matcher.tokens(text)}
            has_id = matcher.TID_RE.search(text) is not None
            for game_id, items in by_game.items():
                # Not one word of the name and no title ID: it cannot be this game.
                if not has_id and not words & names[game_id]:
                    continue
                try:
                    learned = self.notice(game_id, release) or learned
                    relevant.append((release, items))
                except Exception as e:  # noqa: BLE001
                    self.skip(f"a release of {self.games[game_id].name or game_id}", e)
        # First every version is noticed, then the releases are judged: what one release is
        # can depend on the others (see matcher.ladder).
        found = 0
        for release, items in relevant:
            for item in items:
                try:
                    found += self.offer(item, release)
                except Exception as e:  # noqa: BLE001
                    self.skip(f"a release of {item['name']}", e)
        if learned:
            self.reevaluate()
        return found

    # ------------------------------------------------------------ searching

    async def feed(self):
        """The newest posts of every indexer, in one call, held against every missing item."""
        releases, errors = await indexers.search_all(self.session, "")
        self.heard(errors)
        logs.debug(f"New posts: {len(releases)} releases from {len(config.indexers()) - len(errors)} indexer(s)")
        found = self.process(releases, list(self.games))
        if found:
            self.event(f"New posts: found {found} candidate release(s)")

    def heard(self, errors):
        """After a search: which indexers did not answer, and which answer again."""
        for indexer in config.indexers():
            name = f"INDEXERS:{indexer['id']}"
            if indexer["id"] in errors:
                self.provider("INDEXERS", indexer, False, errors[indexer["id"]])
            elif not self.state["services"].get(name, {}).get("ok"):
                self.provider("INDEXERS", indexer, True, "answers")

    async def search_game(self, game_id, words=None):
        """Search the indexers for one game: by its name, or with words of the user's own (for
        releases that are not named after the game). Returns how many new candidates."""
        game = self.games.get(game_id)
        if game is None:
            return 0
        update_id = game_id[:13] + "800"
        queries = [words] if words else [matcher.search_term(game.name) or update_id]
        if not words and config.SEARCH_BY_TITLE_ID and update_id not in queries:
            queries.append(update_id)
        releases = []
        for query in queries:
            found, errors = await indexers.search_all(self.session, query)
            self.heard(errors)
            if errors and len(errors) == len(config.indexers()):
                raise clients.ServiceError(next(iter(errors.values())))  # nobody answered: no use going on
            releases += found
        found = self.process(releases, [game_id])
        logs.debug(f"Searched {queries}: {len(releases)} releases, {found} new candidate(s) for {game.name or game_id}")
        if words:
            return found  # the turn of this game in the searches by name stays what it was
        self.state["searched"][game_id] = int(time.time())
        for item in self.items_of(game_id):
            item["last_search"] = int(time.time())
            item["last_results"] = len(releases)
        return found

    async def backlog(self):
        """Search by name for every game whose last search is longer ago than the interval."""
        due = time.time() - config.SEARCH_INTERVAL_HOURS * 3600
        searched = self.state["searched"]
        queue = sorted(
            (g for g in self.games
             if searched.get(g, 0) < due
             and any(not i["ignored"] and not i["grab"] for i in self.items_of(g))),
            key=lambda g: searched.get(g, 0))
        if config.BACKLOG_PER_RUN > 0:
            queue = queue[:config.BACKLOG_PER_RUN]
        for n, game_id in enumerate(queue):
            if n:
                await asyncio.sleep(config.SEARCH_DELAY_SECONDS)
            if game_id not in self.games:
                continue
            self.status["phase"] = f"searching {n + 1}/{len(queue)}: {self.games[game_id].name or game_id}"
            try:
                await self.search_game(game_id)
            except clients.ServiceError:
                return n  # no indexer answers; heard() has said which
            except Exception as e:  # noqa: BLE001
                self.skip(self.games[game_id].name or game_id, e)
                self.state["searched"][game_id] = int(time.time())  # again after the interval, not every round
            self.save()  # a long first round: keep what was found so far
        if queue:
            self.event(f"Searched {len(queue)} game(s) by name")
        return len(queue)

    # ------------------------------------------------------------ sending

    def drop(self, item, text, why):
        """What was sent did not work out: skip that release from now on, and keep it with
        the failed downloads so the panel can show it and send it once more."""
        grab = item["grab"]
        listed = item["candidates"] + item.get("rejected", [])
        release = next((c for c in listed if c["guid"] == grab["guid"]), None)
        release = {k: release.get(k) for k in RELEASE_FIELDS} if release else {
            "guid": grab["guid"], "title": grab["title"]}
        failed = [f for f in item.get("failed", []) if f["guid"] != grab["guid"]]
        item["failed"] = [{**release, "failed_at": int(time.time()), "why": why}] + failed[:MAX_FAILED - 1]
        self.record("failed", item, grab["title"], note=why, client=grab.get("client_name", ""))
        item["blocked"].append(grab["guid"])
        item["candidates"] = [c for c in item["candidates"] if c["guid"] != grab["guid"]]
        # The same usenet release from another indexer is the same post: it leaves with it.
        item["candidates"] = [c for c in item["candidates"] if not self.failed_before(item, c)]
        item["grab"] = None
        self.event(text, "warn")
        return text

    async def rescan(self):
        """Ask the library to scan. Remembers when it last agreed to: what is put in a folder
        can only be called unseen after a scan that came later."""
        agreed = await clients.library_rescan(self.session)
        if agreed:
            self.state["rescan_at"] = int(time.time())
        return agreed

    def unseen(self, item, waited):
        """What was sent is in the folder of its game, and the library still misses what it was
        sent for: it leaves the queue. Its files stay where they are and the release is not
        rejected, but it counts as tried: it is not sent again by itself."""
        grab = item["grab"]
        folder = grab.get("imported_to") or "the folder of its game"
        self.record("unseen", item, grab["title"], client=grab.get("client_name", ""),
                    note=f"put in {folder}, and still missing in the library after {waited}")
        item["grab"] = None
        text = (f"Imported, but still missing in your library after {waited}: {grab['title']}. It left the queue; "
                f"its files stay in {folder}.")
        self.event(text, "warn")
        return text

    def failed_before(self, item, release):
        """Is this the usenet release of a download that failed, found once more: on another
        indexer, or posted again under the same name? Only if failed downloads are hidden."""
        if not config.HIDE_FAILED_DOWNLOADS or (release.get("protocol") or "usenet") != "usenet":
            return False
        same = matcher.same_release(release["title"])
        return any((f.get("protocol") or "usenet") == "usenet" and f["guid"] != release["guid"]
                   and matcher.same_release(f["title"]) == same for f in item.get("failed", []))

    async def follow_grabs(self):
        """Ask the download clients how the sent releases are doing.

        Failed: the next release gets its turn at once. Downloaded: the library is asked to
        scan and is read again; if the update is still not there after the waiting time, the
        download is left as it is and the user is told (no next release: something between the
        download client and the library is not connected). Unknown to the client: after the
        waiting time it counts as not arrived."""
        pending = [i for i in self.state["items"].values() if i.get("grab")]
        if not pending:
            return
        known, errors = await downloads.states(self.session)
        for client in config.providers("DOWNLOAD_CLIENTS"):
            if client["id"] in errors:
                self.provider("DOWNLOAD_CLIENTS", client, False, errors[client["id"]])
        states = (known, errors)
        now, wait = time.time(), config.GRAB_WAIT_MINUTES * 60
        waited = f"{config.GRAB_WAIT_MINUTES} minutes" if wait < 7200 else f"{config.GRAB_WAIT_MINUTES // 60} hours"
        self.tell_later, self.dropped, self.finished = [], False, False
        self.failed = []  # the sent releases the download client says failed (see follow)
        for item in pending:
            try:
                self.follow(item, states, now, wait, waited)
            except Exception as e:  # noqa: BLE001
                self.skip(f"the download of {item['name']}", e)
        if config.IMPORT_COMPLETED:
            # Downloaded and not in the library yet: put it there. One that could not be put
            # there is tried again every time, in case what was wrong has been put right.
            for item in pending:
                grab = item.get("grab") or {}
                if grab.get("state") in ("done", "stuck") and not grab.get("imported"):
                    try:
                        await self.bring_in(item)
                    except Exception as e:  # noqa: BLE001
                        self.skip(f"the import of {item['name']}", e)
        for grab in self.failed:
            client = next((c for c in config.providers("DOWNLOAD_CLIENTS") if c["id"] == grab.get("client")), None)
            # Remove Failed, as in Radarr: the broken download goes, with its files. Usenet only.
            if client and client.get("remove_failed") and config.protocol_of(client) == "usenet":
                try:
                    await downloads.remove(self.session, client, grab.get("client_id"))
                except clients.ServiceError as e:
                    self.event(f"Download failed, but not removed from {client['name']}: {grab['title']}: {e}", "warn")
        tell, dropped, finished = self.tell_later, self.dropped, self.finished
        placed = [i["grab"]["imported"] for i in pending if (i.get("grab") or {}).get("imported")]
        if placed and (self.state.get("rescan_at") or 0) < max(placed) and now - (self.state.get("rescan_tried") or 0) > wait:
            self.state["rescan_tried"] = int(now)
            finished = True
        if finished and not await self.rescan() and not self.state.get("rescan_hint"):
            self.state["rescan_hint"] = True
            self.event("Switch-library-manager-web refuses to scan on request. Give the API key the Editor "
                       "role, and a download shows up in your library sooner.", "warn")
        waiting = any((i.get("grab") or {}).get("state") == "done" or (i.get("grab") or {}).get("imported")
                      for i in self.state["items"].values())
        if waiting and now - (self.state["library"].get("fetched") or 0) > config.WATCH_SECONDS:
            if await self.sync_library() and self.newly_owned:
                await self.search_games(self.newly_owned)  # between rounds: the backlog would wait for the next one
        for text in tell:
            await self.tell(text, "fail")
        if dropped:
            await self.auto_grab()

    def follow(self, item, states, now, wait, waited):
        """One sent release: what the download client says about it, and what follows."""
        grab = item["grab"]
        answers, errors = states
        if grab.get("client"):
            if grab["client"] in errors:
                return  # its client did not answer: nothing is concluded from that
            known = answers.get(grab["client"], {}).get(grab.get("client_id"))
        else:
            # Sent by a version that had one download client: whichever client knows the id.
            known = next((a[grab.get("client_id")] for a in answers.values() if grab.get("client_id") in a), None)
            if known is None and errors:
                return
        state = (known or {}).get("state")
        grab["percent"] = (known or {}).get("percent")
        grab["left"] = (known or {}).get("left")  # seconds still to go, if the client says
        if (known or {}).get("size"):
            grab["size"] = known["size"]  # kept: a client may forget a download, not its size
        if (known or {}).get("path"):
            grab["path"] = known["path"]  # where the download client says the download is
            # And where this client keeps its finished downloads: for one it no longer lists.
            if grab.get("client"):
                self.state.setdefault("download_folders", {})[grab["client"]] = os.path.dirname(str(known["path"]).rstrip("/"))
        if grab.get("imported"):
            # Its files are in the folder of the game. If the library scanned on request after
            # that, was read a while later and still misses it once the waiting time is over,
            # this release does not bring it. A library that scans only when it wants to may
            # not have seen the files yet: then the download stays in the queue.
            read, asked = self.state["library"].get("fetched") or 0, self.state.get("rescan_at") or 0
            if now - grab["imported"] > wait and asked >= grab["imported"] and read - asked >= config.WATCH_SECONDS:
                self.tell_later.append(self.unseen(item, waited))
                self.dropped = True
                return
        if state == "failed":
            self.failed.append(grab)
            self.tell_later.append(self.drop(
                item, f"Download failed: {grab['title']}. The next release gets its turn.",
                "the download client reports that the download failed"))
            self.dropped = True
        elif state == "downloading":
            grab["state"] = "downloading"
        elif state == "done":
            if grab.get("state") not in ("done", "stuck"):
                grab.update(state="done", done_at=int(now))
                self.finished = True
                self.event(f"Downloaded: {grab['title']}. Waiting for the library.")
            elif grab["state"] == "done" and now - grab["done_at"] > wait:
                grab["state"] = "stuck"
                hint = ("Does Switch-library-manager-web scan the folder of your download client?" if not config.IMPORT_COMPLETED
                        else "It could not be put there: " + grab["import_error"] if grab.get("import_error")
                        else "It was put in its folder; has Switch-library-manager-web scanned since?")
                text = f"Downloaded, but not in your library after {waited}: {grab['title']}. {hint}"
                self.event(text, "warn")
                self.tell_later.append(text)
        elif grab.get("state") not in ("done", "stuck") and now - grab["at"] > wait:
            self.tell_later.append(self.drop(
                item, f"Not arrived after {waited}: {grab['title']}. The next release gets its turn.",
                f"unknown to the download client and not in the library after {waited}"))
            self.dropped = True

    async def bring_in(self, item):
        """Put a finished download in the library (see importer.py). True if it is there now.
        What went wrong is kept with the download and said once, not at every try."""
        grab = item["grab"]
        client = next((c for c in config.providers("DOWNLOAD_CLIENTS") if c["id"] == grab.get("client")), None)
        wanted = {"update": "UPD", "game": "BASE"}.get(item["type"], "DLC")
        try:
            if client is None:
                raise importer.ImportProblem("the download client this was sent to is no longer in the settings")
            if client["type"] == "prowlarr":
                raise importer.ImportProblem("it went through the download client of Prowlarr, which does not say where its downloads are")
            # Moving a file to another disk takes a while: not in the way of everything else.
            done, left = await asyncio.to_thread(importer.bring, client, grab.get("path") or self.guessed_path(client, grab),
                                                 self.files.get(item["game_id"]) or [],
                                                 wanted, grab.get("protocol") or "usenet", (item["game_id"], item["name"]))
        except importer.ImportProblem as e:
            text = str(e)
            if grab.get("import_error") != text:
                grab["import_error"] = text
                self.event(f"Import failed: {grab['title']}: {text}", "warn")
                if hasattr(self, "tell_later"):
                    self.tell_later.append(f"Downloaded, but it could not be put in your library: {grab['title']}. {text}")
            return False
        folder = done[0]["folder"]
        grab.update(imported=int(time.time()), imported_to=folder)
        grab.pop("import_error", None)
        more = f" ({len(left)} file(s) of the game itself left in the download)" if left else ""
        clutter = importer.patterns(config.CLEANUP_EXTENSIONS)
        if (config.DELETE_EMPTY_FOLDERS or clutter) and any(d["how"] == "moved" for d in done):
            # The files went to the library: clutter and empty folders are all that is left of the download.
            where = grab.get("path") or self.guessed_path(client, grab)
            gone = await asyncio.to_thread(importer.tidy, client, where,
                                           (self.state.get("download_folders", {}).get(client["id"]),),
                                           clutter, config.DELETE_EMPTY_FOLDERS)
            if gone:
                more += "; the empty folder of the download was removed"
        self.event(f"Imported: {grab['title']}: {len(done)} file(s) to {folder}{more}", "grab")
        self.record("imported", item, grab["title"], client=grab.get("client_name", ""),
                    note=f"{len(done)} file(s) {done[0]['how']} to {folder}{more}")
        self.finished = True  # the library is asked to scan
        if client.get("remove_completed") and (grab.get("protocol") or "usenet") == "usenet":
            # The files are in the library: what is left of the download can go. Never a torrent, which seeds on.
            try:
                await downloads.remove(self.session, client, grab.get("client_id"))
            except clients.ServiceError as e:
                self.event(f"Imported, but not removed from {client['name']}: {e}", "warn")
        return True

    def unplaced(self):
        """The finished downloads that are not in the folder of their game yet."""
        return [i for i in self.state["items"].values()
                if (i.get("grab") or {}).get("state") in ("done", "stuck") and not i["grab"].get("imported")]

    async def rescan_downloads(self):
        """The task "Rescan Download Folder": ask the download clients once more, and look again
        in the folder of every finished download that is not in the folder of its game yet. For
        after something was put right by hand: a download unpacked, a folder made a volume.
        What still goes wrong is said again, also if it is the same as before. Returns (how
        many were put in the library, how many there were)."""
        if not config.IMPORT_COMPLETED:
            raise clients.ServiceError("Import Completed Downloads is off (Settings > Media Management)")
        # Every download that is not in its place yet, before the clients are asked: asking them
        # puts in place what can be, and those count as done by this task too.
        open_ = [i for i in self.state["items"].values() if i.get("grab") and not i["grab"].get("imported")]
        if open_:
            await self.follow_grabs()  # what finished a moment ago counts too
        waiting = [i for i in open_ if (i.get("grab") or {}).get("state") in ("done", "stuck")]
        self.tell_later = []  # said in the Events, not once more as a notification
        placed = 0
        for item in waiting:
            if not item["grab"].get("imported"):
                item["grab"].pop("import_error", None)  # so it is said again, also if it is the same
                try:
                    await self.bring_in(item)
                except Exception as e:  # noqa: BLE001
                    self.skip(f"the import of {item['name']}", e)
            placed += bool(item["grab"].get("imported"))
        self.tell_later = []
        if placed:
            await self.rescan()
        swept = await asyncio.to_thread(self.sweep) if config.DELETE_EMPTY_FOLDERS else []
        self.event((f"Rescanned the download folder: {placed} of {len(waiting)} finished download(s) put in the library"
                    if waiting else "Rescanned the download folder: no finished download waits to be put in the library")
                   + (f"; {len(swept)} empty folder(s) removed" if swept else ""))
        return placed, len(waiting)

    def sweep(self):
        """Remove the empty folders that earlier downloads left where each download client
        keeps its finished downloads. Returns the folders that are gone."""
        gone = []
        for client in config.providers("DOWNLOAD_CLIENTS"):
            folder = self.state.get("download_folders", {}).get(client["id"])
            if folder:
                gone += importer.sweep(client, folder)
        for folder in gone:
            logs.debug(f"Removed the empty folder {folder}")
        return gone

    def guessed_path(self, client, grab):
        """Where a finished download probably is when its client no longer lists it (taken out
        of its history, by the client itself or by hand): a folder named after the release,
        next to the other finished downloads of that client. None if there is no such folder."""
        folder = self.state.get("download_folders", {}).get(client["id"])
        if not folder:
            return None
        for name in dict.fromkeys((clients.nzb_filename(grab["title"])[:-4], grab["title"])):
            guess = os.path.join(folder, name)
            if os.path.isdir(importer.local_download(client, guess)):
                return guess
        return None

    async def import_now(self, key):
        """The button "Try the import again" of the Queue."""
        item = self.state["items"].get(key)
        grab = (item or {}).get("grab")
        if not grab or grab.get("state") not in ("done", "stuck"):
            raise clients.ServiceError("This download is not finished")
        if grab.get("imported"):
            return True
        self.tell_later = []
        grab.pop("import_error", None)  # so the outcome of this try is said, also if it is the same
        done = await self.bring_in(item)
        self.save()
        if not done:
            raise clients.ServiceError(grab.get("import_error") or "The import failed")
        await self.rescan()
        return True

    def game_name(self, game_id):
        name = next((g.get("name") for g in self.state.get("games", []) if g.get("id") == game_id), None)
        if name is None and game_id in self.games:
            name = self.games[game_id].name or game_id
        if name is None:
            raise clients.ServiceError("This game is not in your library")
        return name

    def find_titles(self, name):
        """The games of the list of all games whose name holds every word of `name` (as the
        start of one of its words): the same name first, then the ones that start with it,
        then the shortest names, then the newest."""
        wanted = words_of(name)
        if not wanted:
            return []
        if getattr(self, "title_words", None) is None or len(self.title_words) != len(self.titles):
            self.title_words = {tid: words_of(t[0]) for tid, t in self.titles.items()}
        hits = []
        for title_id, have in self.title_words.items():
            if all(any(w.startswith(q) for w in have) for q in wanted):
                rank = 0 if have == wanted else 1 if have[:len(wanted)] == wanted else 2
                hits.append((rank, len(have), -(self.titles[title_id][2] or 0), title_id))
        return [t[3] for t in sorted(hits)]

    async def lookup_game(self, name):
        """Add Game: the games of that name, from the list of all games. Without that list, or
        when it has no game of that name, the indexers are searched by name and the games of
        the releases are offered by the title IDs in their names. A Switch 2 title ID is never offered."""
        term = matcher.search_term(name)
        if not term and not words_of(name):
            raise clients.ServiceError("Fill in the name of a game")
        if not self.titles:
            await self.refresh_titles()
        owned = {g["id"] for g in self.state.get("games", [])}
        wanted = {g["id"] for g in self.state["new_games"]}
        hits = self.find_titles(name)[:MAX_LOOKUP] if self.titles else []
        if hits:
            return {"from": "titles", "games": [
                {"id": tid, "name": self.titles[tid][0], "released": self.titles[tid][2] or 0,
                 "cover": bool(self.cover_address(tid)), "owned": tid in owned, "wanted": tid in wanted} for tid in hits]}
        if not term:
            return {"from": "titles", "games": []}
        releases, errors = await indexers.search_all(self.session, term)
        self.heard(errors)
        if errors and len(errors) == len(config.indexers()):
            raise clients.ServiceError(next(iter(errors.values())))
        found = {}
        for release in releases:
            for tid in {m.group(1).upper() for m in matcher.TID_RE.finditer(matcher.clean(release["title"]))}:
                if not tid.startswith("01"):
                    continue  # Switch 2: only the first Switch
                base = f"{matcher.family(tid):016X}"
                entry = found.setdefault(base, {"id": base, "names": {}, "releases": 0})
                entry["releases"] += 1
                guessed = matcher.guessed_name(release["title"])
                if guessed:
                    entry["names"][guessed] = entry["names"].get(guessed, 0) + 1
        offered = sorted(found.values(), key=lambda e: -e["releases"])[:MAX_LOOKUP]
        return {"from": "indexers", "games": [
            {"id": e["id"], "name": max(e["names"], key=e["names"].get) if e["names"] else name.strip(),
             "releases": e["releases"], "cover": bool(self.cover_address(e["id"])),
             "owned": e["id"] in owned, "wanted": e["id"] in wanted} for e in offered]}

    async def add_game(self, game_id, name, search=True):
        """Add Game: look for a game that is not in the library yet. Returns how many releases
        the first search found for it; `search` False: it is searched later (see add_games)."""
        game_id, name = game_id.strip().upper(), " ".join(str(name).split())[:200]
        known = self.titles.get(game_id) or ["", "", 0]
        name = name or known[0]
        if game_id.startswith("04"):
            raise clients.ServiceError("That is a game for the Switch 2: NSWHunter is for the first Switch only")
        if not re.fullmatch(r"01[0-9A-F]{14}", game_id) or int(game_id, 16) & 0x1FFF:
            raise clients.ServiceError("A title ID of a game has 16 characters, starts with 01 and ends with 000")
        if not name:
            raise clients.ServiceError("This title ID is not in the list of all games: fill in the name of the game too")
        if any(g["id"] == game_id for g in self.state.get("games", [])):
            raise clients.ServiceError(f"{name} is in your library already")
        if any(g["id"] == game_id for g in self.state["new_games"]):
            raise clients.ServiceError(f"{name} is on the wishlist already")
        self.state["new_games"].append({"id": game_id, "name": name, "added": int(time.time()), "released": known[2] or 0})
        wanted = {}
        self.want_new_games(self.games, wanted, set())
        key = game_id + ":game"
        self.state["items"][key] = {"key": key, "candidates": [], "blocked": [], "ignored": False, "grab": None,
                                    "first_seen": int(time.time()), **wanted[key]}
        self.event(f"Added to the wishlist: {name}")
        found = await self.search_game(game_id) if search else None
        self.save()
        if search:
            await self.send_now()
        return found

    def pick_title(self, line):
        """One line of a pasted list: (title ID, name). A title ID, a title ID with a name, or
        a name that only one game of the list of all games has."""
        whole = re.fullmatch(r"([0-9A-Fa-f]{16})(?:\s+(.+))?", line)
        if whole:
            return whole.group(1).upper(), whole.group(2) or ""
        hits = self.find_titles(line)
        if not hits:
            raise clients.ServiceError("No game of this name in the list of all games: add it with Search or by title ID")
        same = [tid for tid in hits if words_of(self.titles[tid][0]) == words_of(line)]
        if len(same) == 1 or (not same and len(hits) == 1):
            tid = (same or hits)[0]
            return tid, self.titles[tid][0]
        raise clients.ServiceError(f"{len(same) or len(hits)} games match this name: choose one with Search")

    async def add_games(self, text):
        """Add Game with a list: one name or title ID per line. Returns what became of every
        line. The games that were added are searched one after the other, after this answer."""
        lines = [" ".join(line.split()) for line in str(text).splitlines()]
        lines = [line for line in lines if line]
        if not lines:
            raise clients.ServiceError("Fill in one name or title ID per line")
        if len(lines) > MAX_LIST:
            raise clients.ServiceError(f"At most {MAX_LIST} lines at a time")
        if not self.titles:
            await self.refresh_titles()
        done, added = [], []
        for line in lines:
            try:
                game_id, name = self.pick_title(line)
                await self.add_game(game_id, name, search=False)
                added.append(game_id)
                done.append({"line": line, "ok": True, "text": "Added: " + self.games[game_id].name})
            except clients.ServiceError as e:
                done.append({"line": line, "ok": False, "text": str(e)})
        if added:
            self.later(self.search_games(added))
        return done

    async def search_games(self, game_ids):
        """Search some games by name, one after the other, as the backlog does."""
        for n, game_id in enumerate(game_ids):
            if n:
                await asyncio.sleep(config.SEARCH_DELAY_SECONDS)
            try:
                await self.search_game(game_id)
            except clients.ServiceError:
                break  # no indexer answers; heard() has said which
            except Exception as e:  # noqa: BLE001
                self.skip(game_id, e)
        self.save()
        await self.send_now()

    async def send_now(self):
        """Automatic Download right after a search between rounds, not an hour later in the
        next round. Inside a round nothing is done here: the round sends after its searches."""
        if self.lock.locked() or not self.working("DOWNLOAD_CLIENTS"):
            return
        async with self.lock:
            await self.auto_grab()
            self.save()

    def later(self, work):
        """Run something on its own, after the answer to the panel."""
        task = asyncio.create_task(work)
        self.background.add(task)
        task.add_done_callback(self.background.discard)

    def remove_game(self, game_id):
        """Stop looking for a game of Add Game. What was found for it goes too."""
        key = game_id + ":game"
        item = self.state["items"].get(key)
        if item and item.get("grab"):
            raise clients.ServiceError("This game is in the queue: take it out of the queue first")
        gone = [g for g in self.state["new_games"] if g["id"] == game_id]
        if not gone:
            raise clients.ServiceError("This game is not on the wishlist")
        self.state["new_games"] = [g for g in self.state["new_games"] if g["id"] != game_id]
        self.state["items"].pop(key, None)
        if not self.items_of(game_id):
            self.games.pop(game_id, None)
        self.event(f"Removed from the wishlist: {gone[0]['name']}")
        self.save()

    async def rescan_game(self, game_id):
        """Rescan Folder of a game page: let the library scan its folders, wait until it is
        done, and read it anew. Returns how many updates and DLC the game still misses."""
        name = self.game_name(game_id)
        if not await self.rescan():
            raise clients.ServiceError("Switch-library-manager-web refuses to scan on request: give its API key the Editor role")
        end = time.time() + SCAN_WAIT
        while time.time() < end and await clients.library_scanning(self.session):
            await asyncio.sleep(SCAN_LOOK)
        async with self.lock:
            if not await self.sync_library():
                raise clients.ServiceError(self.state["services"]["slm"]["text"])
            self.save()
        missing = sum(1 for i in self.state["items"].values() if i["game_id"] == game_id and not i.get("ignored"))
        self.event(f"Rescan Folder: {name}: " + (f"{missing} update(s) or DLC still missing" if missing else "nothing missing"))
        return {"missing": missing}

    async def manual_import(self, game_id, path, key=None, dry=False):
        """Manual Import: move the Switch files of a folder or file the user chose to the folder
        of a game. key: the item of the Queue it is done for; its download then counts as put
        in the library. dry: only say what would be moved. Returns {"files": [{"file",
        "folder", "how"}], "left": [names of files that stay where they are]}."""
        name = self.game_name(game_id)
        item = self.state["items"].get(key) if key else None
        if item is not None and item["game_id"] != game_id:
            raise ValueError
        item_type = (item or self.state["items"].get(game_id + ":game") or {}).get("type")
        wanted = {"game": "BASE", None: "UPD", "update": "UPD"}.get(item_type, "DLC")
        try:
            done, left = await asyncio.to_thread(importer.manual, path, self.files.get(game_id) or [], wanted,
                                                 (game_id, name), dry)
        except importer.ImportProblem as e:
            raise clients.ServiceError(str(e)[:1].upper() + str(e)[1:]) from e
        result = {"files": done, "left": [os.path.basename(f) for f in left]}
        if dry:
            return result
        folder, chosen = done[0]["folder"], os.path.basename(str(path).rstrip("/")) or str(path)
        moved = sum(d["how"] == "moved" for d in done)
        more = f" ({len(left)} file(s) left where they are)" if left else ""
        if config.DELETE_EMPTY_FOLDERS and moved:
            spare = [importer.local_download(c, f) for c in config.providers("DOWNLOAD_CLIENTS")
                     for f in [self.state.get("download_folders", {}).get(c["id"])] if f]
            if await asyncio.to_thread(importer.tidy, {}, path, spare):
                more += "; the empty folder was removed"
        self.event(f"Manual import: {chosen}: {len(done)} file(s) of {name} to {folder}{more}", "grab")
        shown = item or {"game_id": game_id, "name": name, "type": "update"}
        self.record("imported", shown, chosen, client="Manual Import", note=f"{len(done)} file(s) {done[0]['how']} to {folder}{more}",
                    **({} if item else {"what": "manual import"}))
        grab = (item or {}).get("grab")
        if grab and not grab.get("imported"):
            # The download this was done for is in the library now: the queue waits for the library.
            grab.update(imported=int(time.time()), imported_to=folder)
            grab.pop("import_error", None)
            if grab.get("state") not in ("done", "stuck"):
                grab.update(state="done", done_at=int(time.time()))
        self.save()
        await self.rescan()
        return result

    async def watch(self):
        """Between rounds: follow the downloads. Skipped while a round runs; that does it too."""
        if self.lock.locked() or config.problems():
            return
        if not any(i.get("grab") for i in self.state["items"].values()):
            return
        async with self.lock:
            await self.followed()
            self.save()

    async def followed(self):
        """follow_grabs, as a task when there is something to follow."""
        if any(i.get("grab") for i in self.state["items"].values()):
            await self.task("downloads", self.follow_grabs())

    async def tell(self, text, about):
        """A notification through every connection that is switched on and wants to hear of
        this. about: "grab", "arrive", "fail", "choice" or "health" (see config.TRIGGERS)."""
        for connection in config.connections():
            if not connection.get("on_" + about, True):
                continue
            try:
                await notify.send(self.session, connection, text)
                self.provider("CONNECTIONS", connection, True, "last message sent")
            except clients.ServiceError as e:
                self.provider("CONNECTIONS", connection, False, str(e))

    def automatic(self, item):
        """The candidate that may go out without a click, or None."""
        threshold = config.auto_min_score()
        if not threshold or not self.awaits(item):
            return None
        best = self.untried(item)[0]  # what was sent before is not sent again without a click
        if best.get("score", 0) < threshold:
            return None
        if best["kind"] == "bundle" and not config.AUTO_BUNDLES:
            return None
        if best["kind"] == "unlocker":
            return None  # a DLC unlocker only goes out with a click of its own
        if item["type"] == "game" and not config.AUTO_WISHLIST:
            return None  # a whole game of the wishlist waits for a click, unless asked otherwise
        return best

    async def grab(self, key, guid, auto=False):
        item = self.state["items"].get(key)
        # Also what fell off or failed before can be sent: the user may know better.
        listed = [r for part in ("candidates", "rejected", "failed") for r in (item or {}).get(part, [])]
        candidate = next((c for c in listed if c["guid"] == guid), None)
        if candidate is None:
            raise clients.ServiceError("This release is no longer in the list")
        candidate = {**candidate, "source": candidate.get("source") or self.legacy_source()}
        try:
            client, client_id = await downloads.send(self.session, candidate)
        except clients.ServiceError:
            source = indexers.by_id(candidate["source"])
            chosen = config.client_for(candidate.get("protocol") or "usenet", source["type"] if source else "")
            if not chosen or chosen["type"] != "prowlarr":
                raise
            # Prowlarr only grabs what it found in the last half hour: search again, try once more.
            await self.search_game(item["game_id"])
            client, client_id = await downloads.send(self.session, candidate)
        logs.debug(f"Handed to {client['name']}: {candidate['title']} (id {client_id})")
        item["grab"] = {"guid": guid, "title": candidate["title"], "at": int(time.time()), "auto": auto,
                        "local_version": item.get("local_version", 0),
                        "dlc_missing": item.get("dlc_missing", 0), "state": "sent",
                        "client": client["id"], "client_name": client["name"], "client_id": client_id,
                        "protocol": candidate.get("protocol") or "usenet", "indexer": candidate.get("indexer") or ""}
        self.record("grabbed", item, candidate["title"], client=client["name"], indexer=candidate.get("indexer") or "",
                    protocol=candidate.get("protocol") or "usenet", auto=auto, score=candidate.get("score"))
        item["ask"] = None  # a question about it in Telegram is answered by this
        item.setdefault("sent", [])
        if guid not in item["sent"]:
            item["sent"].append(guid)
        if any(f["guid"] == guid for f in item.get("failed", [])):
            # Sent once more after it failed: it is no longer a failed download, nor skipped.
            item["failed"] = [f for f in item["failed"] if f["guid"] != guid]
            item["blocked"] = [g for g in item["blocked"] if g != guid]
        how = "Sent automatically" if auto else "Sent"
        self.event(f"{how}: {candidate['title']}", "grab")
        self.save()
        if auto:
            await self.tell(f"Sent automatically: {candidate['title']}", "grab")

    async def auto_grab(self):
        sent = 0
        for item in list(self.state["items"].values()):
            candidate = self.automatic(item)
            if candidate is None:
                continue
            if sent >= config.MAX_GRABS_PER_RUN:
                break
            try:
                await self.grab(item["key"], candidate["guid"], auto=True)
                sent += 1
            except clients.ServiceError as e:
                self.event(f"Sending failed: {candidate['title']}: {e}", "error")
                break
            except Exception as e:  # noqa: BLE001
                self.skip(item["name"], e)

    async def grab_best(self, min_score):
        """The button "Download all": of every item that awaits a choice, send the best
        release if its score is at least `min_score`. Bundles and DLC unlockers are left for
        a click of their own. Returns how many were sent; stops at the first one the download client refuses."""
        sent = 0
        for item in list(self.state["items"].values()):
            if not self.awaits(item):
                continue
            best = self.untried(item)[0]
            if best.get("score", 0) < min_score or best["kind"] in ("bundle", "unlocker"):
                continue
            try:
                await self.grab(item["key"], best["guid"])
            except clients.ServiceError as e:
                raise clients.ServiceError(f"{sent} sent, then: {e}") from e
            sent += 1
        return sent

    async def unsend(self, key, remove=False, block=False):
        """Take a release out of the queue: its item awaits a choice again if it has a release
        that was never sent. `remove`: also take the download, with its files, out of the download client.
        `block`: also reject the release, so it is not offered or sent again."""
        item = self.state["items"][key]
        grab = item.get("grab")
        if not grab:
            return
        if remove:
            client = next((c for c in config.providers("DOWNLOAD_CLIENTS") if c["id"] == grab.get("client")), None)
            if client is None:
                raise clients.ServiceError("The download client this was sent to is no longer in the settings")
            await downloads.remove(self.session, client, grab.get("client_id"))
        item["grab"] = None
        self.event(f"Removed from the queue{' and from ' + grab.get('client_name', 'the download client') if remove else ''}: {grab['title']}")
        if block and grab.get("guid"):
            self.reject(key, grab["guid"])
        self.save()

    # ------------------------------------------------------------ rejecting and restoring

    def turn_down(self, item, release):
        kept = [r for r in item.get("turned_down", []) if r["guid"] != release["guid"]]
        entry = {k: release.get(k) for k in RELEASE_FIELDS}
        item["turned_down"] = ([{**entry, "at": int(time.time())}] + kept)[:MAX_TURNED_DOWN]

    def reject(self, key, guid):
        """Reject one release: it is never offered or sent again, until it is restored."""
        item = self.state["items"][key]
        release = next((c for c in item["candidates"] + item.get("rejected", []) if c["guid"] == guid), None)
        if guid not in item["blocked"]:
            item["blocked"].append(guid)
        item["candidates"] = [c for c in item["candidates"] if c["guid"] != guid]
        if (item.get("ask") or {}).get("guid") == guid:
            item["ask"] = None
        if release:
            self.turn_down(item, release)
        self.save()

    def forget(self, key, guid):
        """Forget that a release was sent before: it is a choice to make again, and may go out
        by itself again. Not the release that is in the queue now."""
        item = self.state["items"][key]
        if (item.get("grab") or {}).get("guid") == guid:
            raise clients.ServiceError("This release is in the queue: take it out of the queue first")
        item["sent"] = [g for g in item.get("sent") or [] if g != guid]
        self.save()

    def dismiss(self, key, guid):
        """Take a failed download off the list. The release stays rejected."""
        item = self.state["items"][key]
        for release in [f for f in item.get("failed", []) if f["guid"] == guid]:
            self.turn_down(item, release)
        item["failed"] = [f for f in item.get("failed", []) if f["guid"] != guid]
        self.save()

    def restore(self, key, guid=None):
        """Take back a rejection. Without a guid: every rejection of this item of which only
        the id was kept (made by an older version); those releases return at the next search."""
        item = self.state["items"][key]
        if guid is None:
            named = {r["guid"] for r in item.get("turned_down", []) + item.get("failed", [])}
            item["blocked"] = [g for g in item["blocked"] if g in named]
        else:
            release = next((r for r in item.get("turned_down", []) if r["guid"] == guid), None)
            item["turned_down"] = [r for r in item.get("turned_down", []) if r["guid"] != guid]
            item["blocked"] = [g for g in item["blocked"] if g != guid]
            # Taken off the blocklist to be offered again: also if it was sent before.
            item["sent"] = [g for g in item.get("sent") or [] if g != guid]
            if release:
                self.place(item, {k: release.get(k) for k in RELEASE_FIELDS})
        self.save()

    async def tell_found(self):
        """A notification when releases are found for a game of the wishlist for the first time.
        With questions in Telegram the question says so itself (see ask)."""
        for item in self.state["items"].values():
            if item["type"] != "game" or item.get("found_told") or not item["candidates"]:
                continue
            if item["grab"] or not self.awaits(item):
                item["found_told"] = True  # sent automatically, or nothing left to choose: said otherwise
                continue
            if self.asking():
                continue  # the question in Telegram tells it
            item["found_told"] = True
            best = self.untried(item)[0]
            await self.tell(f"Found for your wishlist: {item['name']}: {len(self.untried(item))} release(s), "
                            f"the best scores {best.get('score', 0)}/10: {best['title']}", "choice")

    # ------------------------------------------------------------ choosing in Telegram

    def asker(self):
        """The Telegram connection that puts the choices to the user, or None."""
        return next((c for c in config.connections() if c["type"] == "telegram" and c.get("ask")
                     and c.get("on_choice", True) and c.get("bot_token") and c.get("chat_id")), None)

    def asking(self):
        return self.asker() is not None

    async def ask(self):
        """One message per item that awaits a choice, with buttons to download or reject its
        best release from Telegram. Every release is asked about once; at most MAX_ASKS
        messages per round, the highest scores first, the rest in the next rounds."""
        connection = self.asker()
        waiting = [i for i in self.state["items"].values()
                   if self.awaits(i) and i.get("asked") != self.untried(i)[0]["guid"]]
        waiting.sort(key=lambda i: -self.untried(i)[0].get("score", 0))
        for n, item in enumerate(waiting[:MAX_ASKS]):
            if n:
                await asyncio.sleep(ASK_DELAY)
            best = self.untried(item)[0]
            facts = [f"{best['size'] / 2**20:.0f} MB" if best.get("size") else "", best.get("indexer") or "",
                     (best.get("published") or "")[:10]]
            head = f"Found for your wishlist: {item['name']}" if item["type"] == "game" else self.label(item)
            text = "\n".join([head, f"{best.get('score', 0)}/10 · {best['title']}",
                              " · ".join(f for f in facts if f), "; ".join(best.get("reasons") or [])])
            token = secrets.token_hex(6)
            try:
                message_id = await notify.send(self.session, connection, text, buttons=[
                    ("Download", "d:" + token), ("Reject", "r:" + token)])
                self.provider("CONNECTIONS", connection, True, "last message sent")
            except clients.ServiceError as e:
                self.provider("CONNECTIONS", connection, False, str(e))
                return
            item["asked"] = best["guid"]
            item["found_told"] = True
            item["ask"] = {"token": token, "guid": best["guid"], "message_id": message_id,
                           "text": "NSWHunter\n" + text}

    async def telegram_answers(self, wait=50):
        """Wait for a press on a button under one of the questions in Telegram and act on it.
        False if no question is open: then Telegram is not asked anything."""
        if not self.asking() or not any(i.get("ask") for i in self.state["items"].values()):
            return False
        updates = await notify.telegram_call(self.session, self.asker(), "getUpdates", {
            "offset": self.state.get("telegram_offset", 0), "timeout": wait,
            "allowed_updates": ["callback_query"]}, wait=wait)
        for update in updates if isinstance(updates, list) else []:
            self.state["telegram_offset"] = int(update.get("update_id", 0)) + 1
            try:
                await self.pressed(update.get("callback_query") or {})
            except Exception as e:  # noqa: BLE001
                self.skip("a press on a button in Telegram", e)
        if updates:
            self.save()
        return True

    async def pressed(self, query):
        """A press on Download or Reject under a question. Only the chat that is set up may
        decide: a press from anywhere else is not even answered."""
        connection = self.asker()
        chat = (query.get("message") or {}).get("chat") or {}
        mine = str(connection["chat_id"]) if connection else ""
        if not connection or (str(chat.get("id")) != mine
                              and "@" + str(chat.get("username") or "").lower() != mine.lower()):
            return
        action, _, token = str(query.get("data") or "").partition(":")
        item = next((i for i in self.state["items"].values()
                     if token and (i.get("ask") or {}).get("token") == token), None)

        async def answer(text):
            try:
                await notify.telegram_call(self.session, connection, "answerCallbackQuery", {
                    "callback_query_id": query.get("id"), "text": text[:190]})
            except clients.ServiceError:
                pass  # the choice was made; only the small confirmation is lost

        if item is None or action not in ("d", "r"):
            await answer("This release no longer awaits a choice.")
            return
        ask = item["ask"]
        release = next((c for c in item["candidates"] if c["guid"] == ask["guid"]), None)
        if release is None or item["grab"] or item["ignored"]:
            outcome = "This release no longer awaits a choice."
        elif action == "d":
            try:
                await self.grab(item["key"], ask["guid"])
            except clients.ServiceError as e:
                await answer(str(e))  # the question stays open: the press can be tried again
                return
            outcome = "✓ Sent to the download client."
        else:
            self.reject(item["key"], ask["guid"])
            self.event(f"Rejected in Telegram: {release['title']}")
            outcome = "✕ Rejected."
        item["ask"] = None
        await answer(outcome)
        try:
            # Without buttons in the call the buttons disappear: the question is settled.
            await notify.telegram_call(self.session, connection, "editMessageText", {
                "chat_id": chat.get("id"), "message_id": ask["message_id"], "text": ask["text"] + "\n\n" + outcome})
        except clients.ServiceError:
            pass

    # ------------------------------------------------------------ one round

    async def check_services(self):
        """Ask every indexer and download client whether it answers."""
        self.forget_services()
        for indexer in config.indexers():
            try:
                self.provider("INDEXERS", indexer, True, str(await indexers.status(self.session, indexer)))
                if indexer["type"] == "prowlarr":
                    for prowlarr_id, priority in (await indexers.priorities(self.session, indexer)).items():
                        self.priorities[(indexer["id"], prowlarr_id)] = priority
            except clients.ServiceError as e:
                self.provider("INDEXERS", indexer, False, str(e))  # sorting keeps the priorities it had
        for client in config.download_clients():
            try:
                self.provider("DOWNLOAD_CLIENTS", client, True, str(await downloads.status(self.session, client)))
            except clients.ServiceError as e:
                self.provider("DOWNLOAD_CLIENTS", client, False, str(e))

    async def test_connections(self):
        """Try every service with the current settings, right after they were saved."""
        problems = config.problems()
        if problems:
            self.service("config", False, "; ".join(problems))
        else:
            self.state["services"].pop("config", None)
        if config.SLM_URL:
            try:
                self.service("slm", True, f"{len(await clients.library(self.session))} games")
            except clients.ServiceError as e:
                self.service("slm", False, str(e))
        await self.check_services()
        self.save()
        return self.state["services"]

    def backups(self, now=False):
        """The scheduled backup, when it is time (or `now`), and the end of the old ones."""
        try:
            if now or backup.due():
                start = time.time()
                self.event(f"Backup made: {backup.create('scheduled')}")
                self.did("backup", start)
            backup.prune()
            self.state["services"].pop("backup", None)
        except (backup.BackupError, OSError) as e:
            if self.state["services"].get("backup", {}).get("text") != str(e):
                self.event(f"Backup failed: {e}", "error")
            self.service("backup", False, str(e))

    async def round(self):
        """One round. A round that breaks is not only written to the log: the panel, the
        health check and Telegram say so too, until a round works again."""
        try:
            await self.whole_round()
        except Exception as e:  # noqa: BLE001
            text = f"Round failed: {e!r}"
            self.status["error"] = {"text": text, "at": int(time.time())}
            self.event(text, "error")
            if self.state.get("told_error") != text:
                self.state["told_error"] = text
                await self.tell(text + ". The round did not finish; the Events page of the panel has the details.", "health")
            self.save()
        else:
            self.status["error"] = None
            self.state.pop("told_error", None)

    async def whole_round(self):
        problems = config.problems()
        if problems:
            self.service("config", False, "; ".join(problems))
            return
        self.state["services"].pop("config", None)
        async with self.lock:
            self.status.update(running=True, skipped=0)
            try:
                waiting = sum(1 for i in self.state["items"].values() if self.awaits(i))
                self.status["phase"] = "testing the connections"
                await self.task("health", self.check_services())
                self.status["phase"] = "reading the library"
                if self.versions_due():
                    await self.task("versions", self.refresh_versions())
                await self.refresh_titles()
                if await self.task("library", self.sync_library()) and self.working("INDEXERS"):
                    self.status["phase"] = "checking new posts"
                    await self.task("rss", self.feed())
                    start = time.time()
                    if await self.backlog():
                        self.did("search", start)
                self.status["phase"] = "following the downloads"
                await self.followed()
                if self.working("DOWNLOAD_CLIENTS"):
                    self.status["phase"] = "sending"
                    await self.auto_grab()
                now_waiting = sum(1 for i in self.state["items"].values() if self.awaits(i))
                await self.tell_found()
                if self.asking():
                    await self.ask()
                elif now_waiting > waiting:
                    await self.tell(f"{now_waiting} updates or DLC await your choice", "choice")
                self.backups()
            finally:
                self.status.update(running=False, phase=None, last_run=int(time.time()))
                self.save()

    async def search_now(self, key, query=None):
        """The "Search now" button. Does not wait for a running round: a round can take a while."""
        item = self.state["items"].get(key)
        if item is None:
            raise clients.ServiceError("Unknown game")
        found = await self.search_game(item["game_id"], query)
        self.save()
        return found

    async def test(self, kind, entry):
        """A Test button of the settings, with the values that are in the form. kind "slm": the
        library, with `entry` the settings as they would be; else one indexer, download client
        or connection."""
        if kind == "slm":
            return f"{len(await clients.library(self.session, entry))} games in the library"
        saved = next((e for e in config.providers(kind) if e["id"] == entry.get("id")), None) if kind in config.KINDS else None
        try:
            text = await self.tried(kind, entry)
        except clients.ServiceError as e:
            if saved:
                self.provider(kind, saved, False, str(e))
            raise
        if saved:  # the card says what the Test said, not an older failure
            self.provider(kind, saved, True, text)
        return text

    async def tried(self, kind, entry):
        if kind == "INDEXERS":
            return await indexers.status(self.session, entry)
        if kind == "DOWNLOAD_CLIENTS":
            return await downloads.status(self.session, entry)
        if kind == "CONNECTIONS":
            await notify.send(self.session, entry, "This is a test message.")
            return "Test message sent"
        raise clients.ServiceError("Unknown service")

    # ------------------------------------------------------------ for the panel

    def shown(self, item):
        """One item as the panel gets it."""
        inside = ("candidates", "blocked", "rejected", "failed", "turned_down", "ask", "asked")
        shown = {k: v for k, v in item.items() if k not in inside}
        hidden = ("downloadUrl", "rank", "confidence", "indexerId")
        shown["turned_down"] = [{k: v for k, v in r.items() if k not in hidden} for r in item.get("turned_down", [])]
        named = {r["guid"] for r in item.get("turned_down", []) + item.get("failed", [])}
        # Rejections of which an older version kept only the id.
        shown["unnamed"] = sum(1 for g in item["blocked"] if g not in named)
        shown["asked"] = bool(item.get("ask"))
        # What was never sent first: the first of the list is what a download button sends.
        fresh = self.untried(item)
        listed = fresh + [c for c in item["candidates"] if c not in fresh]
        shown["candidates"] = [{k: v for k, v in c.items() if k not in hidden} for c in listed]
        shown["rejected"] = [{k: v for k, v in r.items() if k not in hidden} for r in item.get("rejected", [])]
        shown["failed"] = [{k: v for k, v in f.items() if k not in hidden} for f in item.get("failed", [])]
        if item["type"] == "update":
            shown["ladder"] = self.ladder_text(item["game_id"])
        if item["type"] == "game":
            shown["cover"] = bool(self.cover_address(item["game_id"]))
        auto = self.automatic(item)
        shown["auto_guid"] = auto["guid"] if auto else None
        if item["ignored"]:
            shown["status"] = "ignored"
        elif item["grab"]:
            shown["status"] = "sent"
        elif self.awaits(item):
            shown["status"] = "review"
        elif item["candidates"] and not fresh:
            shown["status"] = "tried"  # every release it has was sent before
        elif item["candidates"]:
            shown["status"] = "covered"  # a DLC pack while the DLC itself is on its way
        elif item.get("last_search"):
            shown["status"] = "none"
        else:
            shown["status"] = "new"
        return shown

    def disk_space(self):
        """The free space where the settings, the library and the downloads are, for the Status
        page. Looked at once a minute at most: the panel asks every few seconds."""
        at, known = self.disks
        if time.time() - at < DISK_SECONDS:
            return known
        places = [("Config folder", config.DATA_DIR)]
        places += [("Root folder", r["path"]) for r in config.ROOT_FOLDERS]
        for client in config.providers("DOWNLOAD_CLIENTS"):
            folder = self.state.get("download_folders", {}).get(client["id"])
            if folder:
                places.append((f"Downloads of {client['name']}", importer.local_download(client, folder)))
        self.disks = (time.time(), importer.disks(places))
        return self.disks[1]

    def view(self):
        """Everything the panel shows. Download links stay inside: they hold the Prowlarr key."""
        items = []
        for item in self.state["items"].values():
            try:
                items.append(self.shown(item))
            except Exception as e:  # noqa: BLE001
                self.skip(str(item.get("name") or item.get("key")), e, count=False)
        order = {"review": 0, "sent": 1, "covered": 1, "tried": 2, "new": 2, "none": 3, "ignored": 4}
        items.sort(key=lambda i: (order[i["status"]], i["name"].lower(), i["type"]))
        return {
            "status": self.status,
            "library": self.state["library"],
            "services": self.state["services"],
            "providers": {kind: [{"id": e["id"], "name": e["name"], "type": e["type"], "enabled": e["enabled"]}
                                 for e in config.providers(kind)] for kind in config.KINDS},
            "items": items,
            "arrived": [a for a in self.state.get("arrived", []) if a["at"] > time.time() - ARRIVED_DAYS * 86400],
            "settings": {
                "auto": config.auto_min_score(), "dlc": config.INCLUDE_DLC,
                "interval": config.SYNC_INTERVAL_MINUTES, "search_hours": config.SEARCH_INTERVAL_HOURS,
                "wait_minutes": config.GRAB_WAIT_MINUTES, "asking": self.asking(),
                "hide_failed": config.HIDE_FAILED_DOWNLOADS,
                "importing": config.IMPORT_COMPLETED, "root_folders": len(config.ROOT_FOLDERS),
            },
            "configured": not config.problems(),
            "missing": config.problems(),
            "disks": self.disk_space(),
        }
