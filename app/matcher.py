"""Decide whether a usenet release is the update (or DLC) a game is missing.

Release names have no fixed format, so nothing here relies on one. A release is judged on
three things, each found anywhere in the title:

* which game it is: a Switch title ID if present, otherwise the game name
* which version it is: an internal number (v131072) or a display version (v1.0.4)
* what it is: an update, DLC, the base game, or a bundle of those

The result is a Candidate with a score from 1 to 10, or a Rejection with the reason.
"""
import datetime
import difflib
import re
import unicodedata
from dataclasses import asdict, dataclass, field

# The score is the chance that a download is the right one, as a mark from 1 to 10. It is the
# product of three chances: that it is this game, that it is the newest update, and that it is
# an update and nothing else.
IDENTITY = {"tid": 1.0, "exact": 0.9, "extras": 0.5, "fuzzy": 0.35}
KIND = {"update": 1.0, "unknown": 0.92, "bundle": 0.75, "dlc": 1.0, "dlcpack": 1.0, "base": 1.0}
UNSAID = 0.85  # a release of a new game that says neither game, update nor DLC
VERSIONED = 0.7  # ... and does have a version above 1.0.0: it can be an update without the word
WHOLE_GAME = 0.75  # an "update" as big as the game itself: the game is probably in it
ODD_SIZE = 0.8  # an update many times bigger or smaller than the one in the library
PACK = 0.55  # a pack of DLC that does not say which DLC
UNLOCKER = 0.35  # a "DLC Unlocker": a small file that opens DLC, not the DLC as the library counts it
UNLOCKER_WORDS = {"unlocker", "unlockers", "unlock"}
CRACK = 0.9  # an update with a crack holds changed files
NAMED = 0.6  # the share of a DLC's own words that must be in a title to call it named

# A release may be posted a little before the official date in titledb (time zones, early dumps).
DATE_SLACK = datetime.timedelta(days=3)
# How late the date of a new update can be in the databases (seen: three weeks).
LATE_SLACK = datetime.timedelta(days=45)

# 01...: Switch. 04...: Switch 2, recognised only to tell that a release is not for the Switch.
TID_RE = re.compile(r"(?<![0-9a-z])(0[14][0-9a-f]{14})(?![0-9a-z])")
SWITCH2_RE = re.compile(r"(?<![0-9a-z])(switch|nsw|ns)[ ._-]?2(?![0-9a-z])")
# v65536, v.131072, "v 196608": five or more digits is always an internal version number.
INTERNAL_RE = re.compile(r"(?<![0-9a-z])v\.?\s?(\d{5,10})(?![0-9a-z])")
BRACKET_INTERNAL_RE = re.compile(r"[\[(](\d{5,10})[\])]")
V0_RE = re.compile(r"(?<![0-9a-z])v0(?![0-9a-z.])")
# v1.0.4, v.1.2, "v 2.0.1.3". Stops before ".nsw" but not in the middle of "1.0.4".
DISPLAY_V_RE = re.compile(r"(?<![0-9a-z])v\.?\s?(\d{1,4}(?:\.\d{1,5}){1,3})(?![0-9a-z]|\.\d)")
# The same without the "v". Only trusted after the game name has been cut off (see parse).
DISPLAY_BARE_RE = re.compile(r"(?<![0-9a-z])(?<!\d\.)(\d{1,2}(?:\.\d{1,5}){1,3})(?![0-9a-z]|\.\d)")
EXTENSION_RE = re.compile(r"\.(nsp|nsz|xci|xcz|rar|zip|7z|nzb|par2)$")
TOKEN_RE = re.compile(r"[0-9a-z]+")

UPDATE_WORDS = {"update", "updates", "upd", "updt", "patch"}
INCLUDE_WORDS = {"incl", "including", "includes"}
# The Console category of an indexer holds every console. These say "not the Switch" ...
OTHER_PLATFORMS = {
    "ps2", "ps3", "ps4", "ps5", "psp", "psv", "psvita", "playstation", "xbox", "xbox360", "x360",
    "xboxone", "xone", "xsx", "wii", "wiiu", "3ds", "n3ds", "nds", "gba", "ngc", "gamecube",
}
# ... as do the product codes of PlayStation releases (CUSA34119).
OTHER_CODE_RE = re.compile(r"(?<![0-9a-z])(cusa|ppsa|pcse|pcsb|bles|blus|npub|npeb|npua)\d{5}(?![0-9a-z])")
# ... as do these, of PC releases and repacks, when the title does not name the Switch: words ...
PC_WORDS = {"pc", "win", "win32", "win64", "windows", "x64", "x86", "gog", "steam", "steamrip", "linux",
            "macos", "osx", "repack", "repacks"}
