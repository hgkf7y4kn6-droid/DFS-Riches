"""Where workhorse pass-catching backs and mobile quarterbacks differ: outcome shape and correlation, not the average.

    python -m scripts.test_archetype_distributions [--data DIR]

The average projection already prices both archetypes (scripts.test_backfield_archetypes, scripts.test_mobile_qbs).
This tests the two places the app ignores them:

  A. Floor / median / ceiling. The app scales each projection by its position's 15th / 50th / 85th percentile
     outcome multiples for the projection range (app.dfs_model.calibration). Here the same multiples are fit by
     position and range, then by position, range and archetype; graded on pinball loss and coverage (the share of
     games under the floor should be 15%, over the ceiling 15%), each of 2023-2025 held out in turn and 2026.
  B. Correlation. Same-game residual correlations (actual minus the app's corrected projection): QB with his top
     two pass catchers and his lead back, by QB archetype; lead backs with their QB by RB archetype; and how
     often QB and pass catcher both hit 1.5x their projections together. The app's lineup checks give every QB
     the same credit per stacked receiver.
  C. Game script. Backs' residuals against the final margin and the pre-game spread, by archetype.

Archetypes, from Sleeper's projected line before the game:
  RB  workhorse pass catcher: 12+ projected carries and 3.5+ targets; workhorse grinder: 12+ carries, fewer
      targets; receiving back: under 12 carries, 40%+ of the projection from receiving; other
  QB  mobile: 25%+ of the projection from rushing; some legs: 12-25%; pocket: under 12%
Writes data/archetype_distribution_tests.json.
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path

import numpy as np

from app import game_model as gm, player_model as pm, projections
from scripts import train_player_model as tpm
from scripts.train_game_model import GAMES_URL, REL, fetch

OUT = Path(__file__).resolve().parent.parent / "data" / "archetype_distribution_tests.json"
TRAIN, TEST = (2023, 2024, 2025), 2026
QS = (0.15, 0.50, 0.85)
BUCKETS = (0, 5, 10, 15, 20, 25, 99)
MIN_CELL = 60


def f(x) -> float:
    return gm._f(x) or 0.0


def mean(xs, default=0.0):
    xs = list(xs)
    return statistics.fmean(xs) if xs else default


def archetype(pos: str, line: dict, raw: float) -> str:
    g = lambda k: f(line.get(k))  # noqa: E731
    if pos == "RB":
        rec_share = (g("rec") + 0.1 * g("rec_yd") + 6 * g("rec_td")) / raw if raw else 0.0
        if g("rush_att") >= 12:
            return "workhorse pass catcher" if g("rec_tgt") >= 3.5 else "workhorse grinder"
        return "receiving back" if rec_share >= 0.40 else "other RB"
    if pos == "QB":
        rush = (0.1 * g("rush_yd") + 6 * g("rush_td")) / raw if raw else 0.0
        return "mobile QB" if rush >= 0.25 else "some legs QB" if rush >= 0.12 else "pocket QB"
    return pos


def bucket(proj: float) -> str:
    for lo, hi in zip(BUCKETS, BUCKETS[1:]):
        if proj < hi:
            return f"{lo}-{hi}"
    return "25-99"


def rows(d: Path, season: int, weeks) -> list[dict]:
    with open(fetch(f"{REL}/stats_player/stats_player_week_{season}.csv", d / f"stats_player_week_{season}.csv"), newline="") as fh:
        st = {(int(s["week"]), pm.key(s["player_display_name"], s["position"])): s
              for s in csv.DictReader(fh) if s.get("season_type", "REG") == "REG" and s.get("week")}
    margin = {}
    with open(fetch(GAMES_URL, d / "games.csv"), newline="") as fh:
        for g in csv.DictReader(fh):
            if g["season"] == str(season) and g["game_type"] == "REG" and g["home_score"]:
                m = float(g["home_score"]) - float(g["away_score"])
                margin[(int(g["week"]), g["home_team"])] = m
                margin[(int(g["week"]), g["away_team"])] = -m
    out = []
    for r in tpm.player_weeks(d, season, weeks):
        s = st.get((r["week"], r["key"]))
        if not s or r["week"] < 2:
            continue
        raw = projections.dk_points_from_line(r["line"], r["pos"]) or r["proj"]
        corrected = max(0.5, r["proj"] + (pm.adjustment(r["pos"], r["f"]) or 0.0))
        out.append({"season": season, "week": r["week"], "key": r["key"], "pos": r["pos"], "team": s["team"],
                    "proj": corrected, "actual": r["actual"], "arch": archetype(r["pos"], r["line"], raw),
                    "spread": r["spread"] or 0.0, "margin": margin.get((r["week"], s["team"]))})
    return out


# ------------------------------------------------------------------ A. quantile multiples
def fit_multiples(train: list[dict], by_arch: bool) -> dict:
    cells = defaultdict(list)
    for r in train:
        ratio = r["actual"] / r["proj"]
        cells[(r["pos"], bucket(r["proj"]))].append(ratio)
        if by_arch:
            cells[(r["pos"], bucket(r["proj"]), r["arch"])].append(ratio)
            cells[(r["pos"], r["arch"])].append(ratio)
    return {k: [float(np.quantile(v, q)) for q in QS] for k, v in cells.items() if len(v) >= MIN_CELL} | {
        ("n", k): len(v) for k, v in cells.items()}


def multiples_for(m: dict, r: dict, by_arch: bool) -> list[float]:
    base = m.get((r["pos"], bucket(r["proj"])))
    if base is None:      # nearest range with enough games
        cands = [k for k in m if isinstance(k, tuple) and len(k) == 2 and k[0] == r["pos"] and k[1] != "n" and "-" in str(k[1])]
        base = m[min(cands, key=lambda k: abs(int(k[1].split("-")[0]) - int(bucket(r["proj"]).split("-")[0])))]
    if not by_arch:
        return base
    cell = m.get((r["pos"], bucket(r["proj"]), r["arch"]))
    if cell is not None:
        return cell
    # sparse cell: the archetype's shift across ranges applied to this range
    arch, pos_all = m.get((r["pos"], r["arch"])), None
    if arch is None:
        return base
    pos_all = [mean(v[i] for k, v in m.items() if isinstance(k, tuple) and len(k) == 2 and k[0] == r["pos"] and "-" in str(k[1]))
               for i in range(3)]
    return [b * a / p if p else b for b, a, p in zip(base, arch, pos_all)]


def grade(test: list[dict], m: dict, by_arch: bool, groups) -> dict:
    out = {}
    for name, sel in groups.items():
        sub = [r for r in test if sel(r)]
        if not sub:
            continue
        res = {"n": len(sub)}
        for i, q in enumerate(QS):
            pred = np.array([multiples_for(m, r, by_arch)[i] * r["proj"] for r in sub])
            y = np.array([r["actual"] for r in sub])
            dd = y - pred
            res[f"pinball_{int(q * 100)}"] = round(float(np.mean(np.maximum(q * dd, (q - 1) * dd))), 3)
            res[f"below_q{int(q * 100)}"] = round(float(np.mean(y < pred)), 3)
        out[name] = res
    return out


def quantile_test(train: list[dict], test: list[dict], groups) -> dict:
    out = {}
    seasons = sorted({r["season"] for r in train})
    for label, by_arch in (("current (position x range)", False), ("with archetype", True)):
        loso = defaultdict(lambda: defaultdict(float))
        for s in seasons:
            m = fit_multiples([r for r in train if r["season"] != s], by_arch)
            g = grade([r for r in train if r["season"] == s], m, by_arch, groups)
            for name, v in g.items():
                for k, x in v.items():
                    loso[name][k] += x * (1 if k == "n" else v["n"])
        loso_out = {name: {k: (int(x) if k == "n" else round(x / v["n"], 3)) for k, x in v.items()} for name, v in loso.items()}
        out[label] = {"loso": loso_out, "test_2026": grade(test, fit_multiples(train, by_arch), by_arch, groups)}
    return out


# ------------------------------------------------------------------ B. correlation
def corr(a, b):
    return round(float(np.corrcoef(a, b)[0, 1]), 3) if len(a) >= 30 else None


def correlations(rs: list[dict]) -> dict:
    team = defaultdict(list)
    for r in rs:
        team[(r["season"], r["week"], r["team"])].append(r)
    qb_pc = defaultdict(lambda: ([], [], []))      # QB arch -> residual pairs with top-2 WR/TE, joint 1.5x booms
    qb_rb = defaultdict(lambda: ([], []))
    rb_qb = defaultdict(lambda: ([], []))
    qb_pc_raw = defaultdict(lambda: ([], []))
    for g in team.values():
        qbs = sorted((r for r in g if r["pos"] == "QB"), key=lambda r: -r["proj"])
        if not qbs or qbs[0]["proj"] < 10:
            continue
        qb = qbs[0]
        rq = qb["actual"] - qb["proj"]
        pcs = sorted((r for r in g if r["pos"] in ("WR", "TE")), key=lambda r: -r["proj"])[:2]
        for p in pcs:
            a = qb_pc[qb["arch"]]
            a[0].append(rq)
            a[1].append(p["actual"] - p["proj"])
            a[2].append((qb["actual"] >= 1.5 * qb["proj"], p["actual"] >= 1.5 * p["proj"]))
            qb_pc_raw[qb["arch"]][0].append(qb["actual"])
            qb_pc_raw[qb["arch"]][1].append(p["actual"])
        rbs = sorted((r for r in g if r["pos"] == "RB"), key=lambda r: -r["proj"])
        if rbs:
            rb = rbs[0]
            qb_rb[qb["arch"]][0].append(rq)
            qb_rb[qb["arch"]][1].append(rb["actual"] - rb["proj"])
            rb_qb[rb["arch"]][0].append(rb["actual"] - rb["proj"])
            rb_qb[rb["arch"]][1].append(rq)
    out = {"qb_with_top2_pass_catchers": {}, "qb_with_lead_rb_by_qb_type": {}, "lead_rb_with_qb_by_rb_type": {}}
    for k, (a, b, booms) in qb_pc.items():
        qb_boom = [x for x in booms if x[0]]
        out["qb_with_top2_pass_catchers"][k] = {
            "pairs": len(a), "residual_corr": corr(a, b), "raw_points_corr": corr(*qb_pc_raw[k]),
            "catcher_booms_when_qb_booms": round(mean(y for _, y in qb_boom), 3) if qb_boom else None,
            "catcher_boom_rate_overall": round(mean(y for _, y in booms), 3)}
    for k, (a, b) in qb_rb.items():
        out["qb_with_lead_rb_by_qb_type"][k] = {"pairs": len(a), "residual_corr": corr(a, b)}
    for k, (a, b) in rb_qb.items():
        out["lead_rb_with_qb_by_rb_type"][k] = {"pairs": len(a), "residual_corr": corr(a, b)}
    return out


# ------------------------------------------------------------------ C. game script
def game_script(rs: list[dict]) -> dict:
    out = {}
    for a in ("workhorse pass catcher", "workhorse grinder", "receiving back"):
        sub = [r for r in rs if r["arch"] == a and r["margin"] is not None]
        if len(sub) < 30:
            continue
        res = np.array([r["actual"] - r["proj"] for r in sub])
        mg = np.array([r["margin"] for r in sub])
        sp = np.array([r["spread"] for r in sub])
        lose = [r for r in sub if r["margin"] <= -10]
        win = [r for r in sub if r["margin"] >= 10]
        out[a] = {"n": len(sub), "points_per_point_of_final_margin": round(float(np.polyfit(mg, res, 1)[0]), 3),
                  "points_per_point_of_spread": round(float(np.polyfit(sp, res, 1)[0]), 3),
                  "miss_when_losing_by_10plus": round(mean(r["actual"] - r["proj"] for r in lose), 2), "n_losing": len(lose),
                  "miss_when_winning_by_10plus": round(mean(r["actual"] - r["proj"] for r in win), 2), "n_winning": len(win),
                  "bust_rate_losing_by_10plus": round(mean(r["actual"] < 0.5 * r["proj"] for r in lose), 3)}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/cache/train")
    ap.add_argument("--test-weeks", type=int, default=6)
    args = ap.parse_args()
    d = Path(args.data)
    train = [r for s in TRAIN for r in rows(d, s, range(1, 19))]
    test = rows(d, TEST, range(1, args.test_weeks + 1))
    print("rows", len(train), len(test))
    arches = sorted({r["arch"] for r in train if r["pos"] in ("RB", "QB")})
    groups = {"all QB/RB": lambda r: r["pos"] in ("QB", "RB"), "all positions": lambda r: True}
    groups |= {a: (lambda a: lambda r: r["arch"] == a)(a) for a in arches}
    res = {"archetype_counts": {a: sum(r["arch"] == a for r in train + test) for a in arches},
           "A_floor_median_ceiling": quantile_test(train, test, groups),
           "A_multiples_2023_2025": {f"{k[0]}|{k[1]}|{k[2]}" if len(k) == 3 else f"{k[0]}|{k[1]}": [round(x, 3) for x in v]
                                     for k, v in fit_multiples(train, True).items()
                                     if k[0] != "n" and (len(k) == 3 or "-" not in str(k[1])) and k[0] in ("QB", "RB")},
           "B_correlation_2023_2026": correlations(train + test),
           "C_game_script_2023_2026": game_script(train + test)}
    OUT.write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
