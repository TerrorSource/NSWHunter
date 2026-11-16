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