# ... and the groups that release for the PC only (the name after the last dash).
PC_GROUPS = {
    "reloaded", "codex", "skidrow", "plaza", "cpy", "hoodlum", "prophet", "tinyiso", "darksiders", "flt",
    "fairlight", "razor1911", "empress", "tenoke", "rune", "elamigos", "fitgirl", "dodi", "xatab", "kaoskrew",
    "simplex", "doge", "chronos", "voksi", "ali213", "3dm", "postmortem", "dinobytes", "steampunks", "goldberg",
    "gog", "rg mechanics", "masquerade", "corepack", "anomaly", "i know", "ksa", "rzr",
}
PC_GROUP_RE = re.compile(r"-\s*([0-9a-z_ ]+?)\s*$")
# ... and the repackers of PC games, wherever they stand: also "[FitGirl Repack]" of a Switch
# game is a PC emulator package. As is a build date ("(build 19.11.2025)").
PC_TAGS = {"elamigos", "fitgirl", "goggames", "fckdrm", "voices38", "dodi", "xatab", "kaoskrew"}
PC_BUILD_RE = re.compile(r"\(build \d{1,2}\.\d{1,2}\.\d{4}\)")
DEMO_WORDS = {"demo", "trial"}
# ... and these say it is the Switch.
SWITCH_WORDS = {"nsw", "switch", "nsp", "nsz", "xci", "xcz", "eshop", "nx"}
UNMARKED = 0.85  # a title that names no platform at all
CRACK_WORDS = {"crack", "cracked"}
DLC_WORDS = {"dlc", "dlcs", "addon", "addons"}
BUNDLE_WORDS = {"base", "incl", "including", "includes", "plus", "with", "and"}
# Words that say nothing about which game it is: platform, format, region, language, scene tags.
NOISE = UPDATE_WORDS | DLC_WORDS | BUNDLE_WORDS | {
    "nsw", "switch", "nintendo", "ns", "nx", "nsp", "nsz", "xci", "xcz", "eshop", "game", "only",
    "eur", "usa", "jpn", "jap", "jp", "eu", "us", "asia", "kor", "chn", "ww", "world", "region", "free",
    "multi", "multilang", "multilanguage", "repack", "proper", "read", "nfo", "internal", "rev", "cfw",
    "full", "unlocker", "en", "fr", "de", "es", "it", "nl", "pt", "ru", "ja", "ko", "zh", "pl",
    "v", "ver", "version", "build", "retail", "digital", "rip", "scene", "p2p", "pack", "complete",
} | CRACK_WORDS
ROMAN = {"ii", "iii", "iv", "vi", "vii", "viii", "ix", "x", "xi", "xii", "xiii"}


@dataclass
class Game:
    id: str  # base title ID, 16 hex characters, upper case
    name: str
    local_version: int = 0
    latest_version: int = 0
    local_display: str | None = None  # "1.0.2" if the library knows it
    dates: dict = field(default_factory=dict)  # internal version -> datetime.date of release
    missing_dlc: list = field(default_factory=list)  # [{"id": ..., "name": ...}]
    dlc: list = field(default_factory=list)  # every DLC of the game, owned or not: [{"id", "name"}]
    update_size: int = 0  # bytes of the newest update in the library, 0 if there is none
    base_size: int = 0  # bytes of the game itself


@dataclass
class Candidate:
    score: int  # 1-10: how likely it is that this download is the right one
    kind: str  # update | bundle | dlc | dlcpack | unlocker | base | unknown
    name_match: str  # tid | exact | fuzzy
    internal_version: int | None
    display_version: str | None
    is_latest: bool | None  # None: cannot tell from the title
    reasons: list
    estimated_version: int | None = None  # what a display version was translated to (see ladder)
    deduced: bool = False  # that translation rests on exact pairs, not on dates

    def to_dict(self):
        return asdict(self)


