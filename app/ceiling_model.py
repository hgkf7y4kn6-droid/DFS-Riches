"""Ceiling: a player's 85th-percentile DraftKings score this week, from a quantile regression fit on 2023-2025.

One linear quantile regression per position (QB / RB / WR / TE), fit by scripts/train_ceiling_model.py to the
85th percentile of actual DK points (pinball loss) and stored in data/ceiling_model.json with its out-of-sample
record. Inputs, all known before the game:

  proj        this week's projection (Sleeper's line plus the role & script model)
  sd          the spread of the player's last 12 games (this season and last), shrunk toward the position's
              typical spread for his projection over 4 pseudo-games
  p85         his own 85th-percentile game over those 12 (6+ games), else mean + 1.04 x typical spread
  td_share    share of the projection that comes from touchdowns (Sleeper's line)
  rush_share  QB: share of the projection from rushing
  yds         projected yards (rushing + receiving; QB: passing) -- the 100/300-yard bonus path
  implied     the team's implied total; abs_spread how lopsided the game is
  ts_l3, snap_l3  target share and snap share over the last three games

On 2026 Weeks 4-6 it beat the formula ceiling it replaced (history x matchup x environment multipliers) on
pinball loss (1.81 vs 1.91) and caught more of each week's top-10% scorers in its top 20% (60% vs 53%).
DSTs keep app.ceiling's formula.
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path

MODEL_FILE = Path(__file__).resolve().parent.parent / "data" / "ceiling_model.json"
HISTORY_GAMES = 12
PRIOR_GAMES = 4
Z_85 = 1.04

_MODEL: dict | None = None


def load() -> dict | None:
    global _MODEL
    if _MODEL is None and MODEL_FILE.exists():
        _MODEL = json.loads(MODEL_FILE.read_text())
    return _MODEL


def inputs(position: str, proj: float, history: list[float], line: dict | None, implied: float | None,
           spread: float | None, ts_l3: float = 0.0, snap_l3: float = 0.0, model: dict | None = None) -> dict | None:
    """The model's inputs for one player. history: DK points of his recent games, oldest first (the last
    HISTORY_GAMES are used); line: Sleeper's projected stat line."""
    m = model or load()
    if not m or position not in m.get("cv_pos", {}):
        return None
    cv = m["cv_pos"][position]
    pts = history[-HISTORY_GAMES:]
    n = len(pts)
    mean = statistics.fmean(pts) if pts else proj
    sd = statistics.pstdev(pts) if n >= 2 else cv * proj
    g = lambda k: float((line or {}).get(k) or 0)  # noqa: E731
    td_pts = 6 * (g("rush_td") + g("rec_td")) + 4 * g("pass_td")
    return {
        "proj": proj,
        "sd": (n * sd + PRIOR_GAMES * cv * proj) / (n + PRIOR_GAMES),
        "p85": sorted(pts)[int(0.85 * (n - 1))] if n >= 6 else mean * (1 + Z_85 * cv),
        "td_share": td_pts / proj if proj else 0.0,
        "rush_share": (g("rush_yd") * 0.1 + 6 * g("rush_td")) / proj if proj else 0.0,
        "yds": g("pass_yd") if position == "QB" else g("rec_yd") + g("rush_yd"),
        "implied": implied if implied is not None else 22.0,
        "abs_spread": abs(spread or 0.0),
        "ts_l3": ts_l3 or 0.0, "snap_l3": snap_l3 or 0.0,
        "n_games": n,
    }


def ceiling(position: str, x: dict | None, model: dict | None = None) -> float | None:
    """The 85th-percentile DK score (never below the projection), or None without a fitted model."""
    m = model or load()
    p = (m or {}).get("positions", {}).get(position)
    if not p or not x:
        return None
    v = p["b"][0] + sum(b * (x[f] - mu) / sd for f, b, mu, sd in zip(p["features"], p["b"][1:], p["mu"], p["sd"]))
    return round(max(x["proj"], v), 1)


def notes(value: float, x: dict, position: str) -> list[str]:
    n = x["n_games"]
    passing = position == "QB"
    hist = f"spread {x['sd']:.1f} over the last {n} game{'s' if n != 1 else ''}" if n else "no recent games (position spread)"
    parts = [f"Ceiling model: {value:.1f} (85th percentile) from projection {x['proj']:.1f}, {hist}"]
    if x["td_share"] >= 0.4:
        parts.append(f"{x['td_share']:.0%} of the projection is touchdowns (boom-or-bust)")
    if x["yds"] >= (270 if passing else 85):
        parts.append(f"{x['yds']:.0f} projected {'passing ' if passing else ''}yards (near the {'300' if passing else '100'}-yard bonus)")
    parts.append(f"team implied {x['implied']:g}")
    return ["; ".join(parts)]
