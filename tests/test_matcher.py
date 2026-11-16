"""Release names in every shape seen on usenet, held against one game."""
import datetime

import pytest

import matcher
from matcher import LIKELY, SURE, UNCERTAIN, Candidate, Game, Rejection, evaluate


def day(text):
    return datetime.date.fromisoformat(text)


def alan():
    return Game(
        id="0100623017A58000", name="Alan Wake Remastered",
        local_version=65536, latest_version=196608, local_display="1.0.1",
        dates={65536: day("2022-11-01"), 131072: day("2023-02-01"), 196608: day("2023-06-01")})


AFTER_LATEST = day("2023-06-05")


@pytest.mark.parametrize("title, confidence, kind, is_latest", [
    ("Alan Wake Remastered [0100623017A58800][v196608].nsz", SURE, "update", True),
    ("Alan Wake Remastered v196608 NSW", SURE, "unknown", True),
    ("[NSW] Alan Wake Remastered (Update v131072) (EUR)", SURE, "update", False),
    ("Alan.Wake.Remastered.Update.v196608.NSW-GRP", SURE, "update", True),
    ("alan wake remastered [0100623017a58800] [v131072] (upd)", SURE, "update", False),
    ("Alan_Wake_Remastered_Update_v1.0.3_NSW-VENOM", LIKELY, "update", True),
    ("Alan.Wake.Remastered.Update.v1.0.3.NSW-SUXXORS", LIKELY, "update", True),
    ("Alan Wake Remastered Update 1.0.3 [NSW]", LIKELY, "update", True),
    ("Alan Wake Remastered [NSP] [Base + Update 1.0.3 + DLC]", LIKELY, "bundle", True),
    ("Alan Wake Remastered Collectors Edition Update v196608", UNCERTAIN, "update", True),
    ("Alan Wake Remasterd Update v196608", UNCERTAIN, "update", True),
])
def test_candidates(title, confidence, kind, is_latest):
    result = evaluate(alan(), title, AFTER_LATEST)
    assert isinstance(result, Candidate), getattr(result, "reason", None)
    assert (result.confidence, result.kind, result.is_latest) == (confidence, kind, is_latest)


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
    "Control Ultimate Edition Update v1.0.3",
])
def test_rejections(title):
    assert isinstance(evaluate(alan(), title, AFTER_LATEST), Rejection)


def test_display_version_posted_before_latest_update_is_not_latest():
    result = evaluate(alan(), "Alan_Wake_Remastered_Update_v1.0.2_NSW-VENOM", day("2023-03-01"))
    assert (result.confidence, result.is_latest) == (UNCERTAIN, False)


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
    assert (result.confidence, result.estimated_version, result.is_latest) == (UNCERTAIN, 131072, None)


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
    assert (result.confidence, result.estimated_version, result.is_latest, result.deduced) == (
        SURE, 720896, True, True)
    assert isinstance(evaluate(naruto(), V170, day("2026-08-20"), seen=NARUTO_SEEN), Rejection)
    # The same without the other releases: the library's own pair is enough.
    assert evaluate(naruto(), V171, day("2026-09-30")).confidence == SURE


def test_ladder_without_the_librarys_display_version():
    """No 1.7.0 from the library: v1.7.0 is update 10 by its date, v1.7.1 the next by its place."""
    game = naruto(display=None)
    steps = matcher.ladder(game, NARUTO_SEEN)
    assert (steps["1.7.0"].version, steps["1.7.0"].how) == (655360, "date")
    assert (steps["1.7.1"].version, steps["1.7.1"].how, steps["1.7.1"].solid) == (720896, "order", False)
    result = evaluate(game, V171, day("2026-09-30"), seen=NARUTO_SEEN)
    assert (result.confidence, result.estimated_version, result.is_latest) == (LIKELY, 720896, True)
    assert isinstance(evaluate(game, V170, day("2026-08-20"), seen=NARUTO_SEEN), Rejection)


def test_ladder_alone_and_dated_late_is_a_doubt_not_a_rejection():
    """Only v1.7.1 seen, nothing from the library: by date it is update 10, but update 11 is
    listed only three weeks later, so it can be that one."""
    result = evaluate(naruto(display=None), V171, day("2026-09-30"))
    assert isinstance(result, Candidate) and (result.confidence, result.is_latest) == (UNCERTAIN, None)