def mark(identity, version, kind, crack=False):
    """The score from 1 to 10 of a release (see IDENTITY)."""
    chance = IDENTITY[identity] * version * KIND[kind] * (CRACK if crack else 1)
    return max(1, min(10, int(chance * 10 + 0.5)))


@dataclass
class Rejection:
    reason: str
    known: bool = False  # it is a release of this game, and it fell off for another reason


def clean(text):
    """Lower case, no accents, no trademark signs or apostrophes. Separators are kept."""
    text = re.sub(r"[™®©℠]", "", text)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"['’‘`´]", "", text.lower())
    return text.replace("&", " and ")


def same_release(title):
    """Two titles with this in common are the same release: indexers differ in dots and spaces."""
    return " ".join(t for t, _, _ in tokens(clean(title)))


def tokens(text):
    """[(token, start, end)] of a cleaned string."""
    return [(m.group(), m.start(), m.end()) for m in TOKEN_RE.finditer(text)]


def search_term(name):
    """The game name as a search query: words only."""
    return " ".join(t for t, _, _ in tokens(clean(name)))


def family(title_id):
    """Base game, update and DLC of one game share everything but the last 13 bits."""
    return int(title_id, 16) & ~0x1FFF


def update_name(version):
    """v720896 is the eleventh update: Nintendo numbers updates in steps of 65536."""
    if version and version % 65536 == 0:
        return f"update {version // 65536}"
    return f"v{version}"


def version_tuple(text):
    return tuple(int(p) for p in text.split("."))


def _is_noise(token):
    return (
        token in NOISE
        or re.fullmatch(r"multi\d+|v\d+|(19|20)\d\d|upd\d+|rev\d+", token) is not None
    )


def _includes_update(toks):
    """"Game incl Update" is the game with an update; "Update incl Crack" is just an update."""
    order = [t for t, _, _ in toks]
    includes = [i for i, t in enumerate(order) if t in INCLUDE_WORDS]
    updates = [i for i, t in enumerate(order) if t in UPDATE_WORDS]
    return bool(includes and updates) and includes[0] < updates[0]


def _find_name(release_tokens, name_tokens):
    """(index, number of words) of the first place where the name's words appear in a row, or
    None. "Ragnarok / Rhapsody" is "Ragnarok and Rhapsody" in a release: an "and" there does not count."""
    words = [t for t, _, _ in release_tokens]
    bare = [t for t in name_tokens if t != "and"]
    for i in range(len(words)):
        if words[i:i + len(name_tokens)] == name_tokens:
            return i, len(name_tokens)
        j, got = i, []
        while j < len(words) and len(got) < len(bare):
            if words[j] != "and" or j == i:
                got.append(words[j])
            j += 1
        if bare and got == bare:
            return i, j - i
    return None


def _marker_offset(text, toks):
    """Where the part that can still be the game name ends: at the first bracket, title ID,
    version or noise word."""
    offsets = [len(text)]
    for regex in (TID_RE, INTERNAL_RE, DISPLAY_V_RE, V0_RE):
        m = regex.search(text)
        if m:
            offsets.append(m.start())
    m = re.search(r"[\[({]", text)
    if m:
        offsets.append(m.start())
    for token, start, _ in toks:
        if _is_noise(token):
            offsets.append(start)
            break
    return min(offsets)


def _versions(text, rest):
    """(internal version or None, display version or None). `rest` is the title without the
    game name, the only place where a version without "v" is believed."""
    internal = None
    m = INTERNAL_RE.search(text)
    if m:
        internal = int(m.group(1))
    else:
        for m in BRACKET_INTERNAL_RE.finditer(text):
            if int(m.group(1)) % 65536 == 0:
                internal = int(m.group(1))
                break
    if internal is None and V0_RE.search(text):
        internal = 0
    display = None
    m = DISPLAY_V_RE.search(text)
    if m:
        display = m.group(1)
    else:
        for m in DISPLAY_BARE_RE.finditer(rest):
            before = {t for t, _, _ in tokens(rest[:m.start()])[-2:]}
            # Three parts (1.0.4) is a version; two parts (1.2) only right after "update".
            if m.group(1).count(".") >= 2 or before & (UPDATE_WORDS | {"v", "ver", "version"}):
                display = m.group(1)
                break
    return internal, display


