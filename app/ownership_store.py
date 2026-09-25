"""Storage for the Bayesian ownership engine (app.ownership_model).

One JSON file per DraftKings slate: data/ownership/{season}_w{week}_{slate_id}.json

  observations  every ownership number ever received, append-only and
                timestamped -- never edited or deleted:
                  kind "source"  a projection pasted from a named source
                  kind "crowd"   a crowdsourced submission (anonymous user id)
                  kind "actual"  actual contest ownership (DK contest standings)
  field_lineups actual field lineups parsed from DK contest standings
                (contest -> list of [player keys]), for learning how the
                field stacks
  history       timestamped posterior snapshots (the "projection history"),
                append-only; the snapshot before lock is what gets graded
  features      the behavioral model's inputs at the latest pre-lock
                snapshot (for training once actual ownership arrives)

data/ownership/learning.json holds what the engine has learned from every
slate with actual ownership (source/user accuracy, calibration, contest
adjustments, behavioral coefficients, field-behavior parameters).

Nothing here is ever presented as actual ownership unless it came from an
actual-ownership upload.
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.config import DATA_DIR
from app.matching import normalize_name, resolve_alias

OWN_DIR = DATA_DIR / "ownership"
LEARNING_PATH = OWN_DIR / "learning.json"
CONTESTS = {
    "gpp": "Large-field GPP",
    "se": "Small/medium-field GPP",
    "3max": "3-max",
    "20max": "20-max",
    "150max": "150-max",
    "cash": "Cash",
    "showdown_flex": "Showdown FLEX",
    "showdown_cpt": "Showdown CPT",
}
CLASSIC_CONTESTS = ("gpp", "se", "3max", "20max", "150max", "cash")
MAX_ENTRIES = 600
_lock = threading.Lock()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_iso(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def player_key(name: str, team: str, position: str) -> str:
    if position in ("DST", "DEF"):
        return f"DST|{(team or '').upper()}"
    return resolve_alias(normalize_name(name))


def slate_path(season: int, week: int, slate_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_]", "_", slate_id)
    return OWN_DIR / f"{season}_w{week}_{safe}.json"


def _empty(season: int, week: int, slate_id: str) -> dict:
    return {"season": season, "week": week, "slate_id": slate_id, "observations": [], "field_lineups": {},
            "history": [], "features": {}}


def load(season: int, week: int, slate_id: str) -> dict:
    path = slate_path(season, week, slate_id)
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return _empty(season, week, slate_id)


def save(data: dict) -> None:
    OWN_DIR.mkdir(parents=True, exist_ok=True)
    path = slate_path(data["season"], data["week"], data["slate_id"])
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, separators=(",", ":")))
    os.replace(tmp, path)


def version(season: int, week: int, slate_id: str) -> float:
    """Changes whenever the slate's ownership file or the learning file changes."""
    out = 0.0
    for p in (slate_path(season, week, slate_id), LEARNING_PATH):
        try:
            out += p.stat().st_mtime
        except OSError:
            pass
    return round(out, 3)


def week_version(season: int, week: int) -> float:
    """Changes whenever any of the week's ownership files, or what the engine learned, changes."""
    out = 0.0
    for p in list(OWN_DIR.glob(f"{season}_w{week}_*.json")) + [LEARNING_PATH]:
        try:
            out += p.stat().st_mtime
        except OSError:
            pass
    return round(out, 3)


def all_slate_files() -> list[Path]:
    if not OWN_DIR.exists():
        return []
    return sorted(p for p in OWN_DIR.glob("*_w*_*.json"))


# ------------------------------------------------------------------ parsing
def parse_lines(text: str) -> list[dict]:
    """"Name, 23.5" / "Name, TEAM, 23.5" / "Name, 23.5, reasoning..." (tabs ok,
    % ok). DSTs by team code ("BUF, 8"). Returns [{"name", "team", "pct", "reasoning"}]."""
    out = []
    for line in (text or "").splitlines()[:MAX_ENTRIES]:
        parts = [p.strip() for p in re.split(r"[,\t]", line) if p.strip()]
        if len(parts) < 2:
            continue
        pct_idx = next((i for i, p in enumerate(parts[1:], 1) if re.fullmatch(r"-?\d+(\.\d+)?%?", p)), None)
        if pct_idx is None:
            continue
        pct = float(parts[pct_idx].rstrip("%"))
        if not 0 <= pct <= 100:
            continue
        team = parts[1].upper() if pct_idx == 2 and re.fullmatch(r"[A-Za-z]{2,3}", parts[1]) else ""
        out.append({"name": parts[0], "team": team, "pct": pct, "reasoning": ", ".join(parts[pct_idx + 1:])[:300]})
    return out


LINEUP_SLOT_RE = re.compile(r"(?:^|\s)(QB|RB|WR|TE|FLEX|DST|CPT)\s+")


