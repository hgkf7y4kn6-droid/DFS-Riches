"""Why do the projected optimal lineups underperform? Compare them with the actual optimal lineups.

    python -m scripts.analyze_optimal_lineups BACKTEST_DIR

Two sources:
  1. The app's own saved projected optimal lineups (data/optimal_lineups.json, 2026), scored, with the hindsight
     "best possible" lineup the app saves.
  2. Rebuilt DraftKings Sunday main slates (2023-2026, real salaries and actual points; built by the construction
     backtest into BACKTEST_DIR as slate_*.pkl / prep_*.pkl): the app's optimizer (app.optimizer.optimize) on
     projection and on ceiling, and on actual points (the actual optimal lineup).

For each lineup: its projected and actual points, its players' game environments (closing-line game total and
team implied total, and the slate rank of the game), matchups (the opponent's dropback / rushing EPA allowed vs
the league, app.game_model, season to date), stacking (pass catchers with their QB, an opposing bring-back),
players per game, salary spent by tier, projected ownership, and how far each player beat his projection. The
selection effect: players the projection optimal picks vs every other player at the same projection.
Writes data/optimal_lineup_analysis.json.
"""
from __future__ import annotations

import json
import pickle
import statistics
import sys
from collections import Counter
from pathlib import Path

import numpy as np

from app import game_model as gm
from app.optimizer import optimize
from scripts import train_game_model as tgm

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "optimal_lineup_analysis.json"
DATA = ROOT / "data" / "cache" / "train"


def mean(xs, default=0.0):
    xs = list(xs)
    return statistics.fmean(xs) if xs else default


def lineup_features(lu: list[dict], game_total: dict, game_rank: dict, implied: dict, matchup: dict, own: dict) -> dict:
    qb = next((p for p in lu if p["position"] == "QB"), None)
    mates = [p for p in lu if qb and p["team"] == qb["team"] and p["position"] in ("WR", "TE")]
    bring = [p for p in lu if qb and p["team"] == qb["opponent"] and p["position"] in ("RB", "WR", "TE")]
    games = Counter(p["game"] for p in lu)
    off = [p for p in lu if p["position"] != "DST"]
    m = [matchup.get((p["opponent"], "pass" if p["position"] in ("QB", "WR", "TE") else "rush")) for p in off]
    return {
        "proj": sum(p["final"] for p in lu), "ceiling": sum(p["ceiling"] for p in lu), "actual": sum(p["actual"] for p in lu),
        "salary": sum(p["salary"] for p in lu),
        "avg_game_total": mean(game_total.get(p["game"], 44) for p in off),
        "players_in_top3_total_games": sum(1 for p in off if game_rank.get(p["game"], 99) <= 3),
        "players_in_bottom_third_games": sum(1 for p in off if game_rank.get(p["game"], 0) > 2 * len(game_rank) / 3),
        "avg_team_implied": mean(implied.get(p["team"], 22) for p in off),
        "avg_matchup_epa_allowed": mean(x for x in m if x is not None),
        "qb_pass_catchers": len(mates), "bring_back": len(bring), "max_players_one_game": max(games.values()),
        "games_used": len(games), "value_players_under_4500": sum(1 for p in off if p["salary"] < 4500),
        "players_7k_plus": sum(1 for p in off if p["salary"] >= 7000),
        "avg_ownership": mean(own.get(p["id"], 0) for p in lu),
        "dst_pts": sum(p["actual"] for p in lu if p["position"] == "DST"),
        "qb_pts": sum(p["actual"] for p in lu if p["position"] == "QB"),
    }


def as_opt(p: dict, metric: str) -> dict:
    return {**p, "dk_draftable_id": p["id"], "proj_points": p["final"], "dk_fppg": 1.0, "injury": "Healthy", "game_info": p["game"],
            "actual_points": p["actual"]}


