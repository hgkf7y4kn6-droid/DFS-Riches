"""Fit the cash model (app.cash_model) and write data/cash_model.json.

    python -m scripts.train_cash_model [--through-season 2026]

Uses the app's own loaders (app.player_games index, nflverse team stats and closing lines), so training and live use build
the same features from the same data. For each player-game with at least 4 earlier games it builds the features from the
earlier games only, fits a ridge regression per position (standardized inputs, penalty 20) on every eligible row, and
reports a holdout first: train on seasons before the test season, score the test season (2025, then 2026 so far) against
the repo-like baseline (trailing-8 DK points + implied total + expected margin, ordinary least squares).
"""
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from statistics import median

import numpy as np

from app import cash_model as cm
from app import nflverse_client as nc
from app import player_games
from app.config import DATA_DIR

RIDGE = 20.0
BASELINE = ["mu8", "impl", "fav_margin"]


async def load(through: int) -> tuple[dict, dict]:
    """(player_key -> games, (season, week, team) -> (implied total, expected margin))."""
    players: dict[str, dict] = {}
    plays: dict = {}
    for season in range(2024, through + 1):
        index = await player_games.get_index(season)
        for key, games in index["players"].items():
            slot = players.setdefault(key, {})
            for g in games:
                slot[(g["season"], g["week"])] = g
        plays.update(await cm.team_plays_by_week(season))
    lines = {}
    for season in range(2023, through + 1):
        for (week, away, home), g in (await nc.get_games(season)).items():
            spread, total = g.get("spread_line"), g.get("total_line")   # spread_line > 0: the home team is favored
            if spread is None or total is None:
                continue
            lines[(season, week, home)] = (round((total + spread) / 2, 2), spread)
            lines[(season, week, away)] = (round((total - spread) / 2, 2), -spread)
    games = cm.build_games({k: list(v.values()) for k, v in players.items()}, plays)
    return games, lines


def rows_for(games: dict, lines: dict) -> list[dict]:
    out = []
    for key, gs in games.items():
        position = key.rsplit("|", 1)[1]
        if position not in cm.FEATURES:
            continue
        for i in range(cm.MIN_PRIOR, len(gs)):
            g = gs[i]
            line = lines.get((g["season"], g["week"], g.get("team")))
            if line is None:
                continue
            f = cm.features(gs[:i], position, line[0], line[1])
            if f is not None:
                out.append({"pos": position, "season": g["season"], "week": g["week"], "y": g["dk"], **f})
    return out


def fit(rows: list[dict], cols: list[str], ridge: float = RIDGE) -> dict:
    med = {c: median([r[c] for r in rows if r[c] is not None] or [0.0]) for c in cols}
    X = np.array([[med[c] if r[c] is None else r[c] for c in cols] for r in rows], dtype=float)
    y = np.array([r["y"] for r in rows], dtype=float)
    mean, sd = X.mean(0), X.std(0) + 1e-9
    A = np.c_[np.ones(len(X)), (X - mean) / sd]
    R = ridge * np.eye(A.shape[1])
    R[0, 0] = 0
    beta = np.linalg.solve(A.T @ A + R, A.T @ y)
    return {"features": cols, "median": med, "mean": dict(zip(cols, mean.tolist())), "sd": dict(zip(cols, sd.tolist())),
            "coef": {"c": float(beta[0]), **dict(zip(cols, beta[1:].tolist()))}, "n": len(rows)}


def predict_rows(model: dict, rows: list[dict]) -> np.ndarray:
    return np.array([cm.predict({"positions": {"x": model}}, "x", r) for r in rows])


def holdout(rows: list[dict]) -> dict:
    report = {}
    for test_season in (2025, 2026):
        tr = [r for r in rows if r["season"] < test_season]
        te = [r for r in rows if r["season"] == test_season]
        if not te or not tr:
            continue
        for pos in cm.FEATURES:
            a, b = [r for r in tr if r["pos"] == pos], [r for r in te if r["pos"] == pos]
            if len(a) < 200 or not b:
                continue
            y = np.array([r["y"] for r in b])
            m_cash, m_base = fit(a, cm.FEATURES[pos]), fit(a, BASELINE, ridge=0.0)
            report[f"{test_season}_{pos}"] = {
                "n": len(b), "mae_cash": round(float(np.abs(predict_rows(m_cash, b) - y).mean()), 3),
                "mae_baseline": round(float(np.abs(predict_rows(m_base, b) - y).mean()), 3),
                "mae_trailing6": round(float(np.abs(np.array([r["mu6"] for r in b]) - y).mean()), 3)}
    return report


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--through-season", type=int, default=2026)
    args = parser.parse_args()
    games, lines = await load(args.through_season)
    # each game needs its team to find the line: carry it from the index rows
    index_teams = {}
    for season in range(2024, args.through_season + 1):
        for key, gs in (await player_games.get_index(season))["players"].items():
            for g in gs:
                index_teams[(key, g["season"], g["week"])] = g["team"]
    for key, gs in games.items():
        for g in gs:
            g["team"] = index_teams.get((key, g["season"], g["week"]))
    rows = rows_for(games, lines)
    print(f"{len(rows)} eligible player-games")
    report = holdout(rows)
    for k, v in report.items():
        print(k, v)
    model = {
        "version": 1,
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "trained_through_season": args.through_season,
        "ridge": RIDGE,
        "holdout_mae": report,
        "positions": {pos: fit([r for r in rows if r["pos"] == pos], cols) for pos, cols in cm.FEATURES.items()},
    }
    (DATA_DIR / "cash_model.json").write_text(json.dumps(model, indent=2) + "\n")
    print("wrote data/cash_model.json")


if __name__ == "__main__":
    asyncio.run(main())
