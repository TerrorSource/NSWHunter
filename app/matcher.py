"""Decide whether a usenet release is the update (or DLC) a game is missing.

Release names have no fixed format, so nothing here relies on one. A release is judged on
three things, each found anywhere in the title:

* which game it is: a Switch title ID if present, otherwise the game name
* which version it is: an internal number (v131072) or a display version (v1.0.4)
* what it is: an update, DLC, the base game, or a bundle of those

The result is a Candidate with a confidence, or a Rejection with the reason.
"""
import datetime
import difflib
import re
import unicodedata
from dataclasses import asdict, dataclass, field

SURE, LIKELY, UNCERTAIN = "sure", "likely", "uncertain"
CONFIDENCE_RANK = {SURE: 2, LIKELY: 1, UNCERTAIN: 0}

# A release may be posted a little before the official date in titledb (time zones, early dumps).
DATE_SLACK = datetime.timedelta(days=3)
# How late the date of a new update can be in the databases (seen: three weeks).
LATE_SLACK = datetime.timedelta(days=45)

TID_RE = re.compile(r"(?<![0-9a-z])(01[0-9a-f]{14})(?![0-9a-z])")
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
DLC_WORDS = {"dlc", "dlcs", "addon", "addons"}
BUNDLE_WORDS = {"base", "incl", "including", "includes", "plus", "with", "and"}
# Words that say nothing about which game it is: platform, format, region, language, scene tags.
NOISE = UPDATE_WORDS | DLC_WORDS | BUNDLE_WORDS | {
    "nsw", "switch", "nintendo", "ns", "nx", "nsp", "nsz", "xci", "xcz", "eshop", "game", "only",
    "eur", "usa", "jpn", "jap", "jp", "eu", "us", "asia", "kor", "chn", "ww", "world", "region", "free",
    "multi", "multilang", "multilanguage", "repack", "proper", "read", "nfo", "internal", "rev", "cfw",
    "full", "unlocker", "en", "fr", "de", "es", "it", "nl", "pt", "ru", "ja", "ko", "zh", "pl",
    "v", "ver", "version", "build", "retail", "digital", "rip", "scene", "p2p", "pack",
}
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


@dataclass
class Candidate:
    confidence: str
    kind: str  # update | bundle | dlc | unknown
    name_match: str  # tid | exact | fuzzy
    internal_version: int | None
    display_version: str | None
    is_latest: bool | None  # None: cannot tell from the title
    reasons: list
    rank: tuple = ()
    estimated_version: int | None = None  # what a display version was translated to (see ladder)
    deduced: bool = False  # that translation rests on exact pairs, not on dates

    def to_dict(self):
        d = asdict(self)
        # Lists all the way down, so a rank compares the same before and after a trip through JSON.
        d["rank"] = [list(x) if isinstance(x, tuple) else x for x in self.rank]
        return d


@dataclass
class Rejection:
    reason: str


def clean(text):
    """Lower case, no accents, no trademark signs or apostrophes. Separators are kept."""
    text = re.sub(r"[™®©℠]", "", text)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"['’‘`´]", "", text.lower())
    return text.replace("&", " and ")


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


def _find_name(release_tokens, name_tokens):
    """Index of the first place where the name's words appear in a row, or None."""
    words = [t for t, _, _ in release_tokens]
    n = len(name_tokens)
    for i in range(len(words) - n + 1):
        if words[i:i + n] == name_tokens:
            return i
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
    how: str  # exact: seen together or the library's own pair; date: by posting date; order: by its place
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


