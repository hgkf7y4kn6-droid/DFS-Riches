"""Fit the kicker projection (app.kicker_model) on cached play-by-play and write data/kicker_model.json.

    python -m scripts.train_kicker_model [--data DIR]

DIR (default data/cache/train) must hold play_by_play_{year}.csv.gz for 2016 onward and games.csv (the files the other
train_* scripts download). A kicker-week's DK points come from the plays: +1 per PAT made, +3 per FG made under 40
yards, +4 for 40-49, +5 for 50+ (the same scoring as app.dk_scoring.dk_kicker_points). Kickers' true talent varies very
little week to week, so the model is a heavy shrinkage of the season-to-date average toward the league average, plus
a small adjustment for the team's expected margin and implied total. The shrinkage (K, in games of league-average
evidence) is chosen by leaving one season out; the adjustment is a ridge regression on what the shrunk average misses.
The record in the file compares it, leave-one-season-out 2019-2026, with the flat season average the app used before.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
FIRST_YEAR, TEST_FROM = 2016, 2019
MIN_GAMES = 3                      # evaluate only kickers with this many games already this season
K_GRID = (0.5, 3, 6, 12, 20, 30, 40, 60, 100)
IMPLIED_CENTER = 22.5
RIDGE = 100.0


def kicker_weeks(d: Path) -> list[dict]:
    """One row per kicker-team-week: DK points, plus the team's implied total and expected margin (closing line)."""
    pts: dict[tuple, float] = defaultdict(float)
    for year in range(FIRST_YEAR, 2100):
        path = d / f"play_by_play_{year}.csv.gz"
        if not path.exists():
            break
        with gzip.open(path, "rt", newline="") as f:
            for p in csv.DictReader(f):
                if p["season_type"] != "REG" or p["play_type"] not in ("field_goal", "extra_point") or not p["kicker_player_id"]:
                    continue
                k = (year, int(p["week"]), p["posteam"], p["kicker_player_id"])
                if p["play_type"] == "extra_point":
                    pts[k] += 1.0 if p["extra_point_result"] == "good" else 0.0
                else:
                    pts[k] += 0.0
                    if p["field_goal_result"] == "made":
                        dist = float(p["kick_distance"] or 0)
                        pts[k] += 3.0 if dist < 40 else 4.0 if dist < 50 else 5.0
    lines: dict[tuple, tuple] = {}                                  # (season, week, team) -> (implied, margin)
    for g in csv.DictReader(open(d / "games.csv", newline="")):
        if g["game_type"] == "REG" and g["total_line"] and g["spread_line"]:
            y, w, t, s = int(g["season"]), int(g["week"]), float(g["total_line"]), float(g["spread_line"])
            lines[(y, w, g["home_team"])] = ((t + s) / 2, s)
            lines[(y, w, g["away_team"])] = ((t - s) / 2, -s)
    rows = [{"season": y, "week": w, "team": team, "kid": kid, "pts": p, "implied": lines[(y, w, team)][0],
             "spread": lines[(y, w, team)][1]}
            for (y, w, team, kid), p in pts.items() if (y, w, team) in lines]
    rows.sort(key=lambda r: (r["season"], r["week"]))
    return rows


def with_prior(rows: list[dict], league: dict[int, float], k: float) -> list[dict]:
    """Each row's season-to-date shrunk average (games before it this season), with `league[season]` as the mean."""
    seen: dict[tuple, list[float]] = {}
    out = []
    for r in rows:
        h = seen.setdefault((r["kid"], r["season"]), [])
        g = len(h)
        out.append({**r, "games": g, "raw": (sum(h) / g) if g else None,
                    "prior": (sum(h) + k * league[r["season"]]) / (g + k)})
        h.append(r["pts"])
    return out


def trailing_league(rows: list[dict]) -> dict[int, float]:
    """League mean DK points per kicker-week for each season, known beforehand: the mean of the two prior seasons."""
    by: dict[int, list[float]] = defaultdict(list)
    for r in rows:
        by[r["season"]].append(r["pts"])
    seasons = sorted(by)
    out = {}
    for i, s in enumerate(seasons):
        prev = [x for p in seasons[max(0, i - 2):i] for x in by[p]] or by[s]
        out[s] = float(np.mean(prev))
    return out


def design(ds: list[dict]) -> np.ndarray:
    return np.array([[1.0, r["implied"] - IMPLIED_CENTER, r["spread"]] for r in ds])


def fit_adjust(ds: list[dict]) -> np.ndarray:
    y = np.array([r["pts"] - r["prior"] for r in ds])
    x = design(ds)
    return np.linalg.solve(x.T @ x + RIDGE * np.diag([0, 1, 1]), x.T @ y)


def metrics(pred: np.ndarray, actual: np.ndarray) -> dict:
    return {"mae": round(float(np.abs(pred - actual).mean()), 3), "rmse": round(float(np.sqrt(((pred - actual) ** 2).mean())), 3)}


def evaluate(rows: list[dict], league: dict[int, float], k: float) -> dict:
    """Leave one season out, 2019 on: flat raw season average (the old projection) vs the shrunk + adjusted model."""
    flat, model, shrunk, actual = [], [], [], []
    for year in range(TEST_FROM, max(r["season"] for r in rows) + 1):
        rp = with_prior(rows, league, k)
        train = [r for r in rp if r["season"] != year and r["games"] >= MIN_GAMES]
        test = [r for r in rp if r["season"] == year and r["games"] >= MIN_GAMES]
        if not test:
            continue
        b = fit_adjust(train)
        flat += [r["raw"] for r in test]
        shrunk += [r["prior"] for r in test]
        model += list(np.array([r["prior"] for r in test]) + design(test) @ b)
        actual += [r["pts"] for r in test]
    a = np.array(actual)
    return {"n": len(actual), "flat_season_average": metrics(np.array(flat), a), "shrunk_only": metrics(np.array(shrunk), a),
            "model": metrics(np.array(model), a)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(ROOT / "data" / "cache" / "train"))
    args = ap.parse_args()
    rows = kicker_weeks(Path(args.data))
    league = trailing_league(rows)
    scores = {}
    for k in K_GRID:                                   # choose K by leave-one-season-out RMSE of the shrunk average alone
        rp = [r for r in with_prior(rows, league, k) if r["season"] >= TEST_FROM and r["games"] >= MIN_GAMES]
        scores[k] = float(np.sqrt(np.mean([(r["prior"] - r["pts"]) ** 2 for r in rp])))
    k = min(scores, key=scores.get)
    record = evaluate(rows, league, k)
    train = [r for r in with_prior(rows, league, k) if r["games"] >= MIN_GAMES]
    intercept, implied, spread = (float(x) for x in fit_adjust(train))
    last = max(r["season"] for r in rows)
    out = {"k": k, "league_mean": round(float(np.mean([r["pts"] for r in rows if r["season"] >= last - 1])), 3),
           "intercept": round(intercept, 4), "implied": round(implied, 4), "spread": round(spread, 4),
           "implied_center": IMPLIED_CENTER, "record": {"seasons": f"{TEST_FROM}-{last}, one held out at a time", **record,
                                                         "rmse_by_k": {str(a): round(b, 3) for a, b in scores.items()}}}
    (ROOT / "data" / "kicker_model.json").write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    sys.exit(main())
