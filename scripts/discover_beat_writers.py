"""Propose beat-writer accounts for review. Never trusted: it only writes data/beat_writer_candidates.json.

For each team it searches Bluesky's public actor search (no key) for accounts whose profile says they cover that
team, scores each by what the bio says, and lists the likeliest with the bio and profile link so a person can decide.
To track one, copy it into data/beat_writers.json and set "verified": true only after confirming the account really
is that reporter (check the outlet's staff page links to it). Candidates are never read by the app.

    python -m scripts.discover_beat_writers             # every team
    python -m scripts.discover_beat_writers --team KC   # one team

Needs internet access to public.api.bsky.app.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import httpx

from app.sources import TEAM_NAMES

SEARCH = "https://public.api.bsky.app/xrpc/app.bsky.actor.searchActors"
OUT = Path(__file__).resolve().parent.parent / "data" / "beat_writer_candidates.json"
ROLE_WORDS = ("beat", "covers", "covering", "reporter", "writer", "columnist", "insider", "correspondent", "staff", "senior")
OUTLET_WORDS = ("athletic", "espn", "nfl network", "nbc sports", "cbs sports", "fox sports", "sports illustrated", "star", "times",
                "tribune", "post", "news", "journal", "globe", "register", "gazette", "sentinel", "herald", "dispatch",
                "inquirer", "chronicle", "observer", "courier", "press", "tennessean", "radio", "pro football talk")
AVOID_WORDS = ("parody", "fan account", "fan page", "not affiliated", "fantasy", "betting", "dfs", "picks", "bot", "memes")
LIMIT = 25
KEEP = 5


def score_actor(actor: dict, nickname: str) -> int:
    """How well a profile reads as "covers this team for an outlet": 0 means it doesn't. Bio words only."""
    bio = f"{actor.get('displayName') or ''} {actor.get('description') or ''}".lower()
    if nickname.lower() not in bio:
        return 0
    if any(w in bio for w in AVOID_WORDS):
        return 0
    return 2 * sum(1 for w in ROLE_WORDS if w in bio) + sum(1 for w in OUTLET_WORDS if w in bio)


def candidates_for(client: httpx.Client, team: str, name: str) -> list[dict]:
    nickname = name.rsplit(" ", 1)[-1]
    found: dict[str, dict] = {}
    for q in (f"{nickname} beat reporter", f"covers the {nickname}"):
        r = client.get(SEARCH, params={"q": q, "limit": LIMIT})
        r.raise_for_status()
        for a in r.json().get("actors", []):
            if (s := score_actor(a, nickname)) > 0 and a["handle"] not in found:
                found[a["handle"]] = {"name": a.get("displayName") or a["handle"], "team": team, "bluesky": a["handle"],
                                      "bio": (a.get("description") or "")[:300], "score": s, "verified": False,
                                      "source_url": f"https://bsky.app/profile/{a['handle']}", "status": "candidate"}
        time.sleep(0.5)
    return sorted(found.values(), key=lambda c: -c["score"])[:KEEP]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--team", help="one team's app abbreviation, e.g. KC")
    args = ap.parse_args()
    teams = {abbr: n for n, abbr in TEAM_NAMES.items() if not args.team or abbr == args.team.upper()}
    if not teams:
        raise SystemExit(f"Unknown team {args.team!r}")
    out: list[dict] = []
    with httpx.Client(timeout=15, headers={"User-Agent": "RichesAnalytics/1.0 (writer discovery)"}) as client:
        for abbr, name in sorted(teams.items()):
            try:
                found = candidates_for(client, abbr, name)
            except httpx.HTTPError as exc:
                print(f"{abbr}: search failed ({exc.__class__.__name__}); skipped")
                continue
            out += found
            print(f"{abbr}: {len(found)} candidate(s)")
    OUT.write_text(json.dumps({"note": "Proposed only. Verify each account before copying it into data/beat_writers.json.",
                               "candidates": out}, indent=1))
    print(f"Wrote {len(out)} candidates to {OUT}")


if __name__ == "__main__":
    main()