@dataclass
class Step:
    """What a display version is, on the ladder of one game's updates."""
    version: int | None  # internal version; None = higher than every update that is known
    how: str  # exact: a known pair; pattern: the version counts the update; date: by posting date; order: by its place
    solid: bool  # rests on exact pairs only, no dates
    after: str | None = None  # the display version one step lower
    floor: int | None = None  # ... and its internal version


def _newest_on(game, day):
    """The newest update that was out on a day, 0 if none was, None if that cannot be told."""
    if day is None or not game.dates:
        return None
    out = [v for v, released in game.dates.items() if released - DATE_SLACK <= day]
    return max(out) if out else 0


def _before_any_newer(game, day):
    """Posted so long before the next update came out that it cannot be that update. With a
    wide margin: the databases often list a new update weeks after it was released."""
    newer = [released for v, released in game.dates.items() if v > game.local_version]
    return bool(newer) and day is not None and day < min(newer) - LATE_SLACK


def _pattern(game, display, known):
    """Some games count the update in the version itself: 1.0.31.0 is update 31, so 1.0.35.0
    is update 35. Believed only when the library's own pair shows it, the count is not a small
    number that fits by chance, and that update exists."""
    number = game.local_version // 65536
    if not game.local_display or game.local_version % 65536 or number < 3:
        return None
    try:
        own, new = version_tuple(game.local_display), version_tuple(display)
    except ValueError:
        return None
    differ = [i for i, (a, b) in enumerate(zip(own, new)) if a != b]
    if len(own) != len(new) or len(differ) != 1 or own[differ[0]] != number:
        return None
    version = new[differ[0]] * 65536
    return version if version in known else None


def ladder(game, seen, vermap=None):
    """Translate display versions (1.7.1) to internal ones (720896 = update 11).

    Nothing lists both numbers of an update. What is known: the internal versions of a game
    and roughly when they came out; the pair the library holds (its own 1.7.0 is update 10);
    and every display version seen in release names with the day it was first posted (`seen`).
    Display versions and internal versions rise together, so walking up the display versions:
    one that was posted when a newer update was out is that update (date), and one that is
    higher than the previous but not newer by date is the next update (order). The dates of
    the newest updates are often weeks late in the databases; the order does not need them.
    Before both comes the pattern: a version that counts the update itself (see _pattern).

    Returns {display: Step}.
    """
    known = set(game.dates) | {v for v in (game.local_version, game.latest_version) if v}
    if not game.dates and (game.latest_version - game.local_version) % 65536 == 0:
        # No list of this game's updates: assume the usual one step per update in between.
        known |= set(range(game.local_version + 65536, game.latest_version, 65536))
    known = sorted(known)
    exact = dict(vermap or {})
    if game.local_display:
        exact[game.local_display] = game.local_version
    displays = []
    for display in set(seen) | set(exact):
        try:
            displays.append((version_tuple(display), display))
        except ValueError:
            continue
    steps, floor, after, floor_solid = {}, None, None, True
    for _, display in sorted(displays):
        if display in exact:
            step = Step(exact[display], "exact", True, after, floor)
        else:
            by_date = _newest_on(game, seen.get(display))
            counted = _pattern(game, display, known)
            if counted is not None and (floor is None or counted > floor):
                step = Step(counted, "pattern", False, after, floor)
            elif by_date is not None and (floor is None or by_date > floor):
                step = Step(by_date, "date", False, after, floor)
            elif floor is not None:
                later = [v for v in known if v > floor]
                step = Step(later[0] if later else None, "order", floor_solid, after, floor)
            else:
                continue
        steps[display] = step
        if step.version is not None:
            floor, after, floor_solid = step.version, display, step.solid
    return steps


def observe(game, title):
    """The display version in a release that is certainly of this game, else None. Feeds
    ladder(): also releases that are not wanted (the version already owned) are steps."""
    result = evaluate(game, title, only_version=True)
    return result if isinstance(result, str) else None


NOT_THIS_GAME = ("title ID of another game", "name does not match")


