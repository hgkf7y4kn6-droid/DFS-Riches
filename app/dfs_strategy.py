"""The DFS lineup-construction framework: how the pieces fit together, not
just who projects best. Cash and GPP use different logic throughout.

Inputs are the DFS Model's player rows (consensus projection, floor,
ceiling, value, ownership or a labeled popularity estimate, uncertainty)
plus real context: Vegas lines, nflverse usage (targets, target share, air
yards share, carries, QB rushing), neutral tempo / pass rate, and each
source's projected stat line (carries, targets, TDs).

Steps (numbered as in the framework):
  1  Slate overview    game environments (total, spread, pace, pass rate,
                       ceiling), shootouts, negative scripts, favorites,
                       live underdogs, the games the field will like, and
                       leverage games where popularity lags the environment
  2-6 Position pools   QB, RB, WR, TE (pay-up vs punt) and DST, each with a
                       Cash and a GPP view and the evidence behind them
  7  Chalk             why the field will play him, how he fails, and a
                       classification (strong / fragile / overpriced / ...)
  8  Leverage          player-vs-player, same-team, salary, game, ownership
  9-10 Stacks          basic / double / full-game stacks; the bring-back
                       compares the opposing WR1 with WR2
  11-17 Lineups        Cash (floor, volume, stability) and GPP (ceiling,
                       correlation, leverage) built as integer programs,
                       each audited against the framework's checklists,
                       scored, and explained
  18 Output            fades by type, and what data is missing

Nothing here invents data: when ownership, props, snaps or routes aren't
connected, the output says so.
"""
from __future__ import annotations

import statistics

from app import lineup_builder
from app import nflverse_client as nc

SALARY_CAP = 50000
GPP_MIN_SALARY = 49000
CASH_MIN_SALARY = 48500
GPP_EXPOSURE_CAP = 6
TOURNAMENT_EXPOSURE_CAP = 8
Q_DISCOUNT = 0.90
WR_FLEX_BONUS = 0.5   # GPP: lean toward WRs for FLEX (ceiling + stacking flexibility)
POS = ("QB", "RB", "WR", "TE", "DST")
SLOTS = ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "DST"]
CHEAP = {"QB": 5200, "RB": 5000, "WR": 4200, "TE": 4000, "DST": 2800}
POP_WEIGHT = {"High": 1.0, "Medium": 0.4, "Low": 0.05}
LEVERAGE_CEILING_SHARE = 0.80   # a leverage alternative needs 80%+ of the chalk player's ceiling

MISSING_DATA = [
    ("Player props", "no props feed is connected"),
    ("Snap share and route participation", "not in nflverse's public box scores"),
    ("Targets per route run / yards per route run", "need route data"),
    ("Red-zone, end-zone and goal-line work", "not in the box-score feed"),
    ("Depth charts", "not connected; roles are read from projected carries/targets and recent usage"),
    ("Historical winning-lineup salary tendencies", "no contest-results data is connected"),
]


# ---------------------------------------------------------------- helpers
def _pct(values: list[float], v: float) -> float:
    """0..1 percentile, 1 = highest."""
    if len(values) <= 1:
        return 1.0
    return sum(1 for x in values if x < v) / (len(values) - 1)


def _z(values: list[float], v: float) -> float:
    if len(values) < 2:
        return 0.0
    sd = statistics.pstdev(values)
    return (v - statistics.fmean(values)) / sd if sd else 0.0


def has_role(r: dict) -> bool:
    """A cheap RB/WR/TE needs real projected opportunity -- never rostered just because he's cheap."""
    if r["position"] not in ("RB", "WR", "TE") or r["salary"] > CHEAP[r["position"]]:
        return True
    return (r.get("proj_opps") or 0) >= (10 if r["position"] == "RB" else 4.5)


def _q(r: dict) -> float:
    return Q_DISCOUNT if r["injury"] == "Q" else 1.0


def _num(v, d=1):
    return "-" if v is None else f"{v:.{d}f}"


def _pct_txt(v):
    return "-" if v is None else f"{v:.0%}"


def _own_txt(r: dict) -> str:
    if r.get("ownership") is not None:
        return f"{r['ownership']:.1f}%"
    return f"est. {r['popularity']}" if r.get("popularity") else "-"


def card(r: dict, **extra) -> dict:
    keys = ("id", "name", "position", "team", "opponent", "salary", "final", "floor", "ceiling", "value",
            "ownership", "popularity", "injury", "uncertainty_label", "n_sources")
    return {**{k: r.get(k) for k in keys}, **extra}


def _join(names: list[str]) -> str:
    names = list(names)
    return names[0] if len(names) == 1 else (", ".join(names[:-1]) + " and " + names[-1] if names else "")


def _spread_txt(spread: float | None) -> str:
    if spread is None:
        return "-"
    return "PK" if spread == 0 else f"{spread:+g}"


# ------------------------------------------------------------ enrichment
def team_context(slate) -> dict[str, dict]:
    ctx = {}
    for g in slate.games:
        c = g.context
        for team, opp, home in ((g.away, g.home, False), (g.home, g.away, True)):
            ctx[team] = {
                "game": f"{g.away}@{g.home}", "opponent": opp, "home": home,
                "implied": (c.home_implied_total if home else c.away_implied_total) if c else None,
                "opp_implied": (c.away_implied_total if home else c.home_implied_total) if c else None,
                "spread": (c.home_spread if home else c.away_spread) if c else None,
                "total": c.total_line if c else None,
            }
    return ctx


def enrich(pool: list[dict], rows: list[dict], slate, usage: dict) -> dict[str, dict]:
    """Adds game context, projected opportunity, recent usage and derived
    flags to every pool row. Returns the team context."""
    ctx = team_context(slate)
    out_by_team: dict[str, list[dict]] = {}
    for r in rows:
        if r["injury"] not in ("Healthy", "Q") and (r.get("dk_fppg") or 0) >= 8 and r["position"] != "DST":
            out_by_team.setdefault(r["team"], []).append(r)
    ceil_by_pos = {p: [x["ceiling"] for x in pool if x["position"] == p] for p in POS}
    final_by_pos = {p: [x["final"] for x in pool if x["position"] == p] for p in POS}
    for r in pool:
        t = ctx.get(r["team"], {})
        r.update({k: t.get(k) for k in ("implied", "opp_implied", "spread", "total", "home")})
        line = r.get("line") or {}
        r["proj_carries"] = line.get("rush_att")
        r["proj_targets"] = line.get("rec_tgt")
        r["proj_rec"] = line.get("rec")
        r["proj_rush_yd"] = line.get("rush_yd")
        catches = line.get("rec_tgt") if line.get("rec_tgt") is not None else line.get("rec")
        r["proj_opps"] = round((line.get("rush_att") or 0) + (catches or 0), 1) if r["position"] in ("RB", "WR", "TE") else None
        tds = (line.get("rush_td") or 0) + (line.get("rec_td") or 0)
        r["proj_tds"] = round(tds, 2)
        td_pts = 6 * tds + 4 * (line.get("pass_td") or 0)
        r["td_share"] = round(td_pts / r["final"], 2) if r["final"] and r["position"] != "DST" else None
        r["rush_share"] = (round(((line.get("rush_yd") or 0) * 0.1 + 6 * (line.get("rush_td") or 0)) / r["final"], 2)
                           if r["position"] == "QB" and r["final"] else None)
        r["usage"] = usage.get("players", {}).get(nc.player_key(r["name"], r["position"])) if r["position"] != "DST" else None
        r["concentration"] = (usage.get("teams", {}).get(r["team"]) or {}).get("concentration")
        r["floor_ratio"] = round(r["floor"] / r["final"], 2) if r["final"] else None
        r["ceiling_pct"] = _pct(ceil_by_pos[r["position"]], r["ceiling"])
        r["final_pct"] = _pct(final_by_pos[r["position"]], r["final"])
        r["matchup_factor"] = next((a["factor"] for a in r["adjustments"] if a["kind"] == "model"), 1.0)
        mates_out = [o for o in out_by_team.get(r["team"], []) if o["position"] == r["position"]
                     or (r["position"] in ("WR", "TE") and o["position"] in ("WR", "TE"))]
        r["injury_opportunity"] = [f"{o['name']} ({o['position']}, {o['injury']})" for o in mates_out]
        r["ceiling_path"] = r["position"] == "DST" or r["ceiling_pct"] >= 0.35 or r["ceiling"] >= 3.5 * r["salary"] / 1000
    return ctx


# ---------------------------------------------------------- 1. the slate
def game_script(g: dict) -> str:
    fav, dog = (g["home"], g["away"]) if (g["spread_home"] or 0) < 0 else (g["away"], g["home"])
    margin = abs(g["spread_home"] or 0)
    total = g["total"]
    if g["shootout"]:
        return f"Shootout path: {total:g} total with {fav} favored by just {margin:g} -- both offenses need to keep scoring"
    if margin >= 6.5:
        return (f"{fav} favored by {margin:g}: if {fav} leads, its run game closes it out and {dog} "
                f"throws from behind -- volume for {dog}'s pass catchers, carries for {fav}'s backs")
    if total is None:
        return "No Vegas line yet"
    return f"Competitive: {total:g} total, {fav} by {margin:g}"