def slate_analysis(bt: Path) -> dict:
    per, sel, matched = [], [], []
    seasons = {}
    for path in sorted(bt.glob("slate_*.pkl")):
        sl = pickle.load(open(path, "rb"))
        prep_path = bt / f"prep_{sl['season']}_{sl['week']}.pkl"
        prep = pickle.load(open(prep_path, "rb")) if prep_path.exists() else None
        own = {r["id"]: r.get("ownership", 0.0) for r in (prep or {}).get("rows", [])}
        s, w = sl["season"], sl["week"]
        if s not in seasons:
            agg, prev = tgm.season_agg(DATA, s), tgm.season_agg(DATA, s - 1)
            seasons[s] = (agg, gm.priors_from_season(gm.season_totals(prev)))
        agg, priors = seasons[s]
        est = gm.team_estimates(gm.season_totals(agg, before_week=w), priors)
        lg = priors["league"]
        nfl = {"LA": "LA"}
        matchup = {}
        for t, e in est.items():
            matchup[(nfl.get(t, t), "pass")] = e["d_pass_epa"] - lg["d_pass_epa"]
            matchup[(nfl.get(t, t), "rush")] = e["d_rush_epa"] - lg["d_rush_epa"]
        implied, game_total = {}, {}
        for g in sl["games"]:
            if g["away_implied"] is not None:
                implied[g["away"]], implied[g["home"]] = g["away_implied"], g["home_implied"]
                game_total[g["game"]] = g["away_implied"] + g["home_implied"]
        order = sorted(game_total, key=lambda g: -game_total[g])
        game_rank = {g: i + 1 for i, g in enumerate(order)}
        players = [p for p in sl["players"] if p["salary"] > 0]
        pool = [as_opt(p, "final") for p in players]
        lus = {}
        lus["projected optimal"] = optimize([p for p in pool if p["final"] > 0], "classic", "proj_points")
        lus["ceiling optimal"] = optimize([p for p in pool if p["final"] > 0], "classic", "ceiling")
        lus["actual optimal"] = optimize(pool, "classic", "actual_points", hindsight=True)
        row = {"season": s, "week": w}
        for k, lu in lus.items():
            if lu:
                row[k] = lineup_features(lu, game_total, game_rank, implied, matchup, own)
        if prep is not None:
            gf = prep["gpp_field"]
            for k in ("projected optimal", "ceiling optimal"):
                if k in row:
                    row[k]["field_percentile"] = float(np.searchsorted(gf, row[k]["actual"]) / len(gf))
        per.append(row)
        # selection effect: projected-optimal players vs others at the same projection (within 1.5 points, same position)
        chosen = {p["id"] for p in lus["projected optimal"] or []}
        for p in players:
            if p["id"] in chosen and p["position"] != "DST":
                peers = [q for q in players if q["id"] not in chosen and q["position"] == p["position"]
                         and abs(q["final"] - p["final"]) <= 1.5 and q["final"] > 0]
                sel.append({"pos": p["position"], "res": p["actual"] - p["final"], "value": p["final"] / (p["salary"] / 1000),
                            "salary": p["salary"], "peer_res": mean(q["actual"] - q["final"] for q in peers), "n_peers": len(peers)})
        # which players make the actual optimal: their projected value rank at the position
        best = {p["id"] for p in lus["actual optimal"] or []}
        for pos in ("QB", "RB", "WR", "TE", "DST"):
            grp = sorted([p for p in players if p["position"] == pos and p["final"] > 0], key=lambda p: -p["final"] / (p["salary"] / 1000))
            rank = {p["id"]: i + 1 for i, p in enumerate(grp)}
            prank = {p["id"]: i + 1 for i, p in enumerate(sorted(grp, key=lambda p: -p["final"]))}
            for p in players:
                if p["id"] in best and p["position"] == pos:
                    matched.append({"pos": pos, "value_rank": rank.get(p["id"]), "proj_rank": prank.get(p["id"]),
                                    "salary": p["salary"], "game_rank": game_rank.get(p["game"]), "proj": p["final"],
                                    "actual": p["actual"], "own": own.get(p["id"], 0)})
    return {"per_slate": per, "selected": sel, "actual_optimal_players": matched}


