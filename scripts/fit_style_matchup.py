"""Fit the style-matchup cells the app shows (data/style_matchup.json), test them as tight-end projection inputs, and
test player archetypes against defensive styles season to season.

    python -m scripts.fit_style_matchup [--data DIR] [--players] [--test-weeks 9]

Styles: app.style_matchup.classify on each season's earlier weeks (from week 4), 2016-2026; play-by-play aggregates
from scripts.train_game_model.season_agg, team-games from scripts.test_scoring_timing (run it first).

1. Cells (offense style x the opposing defense's style): pass and rush attempts and QB/RB/WR/TE DK points against
   what the closing spread and total imply (fit per season), and in how many seasons each pointed the same way;
   carry-over as in scripts.test_archetype_matchups (last season's / all earlier seasons' / this season's earlier
   weeks' cell effects applied to the next games). Written to data/style_matchup.json for the app.
2. --players, 2023-2026 (Sleeper's archived projections):
   a. tight-end inputs for app.player_model -- the TE's offense style and the opposing defense's (continuous:
      te_run_first, te_off_eff, te_opp_porous, te_opp_pass_funnel; or the 16 cells as indicators), each of 2023-2025
      held out and 2026, against the current inputs;
   b. player archetypes (QB / RB from Sleeper's projected line, WR / TE from their target share and depth over their
      last 8 games) against the opposing defense's style, its quality alone and its funnel alone: the current
      model's misses (each of 2023-2025 corrected by a fit on the other two, 2026 by the shipped training seasons),
      cell by cell, and whether last season's cell effects carry to the next season.
Writes data/style_matchup.json (cells) and data/style_matchup_tests.json (everything).

Result (2026 weeks 2-9): neither tight-end version improved held-out error (TE MAE with each season held out
4.529 -> 4.539 continuous, -> 4.535 cells), and no archetype-vs-defense grouping improved the current model's misses
at any position -- so the cells are shown in the app as game-environment tags only, not used in projections.
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import io
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from app import game_model as gm, player_model as pm, projections, style_matchup as sm
from scripts import test_archetype_matchups as tam
from scripts import train_game_model as tgm
from scripts.test_fast_starts import SEASONS

CELLS_OUT = sm.CELLS_FILE
TESTS_OUT = Path(__file__).resolve().parent.parent / "data" / "style_matchup_tests.json"
MIN_WEEK = 4
OUTCOMES = ("pass_att", "rush_att", "dk_QB", "dk_RB", "dk_WR", "dk_TE", "margin_vs_spread", "pts_vs_implied")
TE_CONT = ("te_run_first", "te_off_eff", "te_opp_porous", "te_opp_pass_funnel")
OFF_STYLES = [f"{a} {b}" for a in ("pass-first", "run-first") for b in ("efficient", "inefficient")]
DEF_STYLES = [f"{a} {b}" for a in ("stout", "porous") for b in ("pass-funnel", "run-funnel")]
TE_CELLS = tuple(f"te_cell_{i}" for i in range(16))
CELL_INDEX = {f"{o} vs {d}": i for i, (o, d) in enumerate((o, d) for o in OFF_STYLES for d in DEF_STYLES)}


def styles(d: Path, seasons) -> dict[tuple[int, int, str], dict]:
    out = {}
    for s in seasons:
        agg = tgm.season_agg(d, s)
        weeks = sorted({int(k.split("|")[0]) for k in agg["off"]})
        for w in range(MIN_WEEK, max(weeks) + 2):
            for t, v in sm.classify(gm.season_totals(agg, w)).items():
                out[(s, w, t)] = v
        print("styles", s, flush=True)
    return out


def team_rows(d: Path, st: dict) -> pd.DataFrame:
    tg = pd.read_pickle(d / "scoring_timing_team_games.pkl")
    tg["margin_vs_spread"] = tg.pts_for - tg.pts_against - tg.spread
    tg["pts_vs_implied"] = tg.pts_for - (tg.total_line + tg.spread) / 2
    off = [st.get((r.season, r.week, r.team), {}).get("off_style") for r in tg.itertuples()]
    de = [st.get((r.season, r.week, r.opp), {}).get("def_style") for r in tg.itertuples()]
    tg["cell"] = [f"{o} vs {x}" if o and x else None for o, x in zip(off, de)]
    return tg.dropna(subset=["cell", "spread", "total_line", "dk_QB"])


def cell_summary(p: pd.DataFrame) -> dict:
    """Per cell: n, and per outcome its average against the line (each season's own line fit) and seasons agreeing."""
    p = p.copy()
    out = defaultdict(dict)
    for y in OUTCOMES:
        for s, g in p.groupby("season"):
            f = tam.line_fit(g, y)
            p.loc[g.index, f"r_{y}"] = g[y] - f(g)
        for c, g in p.groupby("cell"):
            per = g.groupby("season")[f"r_{y}"].mean()
            avg = float(g[f"r_{y}"].mean())
            out[c][y] = round(avg, 2)
            out[c][f"{y}_seasons_same_sign"] = int((np.sign(per) == np.sign(avg)).sum())
            out[c]["seasons"] = int(len(per))
            out[c]["n"] = int(len(g))
            out[c][f"{y}_z"] = round(avg / (p[f"r_{y}"].std() / np.sqrt(len(g))), 2)
    return dict(out)


# ------------------------------------------------------------------ players
def style_inputs(position: str, own: dict | None, opp: dict | None) -> dict:
    """Tight ends: their offense's style and the opposing defense's (app.style_matchup.classify z-scores)."""
    if position != "TE" or not own or not opp:
        return {"te_run_first": 0.0, "te_off_eff": 0.0, "te_opp_porous": 0.0, "te_opp_pass_funnel": 0.0}
    return {"te_run_first": -own["pass_lean"], "te_off_eff": own["off_eff"], "te_opp_porous": -opp["def_quality"],
            "te_opp_pass_funnel": opp["pass_funnel"]}


def _hist_index(d: Path, season: int) -> dict[str, list[dict]]:
    out = defaultdict(list)
    for s in (season - 1, season):
        with open(tgm.fetch(f"{tgm.REL}/stats_player/stats_player_week_{s}.csv", d / f"stats_player_week_{s}.csv"), newline="") as fh:
            for r in csv.DictReader(fh):
                if r.get("season_type", "REG") == "REG" and r.get("week") and r.get("position") in pm.POSITIONS:
                    out[pm.key(r["player_display_name"], r["position"])].append(r)
    for v in out.values():
        v.sort(key=lambda r: (int(r["season"]), int(r["week"])))
    return out


def player_archetype(pos: str, line: dict, hist: list[dict]) -> str | None:
    from scripts import test_archetype_distributions as tad, test_wr_te_dst_archetypes as twd
    if pos in ("QB", "RB"):
        raw = projections.dk_points_from_line(line, pos)
        return tad.archetype(pos, line, raw) if raw else None
    return twd.wr_te_archetype(pos, twd.receiving_profile(hist[-8:]))


def player_rows(d: Path, st: dict, test_weeks: int) -> list[dict]:
    from scripts import train_player_model as tpm
    cache = d / f"style_matchup_players_{test_weeks}.pkl"
    if cache.exists():
        return pd.read_pickle(cache)
    rows = []
    for season, weeks in ((2023, range(1, 19)), (2024, range(1, 19)), (2025, range(1, 19)), (2026, range(1, test_weeks + 1))):
        hidx = _hist_index(d, season)
        with open(tgm.fetch(f"{tgm.REL}/stats_player/stats_player_week_{season}.csv", d / f"stats_player_week_{season}.csv"), newline="") as fh:
            tm = {(int(s["week"]), pm.key(s["player_display_name"], s["position"])): (s["team"], s.get("opponent_team") or "")
                  for s in csv.DictReader(fh) if s.get("week") and s.get("season_type", "REG") == "REG"}
        for r in tpm.player_weeks(d, season, weeks):
            if r["week"] < 2:
                continue
            team, opp = tm.get((r["week"], r["key"]), (None, None))
            o, x = st.get((season, r["week"], team)), st.get((season, r["week"], opp))
            hist = [h for h in hidx.get(r["key"], []) if (int(h["season"]), int(h["week"])) < (season, r["week"])]
            f = dict(r["f"])
            f.update(style_inputs(r["pos"], o, x))
            cell = f"{o['off_style']} vs {x['def_style']}" if o and x else None
            for k in TE_CELLS:
                f[k] = 0.0
            if r["pos"] == "TE" and cell:
                f[f"te_cell_{CELL_INDEX[cell]}"] = 1.0
            rows.append({"season": season, "week": r["week"], "key": r["key"], "pos": r["pos"], "f": f, "proj": r["proj"],
                         "actual": r["actual"], "team": team, "opp": opp, "cell": cell,
                         "def_style": x["def_style"] if x else None, "arch": player_archetype(r["pos"], r["line"], hist)})
        print("player rows", season, flush=True)
    pd.to_pickle(rows, cache)
    return rows


def corrected(rows: list[dict]) -> None:
    from scripts import train_player_model as tpm
    train = (2023, 2024, 2025)
    for s in (*train, 2026):
        tr = [r for r in rows if r["season"] in train and r["season"] != s]
        with contextlib.redirect_stdout(io.StringIO()):
            models = tpm.fit_all(tr, pm.FEATURES, sorted({r["season"] for r in tr}))
        for r in rows:
            if r["season"] == s:
                r["corrected"] = r["proj"] + (pm.adjustment(r["pos"], r["f"], {"positions": models}) or 0.0)


def archetype_vs_defense(rows: list[dict]) -> dict:
    df = pd.DataFrame([{k: v for k, v in r.items() if k != "f"} for r in rows]).dropna(subset=["arch", "def_style"])
    df["miss"] = df.actual - df.corrected
    df["spread"] = df["total_line"] = 0.0         # misses are already net of the projection
    df["def_quality"] = df.def_style.str.split(" ").str[0]
    df["def_funnel"] = df.def_style.str.split(" ").str[1]
    out = {}
    for label, col in (("archetype x defense style", "def_style"), ("archetype x defense quality", "def_quality"),
                       ("archetype x defense funnel", "def_funnel")):
        df["c"] = df.arch + " vs " + df[col]
        res = {}
        for pos in ("QB", "RB", "WR", "TE"):
            g = df[df.pos == pos].copy()
            res[pos] = {**tam.evaluate(g, "miss", "c"), "top_cells": tam.cell_table(g, "miss", "c")[:6]}
        out[label] = res
        print(label, {p: (v["last_season"], v["all_prior"], v["in_season"], v["cell_effect_corr_next_season"]) for p, v in res.items()}, flush=True)
    return out


def te_model(rows: list[dict]) -> dict:
    from scripts import test_defensive_injuries as tdi
    train = [r for r in rows if r["season"] in (2023, 2024, 2025)]
    test = [r for r in rows if r["season"] == 2026]
    te = lambda r: r["pos"] == "TE"  # noqa: E731
    return {"continuous": tdi.feature_test(train, test, TE_CONT, te), "cells": tdi.feature_test(train, test, TE_CELLS, te)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/cache/train")
    ap.add_argument("--players", action="store_true")
    ap.add_argument("--test-weeks", type=int, default=9)
    args = ap.parse_args()
    d = Path(args.data)
    cache = d / "style_matchup_styles.pkl"
    st = pd.read_pickle(cache) if cache.exists() else styles(d, SEASONS)
    pd.to_pickle(st, cache)
    p = team_rows(d, st)
    cells = cell_summary(p)
    carry = {y: tam.evaluate(p, y, "cell") for y in OUTCOMES}
    print({y: (v["last_season"], v["all_prior"], v["in_season"], v["cell_effect_corr_next_season"]) for y, v in carry.items()})
    CELLS_OUT.write_text(json.dumps({"seasons": [SEASONS[0], SEASONS[-1]], "team_games": len(p),
                                     "note": "vs the closing spread and total, each season fit on its own; app.style_matchup",
                                     "carry_over_mse_change_pct": carry, "cells": cells}, indent=1, default=float))
    res = {"team_level": {"team_games": len(p), "carry_over_mse_change_pct": carry}}
    if args.players:
        rows = player_rows(d, st, args.test_weeks)
        res["te_model"] = te_model(rows)
        corrected(rows)
        res["archetype_vs_defense"] = archetype_vs_defense(rows)
    TESTS_OUT.write_text(json.dumps(res, indent=1, default=float))


if __name__ == "__main__":
    main()
