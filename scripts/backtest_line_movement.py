"""Line-movement study: does the move from the opening to the closing line tell us where the game lands?

Source: snaketron/NFL `nfl.csv` (GitHub; ~2006-2019 games with opening / min / max / closing spread and total).
Download it to data/cache/train/line_history.csv first:
    curl -L -o data/cache/train/line_history.csv https://raw.githubusercontent.com/snaketron/NFL/master/nfl.csv
Needs pandas (analysis only). Run:  python -m scripts.backtest_line_movement
Writes data/line_movement.json.

Spread: home_line is the home team's handicap (positive = underdog), so the home team is expected to win by
-home_line and the home margin is home_score - away_score.
Questions:
  1. Does the final score land BETWEEN the opening and closing line more often than chance, and does that grow with the move?
  2. Direction: how often does the result beat the closing number on the side the line moved toward, by move size?
  3. Slope of (result - open) on the move: 1.0 = the close fully captures the information, above 1 = the market
     under-reacted (momentum), below 1 = over-reacted; where does the relationship flatten?
  4. Are games with no move, or that moved and came back (big min/max range, small open->close move), more variable?
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

SRC = Path(__file__).resolve().parents[1] / "data" / "cache" / "train" / "line_history.csv"
OUT = Path(__file__).resolve().parents[1] / "data" / "line_movement.json"
BUCKETS = [(0, 0), (0.5, 1), (1.5, 2), (2.5, 99)]       # |move| in points, inclusive on both ends; 0 = no move


def load() -> pd.DataFrame:
    d = pd.read_csv(SRC, sep=";")
    d = d[d["Playoff Game?"].isna()].copy()
    d["date"] = pd.to_datetime(d["Date"])
    d["season"] = d.date.dt.year - (d.date.dt.month < 3)
    d["margin"] = d["Home Score"] - d["Away Score"]
    d["total_pts"] = d["Home Score"] + d["Away Score"]
    # expected home margin = -home_line
    d["s_open"], d["s_close"] = -d["Home Line Open"], -d["Home Line Close"]
    d["s_min"], d["s_max"] = -d["Home Line Max"], -d["Home Line Min"]
    d["t_open"], d["t_close"] = d["Total Score Open"], d["Total Score Close"]
    d["t_min"], d["t_max"] = d["Total Score Min"], d["Total Score Max"]
    return d.dropna(subset=["s_open", "s_close", "t_open", "t_close", "margin"])


def bucket(m: float) -> str | None:
    a = abs(m)
    for lo, hi in BUCKETS:
        if lo <= a <= hi:
            return f"{lo:g}" if lo == hi else f"{lo:g}-{hi:g}" if hi < 99 else f"{lo:g}+"
    return None        # in-between values such as 0.25 / 1.25 do not occur in whole/half-point lines


def study(d: pd.DataFrame, kind: str) -> dict:
    o, c, res = (d["t_open"], d["t_close"], d["total_pts"]) if kind == "total" else (d["s_open"], d["s_close"], d["margin"])
    lo, hi = ((d["t_min"], d["t_max"]) if kind == "total" else (d["s_min"], d["s_max"]))
    move = c - o
    x = pd.DataFrame({"move": move, "bucket": move.map(bucket), "open": o, "close": c, "res": res,
                      "range": hi - lo}).dropna(subset=["bucket"])
    x["miss_close"] = (x.res - x.close).abs()
    x["miss_open"] = (x.res - x.open).abs()
    out = {"n": int(len(x)), "buckets": {}}
    for b, g in x.groupby("bucket", sort=False):
        moved = g[g.move != 0]
        side = np.sign(moved.move)                      # direction the line moved: + = total up / home more favored
        beat = np.sign(moved.res - moved.close)          # result relative to the closing number
        decided = moved[beat != 0]
        agree = (np.sign(decided.res - decided.close) == np.sign(decided.move)).mean() if len(decided) else float("nan")
        lo_, hi_ = np.minimum(g.open, g.close), np.maximum(g.open, g.close)
        between = ((g.res >= lo_) & (g.res <= hi_)).mean()
        out["buckets"][b] = dict(
            n=int(len(g)), move_follows_pct=None if moved.empty else round(float(agree) * 100, 1), n_decided=int(len(decided)),
            lands_between_pct=None if b == "0" else round(float(between) * 100, 1),   # open == close: not meaningful
            mean_miss_close=round(float(g.miss_close.mean()), 2),
            sd_res_minus_close=round(float((g.res - g.close).std()), 2),
            slope_res_open_on_move=None if len(g) < 30 or g.move.std() == 0 else round(float(np.polyfit(g.move, g.res - g.open, 1)[0]), 2))
    mv = x[x.move != 0]
    out["overall_slope_res_open_on_move"] = round(float(np.polyfit(mv.move, mv.res - mv.open, 1)[0]), 2)
    out["overall_corr_res_close_vs_move"] = round(float(np.corrcoef(mv.move, mv.res - mv.close)[0, 1]), 3)
    still = x[(x.move == 0) & (x.range == 0)]
    flat_wiggle = x[(x.move == 0) & (x.range >= (2 if kind == "total" else 1.5))]
    out["variance"] = {
        "no_move_no_range": dict(n=int(len(still)), sd_res_minus_close=round(float((still.res - still.close).std()), 2)),
        "no_net_move_but_wiggled": dict(n=int(len(flat_wiggle)), sd_res_minus_close=round(float((flat_wiggle.res - flat_wiggle.close).std()), 2)) if len(flat_wiggle) else None,
        "moved_2_plus": dict(n=int((x.move.abs() >= 2).sum()), sd_res_minus_close=round(float((x[x.move.abs() >= 2].res - x[x.move.abs() >= 2].close).std()), 2)),
    }
    return out


def main() -> None:
    d = load()
    report = {"seasons": [int(d.season.min()), int(d.season.max())], "games": int(len(d)),
              "spread": study(d, "spread"), "total": study(d, "total")}
    OUT.write_text(json.dumps(report, indent=1, default=float))
    print(json.dumps(report, indent=1, default=float))


if __name__ == "__main__":
    main()