def evaluate(game, title, published=None, vermap=None, want="update", dlc=None, seen=None,
             only_version=False, size=0):
    """Judge one release for one game: a Candidate, or a Rejection with the reason.

    want: "update"; "dlc" with `dlc` = {"id": ..., "name": ...} of the missing DLC;
    "dlcpack" for a pack of the game's DLC that names none of them; or "game" for the game
    itself, of a game that is not in the library yet.
    size: bytes of the release, if known.
    """
    result = _evaluate(game, title, published, vermap, want, dlc, seen, only_version, size)
    if isinstance(result, Rejection):
        result.known = not (result.reason in NOT_THIS_GAME or result.reason.startswith("another game"))
    return result


def size_text(size):
    return f"{size / 2**30:.1f} GB" if size >= 2**30 else f"{size / 2**20:.0f} MB"


def _evaluate(game, title, published, vermap, want, dlc, seen, only_version, size):
    """Judge one release for one game.

    published: datetime.date the release was posted, if known.
    vermap: {"1.0.4": 262144} learned earlier for this game, to translate display versions.
    want: "update", or "dlc" with `dlc` = {"id": ..., "name": ...} of the missing DLC.
    seen: {"1.7.0": date first posted} of every display version seen for this game.
    """
    text = EXTENSION_RE.sub("", clean(title).strip())
    toks = tokens(text)
    words = {t for t, _, _ in toks}
    reasons = []

    # ---- which game
    ids = [m.group(1).upper() for m in TID_RE.finditer(text)]
    own_ids = [i for i in ids if family(i) == family(game.id)]
    if ids and not own_ids:
        return Rejection("title ID of another game")

    name_tokens = [t for t, _, _ in tokens(clean(game.name))]
    rest = text
    name_match = None
    extras = []
    at = None
    if name_tokens:
        found = _find_name(toks, name_tokens)
        if found is not None:
            at, length = found
            name_match = "exact"
            end = toks[at + length - 1][2]
            rest = text[end:]
            rest_toks = tokens(rest)
            limit = _marker_offset(rest, rest_toks)
            gap = [t for t, s, _ in rest_toks if s < limit]
            # Tags in brackets before the name ("[NSW] Game") say nothing about the game.
            before = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", text[:toks[at][1]])
            prefix = [t for t, _, _ in tokens(before) if not _is_noise(t)]
            if gap and (re.fullmatch(r"\d{1,2}", gap[0]) or gap[0] in ROMAN):
                return Rejection(f"another game (sequel '{gap[0]}')")
            extras = prefix + gap
            # A one-word name ("Hades", "Inside") turns up inside many other titles.
            if extras and want != "dlc" and (len(name_tokens) == 1 or len(game.name) <= 5):
                return Rejection("another game (short name with extra words)")
    if own_ids:
        name_match = "tid"
        extras = []
        reasons.append("title ID matches")
    elif name_match is None:
        name_part = " ".join(t for t, s, _ in toks if s < _marker_offset(text, toks))
        wanted = " ".join(name_tokens)
        ratio = difflib.SequenceMatcher(None, name_part, wanted).ratio() if name_part else 0
        shortened = len(name_part.split()) >= 2 and wanted.startswith(name_part + " ")
        # "FIFA 22" and "FIFA 23" are almost the same text and not the same game.
        numbers = lambda ws: {w for w in ws if w.isdigit() or w in ROMAN}  # noqa: E731
        if (ratio < 0.85 and not shortened) or numbers(name_part.split()) != numbers(name_tokens):
            return Rejection("name does not match")
        name_match = "fuzzy"
        reasons.append("name is close, but not the same")
    elif extras:
        reasons.append("extra words in the title: " + " ".join(extras))
    else:
        reasons.append("name matches")

    # ---- which platform
    # Words of the game's own name do not count ("Wii Sports" would otherwise never match).
    outside = {t for t, _, _ in tokens(rest)} | ({t for t, _, _ in toks[:at]} if name_match == "exact" else set())
    if not own_ids:
        other = sorted(outside & OTHER_PLATFORMS) or [m.group() for m in [OTHER_CODE_RE.search(text)] if m]
        if other:
            return Rejection(f"for another platform ({other[0].upper()}), not for the Switch")
        if outside & PC_TAGS or PC_BUILD_RE.search(text):
            return Rejection("for the PC or a repack, not for the Switch")
        group = PC_GROUP_RE.search(text)
        if not words & SWITCH_WORDS and (outside & PC_WORDS or (group and group.group(1) in PC_GROUPS)):
            return Rejection("for the PC or a repack, not for the Switch")
        # Switch 2 releases are left alone on purpose: only the first Switch.
        if SWITCH2_RE.search(rest) or any(i.startswith("04") for i in ids):
            return Rejection("for the Switch 2, not for the Switch")

    # ---- what it is
    has_update = bool(words & UPDATE_WORDS) or any(re.fullmatch(r"upd\d+", w) for w in words)
    has_dlc = bool(words & DLC_WORDS)
    if own_ids:
        parts = {"update" if i.endswith("800") else "base" if i.endswith("000") else "dlc"
                 for i in own_ids}
        kind = parts.pop() if len(parts) == 1 else "bundle"
        if kind == "base":
            kind = "bundle" if has_update else "base"
    elif has_update and (has_dlc or "+" in rest or "base" in words or _includes_update(toks)):
        kind = "bundle"
    elif has_update:
        kind = "update"
    elif has_dlc:
        kind = "dlc"
    else:
        kind = "unknown"

    if want == "game":
        return _evaluate_game(text, rest, words, kind, own_ids, name_match, extras, reasons,
                              bool(outside & SWITCH_WORDS))
    if want in ("dlc", "dlcpack"):
        return _evaluate_dlc(game, dlc, text, own_ids, kind, name_match, extras, reasons,
                             bool(outside & SWITCH_WORDS), pack=want == "dlcpack")
    if kind == "dlc":
        return Rejection("DLC only, not an update")
    if kind == "base":
        return Rejection("base game, not an update")

    # ---- which version
    internal, display = _versions(text, rest)
    clean_name = name_match == "tid" or (name_match == "exact" and not extras)
    if only_version:
        return display if clean_name and display else None
    if internal is not None and display and internal >= 65536:
        if vermap is not None:
            vermap[display] = internal  # both in one title: remember the translation
    elif internal is None and display and vermap and display in vermap:
        internal = vermap[display]
        reasons.append(f"v{display} was seen before as v{internal}")

    is_latest = None
    estimated = None  # the internal version this release is taken to be when its title has none
    deduced = False  # ... and whether that rests on exact pairs only
    chance = 0.3  # that this is the newest update
    local, latest = game.local_version, game.latest_version
    if internal is not None:
        if internal == 0:
            return Rejection("base game (v0), not an update")
        if internal <= local:
            return Rejection(f"v{internal} is not newer than your own version")
        is_latest = bool(latest) and internal >= latest
        chance = 1.0 if is_latest else 0.5
        reasons.append("is the latest version" if is_latest else
                       f"newer than your own version, but not the latest ({update_name(latest)})")
    elif display:
        parsed = version_tuple(display)
        if parsed <= (1, 0, 0) and kind != "update":
            return Rejection("version 1.0.0 is the base game")
        newer_than_own = False
        if game.local_display:
            try:
                if parsed <= version_tuple(game.local_display):
                    return Rejection(f"v{display} is not newer than your own version")
                newer_than_own = True
            except ValueError:
                pass
        chance = 0.45 if newer_than_own else 0.3
        days = [d for d in ((seen or {}).get(display), published) if d]
        first = min(days) if days else None
        step = ladder(game, {**(seen or {}), display: first}, vermap).get(display)
        if step and step.version is None:
            is_latest, deduced = True, step.solid
            chance = 0.9 if deduced else 0.8
            reasons.append(f"v{display} is higher than v{step.after} ({update_name(step.floor)}), the latest update that is known")
        elif step and step.version > local:
            estimated, deduced = step.version, step.solid
            if step.how == "order":
                # The next update at least; more only if a version was never posted.
                is_latest = True if latest and estimated >= latest else None
                chance = (0.97 if deduced else 0.78) if is_latest else 0.45
                reasons.append(f"v{display} is higher than v{step.after} ({update_name(step.floor)}), so "
                               + ("" if is_latest else "at least ") + update_name(estimated))
            elif step.how == "pattern":
                is_latest = bool(latest) and estimated >= latest
                chance = 0.85 if is_latest else 0.4
                reasons.append(f"this game counts the update in its version: your own v{game.local_display} is "
                               f"{update_name(local)}, so v{display} is {update_name(estimated)}")
            else:
                is_latest = bool(latest) and estimated >= latest
                chance = (0.97 if deduced else 0.78) if is_latest else 0.4
                reasons.append(f"v{display} was first posted when {update_name(estimated)} was the latest")
        elif step and not newer_than_own:
            if step.version < local or _before_any_newer(game, first):
                return Rejection(f"v{display} is {update_name(step.version)}: not newer than your own version")
            reasons.append("posted after your own update; can be that update or a newer one")
    elif kind == "unknown":
        return Rejection("no version and no 'update' in the title")
    else:
        # No version at all: only the posting date says something.
        chance = 0.25
        by_date = _newest_on(game, published)
        if by_date is not None and by_date > local:
            estimated = by_date
            is_latest = bool(latest) and estimated >= latest
            chance = 0.6 if is_latest else 0.3
            reasons.append(f"posted when {update_name(estimated)} was the latest")
        elif by_date is not None and (by_date < local or _before_any_newer(game, published)):
            return Rejection("posted before a newer update existed")
    if is_latest is None:
        reasons.append("cannot tell whether this is the latest version")
    elif internal is None and estimated and not is_latest:
        reasons.append(f"the latest is {update_name(latest)}")

    # ---- the score
    crack = bool(words & CRACK_WORDS)
    # A title ID and an internal version number (v131072) exist on the Switch only.
    if not (own_ids or internal is not None and internal >= 65536 or outside & SWITCH_WORDS):
        chance *= UNMARKED
        reasons.append("the title names no platform")
    if kind == "bundle":
        reasons.append("bundle: also holds the base game or DLC")
    elif size and game.base_size and size >= 0.8 * game.base_size and size > 3 * game.update_size:
        chance *= WHOLE_GAME
        reasons.append(f"as big as the whole game ({size_text(size)}): the base game is probably included")
    elif size and game.update_size and not 0.15 <= size / game.update_size <= 5:
        chance *= ODD_SIZE
        reasons.append(f"the size is far from that of your own update ({size_text(size)} against "
                       f"{size_text(game.update_size)})")
    if crack:
        reasons.append("with crack: the files were changed")
    identity = "tid" if name_match == "tid" else "fuzzy" if name_match == "fuzzy" else "extras" if extras else "exact"
    return Candidate(mark(identity, chance, kind, crack), kind, name_match, internal, display, is_latest,
                     reasons, estimated, deduced)


