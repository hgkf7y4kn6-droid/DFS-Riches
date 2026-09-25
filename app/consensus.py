"""Consensus projections: every source's stat line scored the same way
(DraftKings points via app.projections.dk_points_from_line), then combined.

For each player: the equal-weight mean of the sources that project him,
plus median, min, max, standard deviation and the number of sources. A
source that doesn't list the player is recorded as missing -- never
filled in.

Accuracy weighting: scripts/source_accuracy.py grades each source against
actual DK points in past weeks and stores, per position, each source's mean
absolute error relative to Sleeper's on the same player-games
(data/source_accuracy.json). Weights are 1/relative MAE -- but only when
the sources genuinely differ (best vs worst more than WEIGHT_MIN_SPREAD
apart, on at least WEIGHT_MIN_GAMES player-games); otherwise equal weight,
which is hard to beat when sources are about equally good. A source with no
graded history gets the average weight.
"""
from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field

from app.config import DATA_DIR
from app.nflverse_client import player_key
from app.projections import dk_points_from_line

ACCURACY_PATH = DATA_DIR / "source_accuracy.json"
WEIGHT_MIN_SPREAD = 0.05
WEIGHT_MIN_GAMES = 150
LINE_KEYS = ("pass_att", "pass_yd", "pass_td", "rush_att", "rush_yd", "rush_td", "rec_tgt", "rec", "rec_yd", "rec_td",
             "sack", "int", "fum_rec", "pts_allow")


def source_key(name: str, team: str, position: str) -> str:
    return f"DST|{team}" if position == "DST" else player_key(name, position)


def index_rows(rows: list[dict]) -> dict[str, list[dict]]:
    idx: dict[str, list[dict]] = {}
    for r in rows:
        idx.setdefault(source_key(r["name"], r["team"], r["position"]), []).append(r)
    return idx


def lookup(idx: dict[str, list[dict]], name: str, team: str, position: str) -> dict | None:
    cands = idx.get(source_key(name, team, position)) or []
    if len(cands) == 1:
        return cands[0]
    same_team = [c for c in cands if c["team"] == team]
    return same_team[0] if len(same_team) == 1 else None   # ambiguous: refuse to guess


def load_accuracy() -> dict:
    try:
        return json.loads(ACCURACY_PATH.read_text())
    except (OSError, ValueError):
        return {}


def position_weights(accuracy: dict, position: str, sources: list[str]) -> tuple[dict[str, float], str]:
    """(source -> weight, explanation). Equal weights unless the graded
    history shows a real accuracy gap at this position."""
    graded = {s: v for s, v in (accuracy.get("relative_mae", {}).get(position) or {}).items()
              if s in sources and v.get("games", 0) >= WEIGHT_MIN_GAMES}
    if len(graded) < 2:
        return {s: 1.0 for s in sources}, "equal weight (not enough graded history)"
    ratios = {s: v["ratio"] for s, v in graded.items()}
    if max(ratios.values()) / min(ratios.values()) - 1 < WEIGHT_MIN_SPREAD:
        return {s: 1.0 for s in sources}, "equal weight (sources were within 5% of each other historically)"
    inv = {s: 1 / r for s, r in ratios.items()}
    avg = sum(inv.values()) / len(inv)
    weights = {s: inv.get(s, avg) / avg for s in sources}
    return weights, "weighted by 1/historical MAE (sources differed by more than 5%)"


@dataclass
class Consensus:
    by_source: dict[str, float | None]
    mean: float | None
    weighted: float | None
    median: float | None
    low: float | None
    high: float | None
    sd: float | None
    n: int
    missing: list[str] = field(default_factory=list)
    weight_note: str = ""
    line: dict[str, float] = field(default_factory=dict)   # mean of each projected stat across the sources that list it


def consensus_for(indexes: dict[str, dict], name: str, team: str, position: str,
                  weights: dict[str, float], weight_note: str) -> Consensus:
    by_source: dict[str, float | None] = {}
    stat_vals: dict[str, list[float]] = {}
    for src, idx in indexes.items():
        row = lookup(idx, name, team, position) if idx else None
        by_source[src] = dk_points_from_line(row["stats"], position) if row else None
        for k in LINE_KEYS:
            if row and row["stats"].get(k) is not None:
                stat_vals.setdefault(k, []).append(float(row["stats"][k]))
    line = {k: round(statistics.fmean(v), 2) for k, v in stat_vals.items()}
    vals = {s: v for s, v in by_source.items() if v is not None}
    missing = [s for s, v in by_source.items() if v is None]
    if not vals:
        return Consensus(by_source, None, None, None, None, None, None, 0, missing, weight_note, line)
    xs = list(vals.values())
    wsum = sum(weights.get(s, 1.0) for s in vals)
    weighted = sum(v * weights.get(s, 1.0) for s, v in vals.items()) / wsum
    return Consensus(
        by_source=by_source,
        mean=round(statistics.fmean(xs), 2),
        weighted=round(weighted, 2),
        median=round(statistics.median(xs), 2),
        low=round(min(xs), 2),
        high=round(max(xs), 2),
        sd=round(statistics.pstdev(xs), 2) if len(xs) >= 2 else None,
        n=len(xs),
        missing=missing,
        weight_note=weight_note,
        line=line,
    )
