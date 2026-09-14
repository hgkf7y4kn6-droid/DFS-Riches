from app.matching import SleeperNameIndex, normalize_name


def test_normalize_strips_punctuation_and_suffixes():
    assert normalize_name("A.J. Brown") == "aj brown"
    assert normalize_name("Amon-Ra St. Brown") == "amon ra st brown"
    assert normalize_name("Michael Pittman Jr.") == "michael pittman"
    assert normalize_name("Odell Beckham III") == "odell beckham"
    assert normalize_name("  Josh   Allen ") == "josh allen"


def test_normalize_is_idempotent_on_already_clean_names():
    assert normalize_name("josh allen") == "josh allen"


SAMPLE_PLAYERS = {
    "1001": {"first_name": "Josh", "last_name": "Allen", "team": "BUF", "position": "QB"},
    "1002": {"first_name": "Josh", "last_name": "Allen", "team": "JAX", "position": "LB"},
    "1003": {"first_name": "A.J.", "last_name": "Brown", "team": "PHI", "position": "WR"},
    "1004": {"first_name": "Marquise", "last_name": "Brown", "team": "KC", "position": "WR"},
    "SEA": {"first_name": "", "last_name": "", "team": "SEA", "position": "DEF"},
}


def test_unique_name_matches_directly():
    index = SleeperNameIndex(SAMPLE_PLAYERS)
    assert index.find("A.J. Brown", "PHI", "WR") == "1003"


def test_ambiguous_name_disambiguated_by_team():
    index = SleeperNameIndex(SAMPLE_PLAYERS)
    assert index.find("Josh Allen", "BUF", "QB") == "1001"
    assert index.find("Josh Allen", "JAX", "LB") == "1002"


def test_alias_map_bridges_a_configured_nickname(monkeypatch):
    # The shipped data/name_aliases.json starts empty (see its _readme) since
    # guessed aliases have turned out wrong more often than right; this test
    # exercises the lookup mechanism itself with a fake alias, independent of
    # whatever's actually in that file.
    import app.matching as matching

    monkeypatch.setattr(matching, "load_aliases", lambda: {"hollywood brown": "marquise brown"})
    index = SleeperNameIndex(SAMPLE_PLAYERS)
    assert index.find("Hollywood Brown", "KC", "WR") == "1004"


def test_defense_matched_by_team_abbreviation():
    index = SleeperNameIndex(SAMPLE_PLAYERS)
    assert index.find("Seattle Seahawks", "SEA", "DST") == "SEA"


def test_unknown_player_returns_none():
    index = SleeperNameIndex(SAMPLE_PLAYERS)
    assert index.find("Nobody Fake", "ZZZ", "WR") is None
