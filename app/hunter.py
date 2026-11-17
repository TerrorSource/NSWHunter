"""What NSWHunter does each round: read the library, look for releases, judge them, send them."""
import asyncio
import datetime
import json
import os
import secrets
import time

import clients
import config
import matcher

MAX_CANDIDATES = 15
MAX_REJECTED = 25
MAX_FAILED = 10  # failed downloads kept per item, for the panel
# What the panel needs of a release that fell off; the judgement is made again when it counts.
RELEASE_FIELDS = ("guid", "title", "size", "indexer", "indexerId", "published", "downloadUrl",
                  "infoUrl", "grabs", "priority")
# A release that belongs under another item of the same game did not fall off: it is there.
ELSEWHERE = ("is another DLC", "names no DLC", "names one DLC", "has the title ID of one DLC",
             "not DLC", "DLC only", "title ID of another part")
MAX_EVENTS = 1000
MAX_TURNED_DOWN = 25  # releases the user rejected, kept per item so they can be restored
ARRIVED_DAYS = 30  # how long the panel shows what arrived
MAX_ASKS = 10  # questions in Telegram per round
ASK_DELAY = 1.1  # seconds between two messages: Telegram allows about one per second to a chat
DEFAULT_PRIORITY = 25  # what Prowlarr gives an indexer that has none set


def log(*args):
    print(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), *args, flush=True)


def published_date(release):
    try:
        return datetime.date.fromisoformat(release.get("published", "")[:10])
    except ValueError:
        return None


async def no_notify(title, body):
    pass


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