def analyze_games(pool: list[dict], slate, wd, has_own: bool) -> list[dict]:
    games = []
    for g in slate.games:
        c = g.context
        players = [r for r in pool if r["team"] in (g.away, g.home)]
        top = sorted(players, key=lambda r: -r["ceiling"])[:10]
        tempo = {t: (wd.ranks.get("neutral_secs", {}).get(t) if wd else None) for t in (g.away, g.home)}
        passr = {t: (wd.pass_rate_rank.get(t) if wd else None) for t in (g.away, g.home)}
        if has_own:
            pop = sum(r["ownership"] or 0 for r in players)
        else:
            pop = sum(POP_WEIGHT.get(r.get("popularity"), 0) for r in players)
        games.append({
            "game": f"{g.away}@{g.home}", "away": g.away, "home": g.home, "kickoff": g.kickoff_et,
            "total": c.total_line if c else None, "spread_home": c.home_spread if c else None,
            "away_implied": c.away_implied_total if c else None, "home_implied": c.home_implied_total if c else None,
            "tempo_ranks": tempo, "pass_rate_ranks": passr,
            "top10_final": round(sum(r["final"] for r in sorted(players, key=lambda r: -r["final"])[:10]), 1),
            "top10_ceiling": round(sum(r["ceiling"] for r in top), 1), "pop_raw": pop,
        })
    if not games:
        return []
    totals = [x["total"] or 0 for x in games]
    closeness = [-abs(x["spread_home"] or 0) for x in games]
    ceils = [x["top10_ceiling"] for x in games]
    pace = [-statistics.fmean([r or 16 for r in x["tempo_ranks"].values()]) for x in games]
    passing = [-statistics.fmean([r or 16 for r in x["pass_rate_ranks"].values()]) for x in games]
    pop_total = sum(x["pop_raw"] for x in games) or 1
    med_total = statistics.median(totals)
    for i, x in enumerate(games):
        parts = {"total": 0.40 * _z(totals, totals[i]), "closeness": 0.20 * _z(closeness, closeness[i]),
                 "ceiling": 0.20 * _z(ceils, ceils[i]), "pace": 0.10 * _z(pace, pace[i]),
                 "pass_rate": 0.10 * _z(passing, passing[i])}
        x["env_score"] = round(sum(parts.values()), 2)
        x["env_parts"] = {k: round(v, 2) for k, v in parts.items()}
        x["pop_share"] = round(x["pop_raw"] / pop_total, 3)
        margin = abs(x["spread_home"] or 0)
        x["shootout"] = bool(x["total"] and x["total"] >= med_total + 1.5 and margin <= 4.5)
        x["negative_script"] = margin >= 6.5
        fav, dog = (x["home"], x["away"]) if (x["spread_home"] or 0) < 0 else (x["away"], x["home"])
        x["favorite"], x["underdog"] = fav, dog
        dog_imp = x["home_implied"] if dog == x["home"] else x["away_implied"]
        x["live_dog"] = bool(margin >= 3 and dog_imp is not None and dog_imp >= 21.5)
        x["script"] = game_script(x)
    games.sort(key=lambda x: -x["env_score"])
    by_pop = sorted(games, key=lambda x: -x["pop_share"])
    env_rank = {x["game"]: i + 1 for i, x in enumerate(games)}
    pop_rank = {x["game"]: i + 1 for i, x in enumerate(by_pop)}
    n = len(games)
    for x in games:
        x["env_rank"], x["pop_rank"] = env_rank[x["game"]], pop_rank[x["game"]]
        x["popular"] = x["pop_rank"] <= max(2, n // 5)
        x["leverage_game"] = x["env_rank"] <= (n + 1) // 2 and x["pop_rank"] > (n + 1) // 2
        gap = x["pop_rank"] - x["env_rank"]
        if gap >= 3:
            x["ownership_vs_quality"] = f"Under-owned for its environment (#{x['env_rank']} environment, #{x['pop_rank']} in popularity)"
        elif gap <= -3:
            x["ownership_vs_quality"] = f"Popularity outruns the environment (#{x['pop_rank']} in popularity, #{x['env_rank']} environment)"
        else:
            x["ownership_vs_quality"] = f"Popularity roughly matches the environment (#{x['env_rank']} env, #{x['pop_rank']} popularity)"
    return games


def slate_overview(games: list[dict], pool: list[dict], ctx: dict, rows: list[dict], pools: dict, chalk_rows: list[dict],
                   leverage: dict, has_own: bool) -> dict:
    teams = sorted(((t, c) for t, c in ctx.items() if c.get("implied") is not None), key=lambda tc: -tc[1]["implied"])
    injuries = []
    for r in rows:
        if r["injury"] in ("Healthy",) or r["position"] == "DST" or (r.get("dk_fppg") or 0) < 8:
            continue
        benefit = [p for p in pool if p["team"] == r["team"] and p.get("injury_opportunity")
                   and any(r["name"] in s for s in p["injury_opportunity"])]
        injuries.append({"player": r["name"], "team": r["team"], "position": r["position"], "status": r["injury"],
                         "season_fppg": r["dk_fppg"],
                         "impact": [card(p, reason=f"{_num(p['final'])} proj at ${p['salary']:,}") for p in
                                    sorted(benefit, key=lambda p: -p["final"])[:3]]})
    injuries.sort(key=lambda i: (i["status"] == "Q", -i["season_fppg"]))
    cheap_roles = [card(p, reason=f"Role change: {', '.join(p['injury_opportunity'])} out; {_num(p['final'])} proj"
                                  + (f", {p['proj_opps']:.1f} projected opportunities" if p.get("proj_opps") else ""))
                   for p in sorted(pool, key=lambda p: -p["value"])
                   if p.get("injury_opportunity") and p["salary"] <= CHEAP[p["position"]] + 800 and p["final"] >= 6][:6]
    return {
        "top_implied": [{"team": t, "implied": c["implied"], "opponent": c["opponent"], "spread": c["spread"]} for t, c in teams[:6]],
        "top_totals": [{"game": g["game"], "total": g["total"]} for g in sorted(games, key=lambda g: -(g["total"] or 0))[:5]],
        "shootouts": [g["game"] for g in games if g["shootout"]],
        "negative_scripts": [{"game": g["game"], "script": g["script"]} for g in games if g["negative_script"]],
        "heavy_favorites": [{"team": t, "spread": c["spread"], "opponent": c["opponent"]} for t, c in ctx.items()
                            if c.get("spread") is not None and c["spread"] <= -6.5],
        "live_underdogs": [{"team": g["underdog"], "game": g["game"],
                            "implied": g["home_implied"] if g["underdog"] == g["home"] else g["away_implied"]}
                           for g in games if g["live_dog"]],
        "popular_games": [{"game": g["game"], "share": g["pop_share"], "note": g["ownership_vs_quality"]} for g in games if g["popular"]],
        "leverage_games": [{"game": g["game"], "share": g["pop_share"], "note": g["ownership_vs_quality"]} for g in games if g["leverage_game"]],
        "injuries": injuries[:8],
        "cheap_role_changes": cheap_roles,
        "chalk": [c for c in chalk_rows[:8]],
        "leverage": leverage["ownership"][:6],
        "low_owned_ceiling": leverage["ownership"][:6],
        "salary_savers": pools["salary_savers"],
        "best_qb": pools["QB"]["gpp"][:3],
        "best_rb": pools["RB"]["cash"][:3],
        "best_wr_teams": pools["wr_environments"],
        "te_approach": pools["TE"]["recommendation"],
        "popularity_note": "user-provided ownership" if has_own else "popularity estimate (no ownership data connected)",
    }


# ------------------------------------------------------- 2-6. pools
def _usage_txt(r: dict) -> dict:
    u = r.get("usage") or {}
    return {"targets_l4": u.get("targets"), "target_share": u.get("target_share"), "air_yards_share": u.get("air_yards_share"),
            "adot": u.get("adot"), "carries_l4": u.get("carries"), "carry_share": u.get("carry_share"),
            "games": u.get("games"), "this_season_games": u.get("this_season_games")}


def qb_pool(pool: list[dict], games_by_team: dict) -> dict:
    qbs = [r for r in pool if r["position"] == "QB"]
    out = []
    for r in qbs:
        mates = sorted([m for m in pool if m["team"] == r["team"] and m["position"] in ("WR", "TE") and m["ceiling_path"]],
                       key=lambda m: -m["ceiling"])
        rush_yd = r.get("proj_rush_yd") or 0
        rush_bonus = min(4.0, rush_yd / 10)
        stack_q = statistics.fmean([m["ceiling"] for m in mates[:2]]) if mates else 0
        u = r.get("usage") or {}
        g = games_by_team.get(r["team"], {})
        r["gpp_qb_score"] = round(r["ceiling"] * _q(r) + rush_bonus + 0.15 * stack_q + 0.5 * (g.get("env_score") or 0), 2)
        r["cash_qb_score"] = round((r["final"] + 0.5 * r["floor"]) * _q(r) - (2 if r.get("uncertainty_label") == "High" else 0), 2)
        reasons = []
        if rush_yd >= 25:
            reasons.append(f"Rushing path: {rush_yd:.0f} projected rush yds ({_pct_txt(r.get('rush_share'))} of his projection)")
        if r.get("implied"):
            reasons.append(f"{r['team']} implied {r['implied']:g} ({_spread_txt(r.get('spread'))}), game total {r.get('total') or '-'}")
        if r.get("concentration") and r["concentration"] >= 0.45:
            reasons.append(f"Concentrated targets: top two take {r['concentration']:.0%} of {r['team']}'s targets -- easy to stack")
        if u.get("ypa") and u["ypa"] >= 7.8:
            reasons.append(f"Efficient: {u['ypa']:.1f} yds/att, {_pct_txt(u.get('td_rate'))} TD rate (last {u.get('games')} games)")
        if r["ceiling"] >= 30:
            reasons.append(f"Ceiling {r['ceiling']:.1f} can anchor a first-place lineup")
        metrics = {"proj_rush_yd": round(rush_yd, 1), "rush_share": r.get("rush_share"), "ypa": u.get("ypa"),
                   "td_rate": u.get("td_rate"), "pass_att_l4": u.get("pass_att"), "implied": r.get("implied"),
                   "spread": r.get("spread"), "total": r.get("total"), "concentration": r.get("concentration"),
                   "stack_partners": [f"{m['name']} ({m['ceiling']:.1f})" for m in mates[:3]],
                   "double_stack": len(mates) >= 2, "script": g.get("script")}
        out.append((r, metrics, reasons))
    gpp = sorted(out, key=lambda x: -x[0]["gpp_qb_score"])[:4]
    cash = sorted(out, key=lambda x: -x[0]["cash_qb_score"])[:3]
    naked = [x for x in out if (x[0].get("rush_share") or 0) >= 0.25 and x[0]["ceiling_pct"] >= 0.5]
    fmt = lambda xs, key: [card(r, metrics=m, reasons=rs, score=r[key]) for r, m, rs in xs]  # noqa: E731
    return {"gpp": fmt(gpp, "gpp_qb_score"), "cash": fmt(cash, "cash_qb_score"),
            "naked_candidates": fmt(sorted(naked, key=lambda x: -x[0]["gpp_qb_score"])[:2], "gpp_qb_score")}


def rb_pool(pool: list[dict]) -> dict:
    rbs = [r for r in pool if r["position"] == "RB"]
    out = []
    for r in rbs:
        u = r.get("usage") or {}
        opps = r.get("proj_opps") or 0
        workhorse = (u.get("carry_share") or 0) >= 0.6 or (r.get("proj_carries") or 0) >= 16
        receiving = (u.get("target_share") or 0) >= 0.12 or (r.get("proj_targets") or r.get("proj_rec") or 0) >= 3.5
        spread = r.get("spread") or 0
        cash = (r["floor"] + r["final"] + 0.35 * opps + (2 if workhorse else 0) + (1.5 if receiving else 0)
                - (1.5 if spread >= 6.5 else 0) + (1 if spread <= -3 else 0))
        if r["salary"] <= CHEAP["RB"] and opps < 12:
            cash -= 6          # cheap without volume: not a cash play
        if r["injury"] == "Q":
            cash -= 4
        gpp = r["ceiling"] * _q(r) + 0.15 * opps + 3 * (r.get("proj_tds") or 0) + (1 if spread <= -3 else 0)
        r["cash_rb_score"], r["gpp_rb_score"] = round(cash, 2), round(gpp, 2)
        reasons = []
        if workhorse:
            reasons.append(f"Workhorse: {_num(r.get('proj_carries'))} projected carries, {_pct_txt(u.get('carry_share'))} carry share recently")
        if receiving:
            reasons.append(f"Receiving role: {_num(r.get('proj_targets') or r.get('proj_rec'))} projected targets, {_pct_txt(u.get('target_share'))} target share")
        if r.get("injury_opportunity"):
            reasons.append(f"Injury-driven work: {', '.join(r['injury_opportunity'])}")
        if spread <= -3:
            reasons.append(f"Favored by {abs(spread):g}: positive script for carries")
        elif spread >= 6.5:
            reasons.append(f"{spread:g}-point underdog: script can cut into carries")
        if (r.get("proj_tds") or 0) >= 0.6:
            reasons.append(f"TD equity: {r['proj_tds']:.2f} projected TDs, team implied {r.get('implied') or '-'}")
        metrics = {"proj_carries": r.get("proj_carries"), "proj_targets": r.get("proj_targets"), "proj_rec": r.get("proj_rec"),
                   "proj_opps": opps, "proj_tds": r.get("proj_tds"), **_usage_txt(r), "implied": r.get("implied"),
                   "spread": r.get("spread"), "home": r.get("home"), "matchup": r.get("matchup_factor"),
                   "workhorse": workhorse, "receiving_role": receiving}
        out.append((r, metrics, reasons, workhorse, receiving))
    cash = [x for x in sorted(out, key=lambda x: -x[0]["cash_rb_score"]) if x[0]["injury"] != "Q"][:5]
    gpp = sorted(out, key=lambda x: -x[0]["gpp_rb_score"])[:5]
    fmt = lambda xs, key: [card(r, metrics=m, reasons=rs, score=r[key]) for r, m, rs, *_ in xs]  # noqa: E731
    return {"cash": fmt(cash, "cash_rb_score"), "gpp": fmt(gpp, "gpp_rb_score")}


def wr_pool(pool: list[dict], wd) -> dict:
    wrs = [r for r in pool if r["position"] == "WR"]
    out = []
    for r in wrs:
        u = r.get("usage") or {}
        tgts = r.get("proj_targets") or r.get("proj_rec") or 0
        ts = u.get("target_share") or 0
        ays = u.get("air_yards_share") or 0
        cash = r["floor"] + r["final"] + 0.5 * tgts + 10 * ts - (4 if r["injury"] == "Q" else 0)
        if r["salary"] <= CHEAP["WR"] and tgts < 5:
            cash -= 5
        gpp = r["ceiling"] * _q(r) + 8 * ays + 0.2 * tgts
        r["cash_wr_score"], r["gpp_wr_score"] = round(cash, 2), round(gpp, 2)
        reasons = []
        if ts >= 0.22 or tgts >= 7:
            reasons.append(f"Target volume: {_num(tgts)} projected targets, {_pct_txt(ts)} target share recently")
        if ays >= 0.30:
            reasons.append(f"Air yards: {_pct_txt(ays)} of team air yards, aDOT {_num(u.get('adot'))} -- big-play path")
        if r.get("injury_opportunity"):
            reasons.append(f"Injury-driven targets: {', '.join(r['injury_opportunity'])}")
        if r.get("implied") and r["implied"] >= 24:
            reasons.append(f"{r['team']} implied {r['implied']:g}")
        pr = wd.pass_rate_rank.get(r["team"]) if wd else None
        if pr and pr <= 10:
            reasons.append(f"Pass-leaning offense (#{pr} neutral pass rate)")
        metrics = {"proj_targets": r.get("proj_targets"), "proj_rec": r.get("proj_rec"), **_usage_txt(r),
                   "pass_rate_rank": pr, "implied": r.get("implied"), "total": r.get("total")}
        out.append((r, metrics, reasons))
    cash = [x for x in sorted(out, key=lambda x: -x[0]["cash_wr_score"]) if x[0]["injury"] != "Q"][:5]
    gpp = sorted(out, key=lambda x: -x[0]["gpp_wr_score"])[:10]
    fmt = lambda xs, key: [card(r, metrics=m, reasons=rs, score=r[key]) for r, m, rs in xs]  # noqa: E731
    return {"cash": fmt(cash, "cash_wr_score"), "gpp": fmt(gpp, "gpp_wr_score")}


def wr_environments(pool: list[dict], wd) -> list[dict]:
    teams: dict[str, dict] = {}
    for r in pool:
        if r["position"] in ("WR", "TE"):
            t = teams.setdefault(r["team"], {"team": r["team"], "implied": r.get("implied"), "concentration": r.get("concentration"),
                                             "pass_rate_rank": wd.pass_rate_rank.get(r["team"]) if wd else None, "ceiling": 0.0})
            t["ceiling"] += r["ceiling"] if r["ceiling_path"] else 0
    ranked = sorted(teams.values(), key=lambda t: -((t["implied"] or 20) + 0.1 * t["ceiling"] - 0.1 * (t["pass_rate_rank"] or 16)))
    return [{**t, "ceiling": round(t["ceiling"], 1)} for t in ranked[:5]]


def te_analysis(pool: list[dict]) -> dict:
    tes = [r for r in pool if r["position"] == "TE"]
    by_ceiling = sorted(tes, key=lambda r: -r["ceiling"])
    top3 = {r["id"] for r in by_ceiling[:3]}
    pay, punt, mid_fades = [], [], []
    for r in tes:
        u = r.get("usage") or {}
        tgts = r.get("proj_targets") or r.get("proj_rec") or 0
        ts = u.get("target_share") or 0
        if r["salary"] >= 5500 and (ts >= 0.20 or r["id"] in top3):
            pay.append(card(r, reasons=[f"{_pct_txt(ts)} target share, {_num(tgts)} projected targets",
                                        f"Ceiling {r['ceiling']:.1f} (#{1 + by_ceiling.index(r)} TE)",
                                        f"{r['team']} implied {r.get('implied') or '-'}"],
                            edge=round(r["ceiling"] - 3.5 * r["salary"] / 1000, 1)))
        elif r["salary"] <= 4000 and (tgts >= 3.5 or ts >= 0.12):
            punt.append(card(r, reasons=[f"{_num(tgts)} projected targets, {_pct_txt(ts)} target share",
                                         f"{r['team']} implied {r.get('implied') or '-'}", f"Saves ${5500 - r['salary']:,} vs a pay-up TE"],
                             edge=round(r["ceiling"] - 3.5 * r["salary"] / 1000, 1)))
        elif 4000 < r["salary"] < 5500 and r.get("popularity") == "High" and r["id"] not in top3:
            mid_fades.append(card(r, reason=f"Popular mid-range TE without a top-3 ceiling ({r['ceiling']:.1f}) -- GPP fade candidate"))
    pay.sort(key=lambda c: -c["edge"])
    punt.sort(key=lambda c: -c["edge"])
    if pay and punt:
        rec = ("Pay up" if pay[0]["edge"] >= punt[0]["edge"] else "Punt")
        why = (f"Best pay-up option {pay[0]['name']} (ceiling edge {pay[0]['edge']:+.1f}) vs best punt {punt[0]['name']} "
               f"(edge {punt[0]['edge']:+.1f}); edge = ceiling minus 3.5x salary")
    elif pay:
        rec, why = "Pay up", "No cheap TE with a real target role this week"
    elif punt:
        rec, why = "Punt", "No elite TE worth the salary this week"
    else:
        rec, why = "Neither", "No elite TE and no cheap TE with a real target role"
    return {"pay_up": pay[:3], "punt": punt[:3], "mid_fades": mid_fades[:3],
            "recommendation": {"strategy": rec, "why": why}, "cash_ids": [c["id"] for c in pay[:2] + punt[:3]]}


def dst_pool(pool: list[dict], wd, season: int, week: int) -> list[dict]:
    out = []
    for r in pool:
        if r["position"] != "DST":
            continue
        line = r.get("line") or {}
        opp = r["opponent"]
        opp_sacks = nc.team_trailing(wd.index, opp, "sacks_taken", season, week, 8) if wd else None
        opp_give = nc.team_trailing(wd.index, opp, "giveaways", season, week, 8) if wd else None
        score = (r["final"] + 0.5 * (line.get("sack") or 0) + (line.get("int") or 0) + (line.get("fum_rec") or 0)
                 - 0.15 * ((r.get("opp_implied") or 21) - 21) - 0.1 * (r.get("spread") or 0))
        reasons = []
        if r.get("opp_implied") is not None and r["opp_implied"] <= 19:
            reasons.append(f"{opp} implied for just {r['opp_implied']:g}")
        if (r.get("spread") or 0) <= -3:
            reasons.append(f"Favored by {abs(r['spread']):g}: {opp} likely chasing, more dropbacks for sacks/turnovers")
        if opp_sacks and wd and wd.league_sacks and opp_sacks >= wd.league_sacks * 1.1:
            reasons.append(f"{opp} takes {opp_sacks:.1f} sacks/gm (league {wd.league_sacks:.1f})")
        if opp_give and wd and wd.league_giveaways and opp_give >= wd.league_giveaways * 1.15:
            reasons.append(f"{opp} gives it away {opp_give:.1f} times/gm")
        if r.get("home"):
            reasons.append("Home")
        out.append(card(r, reasons=reasons or ["Projection only; no standout script edge"], score=round(score, 2),
                        metrics={"proj_sacks": line.get("sack"), "proj_takeaways": round((line.get("int") or 0) + (line.get("fum_rec") or 0), 2),
                                 "opp_implied": r.get("opp_implied"), "spread": r.get("spread"), "home": r.get("home"),
                                 "opp_sacks_taken": round(opp_sacks, 2) if opp_sacks else None,
                                 "opp_giveaways": round(opp_give, 2) if opp_give else None}))
    return sorted(out, key=lambda c: -c["score"])[:5]


def salary_savers(pool: list[dict]) -> list[dict]:
    out = []
    for r in sorted(pool, key=lambda r: -r["value"]):
        if r["salary"] > CHEAP[r["position"]] or r["final"] < (4 if r["position"] == "DST" else 6):
            continue
        opps = r.get("proj_opps")
        if r["position"] in ("RB", "WR", "TE") and (opps or 0) < (10 if r["position"] == "RB" else 4.5):
            continue    # cheap without a real role is not a salary saver
        why = f"${r['salary']:,} for {r['final']:.1f} proj ({r['value']:.2f}/$1k)"
        if opps:
            why += f", {opps:.1f} projected opportunities"
        if r.get("injury_opportunity"):
            why += f"; role up with {', '.join(r['injury_opportunity'])} out"
        out.append(card(r, reason=why))
        if len(out) >= 8:
            break
    return out


# ------------------------------------------------------------ 7. chalk
def chalk_table(pool: list[dict], games_by_team: dict, has_own: bool) -> list[dict]:
    if has_own:
        chalk = [r for r in pool if (r.get("ownership") or 0) >= 15]
    else:
        chalk = [r for r in pool if r.get("popularity") == "High"]
    pos_value_med = {p: statistics.median([x["value"] for x in pool if x["position"] == p] or [1]) for p in POS}
    rows = []
    for r in sorted(chalk, key=lambda r: -(r.get("ownership") or r.get("pop_score") or 0)):
        why, fail = [], []
        vrank = 1 + sum(1 for x in pool if x["position"] == r["position"] and x["value"] > r["value"])
        frank = 1 + sum(1 for x in pool if x["position"] == r["position"] and x["final"] > r["final"])
        if vrank <= 3:
            why.append(f"#{vrank} value at {r['position']} ({r['value']:.2f}/$1k)")
        if frank <= 3:
            why.append(f"#{frank} projection at {r['position']}")
        if r["salary"] <= CHEAP[r["position"]]:
            why.append("cheap salary")
        if r.get("injury_opportunity"):
            why.append(f"injury opportunity ({', '.join(r['injury_opportunity'])})")
        g = games_by_team.get(r["team"], {})
        if g.get("env_rank") and g["env_rank"] <= 2:
            why.append(f"top-{g['env_rank']} game environment")
        if r["injury"] == "Q":
            fail.append("Questionable -- may sit or be limited")
        if r.get("sd") and r.get("consensus") and r["sd"] / r["consensus"] >= 0.2:
            fail.append(f"sources disagree ({_num(r.get('low'))}-{_num(r.get('high'))})")
        if (r.get("td_share") or 0) >= 0.4:
            fail.append(f"TD-dependent ({r['td_share']:.0%} of his projection is touchdowns)")
        if r["position"] == "RB" and (r.get("spread") or 0) >= 6.5:
            fail.append(f"{r['spread']:g}-point underdog: negative script for carries")
        if r["position"] == "RB" and ((r.get("usage") or {}).get("carry_share") or 1) < 0.55:
            fail.append(f"shares the backfield ({_pct_txt((r.get('usage') or {}).get('carry_share'))} carry share)")
        if (r.get("floor_ratio") or 1) < 0.35:
            fail.append(f"low floor ({_num(r['floor'])})")
        if r.get("injury_opportunity") and ((r.get("usage") or {}).get("this_season_games") or 0) < 2:
            fail.append("new role, small sample")
        if r.get("matchup_factor", 1) < 1:
            fail.append("defense has held this position under projection")
        fail = fail or ["Needs his usual role to hold; nothing specific flagged"]
        cheap_value = r["salary"] <= CHEAP[r["position"]] and vrank <= 3
        if cheap_value:
            cls = "Necessary / value chalk"
        elif r["injury"] == "Q" or len(fail) >= 2 and fail[0] != "Needs his usual role to hold; nothing specific flagged":
            cls = "Fragile chalk"
        elif r["value"] < pos_value_med[r["position"]]:
            cls = "Overpriced chalk"
        elif (r.get("floor_ratio") or 0) >= 0.5 and r["ceiling_pct"] < 0.6:
            cls = "Cash chalk, GPP fade"
        elif g.get("pop_rank") and g.get("env_rank") and g["pop_rank"] > g["env_rank"]:
            cls = "Chalk usable in a leverage stack"
        else:
            cls = "Strong chalk"
        r["chalk_class"] = cls
        rows.append(card(r, why_popular="; ".join(why) or "Projection and salary line up", risk="; ".join(fail),
                         classification=cls, own=_own_txt(r)))
    return rows


# ---------------------------------------------------------- 8. leverage
def leverage_analysis(pool: list[dict], games: list[dict], has_own: bool) -> dict:
    def pop(r):
        return r.get("ownership") if has_own and r.get("ownership") is not None else POP_WEIGHT.get(r.get("popularity"), 0) * 30

    chalk = [r for r in pool if (r.get("chalk_class") or "")]
    pvp, same_team, salary = [], [], []
    for c in chalk:
        for o in pool:
            if (o is c or o["position"] != c["position"] or pop(o) >= pop(c) * 0.6 or not o["ceiling_path"]
                    or o["injury"] == "Q" or not has_role(o)):
                continue
            if c["position"] == "RB" and o["game"] == c["game"] and o["ceiling"] >= LEVERAGE_CEILING_SHARE * c["ceiling"]:
                pvp.append(card(o, reason=f"Instead of chalk {c['name']} (same game): ceiling {o['ceiling']:.1f} vs {c['ceiling']:.1f} "
                                          f"at {_own_txt(o)} vs {_own_txt(c)}"))
            if c["salary"] >= 6500 and o["salary"] <= c["salary"] - 1500 and o["ceiling"] >= LEVERAGE_CEILING_SHARE * c["ceiling"]:
                salary.append(card(o, reason=f"${c['salary'] - o['salary']:,} cheaper than chalk {c['name']} with "
                                             f"{o['ceiling'] / c['ceiling']:.0%} of his ceiling ({_own_txt(o)})"))
        group = ("WR", "TE") if c["position"] in ("WR", "TE") else (c["position"],)
        for o in pool:
            if o is not c and o["team"] == c["team"] and o["position"] in group and o["position"] != "QB" and o["ceiling_path"] \
                    and o["injury"] != "Q" \
                    and pop(o) < pop(c) * 0.6 and o["ceiling_pct"] >= 0.5:
                same_team.append(card(o, reason=f"If {o['name']} hits, {c['name']} (chalk) likely didn't -- they compete for "
                                                f"{c['team']}'s {'targets' if c['position'] in ('WR', 'TE') else 'touches'}"))
    popular = [g for g in games if g["popular"]]
    alt = [g for g in games if g["leverage_game"]]
    game_lev = []
    for g in alt[:3]:
        vs = popular[0]["game"] if popular else None
        game_lev.append({"game": g["game"], "vs": vs, "script": g["script"],
                         "reason": f"#{g['env_rank']} environment but #{g['pop_rank']} in popularity"
                                   + (f"; the field is on {vs}" if vs else "")})
    own_lev = []
    for r in sorted(pool, key=lambda r: -r["ceiling_pct"]):
        if r["ceiling_pct"] >= 0.6 and r["ceiling_path"] and r.get("popularity") == "Low" and r["injury"] != "Q":
            role = []
            if r.get("proj_opps"):
                role.append(f"{r['proj_opps']:.1f} projected opportunities")
            if (r.get("usage") or {}).get("target_share"):
                role.append(f"{r['usage']['target_share']:.0%} target share")
            if r.get("implied"):
                role.append(f"{r['team']} implied {r['implied']:g}")
            rank = 1 + sum(1 for x in pool if x["position"] == r["position"] and x["ceiling"] > r["ceiling"])
            own_lev.append(card(r, reason=f"#{rank} {r['position']} ceiling ({r['ceiling']:.1f}), "
                                          f"{_own_txt(r)}" + (f"; {', '.join(role)}" if role else "")))
        if len(own_lev) >= 10:
            break

    def dedupe(xs, n=6):
        seen, out = set(), []
        for x in xs:
            if x["id"] not in seen:
                seen.add(x["id"])
                out.append(x)
        return out[:n]

    return {"player_vs_player": dedupe(pvp), "same_team": dedupe(same_team), "salary": dedupe(salary),
            "game": game_lev, "ownership": own_lev}


# -------------------------------------------------------- 9-10. stacks
def build_stacks(pool: list[dict], games_by_team: dict) -> list[dict]:
    out = []
    for qb in [r for r in pool if r["position"] == "QB"]:
        mates = sorted([m for m in pool if m["team"] == qb["team"] and m["position"] in ("WR", "TE") and m["ceiling_path"]],
                       key=lambda m: -m["ceiling"])
        opp_wr = sorted([m for m in pool if m["team"] == qb["opponent"] and m["position"] == "WR" and m["ceiling_path"]],
                        key=lambda m: -m["ceiling"])
        opp_other = sorted([m for m in pool if m["team"] == qb["opponent"] and m["position"] in ("TE", "RB") and m["ceiling_path"]],
                           key=lambda m: -m["ceiling"])
        if not mates:
            continue
        g = games_by_team.get(qb["team"], {})
        bring, bring_note = None, ""
        if opp_wr:
            bring = opp_wr[0]
            if len(opp_wr) > 1:
                w1, w2 = opp_wr[0], opp_wr[1]
                if w2["ceiling"] >= 0.85 * w1["ceiling"] and POP_WEIGHT.get(w2.get("popularity"), 0) < POP_WEIGHT.get(w1.get("popularity"), 0):
                    bring = w2
                    bring_note = (f"WR2 {w2['name']} over WR1 {w1['name']}: {w2['ceiling']:.1f} vs {w1['ceiling']:.1f} ceiling at "
                                  f"{_own_txt(w2)} vs {_own_txt(w1)}")
                else:
                    bring_note = f"WR1 {w1['name']} over WR2 {w2['name']} ({w1['ceiling']:.1f} vs {w2['ceiling']:.1f} ceiling)"
        elif opp_other:
            bring = opp_other[0]
            bring_note = f"No playable opposing WR; {bring['position']} {bring['name']} as the bring-back"
        for kind, k in (("Basic", 1), ("Double", 2)):
            if len(mates) < k:
                continue
            members = [qb] + mates[:k] + ([bring] if bring else [])
            salary = sum(m["salary"] for m in members)
            ceil = sum(m["ceiling"] for m in members)
            label = f"{kind} stack + bring-back" if bring else f"{kind} stack"
            out.append({
                "game": g.get("game"), "team": qb["team"], "type": label, "qb": qb["name"],
                "players": [card(m) for m in members], "salary": salary, "final": round(sum(m["final"] for m in members), 1),
                "ceiling": round(ceil, 1), "env_rank": g.get("env_rank"), "pop_rank": g.get("pop_rank"),
                "score": round(ceil - 3.5 * salary / 1000 + 3 * (g.get("env_score") or 0), 1),
                "bring_back_note": bring_note, "script": g.get("script"),
                "reason": f"{g.get('game')} (#{g.get('env_rank')} environment, #{g.get('pop_rank')} popularity); "
                          f"ceiling {ceil:.1f} vs 3.5x salary {3.5 * salary / 1000:.1f}",
            })
    out.sort(key=lambda s: -s["score"])
    return out


# --------------------------------------------------------- 11-17. lineups
def correlation(lineup: list[dict]) -> dict:
    qb = next(p for p in lineup if p["position"] == "QB")
    dst = next(p for p in lineup if p["position"] == "DST")
    pos, neg, groups = [], [], {}
    mates = [p for p in lineup if p["team"] == qb["team"] and p["position"] in ("WR", "TE")]
    qb_rb = [p for p in lineup if p["team"] == qb["team"] and p["position"] == "RB"]
    bring = [p for p in lineup if p["team"] == qb["opponent"] and p["position"] in ("RB", "WR", "TE")]
    score = 2.0 * len(mates) + 0.5 * len(qb_rb) + 1.5 * min(len(bring), 2)
    for m in mates:
        pos.append(f"{qb['name']} + {m['name']} (QB-{m['position']})")
    for b in bring:
        pos.append(f"{b['name']} brings back {qb['team']}'s stack")
    by_team: dict[str, list] = {}
    for p in lineup:
        if p["position"] != "DST":
            by_team.setdefault(p["team"], []).append(p)
    for team, ps in by_team.items():
        rbs = [p for p in ps if p["position"] == "RB"]
        if len(rbs) >= 2:
            neg.append(f"Two {team} RBs compete for the same carries")
            score -= 1.5
    if any(p["team"] == dst["opponent"] and p["position"] != "DST" for p in lineup):
        neg.append(f"{dst['name']} faces your own players")
        score -= 2
    others = [p for p in lineup if p["position"] not in ("QB", "DST") and p not in mates and p not in bring]
    for p in others:
        groups.setdefault(p["game"], []).append(p)
    mini = [ps for ps in groups.values() if len(ps) >= 2]
    for ps in mini:
        pos.append("Mini-correlation: " + " + ".join(p["name"] for p in ps))
        score += 0.5 * (len(ps) - 1)
    stacked_games = {qb["game"]} | {ps[0]["game"] for ps in mini}
    unrelated = [p["name"] for p in lineup if p["position"] not in ("QB",) and p["game"] not in stacked_games]
    return {"score": round(score, 1), "positive": pos, "negative": neg, "unrelated": unrelated,
            "qb_mates": [m["name"] for m in mates], "bring_backs": [b["name"] for b in bring],
            "double_stack": len(mates) >= 2, "game_stack": bool(mates and bring)}


def salary_breakdown(lineup: list[dict]) -> dict:
    total = sum(p["salary"] for p in lineup)
    by_pos: dict[str, list[int]] = {}
    for p in lineup:
        by_pos.setdefault(p["position"], []).append(p["salary"])
    return {"total": total, "remaining": SALARY_CAP - total,
            "by_position": {k: {"total": sum(v), "avg": round(sum(v) / len(v)), "share": round(sum(v) / total, 3)} for k, v in by_pos.items()}}


def _meaningful_leverage(r: dict) -> bool:
    """Lower-owned AND a legitimate ceiling path: top-quarter ceiling at the position, a real role, not Questionable."""
    if r["injury"] == "Q" or not r["ceiling_path"] or not has_role(r) or r["ceiling_pct"] < 0.75:
        return False
    if r.get("ownership") is not None:
        return r["ownership"] <= 8
    return r.get("popularity") == "Low"


def evaluate(lu: list[dict], kind: str, games_by_team: dict, has_own: bool, cash_te_ids: set) -> dict:
    corr = correlation(lu)
    sal = salary_breakdown(lu)
    qb = lu[0]
    te = next(p for p in lu if p["position"] == "TE")
    flex = lu[7]
    own_vals = [p.get("ownership") for p in lu]
    own_total = round(sum(v for v in own_vals if v is not None), 1) if has_own and all(v is not None for v in own_vals) else None
    lev = [p for p in lu if _meaningful_leverage(p)]
    chalk = [p for p in lu if p.get("popularity") == "High"]
    g = games_by_team.get(qb["team"], {})
    if kind == "cash":
        checks = [
            ("QB has a stable projection", qb.get("uncertainty_label") != "High" and qb["injury"] != "Q"),
            ("RB volume is secure", all((p.get("proj_opps") or 0) >= 12 for p in lu if p["position"] == "RB")),
            ("WR target volume is secure", all((p.get("proj_targets") or p.get("proj_rec") or 0) >= 4.5 for p in lu if p["position"] == "WR")),
            ("Cheap value has legitimate opportunity", all(has_role(p) for p in lu)),
            ("No unnecessary dart throws", all(p["final"] >= 6 or p["position"] == "DST" for p in lu)),
            ("Correlation is logical, not forced", not corr["negative"]),
            ("Salary is efficiently allocated", sal["remaining"] <= 1500),
            ("No unnecessary low-owned plays", sum(1 for p in lu if p.get("popularity") == "Low" and p["final_pct"] < 0.5) <= 1),
            ("TE is elite or a cheap real role", te["id"] in cash_te_ids),
            ("Strong floor", sum(p["floor"] for p in lu) >= 0.45 * sum(p["final"] for p in lu)),
        ]
    else:
        checks = [
            ("QB has a correlated teammate (or is a naked rushing QB)", bool(corr["qb_mates"]) or (qb.get("rush_share") or 0) >= 0.25),
            ("Double stack considered", corr["double_stack"]),
            ("Game stack with a bring-back", corr["game_stack"]),
            ("At least one meaningful leverage play", bool(lev)),
            ("WR considered for FLEX (a non-WR FLEX out-ceilings the lineup's lowest WR)",
             flex["position"] == "WR" or flex["ceiling"] >= min(p["ceiling"] for p in lu if p["position"] == "WR")),
            ("No unnecessary negative correlation", not corr["negative"]),
            ("Salary efficiently allocated", sal["remaining"] <= 1000),
            ("No value play used just because it's cheap", all(has_role(p) for p in lu)),
            ("Every player has a ceiling path", all(p["ceiling_path"] for p in lu)),
            ("Ownership not unnecessarily duplicated", len(chalk) <= 4),
            ("Realistic first-place upside", sum(p["ceiling"] for p in lu) >= 230),
            ("Coherent game-script story", len(corr["unrelated"]) <= 4),
        ]
    rb = [p for p in lu if p["position"] == "RB"]
    wr = [p for p in lu if p["position"] == "WR"]
    rb_txt = ", ".join(f"{p['name']} (${p['salary']:,}, {_num(p.get('proj_opps'))} opps)" for p in rb)
    wr_txt = ", ".join(f"{p['name']} (${p['salary']:,})" for p in wr)
    te_strategy = "Pay up" if te["salary"] >= 5500 else ("Punt" if te["salary"] <= 4000 else "Mid-range")
    weakest = max((p for p in lu if p["position"] != "DST"),
                  key=lambda p: p["salary"] * (1 - (p.get("floor_ratio") or 0.5)) * (1.3 if p["injury"] == "Q" else 1))
    if kind == "cash":
        win = f"Volume held: {qb['name']} and the RBs got their projected work, and nobody busted."
    elif corr["game_stack"]:
        win = (f"{g.get('game')} shot out: {qb['name']} threw to {_join(corr['qb_mates'])}, and "
               f"{_join(corr['bring_backs'])} kept the other side scoring")
        if lev:
            win += f"; {_join([p['name'] for p in lev if p['position'] != 'QB'][:2]) or qb['name']} hit at low ownership"
    elif corr["qb_mates"]:
        win = f"{qb['name']} and {', '.join(corr['qb_mates'])} carried the lineup"
    else:
        win = f"{qb['name']} ran for a ceiling game on his own"
    audit = {
        "qb_stack": f"{qb['name']} + {', '.join(corr['qb_mates'])}" if corr["qb_mates"] else f"{qb['name']} naked",
        "double_stack": "Yes" if corr["double_stack"] else "No",
        "game_stack": g.get("game") if corr["game_stack"] else "No",
        "bring_back": ", ".join(corr["bring_backs"]) or "None",
        "rb_construction": rb_txt,
        "wr_construction": wr_txt,
        "te_strategy": f"{te_strategy}: {te['name']} (${te['salary']:,})",
        "flex_strategy": f"{flex['position']} {flex['name']}",
        "leverage": ", ".join(f"{p['name']} ({_own_txt(p)})" for p in lev) or "None",
        "projected_ownership": f"{own_total:.1f}%" if own_total is not None else f"{len(chalk)} est. chalk (no ownership data)",
        "salary_remaining": f"${sal['remaining']:,}",
        "primary_game_script": g.get("script") or "-",
        "biggest_failure_point": f"{weakest['name']}: ${weakest['salary']:,} with a {_num(weakest['floor'])} floor"
                                 + (" and Questionable" if weakest["injury"] == "Q" else ""),
    }
    return {"correlation": corr, "salary": sal, "ownership_total": own_total, "chalk_count": len(chalk),
            "leverage_count": len(lev), "checklist": [{"item": k, "ok": bool(v)} for k, v in checks],
            "audit": audit, "win_scenario": win,
            "raw": {"projection": sum(p["final"] for p in lu), "ceiling": sum(p["ceiling"] for p in lu),
                    "floor": sum(p["floor"] for p in lu), "value": sum(p["final"] for p in lu) / (sal["total"] / 1000),
                    "correlation": corr["score"], "leverage": len(lev), "ownership": -len(chalk) if own_total is None else -own_total,
                    "salary_eff": sal["total"] / SALARY_CAP, "env": g.get("env_score") or 0,
                    "opportunity": sum(p.get("proj_opps") or 0 for p in lu),
                    "stability": -sum(1 for p in lu if p.get("uncertainty_label") == "High")}}


GPP_WEIGHTS = {"ceiling": 0.25, "correlation": 0.20, "leverage": 0.15, "env": 0.15, "ownership": 0.10,
               "projection": 0.05, "salary_eff": 0.05, "uniqueness": 0.05}
CASH_WEIGHTS = {"floor": 0.30, "projection": 0.25, "opportunity": 0.20, "value": 0.10, "stability": 0.15}


def quality_scores(all_lineups: list[dict]) -> None:
    """Step 17: min-max each dimension within a group (cash vs tournament
    lineups), then weight by what that game type needs."""
    for group in ([lu for lu in all_lineups if lu["type"] == "cash"], [lu for lu in all_lineups if lu["type"] != "cash"]):
        _quality_group(group)


def _quality_group(lineups: list[dict]) -> None:
    if not lineups:
        return
    for lu in lineups:
        ids = {p["id"] for p in lu["players"]}
        others = [o for o in lineups if o is not lu]
        overlap = statistics.fmean([len(ids & {p["id"] for p in o["players"]}) for o in others]) if others else 0
        lu["eval"]["raw"]["uniqueness"] = -overlap
    dims = set(GPP_WEIGHTS) | set(CASH_WEIGHTS)
    ranges = {d: (min(lu["eval"]["raw"][d] for lu in lineups), max(lu["eval"]["raw"][d] for lu in lineups)) for d in dims}
    for lu in lineups:
        norm = {}
        for d in dims:
            lo, hi = ranges[d]
            norm[d] = round(100 * (lu["eval"]["raw"][d] - lo) / (hi - lo), 0) if hi > lo else 50.0
        weights = CASH_WEIGHTS if lu["type"] == "cash" else GPP_WEIGHTS
        lu["eval"]["dimensions"] = {d: norm[d] for d in weights}
        lu["eval"]["quality"] = round(sum(norm[d] * w for d, w in weights.items()), 0)


def _player_reason(p: dict, kind: str) -> str:
    bits = []
    if kind == "cash":
        if p["position"] == "RB" and p.get("proj_opps"):
            bits.append(f"{p['proj_opps']:.1f} projected opportunities")
        if p["position"] in ("WR", "TE") and (p.get("usage") or {}).get("target_share"):
            bits.append(f"{p['usage']['target_share']:.0%} target share")
        bits.append(f"floor {_num(p['floor'])}")
        if p["salary"] <= CHEAP[p["position"]]:
            bits.append(f"value {p['value']:.2f}/$1k")
    else:
        bits.append(f"ceiling {_num(p['ceiling'])}")
        if _meaningful_leverage(p):
            bits.append("leverage")
    if p.get("injury_opportunity"):
        bits.append("injury-driven role")
    return ", ".join(bits)


def _lineup_out(lu: list[dict], label: str, kind: str, construction: str, idea: str, ev: dict) -> dict:
    return {"label": label, "type": kind, "construction": construction, "idea": idea,
            "players": [{**card(p), "slot": s, "own": _own_txt(p), "reason": _player_reason(p, kind)} for p, s in zip(lu, SLOTS)],
            "salary": sum(p["salary"] for p in lu), "final": round(sum(p["final"] for p in lu), 1),
            "floor": round(sum(p["floor"] for p in lu), 1), "ceiling": round(sum(p["ceiling"] for p in lu), 1), "eval": ev}


def _mark_considered(ev: dict, *, naked: bool, tried_double: bool) -> None:
    """The checklist asks whether a double stack was *considered*: a naked
    rushing QB, or a construction where the double stack was tried and
    infeasible, passes with the reason stated."""
    for c in ev["checklist"]:
        if c["item"] == "Double stack considered" and not c["ok"]:
            if naked:
                c.update(ok=True, item="Double stack considered (naked rushing QB by design)")
            elif tried_double:
                c.update(ok=True, item="Double stack considered (tried; infeasible with this construction)")


def build_lineups(pool: list[dict], games: list[dict], games_by_team: dict, stacks: list[dict], pools: dict,
                  chalk_rows: list[dict], leverage: dict, has_own: bool) -> dict:
    te_cash_ids = set(pools["TE"]["cash_ids"])
    notes = []

    # --- Cash (Step 13)
    cash_pool = [r for r in pool if r["injury"] != "Q" and (r["position"] == "DST" or r["final"] >= 6)
                 and not (r["position"] in ("RB", "WR", "TE") and r["salary"] <= CHEAP[r["position"]]
                          and (r.get("proj_opps") or 0) < (10 if r["position"] == "RB" else 4.5))
                 and (r["position"] != "TE" or r["id"] in te_cash_ids or not te_cash_ids)]

    def cash_value(r):
        return (r["floor"] + r["final"] + 0.15 * min(r.get("proj_opps") or 0, 25)
                - (2.5 if r.get("uncertainty_label") == "High" else 0))

    cash, prior = [], []
    for i in range(5):
        lu = lineup_builder.build(cash_pool, [cash_value(r) for r in cash_pool], prior=prior, min_unique=2,
                                  min_salary=CASH_MIN_SALARY, one_rb_per_team=True)
        if not lu:
            break
        prior.append({p["id"] for p in lu})
        label = "Recommended cash lineup" if i == 0 else f"Cash alternate {i}"
        cash.append(_lineup_out(lu, label, "cash", "Floor + volume + stability",
                                "Maximizes floor + projection + projected opportunities; no Questionable players, no cheap players "
                                "without a real role, TE elite or a cheap real role, never two RBs from one team",
                                evaluate(lu, "cash", games_by_team, has_own, te_cash_ids)))

    # --- GPP (Steps 14 and 16)
    gpp_pool = [r for r in pool if r["ceiling_path"] and has_role(r)]
    lev_ids = {r["id"] for r in gpp_pool if _meaningful_leverage(r)}
    fragile = {r["id"] for r in pool if r.get("chalk_class") in ("Fragile chalk", "Overpriced chalk", "Cash chalk, GPP fade")}
    env_z = {g["game"]: g["env_score"] for g in games}

    def gpp_value(r, extra=0.0):
        v = r["ceiling"] * _q(r) * (1 + 0.04 * env_z.get(r["game"], 0))
        v += 1.5 if r["id"] in lev_ids else 0
        v -= 2.0 if r["id"] in fragile else 0
        v += WR_FLEX_BONUS if r["position"] == "WR" else 0
        return v + extra

    by_env = [g for g in games]
    by_pop = sorted(games, key=lambda g: -g["pop_share"])
    qbp = {c["id"]: c for c in pools["QB"]["gpp"]}
    qb_by_game: dict[str, list[dict]] = {}
    for r in sorted(gpp_pool, key=lambda r: -r.get("gpp_qb_score", 0)):
        if r["position"] == "QB":
            qb_by_game.setdefault(r["game"], []).append(r)

    constructions = []
    primary = by_env[0]["game"] if by_env else None
    contrarian_game = next((g["game"] for g in games if g["leverage_game"] and g["game"] != primary), None) \
        or next((g["game"] for g in sorted(games, key=lambda g: g["pop_share"]) if g["env_rank"] <= max(3, len(games) // 2)
                 and g["game"] != primary), None)
    strong_chalk = [c for c in chalk_rows if c["classification"] in ("Strong chalk", "Necessary / value chalk",
                                                                     "Chalk usable in a leverage stack")]
    popular_games = {g["game"] for g in by_pop[:2]}
    qbs_by_salary = sorted([r for r in gpp_pool if r["position"] == "QB"], key=lambda r: -r["salary"])
    rb_chalk = next((c for c in chalk_rows if c["position"] == "RB" and c["salary"] >= 7000), None)
    rb_alt = next((x for x in leverage["salary"] + leverage["player_vs_player"] if x["position"] == "RB"), None)
    if rb_chalk and not rb_alt:   # no textbook salary leverage: best cheaper, non-chalk RB with a real role
        cands = [r for r in gpp_pool if r["position"] == "RB" and r["salary"] <= rb_chalk["salary"] - 1000
                 and not r.get("chalk_class") and r["injury"] != "Q"]
        best = max(cands, key=lambda r: r["ceiling"], default=None)
        if best:
            rb_alt = card(best, reason=f"${rb_chalk['salary'] - best['salary']:,} cheaper with {best['ceiling'] / rb_chalk['ceiling']:.0%} "
                                       f"of his ceiling, {_num(best.get('proj_opps'))} projected opportunities, {_own_txt(best)}")
    te_pay = pools["TE"]["pay_up"][0] if pools["TE"]["pay_up"] else None
    naked = pools["QB"]["naked_candidates"][0] if pools["QB"]["naked_candidates"] else None
    second = by_env[1]["game"] if len(by_env) > 1 else None

    if primary:
        constructions.append(("Primary game stack", f"{primary}: the best environment (#{by_env[0]['env_rank']}; "
                              f"{by_env[0]['ownership_vs_quality'].lower()}). QB double stack + opposing WR bring-back.",
                              dict(stack=(2, 1), stack_game=primary, bring_back_pos=("WR",))))
    if contrarian_game:
        g = next(x for x in games if x["game"] == contrarian_game)
        constructions.append(("Contrarian game stack", f"{contrarian_game}: #{g['env_rank']} environment but #{g['pop_rank']} in "
                              f"popularity. {g['script']}.", dict(stack=(2, 1), stack_game=contrarian_game)))
    if strong_chalk:
        force = {c["id"] for c in strong_chalk[:2] if c["position"] != "QB"}
        alt_games = [g for g in games if g["game"] not in popular_games]
        qb_ids = {r["id"] for g in alt_games for r in qb_by_game.get(g["game"], [])[:1]}
        constructions.append(("Chalk + leverage", "Eats the strongest chalk (" + ", ".join(c["name"] for c in strong_chalk[:2]
                              if c["position"] != "QB") + ") and attacks the slate through a QB stack outside the two most popular games.",
                              dict(stack=(1, 1), force=force, qb_ids=qb_ids or None, at_least=[(lev_ids, 1)])))
    if qbs_by_salary:
        top_qbs = {r["id"] for r in qbs_by_salary[:2]}
        cheap_rb = {r["id"] for r in gpp_pool if r["position"] == "RB" and r["salary"] <= 5500 and (r.get("proj_opps") or 0) >= 12}
        cheap_te = {r["id"] for r in gpp_pool if r["position"] == "TE" and r["salary"] <= 4000}
        constructions.append(("Expensive QB", "Pays up at QB (" + " / ".join(r["name"] for r in qbs_by_salary[:2])
                              + ") and saves at RB and TE with players who have a real role.",
                              dict(stack=(1, 1), qb_ids=top_qbs, at_least=[(cheap_rb, 1), (cheap_te, 1)] if cheap_rb and cheap_te else [])))
    if rb_chalk and rb_alt:
        constructions.append(("Mid-tier RB leverage", f"Fades chalk RB {rb_chalk['name']} for {rb_alt['name']} "
                              f"(${rb_alt['salary']:,}): {rb_alt['reason']}.",
                              dict(stack=(1, 1), force={rb_alt["id"]}, exclude={rb_chalk["id"]})))
    if te_pay:
        constructions.append(("Elite TE", f"Builds around {te_pay['name']} at TE instead of a similarly priced WR.",
                              dict(stack=(1, 1), force={te_pay["id"]}, counts={"TE": 1})))
    constructions.append(("Low-owned ceiling", "Three or more lower-owned players, each with a real ceiling path (top-quarter ceiling "
                          "at the position and a role).", dict(stack=(1, 1), at_least=[(lev_ids, 3)])))
    if naked:
        constructions.append(("Naked rushing QB", f"{naked['name']} alone: {naked['reasons'][0] if naked['reasons'] else ''}. "
                              "Salary goes to the best ceilings elsewhere.", dict(qb_ids={naked["id"]}, naked_qb=True)))
    if second:
        constructions.append(("Second environment, WR2 bring-back", f"{second}: double stack with the opposing WR2 as a lower-owned "
                              "bring-back when his ceiling is close to the WR1's.",
                              dict(stack=(2, 1), stack_game=second, bring_back_pos=("WR",), wr2=True)))
    constructions.append(("4-WR onslaught", "WR in the FLEX with a QB double stack: max passing-game correlation.",
                          dict(stack=(2, 1), counts={"WR": 4})))

    gpp, gpp_prior, exposure = [], [], {}
    built_constructions = []
    for name, idea, kw in constructions:
        if len(gpp) >= 10:
            break
        kw = dict(kw)
        exclude = kw.pop("exclude", set())
        wr2 = kw.pop("wr2", False)
        avail = [r for r in gpp_pool if exposure.get(r["id"], 0) < GPP_EXPOSURE_CAP and r["id"] not in exclude]
        if wr2 and kw.get("stack_game"):
            teams = {r["team"] for r in avail if r["game"] == kw["stack_game"]}
            for t in teams:
                wrs = sorted([r for r in avail if r["team"] == t and r["position"] == "WR"], key=lambda r: -r["ceiling"])
                if len(wrs) >= 2 and wrs[1]["ceiling"] >= 0.85 * wrs[0]["ceiling"]:
                    avail = [r for r in avail if r is not wrs[0]]
        attempt = dict(kw)
        relaxed = None
        lu = None
        if attempt.get("stack") == (1, 1):   # always try the double stack first
            lu = lineup_builder.build(avail, [gpp_value(r) for r in avail], prior=gpp_prior, min_unique=3,
                                      min_salary=GPP_MIN_SALARY, one_rb_per_team=True, **{**attempt, "stack": (2, 1)})
            if not lu:
                relaxed = "double stack not feasible with this construction; single stack used"
        if not lu:
            lu = lineup_builder.build(avail, [gpp_value(r) for r in avail], prior=gpp_prior, min_unique=3,
                                      min_salary=GPP_MIN_SALARY, one_rb_per_team=True, **attempt)
        if not lu and attempt.get("at_least"):
            attempt.pop("at_least")
            relaxed = "relaxed the leverage / salary-saver requirement to find a valid lineup"
            lu = lineup_builder.build(avail, [gpp_value(r) for r in avail], prior=gpp_prior, min_unique=3,
                                      min_salary=GPP_MIN_SALARY, one_rb_per_team=True, **attempt)
        if not lu:
            notes.append(f"{name}: no valid lineup with this construction on the current pool")
            continue
        gpp_prior.append({p["id"] for p in lu})
        for p in lu:
            exposure[p["id"]] = exposure.get(p["id"], 0) + 1
        ev = evaluate(lu, "gpp", games_by_team, has_own, te_cash_ids)
        if relaxed:
            ev["note"] = relaxed
        _mark_considered(ev, naked=kw.get("naked_qb", False), tried_double=bool(relaxed and "double" in relaxed))
        gpp.append(_lineup_out(lu, f"GPP {len(gpp) + 1}", "gpp", name, idea, ev))
        built_constructions.append({"name": name, "idea": idea, "lineup": gpp[-1]["label"]})
    while len(gpp) < 10:
        avail = [r for r in gpp_pool if exposure.get(r["id"], 0) < GPP_EXPOSURE_CAP]
        lu = lineup_builder.build(avail, [gpp_value(r) for r in avail], prior=gpp_prior, min_unique=3,
                                  min_salary=GPP_MIN_SALARY, one_rb_per_team=True, stack=(2, 1))
        if not lu:
            break
        gpp_prior.append({p["id"] for p in lu})
        for p in lu:
            exposure[p["id"]] = exposure.get(p["id"], 0) + 1
        gpp.append(_lineup_out(lu, f"GPP {len(gpp) + 1}", "gpp", "Best remaining double stack",
                               "Highest-value QB double stack + bring-back not already used",
                               evaluate(lu, "gpp", games_by_team, has_own, te_cash_ids)))
        built_constructions.append({"name": "Best remaining double stack", "idea": gpp[-1]["idea"], "lineup": gpp[-1]["label"]})

    # --- Contrarian
    contrarian, used_qbs = [], set()
    c_prior = list(gpp_prior)

    def contrarian_value(r):
        base = r["ceiling"] * _q(r)
        if has_own and r.get("ownership") is not None:
            return base * (1 - min(0.6, r["ownership"] / 100 * 0.8))
        return base * (1 - {"High": 0.30, "Medium": 0.12}.get(r.get("popularity"), 0.0))

    for i in range(5):
        avail = [r for r in gpp_pool if exposure.get(r["id"], 0) < TOURNAMENT_EXPOSURE_CAP
                 and not (r["position"] == "QB" and (r["game"] in popular_games or r["id"] in used_qbs))]
        vals = [contrarian_value(r) for r in avail]
        lu, tried_double = None, False
        for stack, lev_k in (((2, 1), 2), ((1, 1), 2), ((1, 1), 0)):
            lu = lineup_builder.build(avail, vals, prior=c_prior, min_unique=3, min_salary=GPP_MIN_SALARY,
                                      one_rb_per_team=True, stack=stack, at_least=[(lev_ids, lev_k)] if lev_k else [])
            if lu:
                break
            tried_double = tried_double or stack == (2, 1)
        if not lu:
            break
        c_prior.append({p["id"] for p in lu})
        used_qbs.add(lu[0]["id"])
        for p in lu:
            exposure[p["id"]] = exposure.get(p["id"], 0) + 1
        ev = evaluate(lu, "gpp", games_by_team, has_own, te_cash_ids)
        _mark_considered(ev, naked=False, tried_double=tried_double)
        contrarian.append(_lineup_out(lu, f"Contrarian {i + 1}", "contrarian", "Contrarian GPP",
                                      "Ceiling discounted by " + ("ownership" if has_own else "estimated popularity")
                                      + "; QB stack outside the two most popular games; at least two meaningful leverage plays",
                                      ev))

    everything = cash + gpp + contrarian
    quality_scores(everything)
    rec = cash[0] if cash else None
    if rec:
        ev = rec["eval"]
        strengths, risks = [], []
        if ev["raw"]["floor"] >= 0.45 * ev["raw"]["projection"]:
            strengths.append(f"Floor {ev['raw']['floor']:.1f} is {ev['raw']['floor'] / ev['raw']['projection']:.0%} of the projection")
        strengths.append(f"{ev['raw']['opportunity']:.0f} projected opportunities across RB/WR/TE")
        if not ev["correlation"]["negative"]:
            strengths.append("No negative correlation")
        worst = min((p for p in rec["players"] if p["position"] != "DST"), key=lambda p: (p["floor"] or 0) / max(p["final"] or 1, 1))
        risks.append(f"Lowest floor relative to projection: {worst['name']} ({_num(worst['floor'])} floor)")
        high_unc = [p["name"] for p in rec["players"] if p.get("uncertainty_label") == "High"]
        if high_unc:
            risks.append("High-uncertainty projections: " + ", ".join(high_unc))
        rec["strengths"], rec["risks"] = strengths, risks
    return {"cash": cash, "gpp": gpp, "contrarian": contrarian, "constructions": built_constructions, "notes": notes}


# ------------------------------------------------------------- 18. fades
def fades(pool: list[dict], chalk_rows: list[dict], pools: dict, games_by_team: dict) -> dict:
    cash_f, gpp_f, poor_fit = [], [], []
    qb_teams = {c["team"] for c in pools["QB"]["gpp"]}
    for r in pool:
        if r["position"] == "DST" or r["salary"] < 4500:
            continue
        if r["injury"] == "Q":
            cash_f.append(card(r, reason="Questionable: cash needs certainty"))
        elif (r.get("floor_ratio") or 1) < 0.35 and r["salary"] >= 6000:
            cash_f.append(card(r, reason=f"Floor {_num(r['floor'])} is only {r['floor_ratio']:.0%} of his projection"))
        elif r["position"] == "RB" and (r.get("spread") or 0) >= 6.5:
            cash_f.append(card(r, reason=f"{r['spread']:g}-point underdog RB: script can erase his carries"))
        if r["salary"] >= 6500 and r["ceiling_pct"] < 0.5:
            gpp_f.append(card(r, reason=f"${r['salary']:,} without a top-half ceiling at {r['position']} ({_num(r['ceiling'])})"))
        g = games_by_team.get(r["team"], {})
        if (r["position"] in ("WR", "TE") and r["salary"] >= 6000 and r["team"] not in qb_teams
                and g.get("env_rank") and g["env_rank"] > len(games_by_team) // 4):
            poor_fit.append(card(r, reason=f"Expensive pass catcher whose QB isn't in the GPP QB pool, in the "
                                           f"#{g['env_rank']} environment -- hard to stack"))
    gpp_f += pools["TE"]["mid_fades"]
    over = [c for c in chalk_rows if c["classification"] in ("Overpriced chalk", "Fragile chalk")]
    return {"cash": cash_f[:8], "gpp": gpp_f[:8],
            "over_owned": [dict(c, reason=c["risk"]) for c in over if c["classification"] == "Overpriced chalk"][:6],
            "fragile_chalk": [dict(c, reason=c["risk"]) for c in over if c["classification"] == "Fragile chalk"][:6],
            "poor_fit": poor_fit[:6]}


# ------------------------------------------------------------------ main
def run(pool: list[dict], rows: list[dict], slate, wd, usage: dict, has_own: bool, season: int, week: int) -> dict:
    ctx = enrich(pool, rows, slate, usage)
    games = analyze_games(pool, slate, wd, has_own)
    games_by_team = {}
    for g in games:
        games_by_team[g["away"]] = g
        games_by_team[g["home"]] = g
    pools = {"QB": qb_pool(pool, games_by_team), "RB": rb_pool(pool), "WR": wr_pool(pool, wd), "TE": te_analysis(pool),
             "DST": dst_pool(pool, wd, season, week), "salary_savers": salary_savers(pool),
             "wr_environments": wr_environments(pool, wd)}
    chalk_rows = chalk_table(pool, games_by_team, has_own)
    lev = leverage_analysis(pool, games, has_own)
    stacks = build_stacks(pool, games_by_team)
    lineups = build_lineups(pool, games, games_by_team, stacks, pools, chalk_rows, lev, has_own)
    gpp_core = sorted([r for r in pool if r["ceiling_path"] and r.get("chalk_class") not in ("Fragile chalk", "Overpriced chalk")],
                      key=lambda r: -(r["ceiling"] * _q(r) + 2 * r["final_pct"]))
    return {
        "overview": slate_overview(games, pool, ctx, rows, pools, chalk_rows, lev, has_own),
        "games": games,
        "pools": pools,
        "gpp_pool": {"core": [card(r, reason=f"Ceiling {r['ceiling']:.1f}, proj {r['final']:.1f}, {_own_txt(r)}") for r in gpp_core[:10]],
                     "chalk": chalk_rows[:10], "leverage": lev["ownership"][:10],
                     "low_owned_ceiling": [x for x in lev["ownership"] if x["salary"] >= 4500][:8],
                     "salary_savers": pools["salary_savers"]},
        "chalk": chalk_rows,
        "leverage": lev,
        "stacks": stacks,
        "lineups": lineups,
        "fades": fades(pool, chalk_rows, pools, games_by_team),
        "missing_data": [{"item": a, "why": b} for a, b in MISSING_DATA]
                        + ([] if has_own else [{"item": "Projected ownership", "why": "no source connected; paste it to replace the popularity estimate"}]),
    }
