"""What NSWHunter does each round: read the library, look for releases, judge them, send them."""
import asyncio
import datetime
import json
import os
import time

import clients
import config
import matcher

MAX_CANDIDATES = 15
MAX_EVENTS = 200
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
            candidate.get("priority", DEFAULT_PRIORITY), -(candidate.get("grabs") or 0))


def published_ordinal(release):
    day = published_date(release)
    return day.toordinal() if day else 0


class Hunter:
    def __init__(self, session, notify=None):
        self.session = session
        self.notify = notify or no_notify
        self.lock = asyncio.Lock()  # one round or search at a time
        self.games = {}  # game id -> matcher.Game, only games that miss something
        self.versions = {}  # titledb: lower-case title id -> {"65536": "2021-10-05"}
        self.priorities = {}  # Prowlarr indexer id -> priority
        self.status = {"running": False, "phase": None, "last_run": None, "next_run": None}
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

    def event(self, text, level="info"):
        log(text)
        self.state["events"].insert(0, {"at": int(time.time()), "text": text, "level": level})
        del self.state["events"][MAX_EVENTS:]

    def service(self, name, ok, text):
        self.state["services"][name] = {"ok": ok, "text": text, "at": int(time.time())}

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
                raise clients.ServiceError("Versielijst: onverwacht antwoord")
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
        games, wanted = {}, {}
        for title in titles:
            game_id = str(title.get("id", "")).upper()
            if len(game_id) != 16:
                continue
            name = title.get("name") or ""
            if name == "Unknown title":
                name = ""  # nothing to match on; only a title ID can identify it
            update = bool(title.get("updateMissing")) and not title.get("updatesIgnored")
            all_dlc = [{"id": str(d.get("id", "")).upper(), "name": d.get("name") or "",
                        "status": d.get("status")} for d in title.get("dlc") or [] if isinstance(d, dict)]
            missing_dlc = [d for d in all_dlc if d["status"] == "missing"] if config.INCLUDE_DLC else []
            if not update and not missing_dlc:
                continue
            game = matcher.Game(
                id=game_id, name=name,
                local_version=int(title.get("localUpdate") or 0),
                latest_version=int(title.get("latestUpdate") or 0),
                local_display=title.get("version") or None,
                dates=self.dates_for(game_id), missing_dlc=missing_dlc, dlc=all_dlc)
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
        items = self.state["items"]
        for key in [k for k in items if k not in wanted]:
            gone = items.pop(key)
            if gone.get("grab"):
                self.event(f"Binnen: {self.label(gone)} staat nu in de bibliotheek")
        for key, facts in wanted.items():
            item = items.setdefault(key, {
                "key": key, "candidates": [], "blocked": [], "ignored": False,
                "grab": None, "first_seen": int(time.time())})
            grab = item.get("grab")
            if grab and facts.get("local_version", 0) > grab.get("local_version", facts.get("local_version", 0)):
                # What was sent arrived, but it was not the newest update: choose again.
                self.event(f"Binnen: {grab['title']}. Er is nog een nieuwere update.")
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
        return True

    @staticmethod
    def label(item):
        if item["type"] == "dlc":
            return f"{item['name']} (DLC: {item.get('dlc_name') or item['key']})"
        return f"{item['name']} (update)"

    def items_of(self, game_id):
        return [i for i in self.state["items"].values() if i["game_id"] == game_id]

    # ------------------------------------------------------------ judging

    def judge(self, item, release):
        game = self.games.get(item["game_id"])
        if game is None:
            return None
        dlc = {"id": item.get("dlc_id", ""), "name": item.get("dlc_name", "")}
        vermap = self.state["vermap"].setdefault(game.id, {})
        result = matcher.evaluate(game, release["title"], published_date(release), vermap,
                                  want=item["type"], dlc=dlc, seen=self.seen(game.id))
        if not self.state["vermap"][game.id]:
            del self.state["vermap"][game.id]
        if isinstance(result, matcher.Rejection):
            return None
        return {**release, **result.to_dict()}

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
        """Add a release to an item's candidates if it is one. True if it is new."""
        if release["guid"] in item["blocked"]:
            return False
        release = {**release, "priority": self.priorities.get(release.get("indexerId"), DEFAULT_PRIORITY)}
        if any(c["guid"] == release["guid"] for c in item["candidates"]):
            return False
        # The same release on several indexers: keep the one from the indexer that goes first.
        same = matcher.same_release(release["title"])
        twin = next((c for c in item["candidates"] if matcher.same_release(c["title"]) == same), None)
        if twin and twin.get("priority", DEFAULT_PRIORITY) <= release["priority"]:
            return False
        candidate = self.judge(item, release)
        if candidate is None:
            return False
        if twin:
            item["candidates"].remove(twin)
        item["candidates"].append(candidate)
        item["candidates"].sort(key=best_first)
        del item["candidates"][MAX_CANDIDATES:]
        return candidate in item["candidates"] and not twin

    def reevaluate(self):
        """The library changed (new local version, newer update out): judge everything again."""
        for item in self.state["items"].values():
            fresh = sorted((c for c in (self.judge(item, c) for c in item["candidates"]) if c), key=best_first)
            kept = {}
            for candidate in sorted(fresh, key=lambda c: c.get("priority", DEFAULT_PRIORITY)):
                kept.setdefault(matcher.same_release(candidate["title"]), candidate)
            item["candidates"] = [c for c in fresh if c in kept.values()]

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
                "basisspel" if step.version == 0 else "nieuwer dan " + matcher.update_name(game.latest_version))
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
                relevant.append((release, items))
                learned = self.notice(game_id, release) or learned
        # First every version is noticed, then the releases are judged: what one release is
        # can depend on the others (see matcher.ladder).
        found = sum(self.offer(item, release) for release, items in relevant for item in items)
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
            self.event(f"Nieuwe posts: {found} kandidaat-release(s) gevonden")

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
            self.status["phase"] = f"zoeken {n + 1}/{len(queue)}: {self.games[game_id].name or game_id}"
            try:
                await self.search_game(game_id)
            except clients.ServiceError as e:
                self.service("prowlarr", False, str(e))
                return
            self.save()  # a long first round: keep what was found so far
        if queue:
            self.event(f"{len(queue)} game(s) op naam gezocht")

    # ------------------------------------------------------------ sending

    def expire_grabs(self):
        """Sent, but still missing after the waiting time: that release did not work out."""
        limit = time.time() - config.GRAB_WAIT_HOURS * 3600
        for item in self.state["items"].values():
            grab = item.get("grab")
            if grab and grab["at"] < limit:
                item["blocked"].append(grab["guid"])
                item["candidates"] = [c for c in item["candidates"] if c["guid"] != grab["guid"]]
                item["grab"] = None
                self.event(f"Niet aangekomen: {grab['title']}. Deze release wordt overgeslagen.", "warn")

    def automatic(self, item):
        """The candidate that may go out without a click, or None."""
        threshold = config.auto_min_score()
        if not threshold or item["ignored"] or item["grab"] or not item["candidates"]:
            return None
        best = item["candidates"][0]
        if best.get("score", 0) < threshold:
            return None
        if best["kind"] == "bundle" and not config.AUTO_BUNDLES:
            return None
        return best

    async def grab(self, key, guid, auto=False):
        item = self.state["items"].get(key)
        candidate = next((c for c in (item or {}).get("candidates", []) if c["guid"] == guid), None)
        if candidate is None:
            raise clients.ServiceError("Deze release staat niet meer in de lijst")
        try:
            await clients.send(self.session, candidate)
        except clients.ServiceError:
            if config.DOWNLOAD_CLIENT != "prowlarr":
                raise
            # Prowlarr only grabs what it found in the last half hour: search again, try once more.
            await self.search_game(item["game_id"])
            await clients.send(self.session, candidate)
        item["grab"] = {"guid": guid, "title": candidate["title"], "at": int(time.time()), "auto": auto,
                        "local_version": item.get("local_version", 0)}
        item.setdefault("sent", [])
        if guid not in item["sent"]:
            item["sent"].append(guid)
        how = "Automatisch verstuurd" if auto else "Verstuurd"
        self.event(f"{how}: {candidate['title']}", "grab")
        self.save()
        if auto:
            await self.notify("NSWHunter: update verstuurd", candidate["title"])

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
                self.event(f"Versturen mislukt: {candidate['title']}: {e}", "error")
                break

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
        problems = config.problems()
        if problems:
            self.service("config", False, "; ".join(problems))
            return
        self.state["services"].pop("config", None)
        async with self.lock:
            self.status["running"] = True
            try:
                waiting = sum(1 for i in self.state["items"].values() if i["candidates"] and not i["grab"])
                self.status["phase"] = "verbindingen testen"
                await self.check_services()
                self.status["phase"] = "bibliotheek ophalen"
                await self.refresh_versions()
                if await self.sync_library() and self.state["services"]["prowlarr"]["ok"]:
                    self.status["phase"] = "nieuwe posts bekijken"
                    await self.feed()
                    await self.backlog()
                self.expire_grabs()
                if self.state["services"]["downloader"]["ok"]:
                    self.status["phase"] = "versturen"
                    await self.auto_grab()
                now_waiting = sum(
                    1 for i in self.state["items"].values()
                    if i["candidates"] and not i["grab"] and not i["ignored"])
                if now_waiting > waiting:
                    await self.notify("NSWHunter", f"{now_waiting} update(s) wachten op je keuze")
            finally:
                self.status.update(running=False, phase=None, last_run=int(time.time()))
                self.save()

    async def search_now(self, key):
        """The "Zoek nu" button. Does not wait for a running round: a round can take a while."""
        item = self.state["items"].get(key)
        if item is None:
            raise clients.ServiceError("Onbekende game")
        found = await self.search_game(item["game_id"])
        self.save()
        return found

    async def test(self, service, cfg):
        """One Test button of the Configuratie tab, with the values that are in the form."""
        if service == "slm":
            return f"{len(await clients.library(self.session, cfg))} games in de bibliotheek"
        if service == "prowlarr":
            return await clients.prowlarr_status(self.session, cfg)
        if service == "downloader":
            return await clients.downloader_status(self.session, cfg)
        raise clients.ServiceError("Onbekende service")

    # ------------------------------------------------------------ for the panel

    def view(self):
        """Everything the panel shows. Download links stay inside: they hold the Prowlarr key."""
        items = []
        for item in self.state["items"].values():
            shown = {k: v for k, v in item.items() if k not in ("candidates", "blocked")}
            shown["candidates"] = [
                {k: v for k, v in c.items() if k not in ("downloadUrl", "rank", "confidence", "indexerId")}
                for c in item["candidates"]]
            if item["type"] == "update":
                shown["ladder"] = self.ladder_text(item["game_id"])
            auto = self.automatic(item)
            shown["auto_guid"] = auto["guid"] if auto else None
            if item["ignored"]:
                shown["status"] = "ignored"
            elif item["grab"]:
                shown["status"] = "sent"
            elif item["candidates"]:
                shown["status"] = "review"
            elif item.get("last_search"):
                shown["status"] = "none"
            else:
                shown["status"] = "new"
            items.append(shown)
        order = {"review": 0, "sent": 1, "new": 2, "none": 3, "ignored": 4}
        items.sort(key=lambda i: (order[i["status"]], i["name"].lower(), i["type"]))
        return {
            "status": self.status,
            "library": self.state["library"],
            "services": self.state["services"],
            "events": self.state["events"][:60],
            "items": items,
            "settings": {
                "auto": config.auto_min_score(), "dlc": config.INCLUDE_DLC,
                "client": config.DOWNLOAD_CLIENT, "category": config.DOWNLOAD_CATEGORY,
                "interval": config.SYNC_INTERVAL_MINUTES, "search_hours": config.SEARCH_INTERVAL_HOURS,
            },
            "configured": not config.problems(),
        }