class Hunter:
    def __init__(self, session, notify=None):
        self.session = session
        self.notify = notify or no_notify
        self.lock = asyncio.Lock()  # one round or search at a time
        self.tell_later, self.dropped, self.finished = [], False, False  # of follow_grabs
        self.games = {}  # game id -> matcher.Game, only games that miss something
        self.versions = {}  # titledb: lower-case title id -> {"65536": "2021-10-05"}
        self.priorities = {}  # Prowlarr indexer id -> priority
        self.status = {"running": False, "phase": None, "last_run": None, "next_run": None,
                       "error": None,  # {"text", "at"} of the last round, if it broke
                       "skipped": 0}  # games and releases the last round had to leave out
        self.troubles = set()  # what was already written to the log about those
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
            "telegram_offset": 0,  # the next update to ask Telegram for
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

    def save(self):
        os.makedirs(config.DATA_DIR, exist_ok=True)
        tmp = config.STATE_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.state, f)
        os.replace(tmp, config.STATE_FILE)

    def log(self):
        """The whole log, for the Log tab."""
        return self.state["events"]

    def event(self, text, level="info"):
        log(text)
        self.state["events"].insert(0, {"at": int(time.time()), "text": text, "level": level})
        del self.state["events"][MAX_EVENTS:]

    def service(self, name, ok, text):
        self.state["services"][name] = {"ok": ok, "text": text, "at": int(time.time())}

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

    async def sync_library(self):
        """Read the export and keep one item per missing update (and per missing DLC)."""
        try:
            titles = await clients.library(self.session)
        except clients.ServiceError as e:
            self.service("slm", False, str(e))
            return False
        games, wanted, broken = {}, {}, set()
        for title in titles:
            try:
                self.read_title(title, games, wanted)
            except Exception as e:  # noqa: BLE001
                game_id = str(title.get("id", "")).upper() if isinstance(title, dict) else ""
                broken.add(game_id)  # what is known about it is kept as it is
                self.skip(f"{game_id or 'a game'} of the library", e)
        items = self.state["items"]
        arrived = []
        for key in [k for k in items if k not in wanted and items[k]["game_id"] not in broken]:
            gone = items.pop(key)
            if gone.get("grab") and gone["type"] != "dlcpack":
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
        self.state["library"] = {
            "fetched": int(time.time()), "games": len(titles),
            "updates": sum(1 for i in items.values() if i["type"] == "update"),
            "dlc": sum(1 for i in items.values() if i["type"] == "dlc"),
        }
        self.service("slm", True, f"{len(titles)} games")
        self.reevaluate()
        for text in arrived:
            self.event(text, "grab")
            await self.tell(text)
        return True

    def read_title(self, title, games, wanted):
        """One game of the export: what it misses, as items to look for."""
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

    def arrive(self, item, grab, note=""):
        """Remember that what was sent is now in the library, for the panel."""
        now = int(time.time())
        what = ("DLC: " + (item.get("dlc_name") or item["key"]) if item["type"] == "dlc"
                else "DLC pack" if item["type"] == "dlcpack" else "update")
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
        return f"{item['name']} (update)"

    def items_of(self, game_id):
        return [i for i in self.state["items"].values() if i["game_id"] == game_id]

    def awaits(self, item):
        """Does this item wait for a choice? A DLC pack does not while every missing DLC of
        its game is already on its way: the pack would bring the same."""
        if item["ignored"] or item["grab"] or not item["candidates"]:
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
                                  size=int(release.get("size") or 0))
        if not self.state["vermap"][game.id]:
            del self.state["vermap"][game.id]
        if isinstance(result, matcher.Rejection):
            return result
        return {**{k: release.get(k) for k in RELEASE_FIELDS}, **result.to_dict()}

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
        return self.place(item, release)

    def place(self, item, release):
        # The priority as Prowlarr has it now; else the one the release was found with.
        release = {**release, "priority": self.priorities.get(release.get("indexerId"), priority_of(release))}
        same = matcher.same_release(release["title"])
        rejected = item.setdefault("rejected", [])
        result = self.judge(item, release)
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
        try:
            releases = await clients.prowlarr_search(self.session, "")
        except clients.ServiceError as e:
            self.service("prowlarr", False, str(e))
            return
        found = self.process(releases, list(self.games))
        if found:
            self.event(f"New posts: found {found} candidate release(s)")

    async def search_game(self, game_id):
        game = self.games.get(game_id)
        if game is None:
            return 0
        update_id = game_id[:13] + "800"
        queries = [matcher.search_term(game.name) or update_id]
        if config.SEARCH_BY_TITLE_ID and update_id not in queries:
            queries.append(update_id)
        releases = []
        for query in queries:
            releases += await clients.prowlarr_search(self.session, query)
        found = self.process(releases, [game_id])
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
            except clients.ServiceError as e:
                self.service("prowlarr", False, str(e))
                return
            except Exception as e:  # noqa: BLE001
                self.skip(self.games[game_id].name or game_id, e)
                self.state["searched"][game_id] = int(time.time())  # again after the interval, not every round
            self.save()  # a long first round: keep what was found so far
        if queue:
            self.event(f"Searched {len(queue)} game(s) by name")

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
        item["blocked"].append(grab["guid"])
        item["candidates"] = [c for c in item["candidates"] if c["guid"] != grab["guid"]]
        item["grab"] = None
        self.event(text, "warn")
        return text

    async def follow_grabs(self):
        """Ask the download client how the sent releases are doing.

        Failed: the next release gets its turn at once. Downloaded: the library is asked to
        scan and is read again; if the update is still not there after the waiting time, the
        download is left as it is and the user is told (no next release: something between the
        download client and the library is not connected). Unknown to the client: after the
        waiting time it counts as not arrived."""
        pending = [i for i in self.state["items"].values() if i.get("grab")]
        if not pending:
            return
        try:
            states = await clients.download_states(self.session)
        except clients.ServiceError as e:
            self.service("downloader", False, str(e))
            states = {}
        now, wait = time.time(), config.GRAB_WAIT_MINUTES * 60
        waited = f"{config.GRAB_WAIT_MINUTES} minutes" if wait < 7200 else f"{config.GRAB_WAIT_MINUTES // 60} hours"
        self.tell_later, self.dropped, self.finished = [], False, False
        for item in pending:
            try:
                self.follow(item, states, now, wait, waited)
            except Exception as e:  # noqa: BLE001
                self.skip(f"the download of {item['name']}", e)
        tell, dropped, finished = self.tell_later, self.dropped, self.finished
        if finished and not await clients.library_rescan(self.session) and not self.state.get("rescan_hint"):
            self.state["rescan_hint"] = True
            self.event("Switch-library-manager-web refuses to scan on request. Give the API key the Editor "
                       "role, and a download shows up in your library sooner.", "warn")
        waiting = any((i.get("grab") or {}).get("state") == "done" for i in self.state["items"].values())
        if waiting and now - (self.state["library"].get("fetched") or 0) > config.WATCH_SECONDS:
            await self.sync_library()
        for text in tell:
            await self.tell(text)
        if dropped and self.state["services"].get("downloader", {}).get("ok", True):
            await self.auto_grab()

    def follow(self, item, states, now, wait, waited):
        """One sent release: what the download client says about it, and what follows."""
        grab = item["grab"]
        known = states.get(grab.get("client_id")) if grab.get("client_id") else None
        state = (known or {}).get("state")
        grab["percent"] = (known or {}).get("percent")
        if state == "failed":
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
                text = (f"Downloaded, but not in your library after {waited}: {grab['title']}. "
                        "Does Switch-library-manager-web scan the folder of your download client?")
                self.event(text, "warn")
                self.tell_later.append(text)
        elif grab.get("state") not in ("done", "stuck") and now - grab["at"] > wait:
            self.tell_later.append(self.drop(
                item, f"Not arrived after {waited}: {grab['title']}. The next release gets its turn.",
                f"unknown to the download client and not in the library after {waited}"))
            self.dropped = True

    async def watch(self):
        """Between rounds: follow the downloads. Skipped while a round runs; that does it too."""
        if self.lock.locked() or config.problems():
            return
        if not any(i.get("grab") for i in self.state["items"].values()):
            return
        async with self.lock:
            await self.follow_grabs()
            self.save()

    async def tell(self, text):
        """A notification: Telegram if it is set up, and whatever else is configured."""
        if config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID:
            try:
                await clients.telegram(self.session, "NSWHunter\n" + text)
                self.service("telegram", True, "last message sent")
            except clients.ServiceError as e:
                self.service("telegram", False, str(e))
        else:
            self.state["services"].pop("telegram", None)
        await self.notify("NSWHunter", text)

    def automatic(self, item):
        """The candidate that may go out without a click, or None."""
        threshold = config.auto_min_score()
        if not threshold or not self.awaits(item):
            return None
        best = item["candidates"][0]
        if best.get("score", 0) < threshold:
            return None
        if best["kind"] == "bundle" and not config.AUTO_BUNDLES:
            return None
        return best

    async def grab(self, key, guid, auto=False):
        item = self.state["items"].get(key)
        # Also what fell off or failed before can be sent: the user may know better.
        listed = [r for part in ("candidates", "rejected", "failed") for r in (item or {}).get(part, [])]
        candidate = next((c for c in listed if c["guid"] == guid), None)
        if candidate is None:
            raise clients.ServiceError("This release is no longer in the list")
        try:
            client_id = await clients.send(self.session, candidate)
        except clients.ServiceError:
            if config.DOWNLOAD_CLIENT != "prowlarr":
                raise
            # Prowlarr only grabs what it found in the last half hour: search again, try once more.
            await self.search_game(item["game_id"])
            client_id = await clients.send(self.session, candidate)
        item["grab"] = {"guid": guid, "title": candidate["title"], "at": int(time.time()), "auto": auto,
                        "local_version": item.get("local_version", 0),
                        "dlc_missing": item.get("dlc_missing", 0), "client_id": client_id, "state": "sent"}
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
            await self.tell(f"Sent automatically: {candidate['title']}")

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
                self.service("downloader", False, str(e))
                self.event(f"Sending failed: {candidate['title']}: {e}", "error")
                break
            except Exception as e:  # noqa: BLE001
                self.skip(item["name"], e)

    async def grab_best(self, min_score):
        """The button "Download all": of every item that awaits a choice, send the best
        release if its score is at least `min_score`. Bundles are left for a click of their
        own. Returns how many were sent; stops at the first one the download client refuses."""
        sent = 0
        for item in list(self.state["items"].values()):
            if not self.awaits(item):
                continue
            best = item["candidates"][0]
            if best.get("score", 0) < min_score or best["kind"] == "bundle":
                continue
            try:
                await self.grab(item["key"], best["guid"])
            except clients.ServiceError as e:
                raise clients.ServiceError(f"{sent} sent, then: {e}") from e
            sent += 1
        return sent

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
            if release:
                self.place(item, {k: release.get(k) for k in RELEASE_FIELDS})
        self.save()

    # ------------------------------------------------------------ choosing in Telegram

    def asking(self):
        return bool(config.TELEGRAM_ASK and config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID)

    async def ask(self):
        """One message per item that awaits a choice, with buttons to download or reject its
        best release from Telegram. Every release is asked about once; at most MAX_ASKS
        messages per round, the highest scores first, the rest in the next rounds."""
        waiting = [i for i in self.state["items"].values()
                   if self.awaits(i) and i.get("asked") != i["candidates"][0]["guid"]]
        waiting.sort(key=lambda i: -i["candidates"][0].get("score", 0))
        for n, item in enumerate(waiting[:MAX_ASKS]):
            if n:
                await asyncio.sleep(ASK_DELAY)
            best = item["candidates"][0]
            facts = [f"{best['size'] / 2**20:.0f} MB" if best.get("size") else "", best.get("indexer") or "",
                     (best.get("published") or "")[:10]]
            text = "\n".join(["NSWHunter", self.label(item), f"{best.get('score', 0)}/10 · {best['title']}",
                              " · ".join(f for f in facts if f), "; ".join(best.get("reasons") or [])])
            token = secrets.token_hex(6)
            try:
                message_id = await clients.telegram(self.session, text, buttons=[
                    ("Download", "d:" + token), ("Reject", "r:" + token)])
                self.service("telegram", True, "last message sent")
            except clients.ServiceError as e:
                self.service("telegram", False, str(e))
                return
            item["asked"] = best["guid"]
            item["ask"] = {"token": token, "guid": best["guid"], "message_id": message_id, "text": text}

    async def telegram_answers(self, wait=50):
        """Wait for a press on a button under one of the questions in Telegram and act on it.
        False if no question is open: then Telegram is not asked anything."""
        if not self.asking() or not any(i.get("ask") for i in self.state["items"].values()):
            return False
        updates = await clients.telegram_call(self.session, "getUpdates", {
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
        chat = (query.get("message") or {}).get("chat") or {}
        mine = str(config.TELEGRAM_CHAT_ID)
        if str(chat.get("id")) != mine and "@" + str(chat.get("username") or "").lower() != mine.lower():
            return
        action, _, token = str(query.get("data") or "").partition(":")
        item = next((i for i in self.state["items"].values()
                     if token and (i.get("ask") or {}).get("token") == token), None)

        async def answer(text):
            try:
                await clients.telegram_call(self.session, "answerCallbackQuery", {
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
            await clients.telegram_call(self.session, "editMessageText", {
                "chat_id": chat.get("id"), "message_id": ask["message_id"], "text": ask["text"] + "\n\n" + outcome})
        except clients.ServiceError:
            pass

    # ------------------------------------------------------------ one round

    async def check_services(self):
        for name, test in (("prowlarr", clients.prowlarr_status), ("downloader", clients.downloader_status)):
            try:
                self.service(name, True, str(await test(self.session)))
            except clients.ServiceError as e:
                self.service(name, False, str(e))
        if self.state["services"]["prowlarr"]["ok"]:
            try:
                self.priorities = await clients.prowlarr_priorities(self.session)
            except clients.ServiceError:
                pass  # sorting then falls back to equal priorities

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
        if config.PROWLARR_URL:
            try:
                self.service("prowlarr", True, str(await clients.prowlarr_status(self.session)))
            except clients.ServiceError as e:
                self.service("prowlarr", False, str(e))
        if not problems or config.DOWNLOAD_CLIENT == "prowlarr":
            try:
                self.service("downloader", True, str(await clients.downloader_status(self.session)))
            except clients.ServiceError as e:
                self.service("downloader", False, str(e))
        self.save()
        return self.state["services"]

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
                await self.tell(text + ". The round did not finish; the Log tab of the panel has the details.")
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
                await self.check_services()
                self.status["phase"] = "reading the library"
                await self.refresh_versions()
                if await self.sync_library() and self.state["services"]["prowlarr"]["ok"]:
                    self.status["phase"] = "checking new posts"
                    await self.feed()
                    await self.backlog()
                self.status["phase"] = "following the downloads"
                await self.follow_grabs()
                if self.state["services"]["downloader"]["ok"]:
                    self.status["phase"] = "sending"
                    await self.auto_grab()
                now_waiting = sum(1 for i in self.state["items"].values() if self.awaits(i))
                if self.asking():
                    await self.ask()
                elif now_waiting > waiting:
                    await self.tell(f"{now_waiting} updates or DLC await your choice")
            finally:
                self.status.update(running=False, phase=None, last_run=int(time.time()))
                self.save()

    async def search_now(self, key):
        """The "Search now" button. Does not wait for a running round: a round can take a while."""
        item = self.state["items"].get(key)
        if item is None:
            raise clients.ServiceError("Unknown game")
        found = await self.search_game(item["game_id"])
        self.save()
        return found

    async def test(self, service, cfg):
        """One Test button of the Configuration tab, with the values that are in the form."""
        if service == "slm":
            return f"{len(await clients.library(self.session, cfg))} games in the library"
        if service == "prowlarr":
            return await clients.prowlarr_status(self.session, cfg)
        if service == "downloader":
            return await clients.downloader_status(self.session, cfg)
        if service == "telegram":
            await clients.telegram(self.session, "NSWHunter\nThis is a test message.", cfg)
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
        shown["candidates"] = [{k: v for k, v in c.items() if k not in hidden} for c in item["candidates"]]
        shown["rejected"] = [{k: v for k, v in r.items() if k not in hidden} for r in item.get("rejected", [])]
        shown["failed"] = [{k: v for k, v in f.items() if k not in hidden} for f in item.get("failed", [])]
        if item["type"] == "update":
            shown["ladder"] = self.ladder_text(item["game_id"])
        auto = self.automatic(item)
        shown["auto_guid"] = auto["guid"] if auto else None
        if item["ignored"]:
            shown["status"] = "ignored"
        elif item["grab"]:
            shown["status"] = "sent"
        elif self.awaits(item):
            shown["status"] = "review"
        elif item["candidates"]:
            shown["status"] = "covered"  # a DLC pack while the DLC itself is on its way
        elif item.get("last_search"):
            shown["status"] = "none"
        else:
            shown["status"] = "new"
        return shown

    def view(self):
        """Everything the panel shows. Download links stay inside: they hold the Prowlarr key."""
        items = []
        for item in self.state["items"].values():
            try:
                items.append(self.shown(item))
            except Exception as e:  # noqa: BLE001
                self.skip(str(item.get("name") or item.get("key")), e, count=False)
        order = {"review": 0, "sent": 1, "covered": 1, "new": 2, "none": 3, "ignored": 4}
        items.sort(key=lambda i: (order[i["status"]], i["name"].lower(), i["type"]))
        return {
            "status": self.status,
            "library": self.state["library"],
            "services": self.state["services"],
            "items": items,
            "arrived": [a for a in self.state.get("arrived", []) if a["at"] > time.time() - ARRIVED_DAYS * 86400],
            "settings": {
                "auto": config.auto_min_score(), "dlc": config.INCLUDE_DLC,
                "client": config.DOWNLOAD_CLIENT, "category": config.DOWNLOAD_CATEGORY,
                "interval": config.SYNC_INTERVAL_MINUTES, "search_hours": config.SEARCH_INTERVAL_HOURS,
                "wait_minutes": config.GRAB_WAIT_MINUTES, "asking": self.asking(),
            },
            "configured": not config.problems(),
        }