def _evaluate_game(text, rest, words, kind, own_ids, name_match, extras, reasons, switch):
    """A release judged as the game itself, for a game that is not in the library yet. A
    bundle with its update or DLC is as good: it holds the game."""
    if kind == "update":
        return Rejection("update only, not the game")
    if kind == "dlc" or words & UNLOCKER_WORDS:
        return Rejection("DLC only, not the game")
    if DEMO_WORDS & set(extras):
        return Rejection("a demo, not the game")
    if not (own_ids or switch):
        # Unmarked whole games turned out to be PC releases, mods and other consoles.
        return Rejection("names no platform: a whole game must say it is for the Switch")
    chance = 1.0
    if kind == "bundle":
        reasons.append("the game with its update or DLC")
    elif kind == "base":
        reasons.append("the game itself")
    else:
        internal, display = _versions(text, rest)
        if internal:
            return Rejection(f"v{internal} is an update, not the game")
        if display and version_tuple(display) > (1, 0, 0):
            chance = VERSIONED
            reasons.append(f"v{display} without 'update': can be an update")
        else:
            chance = UNSAID
            reasons.append("says neither update nor DLC: probably the game itself")
    crack = bool(words & CRACK_WORDS)
    if crack:
        reasons.append("with crack: the files were changed")
    identity = "tid" if name_match == "tid" else "fuzzy" if name_match == "fuzzy" else "extras" if extras else "exact"
    return Candidate(mark(identity, chance, "base", crack), "bundle" if kind == "bundle" else "base",
                     name_match, None, None, None, reasons)


