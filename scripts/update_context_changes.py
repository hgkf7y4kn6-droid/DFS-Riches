"""Detect in-season team changes of fantasy-relevant players and add them to data/context_changes.json.

    python -m scripts.update_context_changes [--season 2026] [--min-share 0.25] [--dry-run]

Reads nflverse weekly rosters and snap counts from data/cache/train/ (download roster_weekly_YYYY.csv from the nflverse
`weekly_rosters` release and snap_counts_YYYY.csv from `snap_counts`). A player counts when he took at least
--min-share of his team's offensive snaps in some game this season or last, so waiver-wire shuffles of backups are
ignored. Auto rows are marked source "auto: roster_weekly" and never overwrite manual rows.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from app import team_changes as tc

ROOT = Path(__file__).resolve().parents[1]
TRAIN = ROOT / "data" / "cache" / "train"
CONTEXT = ROOT / "data" / "context_changes.json"
SOURCE = "auto: roster_weekly"


def norm(name) -> str:
    return "".join(ch for ch in str(name).lower() if ch.isalnum())


def load_rows(season: int):
    frames = []
    for s in (season - 1, season):
        f = TRAIN / f"roster_weekly_{s}.csv"
        if f.exists():
            d = pd.read_csv(f, usecols=["season", "week", "team", "gsis_id", "full_name", "position", "status", "game_type"], low_memory=False)
            frames.append(d[d.game_type == "REG"])
    return pd.concat(frames, ignore_index=True)


def relevant_names(season: int, min_share: float) -> set[str]:
    names = set()
    for s in (season - 1, season):
        f = TRAIN / f"snap_counts_{s}.csv"
        if f.exists():
            d = pd.read_csv(f, usecols=["player", "offense_pct", "game_type"])
            d = d[(d.game_type == "REG") & (d.offense_pct >= min_share)]
            names |= {norm(n) for n in d.player}
    return names


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--min-share", type=float, default=0.25)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    roster = load_rows(args.season)
    keep = relevant_names(args.season, args.min_share)
    roster = roster[roster.full_name.map(norm).isin(keep)]
    rows = [{"season": r.season, "week": r.week, "team": r.team, "player": r.gsis_id or norm(r.full_name), "name": r.full_name,
             "position": r.position, "status": r.status} for r in roster.itertuples()]
    events = [e for e in tc.detect(rows) if e["season"] == args.season]
    for e in events:
        print(f"wk {e['first_week']:>2}  {e['name']:<24} {e['position']}  {e['from_team']} -> {e['to_team']}  (last on {e['from_team']}: wk {e['last_week_old']})")
    if args.dry_run:
        return
    doc = json.loads(CONTEXT.read_text())
    have = {(r["team"], r["season"], r["effective_week"], r["type"], r["note"]) for r in doc["changes"]}
    new = [r for r in tc.context_rows(events, SOURCE) if (r["team"], r["season"], r["effective_week"], r["type"], r["note"]) not in have]
    doc["changes"] = [r for r in doc["changes"] if r.get("source") != SOURCE] + new      # auto rows are rebuilt each run
    CONTEXT.write_text(json.dumps(doc, indent=2) + "\n")
    print(f"{len(new)} auto rows written")


if __name__ == "__main__":
    main()