def test_ladder_two_updates_behind():
    """Library at update 9: v1.7.0 is the update in between, v1.7.1 the newest."""
    game = naruto(local=589824, display="1.6.0")
    between = evaluate(game, V170, day("2026-08-20"), seen=NARUTO_SEEN)
    assert (between.estimated_version, between.is_latest) == (655360, False)
    newest = evaluate(game, V171, day("2026-09-30"), seen=NARUTO_SEEN)
    assert (newest.confidence, newest.estimated_version, newest.is_latest) == (LIKELY, 720896, True)


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
    assert (result.confidence, result.is_latest) == (UNCERTAIN, None)


def test_display_version_is_translated_once_seen_next_to_an_internal_one():
    vermap = {}
    evaluate(alan(), "Alan Wake Remastered v1.0.2 [0100623017A58800][v131072]", None, vermap)
    assert vermap == {"1.0.2": 131072}
    result = evaluate(alan(), "Alan_Wake_Remastered_Update_v1.0.2_NSW-VENOM", None, vermap)
    assert (result.confidence, result.internal_version, result.is_latest) == (SURE, 131072, False)


def test_title_id_alone_is_enough():
    result = evaluate(alan(), "aW5kZXhlcg [0100623017A58800][v196608]", None)
    assert (result.confidence, result.name_match) == (SURE, "tid")


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
    assert isinstance(result, Candidate) and result.confidence == SURE, getattr(result, "reason", None)


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
    assert (result.confidence, result.name_match) == (UNCERTAIN, "fuzzy")


def test_short_name_exact():
    game = Game(id="0100AAAA0000A000", name="Hades", local_version=0, latest_version=65536)
    assert evaluate(game, "Hades Update v65536 NSW-GRP").confidence == SURE


def test_unknown_title_needs_a_title_id():
    game = Game(id="0100AAAA0000A000", name="", local_version=0, latest_version=65536)
    assert isinstance(evaluate(game, "Whatever Update v65536"), Rejection)
    assert evaluate(game, "Whatever [0100AAAA0000A800][v65536]").confidence == SURE


def test_best_candidate_ranks_first():
    titles = [
        "Alan Wake Remastered Collectors Edition Update v196608",
        "Alan Wake Remastered [NSP] [Base + Update 1.0.3 + DLC]",
        "[NSW] Alan Wake Remastered (Update v131072) (EUR)",
        "Alan Wake Remastered [0100623017A58800][v196608].nsz",
        "Alan_Wake_Remastered_Update_v1.0.3_NSW-VENOM",
    ]
    ranked = sorted(titles, key=lambda t: evaluate(alan(), t, AFTER_LATEST).to_dict()["rank"], reverse=True)
    assert ranked[0] == "Alan Wake Remastered [0100623017A58800][v196608].nsz"
    assert ranked[1] == "[NSW] Alan Wake Remastered (Update v131072) (EUR)"
    assert ranked[-1] == "Alan Wake Remastered Collectors Edition Update v196608"


DLC = {"id": "0100623017A59001", "name": "Alan Wake Remastered - Bonus Pack"}


def test_dlc_by_title_id():
    result = evaluate(alan(), "Alan Wake Remastered [0100623017A59001][v0] DLC", want="dlc", dlc=DLC)
    assert result.confidence == SURE
    other = evaluate(alan(), "Alan Wake Remastered [0100623017A59002][v0] DLC", want="dlc", dlc=DLC)
    assert isinstance(other, Rejection)


def test_dlc_by_name():
    named = evaluate(alan(), "Alan_Wake_Remastered_Bonus_Pack_DLC_NSW-GRP", want="dlc", dlc=DLC)
    assert named.confidence == LIKELY
    vague = evaluate(alan(), "Alan Wake Remastered DLC Pack NSW", want="dlc", dlc=DLC)
    assert vague.confidence == UNCERTAIN
    update = evaluate(alan(), "Alan_Wake_Remastered_Update_v1.0.3_NSW", want="dlc", dlc=DLC)
    assert isinstance(update, Rejection)


def test_search_term():
    assert matcher.search_term("Pokémon™ Scarlet: The Hidden Treasure") == "pokemon scarlet the hidden treasure"