def guessed_name(title):
    """The name of the game at the start of a release title: up to the first bracket, title ID,
    version or word of the platform. "" if nothing is left."""
    text = EXTENSION_RE.sub("", title.strip())
    text = re.split(r"[\[(]|(?<![0-9a-z])0[14][0-9a-f]{14}|[ ._-][vV]\.?\d|[ ._-](?:NSW|NSP|NSZ|XCI|XCZ|Switch|Update|UPD|DLC|Base|incl)(?![0-9a-z])",
                    text, maxsplit=1, flags=re.IGNORECASE)[0]
    return " ".join(re.sub(r"[._]", " ", text).split()).strip(" -")


def _dlc_words(game, name, telling=True):
    """The words of a DLC's name that are its own: not the game's name, not noise. With
    `telling` also without the words that all DLCs of the game share ("In-Game Commentary -
    Dutch", "... - Spanish"): those do not tell one DLC from another."""
    game_tokens = {t for t, _, _ in tokens(clean(game.name))}

    def own(text):
        words = []
        for token, _, _ in tokens(clean(text or "")):
            if token not in game_tokens and not _is_noise(token) and token not in words:
                words.append(token)
        return words

    all_words = [own(d.get("name", "")) for d in game.dlc]
    shared = {t for words in all_words for t in words
              if len(all_words) > 1 and all(t in other for other in all_words)}
    mine = own(name)
    if not telling:
        return mine
    return [t for t in mine if t not in shared] or mine


