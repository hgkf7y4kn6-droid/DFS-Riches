"""Offense and defense style archetypes, from this season's games only, and what each matchup of them tends to do.

Offense: pass-first / run-first (neutral-situation dropback rate) x efficient / inefficient (EPA per play).
Defense: stout / porous (dropback plus rushing EPA allowed) x pass-funnel / run-funnel (which of the two it is
weaker against). Each team's rates are shrunk toward this season's league rate (app.game_model's play weights, about
four games), then placed against the other teams as z-scores, so a high- or low-scoring season is its own scale.

A matchup is an offense's style against the opposing defense's: data/style_matchup.json (scripts.fit_style_matchup)
holds each of the 16 cells' pass and rush attempts and position DK points against what the closing spread and total
imply, 2016-2026, and in how many seasons each pointed the same way.
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path

from app import game_model as gm

CELLS_FILE = Path(__file__).resolve().parent.parent / "data" / "style_matchup.json"
MIN_WEEK = 4                    # styles start once teams have three games (as back-tested)
MIN_PLAYS = 60                  # a team needs this many plays (about one game) to be classified
LEAN_ATT = 1.5                  # pass-attempt shift vs the line that makes a cell lean pass or run
LEAN_SEASONS = 0.75             # ... in at least this share of seasons


def _rates(totals: dict) -> dict[str, dict[str, float]]:
    pooled = {k: [0.0, 0.0] for k in ("pass", "eff", "dpass", "drush")}
    raw = {}
    for team, t in totals.items():
        o, d = t.get("off") or {}, t.get("def") or {}
        if (o.get("db", 0) + o.get("rush", 0)) < MIN_PLAYS or (d.get("db", 0) + d.get("rush", 0)) < MIN_PLAYS:
            continue
        r = {"pass": (o.get("neutral_db", 0.0), o.get("neutral", 0.0), gm.K["neutral"]),
             "eff": (o.get("db_epa", 0.0) + o.get("rush_epa", 0.0), o.get("db", 0.0) + o.get("rush", 0.0), gm.K["plays"]),
             "dpass": (d.get("db_epa", 0.0), d.get("db", 0.0), gm.K["db"]),
             "drush": (d.get("rush_epa", 0.0), d.get("rush", 0.0), gm.K["rush"])}
        raw[team] = r
        for k, (n, den, _k) in r.items():
            pooled[k][0] += n
            pooled[k][1] += den
    lg = {k: n / den if den else 0.0 for k, (n, den) in pooled.items()}
    return {t: {k: (n + kk * lg[k]) / (den + kk) for k, (n, den, kk) in r.items()} for t, r in raw.items()}


def _z(vals: dict[str, float]) -> dict[str, float]:
    if len(vals) < 4:
        return {t: 0.0 for t in vals}
    m, s = statistics.fmean(vals.values()), statistics.pstdev(vals.values()) or 1.0
    return {t: (v - m) / s for t, v in vals.items()}


def classify(totals: dict) -> dict[str, dict]:
    """{team: {"off_style", "def_style", "pass_lean", "off_eff", "def_quality", "pass_funnel"}} (z-scores across
    the league) from app.game_model.season_totals of this season's earlier weeks."""
    r = _rates(totals)
    if not r:
        return {}
    lean = _z({t: v["pass"] for t, v in r.items()})
    eff = _z({t: v["eff"] for t, v in r.items()})
    dp = _z({t: v["dpass"] for t, v in r.items()})
    dr = _z({t: v["drush"] for t, v in r.items()})
    out = {}
    for t in r:
        quality = -(dp[t] + dr[t])
        funnel = dp[t] - dr[t]
        out[t] = {"off_style": ("pass-first" if lean[t] >= 0 else "run-first") + (" efficient" if eff[t] >= 0 else " inefficient"),
                  "def_style": ("stout" if quality >= 0 else "porous") + (" pass-funnel" if funnel >= 0 else " run-funnel"),
                  "pass_lean": round(lean[t], 3), "off_eff": round(eff[t], 3),
                  "def_quality": round(quality, 3), "pass_funnel": round(funnel, 3)}
    return out


def off_text(style: str) -> str:
    """"pass-first efficient" -> "pass-heavy and efficient" (what the card shows)."""
    if " " not in style:
        return style
    lean, eff = style.split(" ", 1)
    return f"{'pass' if lean == 'pass-first' else 'run'}-heavy and {eff}"


def def_text(style: str) -> str:
    """"stout run-funnel" -> "tough, weaker against the run"; "porous pass-funnel" -> "leaky, weaker against the pass"."""
    if " " not in style:
        return style
    quality, funnel = style.split(" ", 1)
    return f"{'tough' if quality == 'stout' else 'leaky'}, weaker against the {funnel.split('-')[0]}"


_CELLS: dict | None = None


def cells() -> dict:
    global _CELLS
    if _CELLS is None:
        _CELLS = json.loads(CELLS_FILE.read_text()).get("cells", {}) if CELLS_FILE.exists() else {}
    return _CELLS


def describe(offense: str, defense: str, off_style: str, def_style: str) -> dict:
    """One side of a game: the offense's style against the defense's, and what that cell has done vs the line."""
    c = cells().get(f"{off_style} vs {def_style}") or {}
    pa, ra = c.get("pass_att"), c.get("rush_att")
    n_s, same = c.get("seasons", 0), c.get("pass_att_seasons_same_sign", 0)
    lean = None
    if pa is not None and n_s and same / n_s >= LEAN_SEASONS:
        lean = "pass" if pa >= LEAN_ATT else "run" if pa <= -LEAN_ATT else None
    text = f"{offense} {off_style} offense vs {defense} {def_style} defense"
    if pa is not None:
        text += (f": {pa:+.1f} pass / {ra:+.1f} rush attempts vs the line"
                 f" ({same} of {n_s} seasons the same way on passes)")
    if lean:
        lean_text = (f"Leans {lean}: this pairing has meant {abs(pa):.1f} {'more' if pa > 0 else 'fewer'} pass attempts than "
                     f"the line implies, in {same} of {n_s} seasons since 2016")
    elif pa is None:
        lean_text = "No history for this pairing"
    else:
        lean_text = "No consistent lean: it hasn't moved pass attempts the same way in enough seasons"
    return {"offense": offense, "defense": defense, "off_style": off_style, "def_style": def_style, "lean": lean,
            "off_text": off_text(off_style), "def_text": def_text(def_style), "lean_text": lean_text,
            "pass_att": pa, "rush_att": ra, "dk": {p: c.get(f"dk_{p}") for p in ("QB", "RB", "WR", "TE")}, "text": text}


def game(away: str, home: str, styles: dict[str, dict], app_team=lambda t: t) -> list[dict] | None:
    """Both sides of AWAY@HOME (nflverse codes in `styles`, app codes in the output)."""
    a, h = styles.get(away), styles.get(home)
    if not a or not h:
        return None
    return [describe(app_team(away), app_team(home), a["off_style"], h["def_style"]),
            describe(app_team(home), app_team(away), h["off_style"], a["def_style"])]
