"""Release names in every shape seen on usenet, held against one game."""
import datetime

import pytest

import matcher
from matcher import Candidate, Game, Rejection, evaluate


def day(text):
    return datetime.date.fromisoformat(text)


def alan():
    return Game(
        id="0100623017A58000", name="Alan Wake Remastered",
        local_version=65536, latest_version=196608, local_display="1.0.1",
        dates={65536: day("2022-11-01"), 131072: day("2023-02-01"), 196608: day("2023-06-01")})


AFTER_LATEST = day("2023-06-05")


# The score is the chance that the download is right: title ID and version number 10, name and
# version number 9, a version worked out from dates 7, something in between or beside it 5 or less.
@pytest.mark.parametrize("title, score, kind, is_latest", [
    ("Alan Wake Remastered [0100623017A58800][v196608].nsz", 10, "update", True),
    ("Alan.Wake.Remastered.Update.v196608.NSW-GRP", 9, "update", True),
    ("Alan Wake Remastered v196608 NSW", 8, "unknown", True),
    ("Alan_Wake_Remastered_Update_v1.0.3_NSW-VENOM", 7, "update", True),
    ("Alan.Wake.Remastered.Update.v1.0.3.NSW-SUXXORS", 7, "update", True),
    ("Alan Wake Remastered Update 1.0.3 [NSW]", 7, "update", True),
    ("Alan.Wake.Remastered.Update.v1.0.3.incl.Offline.Crack.NSW-VENOM", 6, "update", True),
    ("[NSW] Alan Wake Remastered (Update v131072) (EUR)", 5, "update", False),
    ("alan wake remastered [0100623017a58800] [v131072] (upd)", 5, "update", False),
    ("Alan Wake Remastered [NSP] [Base + Update 1.0.3 + DLC]", 5, "bundle", True),
    ("Alan Wake Remastered incl Update v1.0.3 NSW", 5, "bundle", True),
    ("Alan Wake Remastered Collectors Edition Update v196608", 5, "update", True),
    ("Alan Wake Remastered Update NSW", 5, "update", True),
    ("Alan Wake Remasterd Update v196608", 4, "update", True),
])
def test_candidates(title, score, kind, is_latest):
    result = evaluate(alan(), title, AFTER_LATEST)
    assert isinstance(result, Candidate), getattr(result, "reason", None)
    assert (result.score, result.kind, result.is_latest) == (score, kind, is_latest)


@pytest.mark.parametrize("title", [
    "Alan Wake Remastered [v65536]",                         # the version already in the library
    "Alan Wake Remastered [0100623017A58000][v0].nsp",       # base game
    "Alan Wake Remastered NSW-VENOM",                        # base game, no version at all
    "Alan Wake Remastered v1.0.0 NSW",                       # 1.0.0 is the base game
    "Alan Wake Remastered Update 1.0.1",                     # not newer than the local 1.0.1
    "Alan Wake 2 Update v1.0.5",                             # other game
    "Alan Wake Remastered 2 Update v1.0.5",                  # sequel
    "Alan Wake Remastered II Update v196608",                # sequel, roman
    "Alan Wake Remastered [0100AAAA00000800][v196608]",      # name fits, title ID of another game
    "Alan Wake Remastered [0100623017A59001][v0] DLC",       # DLC, not an update
    "Some Other Game Update v196608 NSW",
    "Alan.Wake.Remastered.Update.v1.0.3.PS4-GRP",            # another console
    "Alan Wake Remastered v1.03 incl DLC PS4-CUSA34119",
    "Alan Wake Remastered Update v1.0.3 CUSA34119",          # a PlayStation product code
    "Alan Wake Remastered Update v1.0.3 XBOX360",
    "Alan Wake Remastered Update v1.0.3 NSW2-GRP",           # Switch 2: left alone on purpose
    "Alan Wake Remastered Nintendo Switch 2 Edition Update v1.0.3",
    "Alan Wake Remastered [0400623017A58800][v196608]",
    "Control Ultimate Edition Update v1.0.3",
])
def test_rejections(title):
    assert isinstance(evaluate(alan(), title, AFTER_LATEST), Rejection)


def test_display_version_posted_before_latest_update_is_not_latest():
    result = evaluate(alan(), "Alan_Wake_Remastered_Update_v1.0.2_NSW-VENOM", day("2023-03-01"))
    assert (result.score, result.is_latest) == (4, False)


def test_release_posted_before_any_newer_update_existed():
    result = evaluate(alan(), "Alan Wake Remastered Update NSW", day("2022-12-01"))
    assert isinstance(result, Rejection)