def parse_dk_standings(text: str) -> dict:
    """DraftKings contest-standings CSV -> {"ownership": {name: pct},
    "lineups": [[(slot, name), ...]], "entries": n}. The right-hand columns
    (Player, Roster Position, %Drafted) carry each player's actual ownership;
    the Lineup column carries every entry's roster."""
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        return {"ownership": {}, "lineups": [], "entries": 0}
    head = [h.strip() for h in rows[0]]
    idx = {h: i for i, h in enumerate(head) if h}
    own: dict[str, tuple[str, float]] = {}
    lineups = []
    for r in rows[1:]:
        if "Lineup" in idx and len(r) > idx["Lineup"] and r[idx["Lineup"]].strip():
            parts = LINEUP_SLOT_RE.split(" " + r[idx["Lineup"]].strip())
            lu = [(parts[i], parts[i + 1].strip()) for i in range(1, len(parts) - 1, 2)]
            if lu:
                lineups.append(lu)
        if "Player" in idx and "%Drafted" in idx and len(r) > idx["%Drafted"] and r[idx["Player"]].strip():
            try:
                pct = float(r[idx["%Drafted"]].strip().rstrip("%"))
            except ValueError:
                continue
            slot = r[idx["Roster Position"]].strip() if "Roster Position" in idx and len(r) > idx["Roster Position"] else ""
            own[(r[idx["Player"]].strip(), slot)] = pct
    return {"ownership": own, "lineups": lineups, "entries": len(lineups)}


# ------------------------------------------------------------------ writing
def resolve(players: list[dict], name: str, team: str = "", slot: str = "") -> dict | None:
    """Match a pasted name to a slate player (DSTs by team code or DK name)."""
    want = resolve_alias(normalize_name(name))
    team = (team or "").upper()
    cands = []
    for p in players:
        if slot and p.get("roster_slot", "") and p["roster_slot"] != slot:
            continue
        if p["position"] == "DST":
            if name.upper() == p["team"] or want == normalize_name(p["name"]) or want in normalize_name(p["name"]).split():
                cands.append(p)
        elif resolve_alias(normalize_name(p["name"])) == want:
            cands.append(p)
    if team:
        cands = [c for c in cands if c["team"] == team] or cands
    keys = {c["key"] for c in cands}
    return cands[0] if len(keys) == 1 else None   # ambiguous or unknown: refuse to guess


def add_observations(season: int, week: int, slate_id: str, kind: str, contest: str, entries: list[dict],
                     players: list[dict], *, source: str = "", user_id: str = "", display_name: str = "",
                     confidence: int | None = None, platform: str = "DraftKings") -> dict:
    """Append matched entries; returns {"added", "unmatched"}."""
    if contest not in CONTESTS:
        raise ValueError(f"Unknown contest type: {contest}")
    if kind not in ("source", "crowd", "actual"):
        raise ValueError(f"Unknown observation kind: {kind}")
    ts = now_iso()
    added, unmatched = 0, []
    with _lock:
        data = load(season, week, slate_id)
        batch = uuid.uuid4().hex[:10]
        for e in entries[:MAX_ENTRIES]:
            p = resolve(players, e["name"], e.get("team", ""), e.get("slot", ""))
            if p is None:
                unmatched.append(e["name"])
                continue
            data["observations"].append({
                "id": uuid.uuid4().hex[:12], "batch": batch, "kind": kind, "contest": contest, "key": p["key"],
                "name": p["name"], "team": p["team"], "position": p["position"], "pct": round(float(e["pct"]), 3),
                "source": source[:60], "user_id": user_id[:64], "display_name": display_name[:40],
                "confidence": confidence, "reasoning": e.get("reasoning", "")[:300], "platform": platform,
                "slate": slate_id, "timestamp": ts,
            })
            added += 1
        save(data)
    return {"added": added, "unmatched": unmatched[:50], "batch": batch, "timestamp": ts}


def add_field_lineups(season: int, week: int, slate_id: str, contest: str, lineups: list[list[str]]) -> None:
    with _lock:
        data = load(season, week, slate_id)
        data.setdefault("field_lineups", {})[contest] = lineups[:200000]
        save(data)


def append_history(season: int, week: int, slate_id: str, snapshot: dict, features: dict, lock: str | None) -> None:
    with _lock:
        data = load(season, week, slate_id)
        data["history"].append(snapshot)
        data["features"] = features
        if lock:
            data["lock"] = lock
        save(data)


def load_learning() -> dict:
    try:
        return json.loads(LEARNING_PATH.read_text())
    except (OSError, ValueError):
        return {}


def save_learning(learning: dict) -> None:
    OWN_DIR.mkdir(parents=True, exist_ok=True)
    tmp = LEARNING_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(learning, indent=1))
    os.replace(tmp, LEARNING_PATH)


def hours_between(a: str, b: str) -> float:
    return (parse_iso(b) - parse_iso(a)).total_seconds() / 3600


def epoch() -> float:
    return time.time()
