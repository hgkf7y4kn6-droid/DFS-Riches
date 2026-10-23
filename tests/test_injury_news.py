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


def test_zero_out_players_who_wont_play():
    out, doubtful, q = _p("A", 6000, injury="OUT", proj=12.0), _p("B", 5000, injury="D", proj=8.0), _p("C", 4000, injury="Q", proj=9.0)
    out.ceiling, q.ceiling, out.value_per_1k = 20.0, 15.0, 2.0
    injury_news.zero_out([out, doubtful, q])
    assert (out.proj_points, out.ceiling, out.value_per_1k) == (0.0, 0.0, 0.0) and "zeroed (was 12.0)" in out.proj_notes[-1]
    assert doubtful.proj_points == 0.0
    assert (q.proj_points, q.ceiling) == (9.0, 15.0)


MODEL = {"with_practice": {"intercept": 0.8, "coef": {"dnp": -1.0, "fp": 1.15, "qb": -1.26, "star": 0.47}},
         "without_practice": {"intercept": 0.79, "coef": {"qb": -1.1, "star": 0.36}},
         "if_played": {"factor": 0.94}}


def test_practice_trend_reads_the_last_day():
    assert injury_news.practice_trend({"Wed": "DNP", "Thu": "LP", "Fri": "FP"}) == {
        "log": ["DNP", "LP", "FP"], "last": "FP", "trend": "up", "days_practiced": 2}
    assert injury_news.practice_trend({"Wed": "LP", "Thu": "DNP"})["trend"] == "down"
    assert injury_news.practice_trend({"Wed": "(-)"}) is None


def test_play_chance_rises_with_practice_and_falls_for_quarterbacks():
    dnp, lp, fp = (injury_news.play_chance(MODEL, "WR", d, 14.0) for d in ("DNP", "LP", "FP"))
    assert dnp < lp < fp
    assert injury_news.play_chance(MODEL, "QB", "LP", 14.0) < lp
    assert injury_news.play_chance(MODEL, "WR", "LP", 6.0) < lp                    # not an established scorer
    assert 0 < injury_news.play_chance(MODEL, "WR", None, 14.0) < 1                # no practice log: the no-practice fit


def _wr(name, injury="Q", proj=14.0, season=13.0):
    p = _p(name, 6000, injury=injury, proj=proj, season=season)
    p.position, p.ceiling = "WR", 25.0
    return p


def test_questionable_projection_scaled_by_chance_until_inactives():
    from datetime import datetime, timedelta, timezone
    now = datetime(2026, 10, 25, 15, 0, tzinfo=timezone.utc)
    reports = {"PHI": {"a b": {"name": "A B", "practice": {"Wed": "DNP", "Thu": "LP", "Fri": "FP"}, "game_status": "Questionable",
                               "game_status_raw": "QUESTIONABLE"}}}
    early = _wr("A B")
    injury_news.apply_play_chance([early], reports, {"PHI": now + timedelta(hours=3)}, now=now, model=MODEL)
    chance = injury_news.play_chance(MODEL, "WR", "FP", 13.0)
    assert early.play_chance == round(chance, 2) and early.practice == "Wed DNP · Thu LP · Fri FP"
    assert early.proj_points == round(14.0 * chance * 0.94, 2)
    assert early.ceiling == round(25.0 * 0.94, 1)                                   # his ceiling if he plays
    midweek = _wr("A B")
    reports_mid = {"PHI": {"a b": {**reports["PHI"]["a b"], "game_status": None, "game_status_raw": "UNSPECIFIED"}}}
    injury_news.apply_play_chance([midweek], reports_mid, {"PHI": now + timedelta(hours=3)}, now=now, model=MODEL)
    assert midweek.play_chance == round((chance + injury_news.play_chance(MODEL, "WR", None, 13.0)) / 2, 2)
    late = _wr("A B")
    injury_news.apply_play_chance([late], reports, {"PHI": now + timedelta(minutes=60)}, now=now, model=MODEL)
    assert late.play_chance == 1.0 and late.proj_points == round(14.0 * 0.94, 2)   # active: inactives are out


def test_no_discount_without_a_game_status_or_for_healthy_players():
    reports = {"PHI": {"a b": {"name": "A B", "practice": {"Fri": "FP"}, "game_status": None, "game_status_raw": "(-)"}}}
    q, healthy = _wr("A B"), _wr("C D", injury="Healthy")
    injury_news.apply_play_chance([q, healthy], reports, {}, model=MODEL)
    assert q.proj_points == 14.0 and q.play_chance is None
    assert healthy.proj_points == 14.0


def test_report_status_rules_out_players_draftkings_lists_healthy():
    reports = {"PHI": {"a b": {"name": "A B", "practice": {}, "game_status": "Doubtful", "game_status_raw": "DOUBTFUL"}}}
    p = _wr("A B", injury="Healthy")
    injury_news.apply_report_statuses([p], reports)
    assert p.injury == "D" and "lists him Doubtful" in p.proj_notes[-1]