def test_posting_date_tells_which_update_a_display_version_is():
    result = evaluate(alan(), "Alan_Wake_Remastered_Update_v1.0.3_NSW-VENOM", AFTER_LATEST)
    assert (result.estimated_version, result.is_latest) == (196608, True)
    older = evaluate(alan(), "Alan_Wake_Remastered_Update_v1.0.2_NSW-VENOM", day("2023-03-01"))
    assert (older.estimated_version, older.is_latest) == (131072, False)


def test_a_newer_display_version_is_not_rejected_on_dates_alone():
    """Higher than the library's own version, so at least the next update, whatever the dates say."""
    result = evaluate(alan(), "Alan_Wake_Remastered_Update_v1.0.2_NSW-VENOM", day("2022-12-01"))
    assert isinstance(result, Candidate)
    assert (result.score, result.estimated_version, result.is_latest) == (4, 131072, None)


# The user's real case, with the dates as the databases have them: update 11 is listed on
# 21 October, the release with v1.7.1 was posted on 30 September.
NARUTO_SEEN = {"1.7.0": day("2026-08-20"), "1.7.1": day("2026-09-30")}
V171 = "NARUTO X BORUTO Ultimate Ninja STORM CONNECTIONS Update v1.7.1 NSW-SUXXORS"
V170 = "NARUTO X BORUTO Ultimate Ninja STORM CONNECTIONS Update v1.7.0 NSW-SUXXORS"


def naruto(local=655360, display="1.7.0"):
    return Game(
        id="0100D2D0190A4000", name="NARUTO X BORUTO Ultimate Ninja STORM CONNECTIONS",
        local_version=local, latest_version=720896, local_display=display,
        dates={524288: day("2024-09-24"), 589824: day("2025-02-03"), 655360: day("2026-08-19"),
               720896: day("2026-10-21")})


def test_ladder_own_version_is_the_anchor():
    """The library has 1.7.0 = update 10; v1.7.1 is higher, and only update 11 is newer."""
    result = evaluate(naruto(), V171, day("2026-09-30"), seen=NARUTO_SEEN)
    assert (result.score, result.estimated_version, result.is_latest, result.deduced) == (
        9, 720896, True, True)
    assert isinstance(evaluate(naruto(), V170, day("2026-08-20"), seen=NARUTO_SEEN), Rejection)
    # The same without the other releases: the library's own pair is enough.
    assert evaluate(naruto(), V171, day("2026-09-30")).score == 9


def test_ladder_without_the_librarys_display_version():
    """No 1.7.0 from the library: v1.7.0 is update 10 by its date, v1.7.1 the next by its place."""
    game = naruto(display=None)
    steps = matcher.ladder(game, NARUTO_SEEN)
    assert (steps["1.7.0"].version, steps["1.7.0"].how) == (655360, "date")
    assert (steps["1.7.1"].version, steps["1.7.1"].how, steps["1.7.1"].solid) == (720896, "order", False)
    result = evaluate(game, V171, day("2026-09-30"), seen=NARUTO_SEEN)
    assert (result.score, result.estimated_version, result.is_latest) == (7, 720896, True)
    assert isinstance(evaluate(game, V170, day("2026-08-20"), seen=NARUTO_SEEN), Rejection)


def test_ladder_alone_and_dated_late_is_a_doubt_not_a_rejection():
    """Only v1.7.1 seen, nothing from the library: by date it is update 10, but update 11 is
    listed only three weeks later, so it can be that one."""
    result = evaluate(naruto(display=None), V171, day("2026-09-30"))
    assert isinstance(result, Candidate) and (result.score, result.is_latest) == (3, None)


def test_ladder_two_updates_behind():
    """Library at update 9: v1.7.0 is the update in between, v1.7.1 the newest."""
    game = naruto(local=589824, display="1.6.0")
    between = evaluate(game, V170, day("2026-08-20"), seen=NARUTO_SEEN)
    assert (between.estimated_version, between.is_latest) == (655360, False)
    newest = evaluate(game, V171, day("2026-09-30"), seen=NARUTO_SEEN)
    assert (newest.score, newest.estimated_version, newest.is_latest) == (7, 720896, True)


def test_ladder_higher_than_everything_known():
    seen = {**NARUTO_SEEN, "1.8.0": day("2026-11-10")}
    result = evaluate(naruto(), V171.replace("1.7.1", "1.8.0"), day("2026-11-10"), seen=seen)
    assert (result.is_latest, result.estimated_version) == (True, None)


