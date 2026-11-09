"""Cash model v2: a fitted projection for the Safe (cash) lineup, behind a flag.

Off by default. Turn it on with the environment variable CASH_MODEL=v2; the Safe lineup (and only that lineup) is then
built on this model's points instead of the app's blended projection.

What it is. A ridge regression per position (data/cash_model.json, fit by scripts/train_cash_model.py) on a player's
games before the week, using only features that were backtested:

  RB/WR/TE: trailing-8 DK points, the team's implied total, snap share (last 6), touches per team play (last 6) and its
            recent trend. QB: trailing-8 DK points, implied total, expected margin, rushing attempts, pass attempts.

Backtest (2025 + 2026 Weeks 1-9, 27 weeks, salaries proxied from trailing production because DraftKings keeps no price
history): the Safe lineup built on these points scored about +10 to +18 DK points a lineup more than one built on a
trailing-8-plus-Vegas baseline (two implementations of the same model; 90% intervals roughly +2 to +27, so the size is
uncertain though the sign held in both seasons), and its projection stopped overstating the lineup (about 13 points
high for the baseline, about 2 for this model). Holdout accuracy per position is in data/cash_model.json. A richer version
that also used red-zone-weighted opportunity (WOV) and a consistency factor from play-by-play gained about +17 in
the first implementation; that is not built here.

Rules that were part of the tested lineup, kept here:
  - eligible only with at least 4 prior games and a trailing-6 average of 5+ DK points (QB 10+): no rookies or new roles;
  - an RB/WR/TE needs a trailing-6 snap share of at least 60%;
  - a player priced under $4,000 also needs a projection of at least 8 (QBs exempt);
  - the DST keeps the app's projection (the model does not cover it).

The model replaces, not blends with, the app's projection: the app's own projections have no history to backtest, so the
backtest baseline was a trailing-average-plus-Vegas projection. Treat the flag as an experiment until real DraftKings
salaries (data/salaries/) give a backtest at true prices.
"""
from __future__ import annotations

import json
import os
from statistics import fmean

from app import nflverse_client as nc
from app import player_games
from app.config import DATA_DIR

MODEL_PATH = DATA_DIR / "cash_model.json"
SKILL = ("RB", "WR", "TE")
MIN_PRIOR = 4
MIN_TRAIL = {"QB": 10.0, "RB": 5.0, "WR": 5.0, "TE": 5.0}   # trailing-6 DK average that counts as a real role
MIN_SNAP = 0.60                                              # trailing-6 offensive snap share (RB/WR/TE; the QB is exempt)
CHEAP_SALARY = 4000
CHEAP_MIN_PROJ = 8.0
FEATURES = {
    "QB": ["mu8", "impl", "fav_margin", "car_mu", "att_mu"],
    "RB": ["mu8", "impl", "snap", "os_mu", "trend"],
    "WR": ["mu8", "impl", "snap", "os_mu", "trend"],
    "TE": ["mu8", "impl", "snap", "os_mu", "trend"],
}

_model: dict | None = None


def enabled() -> bool:
    return os.environ.get("CASH_MODEL", "").strip().lower() in ("v2", "1", "on", "true")


def load() -> dict | None:
    global _model
    if _model is None and MODEL_PATH.exists():
        _model = json.loads(MODEL_PATH.read_text())
    return _model


def _tail_mean(vals: list, n: int, minimum: int) -> float | None:
    vals = [v for v in vals[-n:] if v is not None]
    return fmean(vals) if len(vals) >= minimum else None


def features(prior: list[dict], position: str, impl: float | None, margin: float | None) -> dict | None:
    """The model's inputs from a player's earlier games (oldest first), or None when he's not eligible.

    A game is {"dk", "snap" (0-1 or None), "os" (touches / team plays or None), "car", "att"}."""
    if len(prior) < MIN_PRIOR:
        return None
    mu6 = _tail_mean([g["dk"] for g in prior], 6, MIN_PRIOR)
    if mu6 is None or mu6 < MIN_TRAIL[position]:
        return None
    os_all = [g.get("os") for g in prior]
    os_mu = _tail_mean(os_all, 6, 3)
    os_3 = _tail_mean(os_all, 3, 2)
    return {
        "mu6": mu6,
        "mu8": _tail_mean([g["dk"] for g in prior], 8, MIN_PRIOR),
        "impl": impl,
        "fav_margin": margin,
        "snap": _tail_mean([g.get("snap") for g in prior], 6, 3),
        "os_mu": os_mu,
        "trend": None if os_mu is None or os_3 is None else min(2.0, max(0.3, os_3 / max(os_mu, 0.01))),
        "car_mu": _tail_mean([g.get("car") for g in prior], 6, 3),
        "att_mu": _tail_mean([g.get("att") for g in prior], 6, 3),
    }