def _named(words, own):
    """How well a release names a DLC: (share of the DLC's own words in the title, how many)."""
    hits = [t for t in own if t in words]
    return (len(hits) / len(own), len(hits)) if own else (0.0, 0)


def _evaluate_dlc(game, dlc, text, own_ids, kind, name_match, extras, reasons, switch=True, pack=False):
    """A missing DLC: only its own title ID makes it certain; a name is a guess."""
    dlc_id = (dlc or {}).get("id", "").upper()
    if own_ids and pack:
        return Rejection("has the title ID of one DLC: listed under that DLC")
    if own_ids:
        if dlc_id in own_ids:
            return Candidate(10, "dlc", "tid", None, None, None, ["title ID of this DLC matches"])
        return Rejection("title ID of another part of this game")
    if kind not in ("dlc", "bundle"):
        return Rejection("not DLC")
    if name_match == "fuzzy":
        return Rejection("name does not match")
    words = {t for t, _, _ in tokens(text)}
    own = [] if pack else _dlc_words(game, (dlc or {}).get("name", ""))
    mine = _named(words, own)
    # A game can have twenty DLCs with almost the same name ("Commentary - Dutch", "... -
    # Spanish"). A release that names another one better is that other one.
    others = [(_named(words, _dlc_words(game, other.get("name", ""))), other.get("name", ""))
              for other in game.dlc if pack or str(other.get("id", "")).upper() != dlc_id]
    rival = max(others, default=((0.0, 0), ""))
    if rival[0][0] >= NAMED and rival[0] > mine:
        return Rejection(f"is another DLC of this game: {rival[1]}")
    # Words of the DLC's name between the game's name and "DLC" are not extra words.
    whole = _dlc_words(game, (dlc or {}).get("name", ""), telling=False)
    left = [e for e in extras if e not in whole]
    reasons = ["extra words in the title: " + " ".join(left)] if left else ["name matches"]
    if pack:
        # "DLC Unlocker", "DLC Pack": listed once per game, not under every missing DLC.
        if mine[0] >= NAMED or rival[0][0] >= NAMED:
            return Rejection("names one DLC: listed under that DLC")
        unlocker = bool(words & UNLOCKER_WORDS)
        chance = UNLOCKER if unlocker else PACK
        reasons.append("a DLC unlocker: a small file that opens DLC, which your library may not count as the DLC it misses"
                       if unlocker else "pack with DLC of this game; cannot tell which are in it")
    elif mine[0] >= NAMED:
        only = rival[0] < mine
        chance = 0.85 if only else 0.6
        reasons.append("the title names the DLC" + ("" if only else "; also fits another DLC"))
    else:
        return Rejection("names no DLC: listed under the DLC pack of this game")
    if not switch:
        chance *= UNMARKED
        reasons.append("the title names no platform")
    kind = "bundle" if kind == "bundle" else "dlcpack" if pack else "dlc"
    shown = "unlocker" if pack and words & UNLOCKER_WORDS else "dlcpack" if pack else "dlc"
    return Candidate(mark("extras" if left else "exact", chance, kind), shown,
                     name_match, None, None, None, reasons)