def test_observe_reads_the_version_only_from_releases_of_this_game():
    assert matcher.observe(naruto(), V170) == "1.7.0"
    assert matcher.observe(naruto(), "NARUTO X BORUTO Ultimate Ninja STORM CONNECTIONS 2 Update v1.7.0") is None
    assert matcher.observe(naruto(), "Some Other Game Update v1.7.0") is None


def test_update_name():
    assert matcher.update_name(720896) == "update 11" and matcher.update_name(100) == "v100"


def test_without_dates_a_display_version_stays_uncertain():
    game = alan()
    game.dates = {}
    result = evaluate(game, "Alan_Wake_Remastered_Update_v1.0.3_NSW-VENOM", AFTER_LATEST)
    assert (result.score, result.is_latest) == (4, None)


def test_display_version_is_translated_once_seen_next_to_an_internal_one():
    vermap = {}
    evaluate(alan(), "Alan Wake Remastered v1.0.2 [0100623017A58800][v131072]", None, vermap)
    assert vermap == {"1.0.2": 131072}
    result = evaluate(alan(), "Alan_Wake_Remastered_Update_v1.0.2_NSW-VENOM", None, vermap)
    assert (result.score, result.internal_version, result.is_latest) == (5, 131072, False)


def test_title_id_alone_is_enough():
    result = evaluate(alan(), "aW5kZXhlcg [0100623017A58800][v196608]", None)
    assert (result.score, result.name_match) == (10, "tid")


@pytest.mark.parametrize("name, title", [
    ("Pokémon™ Scarlet", "Pokemon.Scarlet.Update.v65536.NSW-GRP"),
    ("Luigi's Mansion™ 3", "Luigis_Mansion_3_Update_v65536_NSW-X"),
    ("Mario + Rabbids® Kingdom Battle", "Mario Rabbids Kingdom Battle [v65536] (Update)"),
    ("The Legend of Zelda: Tears of the Kingdom", "The.Legend.of.Zelda.Tears.of.the.Kingdom.Update.v65536.NSW"),
    ("Ori & the Blind Forest", "Ori and the Blind Forest Update v65536"),
])
def test_names_with_signs_and_punctuation(name, title):
    game = Game(id="0100AAAA0000A000", name=name, local_version=0, latest_version=65536)
    result = evaluate(game, title)
    assert isinstance(result, Candidate) and result.score == 9, getattr(result, "reason", None)


@pytest.mark.parametrize("name, title", [
    ("Hades", "Hades II Update v65536"),
    ("Hades", "Hades Battle Out of Hell Update v65536"),
    ("Inside", "Inside the Backrooms Update v65536 NSW"),
    ("FIFA 22", "FIFA 23 Update v65536"),
    ("Limbo", "Out of Limbo Update v65536"),
])
def test_other_games_with_similar_names(name, title):
    game = Game(id="0100AAAA0000A000", name=name, local_version=0, latest_version=65536)
    assert isinstance(evaluate(game, title), Rejection)


def test_shortened_name_is_a_doubt_not_a_match():
    """A release that drops the end of a long name may be the same game: the user decides."""
    game = Game(id="0100AAAA0000A000", name="Mario Kart 8 Deluxe", local_version=0, latest_version=65536)
    result = evaluate(game, "Mario Kart 8 Update v65536")
    assert (result.score, result.name_match) == (4, "fuzzy")


def test_short_name_exact():
    game = Game(id="0100AAAA0000A000", name="Hades", local_version=0, latest_version=65536)
    assert evaluate(game, "Hades Update v65536 NSW-GRP").score == 9


def test_unknown_title_needs_a_title_id():
    game = Game(id="0100AAAA0000A000", name="", local_version=0, latest_version=65536)
    assert isinstance(evaluate(game, "Whatever Update v65536"), Rejection)
    assert evaluate(game, "Whatever [0100AAAA0000A800][v65536]").score == 10


DIABLO = "Diablo.II.Resurrected.Update.v1.0.35.0.incl.Offline.Crack.NSW-VENOM"


def diablo():
    """The user's real case: the library has 1.0.31.0 = update 31, the newest is update 35, and
    the databases list update 35 after the release was posted."""
    return Game(
        id="0100726014352000", name="Diablo® II: Resurrected™",
        local_version=31 * 65536, latest_version=35 * 65536, local_display="1.0.31.0",
        dates={31 * 65536: day("2026-03-01"), 33 * 65536: day("2026-06-01"),
               34 * 65536: day("2026-09-01"), 35 * 65536: day("2026-11-20")})


