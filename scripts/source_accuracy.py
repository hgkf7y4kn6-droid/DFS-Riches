"""Grade each projection source against actual DraftKings points, and
calibrate the floor/median/ceiling spread around the consensus.

    python -m scripts.source_accuracy            # 2025 Weeks 4-17 + this season's finished weeks
    python -m scripts.source_accuracy --weeks 2025:4-17 2026:1-2

Writes data/source_accuracy.json:

  relative_mae   position -> source -> {ratio, mae, sleeper_mae, games}: the
                 source's mean absolute error divided by Sleeper's on the
                 same player-games (Sleeper covers everyone, so it's the
                 common yardstick). app.consensus weights by 1/ratio only
                 when sources differ by more than 5%.
  consensus      position -> {mae_consensus, mae_sleeper, games}: does the
                 equal-weight consensus beat a single source?
  calibration    position -> projection bucket -> {q15, q50, q85, games}:
                 actual / consensus quantiles, used for Floor (15th pct),
                 Median (50th) and the projection-based half of Ceiling.

Only player-games where the player recorded a stat (nflverse box score) and
the source projected at least MIN_GRADE points are graded, so a player
ruled out after the projections were made doesn't count against a source.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
from datetime import datetime, timezone

from app import consensus, sources
from app import nflverse_client as nc
from app.config import DATA_DIR
from app.projections import dk_points_from_line

OUT = DATA_DIR / "source_accuracy.json"
MIN_GRADE = 3.0
POSITIONS = ("QB", "RB", "WR", "TE", "DST")
BUCKETS = [(0, 8), (8, 12), (12, 16), (16, 20), (20, 99)]
HISTORY_SOURCES = ("sleeper", "espn", "fftoday", "fantasypros")   # CBS keeps no past weeks


def bucket_label(proj: float) -> str:
    for lo, hi in BUCKETS:
        if lo <= proj < hi:
            return f"{lo}-{hi}"
    return f"{BUCKETS[-1][0]}-{BUCKETS[-1][1]}"


def quantile(xs: list[float], q: float) -> float:
    xs = sorted(xs)
    k = (len(xs) - 1) * q
    f = int(k)
    c = min(f + 1, len(xs) - 1)
    return xs[f] + (xs[c] - xs[f]) * (k - f)


def parse_weeks(specs: list[str]) -> list[tuple[int, int]]:
    out = []
    for spec in specs:
        season, rng = spec.split(":")
        lo, _, hi = rng.partition("-")
        out += [(int(season), w) for w in range(int(lo), int(hi or lo) + 1)]
    return out


async def grade_week(season: int, week: int) -> list[dict]:
    """One record per graded player-game: position, actual, per-source projections."""
    actuals = await nc.get_week_actuals(season, week)
    if not actuals["teams"]:
        return []
    rows_by_source = {s: await sources.get_source(s, season, week, current=False) for s in HISTORY_SOURCES}
    idx = {s: consensus.index_rows(rows) for s, rows in rows_by_source.items()}
    records = []
    for key, entries in idx["sleeper"].items():
        base = entries[0]
        pos = base["position"]
        if pos == "DST":
            actual = actuals["dst"].get(base["team"])
        else:
            actual = actuals["players"].get(key)
        if actual is None:
            continue
        projs = {}
        for s in HISTORY_SOURCES:
            row = consensus.lookup(idx[s], base["name"], base["team"], pos)
            if row:
                projs[s] = dk_points_from_line(row["stats"], pos)
        projs = {s: v for s, v in projs.items() if v >= MIN_GRADE}
        if "sleeper" in projs:
            records.append({"pos": pos, "actual": actual, "proj": projs, "season": season, "week": week})
    return records


def summarize(records: list[dict]) -> dict:
    rel: dict[str, dict] = {}
    cons: dict[str, dict] = {}
    calib: dict[str, dict] = {}
    for pos in POSITIONS:
        recs = [r for r in records if r["pos"] == pos]
        rel[pos] = {}
        for s in HISTORY_SOURCES:
            pairs = [(abs(r["proj"][s] - r["actual"]), abs(r["proj"]["sleeper"] - r["actual"])) for r in recs if s in r["proj"]]
            if len(pairs) < 20:
                continue
            mae = statistics.fmean(a for a, _ in pairs)
            smae = statistics.fmean(b for _, b in pairs)
            rel[pos][s] = {"ratio": round(mae / smae, 3), "mae": round(mae, 2), "sleeper_mae": round(smae, 2), "games": len(pairs)}
        multi = [r for r in recs if len(r["proj"]) >= 2]
        if multi:
            cons[pos] = {
                "mae_consensus": round(statistics.fmean(abs(statistics.fmean(r["proj"].values()) - r["actual"]) for r in multi), 2),
                "mae_sleeper": round(statistics.fmean(abs(r["proj"]["sleeper"] - r["actual"]) for r in multi), 2),
                "games": len(multi),
            }
        calib[pos] = {}
        by_bucket: dict[str, list[float]] = {}
        for r in recs:
            c = statistics.fmean(r["proj"].values())
            if c >= MIN_GRADE:
                by_bucket.setdefault(bucket_label(c), []).append(r["actual"] / c)
        for b, ratios in by_bucket.items():
            if len(ratios) >= 30:
                calib[pos][b] = {"q15": round(quantile(ratios, 0.15), 3), "q50": round(quantile(ratios, 0.50), 3),
                                 "q85": round(quantile(ratios, 0.85), 3), "games": len(ratios)}
    return {"relative_mae": rel, "consensus": cons, "calibration": calib}


async def main(weeks: list[tuple[int, int]]) -> None:
    records = []
    for season, week in weeks:
        got = await grade_week(season, week)
        print(f"{season} W{week}: {len(got)} graded player-games")
        records += got
    result = summarize(records)
    result["weeks"] = [f"{s}:{w}" for s, w in weeks]
    result["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    OUT.write_text(json.dumps(result, indent=1) + "\n")
    print(json.dumps({k: result[k] for k in ("relative_mae", "consensus")}, indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--weeks", nargs="*", default=["2025:4-17", "2026:1-2"])
    asyncio.run(main(parse_weeks(ap.parse_args().weeks)))
