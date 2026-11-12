"""Part 3 of scripts.test_fast_starts: the pre-game expected first-quarter margin as player-correction inputs.

q1_trail_x_pass: the team's expected first-quarter deficit (minus scripts.test_fast_starts' q1_exp_margin) for
QB / WR / TE; q1_trail_x_rb: the same for running backs. Zero before week 4 (no rating yet). Train 2023-2025, each
season held out in turn, and 2026 -- against the current app.player_model inputs.
"""
from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd

from scripts import test_defensive_injuries as tdi
from scripts import train_player_model as tpm
from scripts.train_game_model import REL, fetch
from app import player_model as pm

TRAIN, TEST = (2023, 2024, 2025), 2026
FEATS = ("q1_trail_x_pass", "q1_trail_x_rb")


def rows(d: Path, season: int, weeks, rating: dict) -> list[dict]:
    st = csv.DictReader(open(fetch(f"{REL}/stats_player/stats_player_week_{season}.csv",
                                   d / f"stats_player_week_{season}.csv"), newline=""))
    team = {(int(s["week"]), pm.key(s["player_display_name"], s["position"])): s["team"].replace("LAR", "LA")
            for s in st if s.get("week") and s.get("season_type", "REG") == "REG"}
    out = []
    for r in tpm.player_weeks(d, season, weeks):
        if r["week"] < 2:
            continue
        t = team.get((r["week"], r["key"]))
        q = rating.get((season, r["week"], t))
        trail = -q if q is not None else 0.0
        f = {**r["f"], "q1_trail_x_pass": trail if r["pos"] in ("QB", "WR", "TE") else 0.0,
             "q1_trail_x_rb": trail if r["pos"] == "RB" else 0.0}
        out.append({"season": season, "week": r["week"], "key": r["key"], "pos": r["pos"], "f": f, "proj": r["proj"],
                    "actual": r["actual"], "rated": q is not None})
    return out


def run(d: Path, r: pd.DataFrame, test_weeks: int) -> dict:
    rating = {(int(x.season), int(x.week), x.team): float(x.q1_exp_margin) for x in r.itertuples()}
    train = [x for s in TRAIN for x in rows(d, s, range(1, 19), rating)]
    test = rows(d, TEST, range(1, test_weeks + 1), rating)
    big = lambda x: abs(x["f"]["q1_trail_x_pass"] + x["f"]["q1_trail_x_rb"]) >= 2.0  # noqa: E731
    return {"rows": {"train": len(train), "test": len(test), "train_rated": sum(x["rated"] for x in train),
                     "test_rated": sum(x["rated"] for x in test)},
            "subset": "|expected Q1 margin| >= 2 points",
            "test": tdi.feature_test(train, test, FEATS, big)}