def ladder(game, seen, vermap=None):
    """Translate display versions (1.7.1) to internal ones (720896 = update 11).

    Nothing lists both numbers of an update. What is known: the internal versions of a game
    and roughly when they came out; the pair the library holds (its own 1.7.0 is update 10);
    and every display version seen in release names with the day it was first posted (`seen`).
    Display versions and internal versions rise together, so walking up the display versions:
    one that was posted when a newer update was out is that update (date), and one that is
    higher than the previous but not newer by date is the next update (order). The dates of
    the newest updates are often weeks late in the databases; the order does not need them.

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
            if by_date is not None and (floor is None or by_date > floor):
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


def evaluate(game, title, published=None, vermap=None, want="update", dlc=None, seen=None,
             only_version=False):
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
        return Rejection("title ID van een andere game")

    name_tokens = [t for t, _, _ in tokens(clean(game.name))]
    rest = text
    name_match = None
    extras = []
    if name_tokens:
        at = _find_name(toks, name_tokens)
        if at is not None:
            name_match = "exact"
            end = toks[at + len(name_tokens) - 1][2]
            rest = text[end:]
            rest_toks = tokens(rest)
            limit = _marker_offset(rest, rest_toks)
            gap = [t for t, s, _ in rest_toks if s < limit]
            # Tags in brackets before the name ("[NSW] Game") say nothing about the game.
            before = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", text[:toks[at][1]])
            prefix = [t for t, _, _ in tokens(before) if not _is_noise(t)]
            if gap and (re.fullmatch(r"\d{1,2}", gap[0]) or gap[0] in ROMAN):
                return Rejection(f"andere game (vervolgdeel '{gap[0]}')")
            extras = prefix + gap
            # A one-word name ("Hades", "Inside") turns up inside many other titles.
            if extras and want != "dlc" and (len(name_tokens) == 1 or len(game.name) <= 5):
                return Rejection("andere game (korte naam met extra woorden)")
    if own_ids:
        name_match = "tid"
        extras = []
        reasons.append("title ID komt overeen")
    elif name_match is None:
        name_part = " ".join(t for t, s, _ in toks if s < _marker_offset(text, toks))
        wanted = " ".join(name_tokens)
        ratio = difflib.SequenceMatcher(None, name_part, wanted).ratio() if name_part else 0
        shortened = len(name_part.split()) >= 2 and wanted.startswith(name_part + " ")
        # "FIFA 22" and "FIFA 23" are almost the same text and not the same game.
        numbers = lambda ws: {w for w in ws if w.isdigit() or w in ROMAN}  # noqa: E731
        if (ratio < 0.85 and not shortened) or numbers(name_part.split()) != numbers(name_tokens):
            return Rejection("naam komt niet overeen")
        name_match = "fuzzy"
        reasons.append("naam lijkt erop, maar is niet gelijk")
    elif extras:
        reasons.append("extra woorden in de titel: " + " ".join(extras))
    else:
        reasons.append("naam komt overeen")

    # ---- what it is
    has_update = bool(words & UPDATE_WORDS) or any(re.fullmatch(r"upd\d+", w) for w in words)
    has_dlc = bool(words & DLC_WORDS)
    if own_ids:
        parts = {"update" if i.endswith("800") else "base" if i.endswith("000") else "dlc"
                 for i in own_ids}
        kind = parts.pop() if len(parts) == 1 else "bundle"
        if kind == "base":
            kind = "bundle" if has_update else "base"
    elif has_update and (has_dlc or "+" in rest or words & {"base", "incl", "including", "includes"}):
        kind = "bundle"
    elif has_update:
        kind = "update"
    elif has_dlc:
        kind = "dlc"
    else:
        kind = "unknown"

    if want == "dlc":
        return _evaluate_dlc(game, dlc, text, own_ids, kind, name_match, extras, reasons)
    if kind == "dlc":
        return Rejection("alleen DLC, geen update")
    if kind == "base":
        return Rejection("basisspel, geen update")

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
        reasons.append(f"v{display} is eerder gezien als v{internal}")

    is_latest = None
    estimated = None  # the internal version this release is taken to be when its title has none
    deduced = False  # ... and whether that rests on exact pairs only
    local, latest = game.local_version, game.latest_version
    if internal is not None:
        if internal == 0:
            return Rejection("basisspel (v0), geen update")
        if internal <= local:
            return Rejection(f"v{internal} is niet nieuwer dan je eigen versie")
        is_latest = bool(latest) and internal >= latest
        reasons.append("is de nieuwste versie" if is_latest else
                       f"nieuwer dan je eigen versie, maar niet de nieuwste ({update_name(latest)})")
    elif display:
        parsed = version_tuple(display)
        if parsed <= (1, 0, 0) and kind != "update":
            return Rejection("versie 1.0.0 is het basisspel")
        newer_than_own = False
        if game.local_display:
            try:
                if parsed <= version_tuple(game.local_display):
                    return Rejection(f"v{display} is niet nieuwer dan je eigen versie")
                newer_than_own = True
            except ValueError:
                pass
        days = [d for d in ((seen or {}).get(display), published) if d]
        first = min(days) if days else None
        step = ladder(game, {**(seen or {}), display: first}, vermap).get(display)
        if step and step.version is None:
            is_latest, deduced = True, step.solid
            reasons.append(f"v{display} is hoger dan v{step.after} ({update_name(step.floor)}), de nieuwste update die bekend is")
        elif step and step.version > local:
            estimated, deduced = step.version, step.solid
            if step.how == "order":
                # The next update at least; more only if a version was never posted.
                is_latest = True if latest and estimated >= latest else None
                reasons.append(f"v{display} is hoger dan v{step.after} ({update_name(step.floor)}), dus "
                               + ("" if is_latest else "minstens ") + update_name(estimated))
            else:
                is_latest = bool(latest) and estimated >= latest
                reasons.append(f"v{display} is voor het eerst geplaatst toen {update_name(estimated)} de nieuwste was")
        elif step and not newer_than_own:
            if step.version < local or _before_any_newer(game, first):
                return Rejection(f"v{display} is {update_name(step.version)}: niet nieuwer dan je eigen versie")
            reasons.append("geplaatst na je eigen update; kan die update zijn of een nieuwere")
    elif kind == "unknown":
        return Rejection("geen versie en geen 'update' in de titel")
    else:
        # No version at all: only the posting date says something.
        by_date = _newest_on(game, published)
        if by_date is not None and by_date > local:
            estimated = by_date
            is_latest = bool(latest) and estimated >= latest
            reasons.append(f"geplaatst toen {update_name(estimated)} de nieuwste was")
        elif by_date is not None and (by_date < local or _before_any_newer(game, published)):
            return Rejection("geplaatst voordat er een nieuwere update bestond")
    if is_latest is None:
        reasons.append("niet te zien of dit de nieuwste versie is")
    elif internal is None and estimated and not is_latest:
        reasons.append(f"de nieuwste is {update_name(latest)}")

    # ---- how sure
    if clean_name and (internal is not None or (deduced and is_latest)):
        confidence = SURE
    elif clean_name and display and is_latest:
        confidence = LIKELY
    else:
        confidence = UNCERTAIN
    if kind == "bundle":
        reasons.append("bundel: bevat ook het basisspel of DLC")

    kind_rank = {"update": 2, "unknown": 1, "bundle": 0}[kind]
    rank = (
        CONFIDENCE_RANK[confidence],
        {True: 2, None: 1, False: 0}[is_latest],
        kind_rank,
        internal or estimated or 0,
        version_tuple(display) if display else (),
        published.toordinal() if published else 0,
    )
    return Candidate(confidence, kind, name_match, internal, display, is_latest, reasons, rank,
                     estimated, deduced)


def _evaluate_dlc(game, dlc, text, own_ids, kind, name_match, extras, reasons):
    """A missing DLC: only its own title ID makes it certain; a name is a guess."""
    dlc_id = (dlc or {}).get("id", "").upper()
    if own_ids:
        if dlc_id in own_ids:
            return Candidate(SURE, "dlc", "tid", None, None, None,
                             ["title ID van deze DLC komt overeen"], (2, 1, 2, 0, (), 0))
        return Rejection("title ID van een ander onderdeel van deze game")
    if kind not in ("dlc", "bundle"):
        return Rejection("geen DLC")
    if name_match == "fuzzy":
        return Rejection("naam komt niet overeen")
    dlc_tokens = [t for t, _, _ in tokens(clean((dlc or {}).get("name", "")))]
    game_tokens = {t for t, _, _ in tokens(clean(game.name))}
    own = [t for t in dlc_tokens if t not in game_tokens and not _is_noise(t)]
    words = {t for t, _, _ in tokens(text)}
    if own and all(t in words for t in own):
        reasons.append("naam van de DLC staat in de titel")
        confidence = UNCERTAIN if [e for e in extras if e not in dlc_tokens] else LIKELY
    else:
        reasons.append("DLC van deze game, maar niet te zien welke")
        confidence = UNCERTAIN
    return Candidate(confidence, "dlc", name_match, None, None, None, reasons,
                     (CONFIDENCE_RANK[confidence], 1, 2 if kind == "dlc" else 0, 0, (), 0))