def summarize(res: dict) -> dict:
    per = res["per_slate"]
    out = {"slates": len(per)}
    keys = [k for k in per[0]["projected optimal"] if isinstance(per[0]["projected optimal"][k], (int, float))]
    comp = {}
    for k in keys:
        comp[k] = {name: round(mean(r[name][k] for r in per if name in r and k in r[name]), 2)
                   for name in ("projected optimal", "ceiling optimal", "actual optimal")}
    out["lineup_comparison"] = comp
    po = [r["projected optimal"] for r in per if "projected optimal" in r]
    out["projected_optimal_shortfall"] = {
        "avg_projected": round(mean(x["proj"] for x in po), 1), "avg_actual": round(mean(x["actual"] for x in po), 1),
        "beat_projection": round(mean(x["actual"] > x["proj"] for x in po), 3),
        "avg_share_of_actual_optimal": round(mean(r["projected optimal"]["actual"] / r["actual optimal"]["actual"] for r in per), 3),
        "avg_field_percentile": round(mean(x.get("field_percentile", 0) for x in po if "field_percentile" in x), 3)}
    # which lineup features go with a bigger shortfall (actual - projected), across slates
    short = np.array([x["actual"] - x["proj"] for x in po])
    out["shortfall_correlations"] = {}
    for k in ("avg_game_total", "players_in_top3_total_games", "players_in_bottom_third_games", "avg_team_implied",
              "avg_matchup_epa_allowed", "qb_pass_catchers", "bring_back", "max_players_one_game", "value_players_under_4500",
              "players_7k_plus", "avg_ownership", "games_used"):
        v = np.array([x[k] for x in po])
        if v.std() > 0:
            out["shortfall_correlations"][k] = round(float(np.corrcoef(v, short)[0, 1]), 3)
    sel = res["selected"]
    out["selection_effect"] = {
        "players": len(sel), "avg_miss_selected": round(mean(x["res"] for x in sel), 2),
        "avg_miss_same_projection_not_selected": round(mean(x["peer_res"] for x in sel if x["n_peers"]), 2),
        "by_position": {pos: {"n": len(g), "selected": round(mean(x["res"] for x in g), 2),
                              "peers": round(mean(x["peer_res"] for x in g if x["n_peers"]), 2)}
                        for pos in ("QB", "RB", "WR", "TE") for g in [[x for x in sel if x["pos"] == pos]] if g},
        "by_value_tier": {}}
    vals = sorted(x["value"] for x in sel)
    if vals:
        cuts = np.quantile(vals, [1 / 3, 2 / 3])
        for label, lo, hi in (("lowest-value third", -1, cuts[0]), ("middle", cuts[0], cuts[1]), ("highest-value third", cuts[1], 99)):
            g = [x for x in sel if lo < x["value"] <= hi]
            out["selection_effect"]["by_value_tier"][label] = {"n": len(g), "selected": round(mean(x["res"] for x in g), 2),
                                                              "peers": round(mean(x["peer_res"] for x in g if x["n_peers"]), 2)}
    m = res["actual_optimal_players"]
    out["actual_optimal_players"] = {}
    for pos in ("QB", "RB", "WR", "TE", "DST"):
        g = [x for x in m if x["pos"] == pos and x["value_rank"]]
        if g:
            out["actual_optimal_players"][pos] = {
                "n": len(g), "median_projected_value_rank": float(np.median([x["value_rank"] for x in g])),
                "median_projection_rank": float(np.median([x["proj_rank"] for x in g])),
                "in_top3_projected_value": round(mean(x["value_rank"] <= 3 for x in g), 3),
                "from_top3_total_games": round(mean((x["game_rank"] or 99) <= 3 for x in g), 3),
                "avg_projected_ownership": round(mean(x["own"] for x in g), 1),
                "avg_beat_projection_by": round(mean(x["actual"] - x["proj"] for x in g), 1)}
    return out


def app_saved() -> dict:
    """The app's saved 2026 lineups: projected vs actual vs the hindsight best."""
    d = json.loads((ROOT / "data" / "optimal_lineups.json").read_text())
    rows = []
    for season, weeks in d.items():
        if season.startswith("_"):
            continue
        for w, slates in weeks.items():
            for sid, rec in slates.items():
                if not isinstance(rec, dict) or not rec.get("hindsight") or not sid.startswith("classic"):
                    continue
                best = sum(p.get("actual") or 0 for p in rec["hindsight"]["players"])
                for lu in rec.get("lineups") or []:
                    ps = lu["players"]
                    if any(p.get("actual") is None for p in ps):
                        continue
                    qb = next((p for p in ps if p["position"] == "QB"), None)
                    rows.append({"week": int(w), "slate": sid, "metric": lu["metric"],
                                 "proj": round(sum(p.get(lu["metric"]) or 0 for p in ps), 1),
                                 "proj_points": round(sum(p.get("proj_points") or 0 for p in ps), 1),
                                 "actual": round(sum(p["actual"] for p in ps), 1), "best": round(best, 1),
                                 "qb_stacked": sum(1 for p in ps if qb and p["team"] == qb["team"] and p["position"] in ("WR", "TE")),
                                 "games_used": len({p.get("game_info") for p in ps}),
                                 "players_overlapping_best": len({p["dk_draftable_id"] for p in ps} & {p["dk_draftable_id"] for p in rec["hindsight"]["players"]})})
    return {"lineups": sorted(rows, key=lambda r: (r["slate"], r["metric"], r["week"])),
            "summary": {m: {"n": len(g), "avg_projected_points": round(mean(r["proj_points"] for r in g), 1),
                            "avg_actual": round(mean(r["actual"] for r in g), 1), "avg_best_possible": round(mean(r["best"] for r in g), 1),
                            "avg_share_of_best": round(mean(r["actual"] / r["best"] for r in g), 3),
                            "beat_projection": round(mean(r["actual"] > r["proj_points"] for r in g), 3),
                            "avg_players_in_best": round(mean(r["players_overlapping_best"] for r in g), 2),
                            "avg_qb_pass_catchers": round(mean(r["qb_stacked"] for r in g), 2)}
                        for m in ("proj_points", "ceiling") for g in [[r for r in rows if r["metric"] == m]] if g}}


def main():
    bt = Path(sys.argv[1])
    res = slate_analysis(bt)
    out = {"app_saved_2026": app_saved(), "backtest_slates": summarize(res)}
    OUT.write_text(json.dumps(out, indent=1, default=float))
    print(json.dumps(out["app_saved_2026"]["summary"], indent=1))
    print(json.dumps(out["backtest_slates"], indent=1, default=float))


if __name__ == "__main__":
    main()
