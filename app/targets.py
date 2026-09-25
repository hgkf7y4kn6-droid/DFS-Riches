"""Per-team DFS targets for a game, tailored to the matchup.

Candidates are players who could actually play (Healthy/Questionable, with
a game this season and a projected line of at least 3 DK points). Each is scored by its Ceiling (app.ceiling), which
already folds in the opponent's DK points allowed to the position, the
team's implied total, the Week Breakdown flags (funnels, tempo, efficiency
mismatch) and the player's usage trend -- then tilted toward how the
offense operates: a pass-leaning offense (top-10 neutral pass rate) favors
its QB/WR/TE, a run-leaning one (bottom-10) its RBs.

Two "core" targets by score, plus one "value" target (best ceiling per $1k
at $5,500 or less) when one stands out; at most two per position. Each
comes with up to three short, plain-English reasons drawn from the factors
that actually lifted it. Each team's DST is listed too (pick_dst), with
where its ceiling ranks among the week's DSTs and why.
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
MIN_ROLE_PROJ = 3.0   # projected under this = no real role this week (backup/inactive)


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
                or not p.dk_fppg or p.proj_points < MIN_ROLE_PROJ or p.roster_slot == "CPT"):
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


def dst_ceiling_ranks(players: list, ctx: ceiling.CeilingContext) -> dict[str, int]:
    """team -> rank of its DST ceiling among the slate's DSTs (1 = highest)."""
    values = {}
    for p in players:
        if p.position == "DST" and p.roster_slot != "CPT":
            d = ceiling.player_ceiling_detail(ctx, name=p.name, position="DST", team=p.team,
                                              opponent=p.opponent, fallback_mean=p.dk_fppg)
            if d:
                values[p.team] = d.value
    return {t: i + 1 for i, (t, _v) in enumerate(sorted(values.items(), key=lambda kv: -kv[1]))}


def pick_dst(players: list, team: str, opponent: str, ctx: ceiling.CeilingContext, *,
             opp_sacks: float | None, opp_giveaways: float | None,
             league_sacks: float | None, league_giveaways: float | None,
             opp_implied_rank: int | None, n_teams: int, dst_rank: int | None, n_dst: int) -> TopPlayer | None:
    """The team's DST as a target: ceiling, where it ranks among the week's
    DSTs, and why -- the opponent's implied total, how often it takes sacks
    and gives the ball away vs league average, and its efficiency."""
    p = next((x for x in players if x.team == team and x.position == "DST" and x.roster_slot != "CPT"), None)
    if p is None:
        return None
    d = ceiling.player_ceiling_detail(ctx, name=p.name, position="DST", team=team, opponent=opponent, fallback_mean=p.dk_fppg)
    if d is None:
        return None

    good: list[str] = []
    bad: list[str] = []
    imp = ctx.implied.get(opponent)
    if imp is not None and opp_implied_rank is not None:
        lowest = n_teams - opp_implied_rank + 1
        if lowest <= 8:
            good.append(f"{opponent} implied for just {imp:g} ({_ord(lowest)}-lowest this week)")
        elif opp_implied_rank <= 8:
            bad.append(f"Tough spot: {opponent} implied for {imp:g} ({_ord(opp_implied_rank)}-highest)")
    if opp_sacks is not None and league_sacks:
        if opp_sacks >= league_sacks * 1.10:
            good.append(f"{opponent} takes {opp_sacks:.1f} sacks/gm ({opp_sacks / league_sacks - 1:+.0%} vs avg)")
        elif opp_sacks <= league_sacks * 0.85:
            bad.append(f"{opponent} rarely takes sacks ({opp_sacks:.1f}/gm)")
    if opp_giveaways is not None and league_giveaways:
        if opp_giveaways >= league_giveaways * 1.15:
            good.append(f"{opponent} gives it away {opp_giveaways:.1f} times/gm ({opp_giveaways / league_giveaways - 1:+.0%} vs avg)")
        elif opp_giveaways <= league_giveaways * 0.75:
            bad.append(f"{opponent} protects the ball ({opp_giveaways:.1f} giveaways/gm)")
    good.extend(d.flags)

    reasons = []
    if dst_rank is not None:
        reasons.append(f"#{dst_rank} DST ceiling of {n_dst} this week")
    reasons += good[:2] + bad[:1]
    return TopPlayer(
        name=p.name, position="DST", salary=p.salary, trend_l3=p.trend_l3,
        ceiling=d.value, proj_points=p.proj_points, role="DST", reasons=reasons,
    )


def _ord(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"
