"""Median-based player prop pricing: the chance a player goes over a line, and each ladder rung, from his
projected stat line.

Sportsbooks set a prop line near the median outcome. Projections (Sleeper's, and the app's corrected one) are
averages, and yards and catches are skewed right: a few big games pull the average above what usually happens.
Pricing a line against the average overstates every over (in 2026, 44% of results beat the average stat
projection; 49% beat this median). Here each projected stat is a shifted lognormal: median = (projection + shift)
x e^bias - shift, P(stat > line) = 1 - Phi((ln(line + shift) - ln(median + shift)) / sigma). From a stat's
tail_from rung on, a two-piece normal around the median (widths growing with the projection) prices the far rungs
instead, where it did better in training: QB rushing 75+, RB receiving 100+, RB catches 6+, TE catches 7+ and
QB passing yards (near-normal). Elsewhere the lognormal won at every rung once its shift was fit.

Fit per stat and position on 2023-2025 by scripts.fit_prop_pricer (data/prop_pricer.json, with its 2026 record).
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from scipy import special

PARAMS_FILE = Path(__file__).resolve().parent.parent / "data" / "prop_pricer.json"
# Sleeper stat key -> (label, positions priced)
STATS = {"pass_yd": ("Passing yards", ("QB",)), "rush_yd": ("Rushing yards", ("QB", "RB")),
         "rec_yd": ("Receiving yards", ("RB", "WR", "TE")), "rec": ("Receptions", ("RB", "WR", "TE"))}
RUNGS = {"pass_yd": (200, 225, 250, 275, 300, 325), "rush_yd": (25, 50, 75, 100, 125),
         "rec_yd": (25, 50, 75, 100, 125), "rec": (3, 4, 5, 6, 7, 8)}

_PARAMS: dict | None = None


def load() -> dict | None:
    global _PARAMS
    if _PARAMS is None and PARAMS_FILE.exists():
        _PARAMS = json.loads(PARAMS_FILE.read_text())
    return _PARAMS


def params(stat: str, position: str, fitted: dict | None = None) -> dict | None:
    return ((fitted or load() or {}).get("params") or {}).get(f"{stat}|{position}")


def median(proj: float, p: dict) -> float:
    return max(0.0, (max(proj, 0.0) + p["shift"]) * math.exp(p["bias"]) - p["shift"])


def p_lognormal(line: float, proj: float, p: dict) -> float:
    """P(stat > line) under the shifted lognormal."""
    z = (math.log(max(line, 0.0) + p["shift"]) - math.log(median(proj, p) + p["shift"])) / p["sigma"]
    return float(1 - special.ndtr(z))


def p_two_piece(line: float, proj: float, p: dict) -> float:
    """P(stat > line) under the two-piece normal around the median (widths x scale^power)."""
    tp = p["two_piece"]
    scale = (max(proj, 0.0) + p["shift"]) ** tp["power"]
    center = median(proj, p) + tp["offset"] * scale
    sd = (tp["hi"] if line >= center else tp["lo"]) * scale
    return float(1 - special.ndtr((line - center) / sd))


def p_over(line: float, proj: float, p: dict) -> float:
    """P(stat > line): the lognormal for standard lines, the two-piece normal from the stat's tail_from rung on."""
    tail = p.get("tail_from")
    return p_two_piece(line, proj, p) if tail is not None and line >= tail else p_lognormal(line, proj, p)


def fair_american(prob: float) -> int | None:
    """The no-vig American odds for a probability."""
    if not 0.0 < prob < 1.0:
        return None
    return round(-100 * prob / (1 - prob)) if prob >= 0.5 else round(100 * (1 - prob) / prob)


def price(stat_line: dict, position: str, ratio: float = 1.0, fitted: dict | None = None) -> dict:
    """{stat: {label, projection, median, ladder: {rung: P(stat >= rung)}}} for a projected stat line (Sleeper's
    keys). ratio carries the app's points correction (corrected / Sleeper DK points) to each stat."""
    out = {}
    for stat, (label, positions) in STATS.items():
        p = params(stat, position, fitted)
        proj = float(stat_line.get(stat) or 0.0) * ratio
        if position not in positions or not p or proj <= 0:
            continue
        # rungs are "N or more": over N - 0.5 for counts, over N - 0.01 for yards
        step = 0.5 if stat == "rec" else 0.01
        out[stat] = {"label": label, "projection": round(proj, 1), "median": round(median(proj, p), 1),
                     "ladder": {str(r): round(p_over(r - step, proj, p), 3) for r in RUNGS[stat]}}
    return out