def predict(model: dict, position: str, feats: dict) -> float:
    """Standardized ridge prediction; a missing input takes the training median."""
    m = model["positions"][position]
    z = m["coef"]["c"]
    for f in m["features"]:
        v = feats.get(f)
        v = m["median"][f] if v is None else v
        z += m["coef"][f] * (v - m["mean"][f]) / m["sd"][f]
    return z


def build_games(index_players: dict, team_plays: dict) -> dict[str, list[dict]]:
    """player_key -> chronological game dicts (see features), from app.player_games' index and
    {(season, week, team): team plays} (attempts + carries + sacks)."""
    out: dict[str, list[dict]] = {}
    for key, games in index_players.items():
        rows = []
        for g in games:
            st = g.get("stats") or {}
            rush = (st.get("rushing") or {}).get("att", 0)
            tgt = (st.get("receiving") or {}).get("tgt", 0)
            plays = team_plays.get((g["season"], g["week"], g["team"]))
            snap = g.get("snap_pct")
            rows.append({
                "season": g["season"], "week": g["week"], "dk": g["dk_points"],
                "snap": None if snap is None else snap / 100.0,
                "os": (rush + tgt) / plays if plays else None,
                "car": rush, "att": (st.get("passing") or {}).get("att"),
            })
        rows.sort(key=lambda r: (r["season"], r["week"]))
        out[key] = rows
    return out


async def team_plays_by_week(season: int) -> dict:
    out = {}
    for szn in (season - 1, season):
        for row in await nc._fetch_team_week_rows(szn):
            w = nc._to_int(row.get("week"))
            if w is None or row.get("season_type", "REG") != "REG":
                continue
            plays = sum(nc._to_float(row.get(c)) or 0.0 for c in ("attempts", "carries", "sacks_suffered"))
            out[(szn, w, nc.to_app_team(row.get("team", "")))] = plays
    return out


async def context(season: int) -> dict[str, list[dict]]:
    index = await player_games.get_index(season)
    return build_games(index["players"], await team_plays_by_week(season))


def team_lines(slate) -> dict[str, tuple[float, float]]:
    """team -> (implied total, expected margin; positive when favored) for the slate's games."""
    out = {}
    for g in slate.games:
        c = g.context
        if c and c.home_spread is not None and c.home_implied_total is not None:
            out[g.home] = (c.home_implied_total, -c.home_spread)
            out[g.away] = (c.away_implied_total, c.home_spread)
    return out


async def projections(season: int, week: int, players: list, slate) -> dict:
    """DK draftable id -> {"proj": cash points, "snap": trailing snap share} for the slate's players the model covers.
    A QB/RB/WR/TE it does not cover (too little history, a small role, no line) is absent, so the Safe lineup cannot
    pick him; the DST is covered by the app's own projection."""
    model = load()
    if model is None:
        return {}
    games = await context(season)
    lines = team_lines(slate)
    out = {}
    for p in players:
        pos = p.position
        if pos == "DST":
            out[p.dk_draftable_id] = {"proj": p.proj_points, "snap": None}
            continue
        if pos not in FEATURES or p.team not in lines:
            continue
        prior = [g for g in games.get(nc.player_key(p.name, pos), []) if (g["season"], g["week"]) < (season, week)]
        impl, margin = lines[p.team]
        feats = features(prior, pos, impl, margin)
        if feats is None:
            continue
        out[p.dk_draftable_id] = {"proj": round(predict(model, pos, feats), 2), "snap": feats["snap"]}
    return out


def eligible(position: str, salary: float, proj: float, snap: float | None) -> bool:
    """The tested lineup's stability filters for one covered player."""
    if position in ("QB", "DST"):
        return True
    if snap is None or snap < MIN_SNAP:
        return False
    return not (salary < CHEAP_SALARY and proj < CHEAP_MIN_PROJ)