def test_version_that_counts_the_update():
    """1.0.31.0 is update 31, so 1.0.35.0 is update 35, whatever the dates say."""
    result = evaluate(diablo(), DIABLO, day("2026-11-12"))
    assert (result.estimated_version, result.is_latest, result.kind) == (35 * 65536, True, "update")
    assert result.score == 7  # 8 without the crack
    assert evaluate(diablo(), DIABLO.replace(".incl.Offline.Crack", ""), day("2026-11-12")).score == 8
    older = evaluate(diablo(), "Diablo.II.Resurrected.Update.v1.0.34.0.NSW-VENOM", day("2026-09-02"))
    assert (older.estimated_version, older.is_latest, older.score) == (34 * 65536, False, 4)


def test_pattern_needs_the_librarys_own_pair_to_show_it():
    game = diablo()
    game.local_display = "1.0.9.0"  # update 31 is not in this version: no pattern
    result = evaluate(game, DIABLO, day("2026-11-12"))
    assert result.estimated_version == 34 * 65536  # by date


def test_mark():
    assert matcher.mark("tid", 1.0, "update") == 10
    assert matcher.mark("fuzzy", 0.25, "bundle") == 1
    assert all(1 <= matcher.mark(i, c, k, crack) <= 10 for i in matcher.IDENTITY for k in matcher.KIND
               for c in (0.0, 0.3, 1.0) for crack in (True, False))


DLC = {"id": "0100623017A59001", "name": "Alan Wake Remastered - Bonus Pack"}


def test_dlc_by_title_id():
    result = evaluate(alan(), "Alan Wake Remastered [0100623017A59001][v0] DLC", want="dlc", dlc=DLC)
    assert result.score == 10
    other = evaluate(alan(), "Alan Wake Remastered [0100623017A59002][v0] DLC", want="dlc", dlc=DLC)
    assert isinstance(other, Rejection)


def test_dlc_by_name():
    named = evaluate(alan(), "Alan_Wake_Remastered_Bonus_Pack_DLC_NSW-GRP", want="dlc", dlc=DLC)
    assert named.score == 8
    # A release that names no DLC is a pack: listed once per game, not under each DLC.
    assert isinstance(evaluate(alan(), "Alan Wake Remastered DLC Pack NSW", want="dlc", dlc=DLC), Rejection)
    vague = evaluate(alan(), "Alan Wake Remastered DLC Pack NSW", want="dlcpack")
    assert (vague.score, vague.kind) == (5, "dlcpack")
    update = evaluate(alan(), "Alan_Wake_Remastered_Update_v1.0.3_NSW", want="dlc", dlc=DLC)
    assert isinstance(update, Rejection)


def test_search_term():
    assert matcher.search_term("Pokémon™ Scarlet: The Hidden Treasure") == "pokemon scarlet the hidden treasure"


def test_dlc_named_without_the_abbreviation_of_the_game():
    game = Game(id="01006560184E6000", name="Mortal Kombat™ 1")
    dlc = {"id": "01006560184E7005", "name": "MK1: MKII Movie Skins"}
    named = evaluate(game, "Mortal Kombat 1 MKII Movie Skins DLC NSW-VENOM", want="dlc", dlc=dlc)
    assert named.score == 8
    assert isinstance(evaluate(game, "Mortal Kombat 1 v1.28.0 DLC Unlocker NSW-VENOM-FTP", want="dlc", dlc=dlc),
                      Rejection)
    game.dlc = [dlc]
    pack = evaluate(game, "Mortal Kombat 1 v1.28.0 DLC Unlocker NSW-VENOM-FTP", want="dlcpack")
    assert pack.score == 5
    # A release that names a DLC is not a pack.
    assert isinstance(evaluate(game, "Mortal Kombat 1 MKII Movie Skins DLC NSW-VENOM", want="dlcpack"), Rejection)


def fc25():
    names = ["Dutch", "Spanish", "Latin American Spanish", "Brazilian Portuguese"]
    return Game(id="010054E01D878000", name="EA SPORTS FC™ 25", dlc=[
        {"id": f"010054E01D87900{n}", "name": f"EA SPORTS FC™ 25 In-Game Commentary - {name}"}
        for n, name in enumerate(names, 1)])


def fc25_release(language):
    return f"EA SPORTS FC 25 In-Game Commentary {language} DLC NSW-VENOM"


@pytest.mark.parametrize("wanted, release, score", [
    (0, "Dutch", 8),
    (1, "Spanish", 8),
    (2, "Latin American Spanish", 8),
    (3, "Brazilian Portuguese", 8),
    (0, "Spanish", None),                    # names another DLC
    (3, "Dutch", None),
    (1, "Latin American Spanish", None),     # "Spanish" is in it, but the other names it better
    (2, "Spanish", None),
    (0, "Japanese", None),                   # names none of the known DLCs: goes to the pack
])
def test_release_belongs_to_the_dlc_it_names_best(wanted, release, score):
    game = fc25()
    result = evaluate(game, fc25_release(release), want="dlc", dlc=game.dlc[wanted])
    assert getattr(result, "score", None) == score, getattr(result, "reason", None)


