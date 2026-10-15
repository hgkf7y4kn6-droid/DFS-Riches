from app import injury_news
from app.models import Player


def _p(name, salary, injury="Healthy", proj=0.0, season=None, slot=""):
    return Player(name=name, team="PHI", opponent="CAR", position="QB", roster_slot=slot, salary=salary,
                  proj_points=proj, value_per_1k=0.0, game_info="CAR @ PHI", injury=injury, trend_season=season)


def test_apply_news_only_overrides_healthy():
    hurts, other = _p("Jalen Hurts", 6100), _p("Someone Else", 5000, injury="Q")
    news = {("PHI", "jalen hurts"): {"code": "OUT", "status": "Out"}, ("PHI", "someone else"): {"code": "OUT", "status": "Out"}}
    injury_news.apply_news([hurts, other], news)
    assert hurts.injury == "OUT" and "ESPN lists him Out" in hurts.proj_notes[-1]
    assert other.injury == "Q"            # DraftKings' own designation stands


def test_replacement_is_highest_salaried_healthy_qb():
    hurts = _p("Jalen Hurts", 6100, injury="OUT", season=16.6)
    mckee, payton = _p("Tanner McKee", 4200), _p("Cole Payton", 4000)
    [(rows, starter)] = injury_news.replacement_qbs([hurts, mckee, payton])
    assert starter is hurts and [p.name for p in rows] == ["Tanner McKee"]


def test_no_replacement_once_sleeper_projects_one():
    hurts = _p("Jalen Hurts", 6100, injury="OUT", season=16.6)
    assert injury_news.replacement_qbs([hurts, _p("Tanner McKee", 4000, proj=9.8)]) == []
    assert injury_news.replacement_qbs([_p("Jalen Hurts", 6100, season=16.6), _p("Tanner McKee", 4000)]) == []


def test_replacement_covers_showdown_rows():
    rows = [_p("Jalen Hurts", 9150, injury="OUT", season=16.6, slot="CPT"), _p("Jalen Hurts", 6100, injury="OUT", season=16.6, slot="FLEX"),
            _p("Tanner McKee", 6000, slot="CPT"), _p("Tanner McKee", 4000, slot="FLEX")]
    [(got, _)] = injury_news.replacement_qbs(rows)
    assert sorted(p.roster_slot for p in got) == ["CPT", "FLEX"]
