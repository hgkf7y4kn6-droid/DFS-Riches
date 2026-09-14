"""Matches DraftKings salary rows to Sleeper player_id's so DK salaries can
be merged with Sleeper's weekly projections.

The two providers use unrelated id systems (Sleeper's numeric player_id vs.
DraftKings' playerDkId), so the merge key is the player's name, normalized to
strip punctuation/suffixes that differ between the two ("A.J. Brown" vs
"AJ Brown", "Marquise Brown" vs "Hollywood Brown"), then disambiguated by
team when a name collides. Team defenses are special-cased since Sleeper
keys them by team abbreviation rather than a person's name.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache

from app.config import NAME_ALIASES_PATH

_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}
_PUNCT_RE = re.compile(r"[.'’,]")
_WS_RE = re.compile(r"\s+")


def normalize_name(name: str) -> str:
    s = name.lower()
    s = _PUNCT_RE.sub("", s)
    s = s.replace("-", " ")
    s = _WS_RE.sub(" ", s).strip()
    tokens = [t for t in s.split(" ") if t not in _SUFFIXES]
    return " ".join(tokens)


@lru_cache(maxsize=1)
def load_aliases() -> dict[str, str]:
    if not NAME_ALIASES_PATH.exists():
        return {}
    with NAME_ALIASES_PATH.open() as f:
        raw = json.load(f)
    aliases = {}
    for k, v in raw.items():
        if k.startswith("_"):
            continue
        aliases[normalize_name(k)] = normalize_name(v)
    return aliases


def resolve_alias(normalized: str) -> str:
    return load_aliases().get(normalized, normalized)


class SleeperNameIndex:
    """normalized full name -> list of (player_id, team, position) candidates."""

    def __init__(self, players: dict[str, dict]):
        self._by_name: dict[str, list[tuple[str, str, str]]] = {}
        self._defense_by_team: dict[str, str] = {}

        for pid, p in players.items():
            position = (p.get("position") or "").upper()
            team = (p.get("team") or "").upper()

            if position == "DEF":
                # Sleeper keys team defenses by team abbreviation.
                self._defense_by_team[pid.upper()] = pid
                continue

            full_name = f"{p.get('first_name', '')} {p.get('last_name', '')}".strip()
            if not full_name:
                continue
            key = normalize_name(full_name)
            self._by_name.setdefault(key, []).append((pid, team, position))

    def find(self, name: str, team: str, position: str) -> str | None:
        if position.upper() == "DST":
            return self._defense_by_team.get(team.upper())

        key = resolve_alias(normalize_name(name))
        candidates = self._by_name.get(key, [])
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0][0]

        team_matches = [c for c in candidates if c[1] == team.upper()]
        if len(team_matches) == 1:
            return team_matches[0][0]

        pos_matches = [c for c in candidates if c[2] == position.upper()]
        if len(pos_matches) == 1:
            return pos_matches[0][0]

        both = [c for c in candidates if c[1] == team.upper() and c[2] == position.upper()]
        if both:
            return both[0][0]

        # Ambiguous and unresolved by team/position; refuse to guess.
        return None