def test_same_release_whatever_the_separators():
    assert matcher.same_release("Diablo.II.Resurrected.Update.v1.0.35.0.incl.Offline.Crack.NSW-VENOM") == \
        matcher.same_release("Diablo II Resurrected Update v1.0.35.0 incl Offline Crack NSW-VENOM")
    assert matcher.same_release("Game Update v1.0.1 NSW-A") != matcher.same_release("Game Update v1.0.2 NSW-A")


def test_only_the_switch():
    """The user's real case: the Console category also holds PS4 releases of the same game."""
    game = Game(id="0100B04011742000", name="Monster Hunter Rise", dlc=[
        {"id": "0100B04011743001", "name": '"Morale Boost" gesture'}])
    ps4 = evaluate(game, "Monster.Hunter.Rise.v16.01.incl.DLC.PS4-CUSA34119", want="dlc", dlc=game.dlc[0])
    assert isinstance(ps4, Rejection) and "PS4" in ps4.reason
    assert matcher.observe(game, "Monster.Hunter.Rise.Update.v16.01.PS4-GRP") is None
    # A title ID is of the Switch whatever else the title says.
    assert evaluate(game, "Monster Hunter Rise [0100B04011743001][v0] DLC PS4 port", want="dlc",
                    dlc=game.dlc[0]).score == 10


def test_platform_word_in_the_games_own_name_is_not_a_platform():
    game = Game(id="0100AAAA0000A000", name="Wii Sports Club", local_version=0, latest_version=65536)
    assert evaluate(game, "Wii Sports Club Update v65536 NSW-GRP").score == 9


def test_title_without_any_platform_scores_lower():
    marked = evaluate(alan(), "Alan_Wake_Remastered_Update_v1.0.3_NSW-VENOM", AFTER_LATEST)
    bare = evaluate(alan(), "Alan Wake Remastered Update v1.0.3", AFTER_LATEST)
    assert (marked.score, bare.score) == (7, 6)
    assert "the title names no platform" in bare.reasons
    # An internal version number is a Switch thing: no doubt about the platform.
    assert evaluate(alan(), "Alan Wake Remastered Update v196608").score == 9


def test_rejection_says_whether_it_was_this_game():
    """Only releases of this game are shown as fallen off; the rest is simply not ours."""
    ours = evaluate(alan(), "Alan Wake Remastered [v65536] NSW", AFTER_LATEST)
    assert isinstance(ours, Rejection) and ours.known
    ps4 = evaluate(alan(), "Alan.Wake.Remastered.Update.v1.0.3.PS4-GRP", AFTER_LATEST)
    assert ps4.known and "PS4" in ps4.reason
    for title in ("Some Other Game Update v196608 NSW", "Alan Wake 2 Update v1.0.5",
                  "Alan Wake Remastered II Update v196608", "Alan Wake Remastered [0100AAAA00000800][v196608]"):
        other = evaluate(alan(), title, AFTER_LATEST)
        assert isinstance(other, Rejection) and not other.known, title


def sized(update_size=380_000_000, base_size=12_000_000_000):
    game = alan()
    game.update_size, game.base_size = update_size, base_size
    return game


@pytest.mark.parametrize("size, score, said", [
    (400_000_000, 9, None),                              # about the size of the update in the library
    (1_500_000_000, 9, None),                            # four times: still fine (compression, extra files)
    (2_400_000_000, 7, "the size is far from"),          # six times
    (30_000_000, 7, "the size is far from"),             # a twelfth
    (12_900_000_000, 7, "as big as the whole game"),     # the game itself is in it
    (0, 9, None),                                        # size unknown
])
def test_size_weighs_in(size, score, said):
    result = evaluate(sized(), "Alan.Wake.Remastered.Update.v196608.NSW-GRP", AFTER_LATEST, size=size)
    assert result.score == score
    about_size = [r for r in result.reasons if r.startswith(("the size is", "as big as"))]
    assert [r[:len(said)] for r in about_size] == ([said] if said else []), result.reasons


def test_size_says_nothing_without_an_update_in_the_library():
    result = evaluate(sized(update_size=0, base_size=0), "Alan.Wake.Remastered.Update.v196608.NSW-GRP", size=99_000_000_000)
    assert result.score == 9
