"""Per-team DFS targets for a game, tailored to the matchup.

Candidates are players who could actually play (Healthy/Questionable, with
a game this season). Each is scored by its Ceiling (app.ceiling), which
already folds in the opponent's DK points allowed to the position, the
team's implied total, the Week Breakdown flags (funnels, tempo, efficiency
mismatch) and the player's usage trend -- then tilted toward how the
offense operates: a pass-leaning offense (top-10 neutral pass rate) favors
its QB/WR/TE, a run-leaning one (bottom-10) its RBs.

Two "core" targets by score, plus one "value" target (best ceiling per $1k
at $5,500 or less) when one stands out; at most two per position. Each
comes with up to three short, plain-English reasons drawn from the factors
that actually lifted it.
"""
from __future__ import annotations

from app import ceiling
from app.models import TopPlayer

ELIGIBLE_STATUSES = {"Healthy", "Q"}
SKILL_POSITIONS = ("QB", "RB", "WR", "TE")
CORE_TARGETS = 2
VALUE_MAX_SALARY = 5500
VALUE_MIN_CEILING = 14.0
MAX_PER_POSITION = 2
TENDENCY_TILT = 0.04
TOP_RANK, BOTTOM_RANK = 10, 23


def _alignment(position: str, pass_rank: int | None, pass_rate: float | None, team: str) -> tuple[float, str | None]:
    """Multiplier + reason for how well the position fits the offense's tendency."""
    if pass_rank is None or pass_rate is None:
        return 1.0, None
    passer = position in ("QB", "WR", "TE")
    if pass_rank <= TOP_RANK:
        return (1 + TENDENCY_TILT, f"{team} is pass-leaning ({pass_rate:.0%} neutral pass rate, #{pass_rank})") if passer else (1 - TENDENCY_TILT / 2, None)
    if pass_rank >= BOTTOM_RANK:
        return (1 + TENDENCY_TILT, f"{team} is run-leaning ({1 - pass_rate:.0%} neutral run rate)") if not passer else (1 - TENDENCY_TILT / 2, None)
    return 1.0, None


def _reasons(d: ceiling.CeilingDetail, alignment_reason: str | None) -> list[str]:
    ranked: list[tuple[float, str]] = []
    for key in ("matchup", "game_env", "usage"):
        m = d.factors.get(key)
        if m is not None and m >= 1.03 and key in d.reasons:
            ranked.append((m, d.reasons[key]))
    if "breakdown" in d.factors:
        ranked.extend((d.factors["breakdown"], f) for f in d.flags)
    if d.usage_l3 is not None and d.usage_l3 >= 0.25 and not any("targets+carries" in r for _, r in ranked):
        ranked.append((1.02, d.reasons["usage"]))
    if alignment_reason:
        ranked.append((1 + TENDENCY_TILT, alignment_reason))
    ranked.sort(key=lambda x: -x[0])
    reasons = [r for _, r in ranked[:3]]
    return reasons or ["Top ceiling on the team; no standout edge either way"]


def pick_targets(players: list, team: str, opponent: str, ctx: ceiling.CeilingContext,
                 pass_rank: int | None, pass_rate: float | None) -> list[TopPlayer]:
    scored = []
    for p in players:
        if (p.team != team or p.position not in SKILL_POSITIONS or p.injury not in ELIGIBLE_STATUSES
                or not p.proj_points or p.roster_slot == "CPT"):
            continue
        d = ceiling.player_ceiling_detail(ctx, name=p.name, position=p.position, team=team,
                                          opponent=opponent, fallback_mean=p.dk_fppg)
        if d is None:
            continue
        tilt, align_reason = _alignment(p.position, pass_rank, pass_rate, team)
        scored.append((d.value * tilt, p, d, align_reason))

    picks: list[tuple[str, tuple]] = []
    per_pos: dict[str, int] = {}

    def take(entry, role):
        picks.append((role, entry))
        per_pos[entry[1].position] = per_pos.get(entry[1].position, 0) + 1

    for entry in sorted(scored, key=lambda e: -e[0]):
        if len(picks) >= CORE_TARGETS:
            break
        if per_pos.get(entry[1].position, 0) < MAX_PER_POSITION:
            take(entry, "Core")

    chosen = {id(e[1]) for _, e in picks}
    values = [e for e in scored if id(e[1]) not in chosen and e[1].salary <= VALUE_MAX_SALARY
              and e[2].value >= VALUE_MIN_CEILING and per_pos.get(e[1].position, 0) < MAX_PER_POSITION]
    if values:
        take(max(values, key=lambda e: e[2].value / e[1].salary), "Value")
    else:
        for entry in sorted(scored, key=lambda e: -e[0]):
            if id(entry[1]) not in chosen and per_pos.get(entry[1].position, 0) < MAX_PER_POSITION:
                take(entry, "Core")
                break

    return [
        TopPlayer(
            name=p.name, position=p.position, salary=p.salary, trend_l3=p.trend_l3,
            ceiling=d.value, proj_points=p.proj_points, role=role,
            usage_l3=d.usage_l3, reasons=_reasons(d, align_reason),
        )
        for role, (_score, p, d, align_reason) in picks
    ]
