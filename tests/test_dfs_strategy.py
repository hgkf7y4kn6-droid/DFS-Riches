from types import SimpleNamespace

from app import dfs_strategy as ds
from app import lineup_builder
from app import usage


def _row(pid, name, pos, team, opp, salary, final, ceiling, *, pop="Low", injury="Healthy", opps=None, rush_yd=None,
         floor=None, game=None):
    game = game or ("A@B" if team in ("A", "B") else "C@D")
    line = {}
    if pos == "RB":
        line = {"rush_att": opps or 0, "rec_tgt": 3.0}
    elif pos in ("WR", "TE"):
        line = {"rec_tgt": opps or 0}
    elif pos == "QB":
        line = {"rush_yd": rush_yd or 0}
    return {"id": pid, "name": name, "position": pos, "team": team, "opponent": opp, "salary": salary, "game": game,
            "final": final, "ceiling": ceiling, "floor": floor if floor is not None else round(final * 0.45, 1),
            "value": round(final / (salary / 1000), 2), "popularity": pop, "ownership": None, "injury": injury,
            "uncertainty_label": "Medium", "uncertainty_reasons": [], "adjustments": [], "line": line, "dk_fppg": final,
            "n_sources": 4, "sd": 1.0, "consensus": final, "low": final - 1, "high": final + 1}


def _pool():
    rows, pid = [], 0

    def add(*a, **k):
        nonlocal pid
        pid += 1
        rows.append(_row(pid, *a, **k))

    for t, o in (("A", "B"), ("B", "A"), ("C", "D"), ("D", "C")):
        add(f"QB{t}", "QB", t, o, 6000 + (500 if t == "A" else 0), 20, 32, rush_yd=40 if t == "A" else 10)
        for i in range(3):
            add(f"RB{t}{i}", "RB", t, o, 6500 - 1500 * i, 15 - 3 * i, 28 - 5 * i, opps=20 - 6 * i)
            add(f"WR{t}{i}", "WR", t, o, 7000 - 1500 * i, 16 - 3 * i, 30 - 5 * i, opps=9 - 2 * i)
        add(f"TE{t}", "TE", t, o, 4000, 9, 18, opps=5)
        add(f"DST{t}", "DST", t, o, 3000, 7, 14)
    return rows


def _slate():
    ctx = lambda h_sp, total: SimpleNamespace(home_spread=h_sp, away_spread=-h_sp, total_line=total,  # noqa: E731
                                                home_implied_total=(total - h_sp) / 2, away_implied_total=(total + h_sp) / 2)
    return SimpleNamespace(games=[
        SimpleNamespace(away="A", home="B", kickoff_et="Sun 1:00", context=ctx(-2.5, 52.5)),
        SimpleNamespace(away="C", home="D", kickoff_et="Sun 1:00", context=ctx(-9.5, 40.5)),
    ])


def test_usage_summary_averages_rates_over_totals():
    games = [{"targets": 10, "air_yards": 100, "pass_att": None}, {"targets": 0, "air_yards": 0, "pass_att": None}]
    assert usage.summarize(games)["adot"] == 10.0 and usage.summarize(games)["targets"] == 5.0
    qb = usage.summarize([{"pass_att": 30, "pass_yds": 240, "pass_td": 3}, {"pass_att": 10, "pass_yds": 60, "pass_td": 1}])
    assert qb["ypa"] == 7.5 and qb["td_rate"] == 0.1


def test_game_analysis_flags_shootout_script_and_ranks_environment():
    pool = _pool()
    slate = _slate()
    ds.enrich(pool, pool, slate, {"players": {}, "teams": {}})
    games = ds.analyze_games(pool, slate, None, has_own=False)
    top, other = games
    assert top["game"] == "A@B" and top["env_rank"] == 1
    assert other["negative_script"] and "D favored by 9.5" in other["script"]
    assert not top["negative_script"]


def test_cheap_players_need_a_real_role():
    cheap_wr = _row(1, "Cheap", "WR", "A", "B", 3500, 7, 16, opps=2.0)
    ds.enrich([cheap_wr], [cheap_wr], _slate(), {})
    assert not ds.has_role(cheap_wr)
    cheap_wr["proj_opps"] = 6
    assert ds.has_role(cheap_wr)


def test_chalk_classification_and_failure_modes():
    pool = _pool()
    ds.enrich(pool, pool, _slate(), {})
    q = next(r for r in pool if r["name"] == "WRA0")
    q.update(popularity="High", injury="Q")
    cheap = next(r for r in pool if r["name"] == "RBC2")
    cheap.update(popularity="High", salary=3500, final=12, value=3.43)
    rows = ds.chalk_table(pool, {}, has_own=False)
    by_name = {r["name"]: r for r in rows}
    assert by_name["WRA0"]["classification"] == "Fragile chalk" and "Questionable" in by_name["WRA0"]["risk"]
    assert by_name["RBC2"]["classification"] == "Necessary / value chalk"


def test_builder_supports_force_exclude_naked_qb_and_one_rb_per_team():
    pool = _pool()
    ds.enrich(pool, pool, _slate(), {})
    vals = [r["ceiling"] for r in pool]
    qa = next(r for r in pool if r["name"] == "QBA")
    lu = lineup_builder.build(pool, vals, qb_ids={qa["id"]}, naked_qb=True, one_rb_per_team=True, min_salary=45000)
    assert lu[0]["name"] == "QBA"
    assert not any(p["team"] == "A" and p["position"] in ("WR", "TE") for p in lu)
    rb_teams = [p["team"] for p in lu if p["position"] == "RB"]
    assert len(rb_teams) == len(set(rb_teams))
    forced = next(r for r in pool if r["name"] == "TEC")
    lu2 = lineup_builder.build(pool, vals, force={forced["id"]}, at_least=[({forced["id"]}, 1)])
    assert forced in lu2


def test_full_run_builds_cash_and_gpp_with_audits():
    pool = _pool()
    result = ds.run(pool, pool, _slate(), None, {"players": {}, "teams": {}}, False, 2026, 3)
    L = result["lineups"]
    assert L["cash"] and L["cash"][0]["label"] == "Recommended cash lineup"
    assert all(p["injury"] != "Q" for p in L["cash"][0]["players"])
    assert L["gpp"], "at least one GPP construction should build"
    for lu in L["gpp"]:
        ev = lu["eval"]
        assert set(ev["audit"]) >= {"qb_stack", "bring_back", "te_strategy", "biggest_failure_point", "salary_remaining"}
        assert ev["salary"]["total"] <= 50000 and ev["salary"]["total"] >= ds.GPP_MIN_SALARY
        assert 0 <= ev["quality"] <= 100 and ev["win_scenario"]
        teams = [p["team"] for p in lu["players"] if p["position"] == "RB"]
        assert len(teams) == len(set(teams))
    assert any(m["item"] == "Player props" for m in result["missing_data"])
    assert any(m["item"] == "Ownership sources" for m in result["missing_data"])


def test_correlation_scores_stacks_and_penalizes_conflicts():
    pool = _pool()
    ds.enrich(pool, pool, _slate(), {})
    by = {r["name"]: r for r in pool}
    lu = [by[n] for n in ("QBA", "RBC0", "RBC1", "WRA0", "WRA1", "WRB0", "TED", "WRD0", "DSTB")]
    c = ds.correlation(lu)
    assert c["double_stack"] and c["game_stack"]
    assert any("Two C RBs" in n for n in c["negative"])
    assert any("faces your own players" in n for n in c["negative"])
