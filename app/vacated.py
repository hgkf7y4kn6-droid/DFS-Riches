"""Teammates' share of a ruled-out player's volume, until Sleeper catches up -- and a small top-up for regulars after it has.

When Sleeper processes a player being out it zeroes his line and raises his teammates' (2026 Week 7: Mike Evans
and Deebo Samuel out, George Kittle 14.8 -> 16.6, Brandin Cooks 5.3 -> 7.4). Before it does -- news fresher than its
projections: a coach's announcement entered as breaking news, a DraftKings or team-report Out -- the out player's
line is still projected and his teammates' aren't raised. Until then, each teammate gets the share of the out
player's projected targets and carries that teammates took in the first game a regular missed, 2019-2026
(scripts/test_vacated_opportunity.py: the remaining players' share of team targets / carries that game against
their previous three):

  targets, a WR out:  the top three remaining WRs by projected targets 20% each, a fourth 17%, every RB and
                      TE 3.6%
  targets, a TE out:  the top two remaining TEs 24%, every RB and WR 5.9%
  targets, an RB out: the top remaining RB 36%, the next 29%, every WR and TE 4.3%
  carries, an RB out: the top remaining RB 42%, the next 21%, the third 4%

at his own projected points per target (per carry), or the position's 2023-2025 average without a projected line.
A Questionable player counts by his chance of sitting (app.injury_news). Once Sleeper has zeroed the out player
this stops: its own redistribution takes over (and the held-out tests found nothing to add on top of it).

Once Sleeper has processed the news (zeroed the out player), top_up() adds what scripts/test_vacated_recipients.py found it
still leaves on the table, 2023-2026, for the one group with a gap: teammates who are themselves regulars (12%+ of targets or
25%+ of carries over their last three games). Actual minus Sleeper's final projection, per 100% of the team's target share
vacated by out WR/TE regulars: +4.65 DK points for WR/TE regulars (t 2.5); per 100% of carries vacated by out RBs: +5.69 for
RB regulars (t 2.3). A player traded away counts as out: he is absent from his old team's next game the same way. Backups and
other non-regulars get nothing -- Sleeper does not under-project them (+0.4 per 100% vacated, t 0.4), so a backup stepping in
is already in its number. The WR/TE sign flipped in 2026 (-3.3), so the top-up is half the measured slope and capped.
"""
from __future__ import annotations

from app import injury_news
from app.injury_news import NOT_PLAYING
from app.projections import dk_points_from_line

SKILL = ("RB", "WR", "TE")
MIN_ADJ = 0.2                  # DK points: smaller bumps aren't worth a line
STILL_PROJECTED = 3.0          # DK points: Sleeper still projects the out player -- it hasn't processed the news
# each recipient's share of the out player's projected targets: by the out player's position, the recipient's
# rank at that position (by projected targets) -- or "other" for every player at the other positions
TARGETS = {"WR": {"same": (0.20, 0.20, 0.20, 0.17), "other": 0.036},
           "TE": {"same": (0.24, 0.24), "other": 0.059},
           "RB": {"same": (0.36, 0.29), "other": 0.043}}
CARRIES = {"RB": (0.42, 0.21, 0.04)}
PER_TARGET = {"WR": 1.72, "TE": 1.75, "RB": 1.55}     # DK receiving points per target, 2023-2025
PER_CARRY = {"WR": 0.79, "TE": 0.73, "RB": 0.61}       # DK rushing points per carry


# top_up(): DK points per 100% of the vacated share (scripts/test_vacated_recipients.py), halved, capped
TOP_UP_WRTE, TOP_UP_RB_CARRIES = 4.65, 5.69
TOP_UP_SHRINK = 0.5
MIN_VAC_TS, MIN_VAC_CS = 0.15, 0.25
MAX_TOP_UP = {"WR": 1.5, "TE": 1.5, "RB": 2.0}
MIN_PROJ = 3.0                      # the test's sample: recipients Sleeper projects at 3+ points


def _f(x) -> float:
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def per_target(line: dict, position: str) -> float:
    tgt = _f(line.get("rec_tgt"))
    if tgt < 1.5:
        return PER_TARGET[position]
    return (_f(line.get("rec")) + 0.1 * _f(line.get("rec_yd")) + 6 * _f(line.get("rec_td"))) / tgt


def per_carry(line: dict, position: str) -> float:
    att = _f(line.get("rush_att"))
    if att < 2:
        return PER_CARRY[position]
    return (0.1 * _f(line.get("rush_yd")) + 6 * _f(line.get("rush_td"))) / att


def _weight(p) -> float:
    """How much of his volume is vacated: all of it when he's out, his chance of sitting when Questionable."""
    if p.injury in NOT_PLAYING or p.injury in ("O", "OUT", "IR"):
        return 1.0
    if p.injury == "Q" and p.play_chance is not None:
        return 1.0 - p.play_chance
    return 0.0


def _who(p) -> str:
    if p.injury == "Q" and p.play_chance is not None:
        return f"{p.name} (Questionable, sits {1 - p.play_chance:.0%})"
    return f"{p.name} ({'Doubtful' if p.injury == 'D' else 'out'})"


def redistribute(players, lines: dict[str, dict]) -> None:
    """Raises each RB/WR/TE's projection (and ceiling, in proportion) by his share of his out teammates' projected
    volume while Sleeper still projects them (lines: Sleeper player id -> projected stat line). Sets vacated_adj."""
    people: dict[tuple[str, str], list] = {}          # (team, name) -> his rows (a Showdown CPT and FLEX)
    for p in players:
        if p.position in SKILL:
            people.setdefault((p.team, p.name), []).append(p)
    by_team: dict[str, list[tuple[object, dict]]] = {}
    for (team, _name), rows in people.items():
        p = rows[0]
        by_team.setdefault(team, []).append((p, lines.get(p.sleeper_player_id or "") or {}))
    for team, mates in by_team.items():
        gone = [(p, ln, _weight(p)) for p, ln in mates
                if _weight(p) > 0 and dk_points_from_line(ln, p.position) >= STILL_PROJECTED]
        if not gone:
            continue
        out_ids = {id(g[0]) for g in gone}
        healthy = [(p, ln) for p, ln in mates if id(p) not in out_ids and p.injury not in NOT_PLAYING
                   and p.injury not in ("O", "OUT", "IR")]
        add: dict[str, list] = {}                     # name -> [points, targets, carries, sources]
        for out, oln, w in gone:
            tgt, car = _f(oln.get("rec_tgt")) * w, _f(oln.get("rush_att")) * w
            rule = TARGETS[out.position]
            same = sorted([(p, ln) for p, ln in healthy if p.position == out.position], key=lambda x: -_f(x[1].get("rec_tgt")))
            for share, (p, ln) in zip(rule["same"], same):
                a = add.setdefault(p.name, [0.0, 0.0, 0.0, set()])
                a[0] += share * tgt * per_target(ln, p.position)
                a[1] += share * tgt
                a[3].add(_who(out))
            for p, ln in healthy:
                if p.position != out.position and _f(ln.get("rec_tgt")) >= 1:
                    a = add.setdefault(p.name, [0.0, 0.0, 0.0, set()])
                    a[0] += rule["other"] * tgt * per_target(ln, p.position)
                    a[1] += rule["other"] * tgt
                    a[3].add(_who(out))
            if out.position in CARRIES and car:
                backs = sorted([(p, ln) for p, ln in healthy if p.position == "RB"], key=lambda x: -_f(x[1].get("rush_att")))
                for share, (p, ln) in zip(CARRIES[out.position], backs):
                    a = add.setdefault(p.name, [0.0, 0.0, 0.0, set()])
                    a[0] += share * car * per_carry(ln, p.position)
                    a[2] += share * car
                    a[3].add(_who(out))
        factor = (injury_news.load().get("if_played") or {}).get("factor", 1.0)
        for name, (pts, t, c, src) in add.items():
            first = people[(team, name)][0]
            if first.injury == "Q" and first.play_chance is not None:
                pts *= first.play_chance * factor        # his own projection is already his chance x what he scores
            if pts < MIN_ADJ:
                continue
            for p in people[(team, name)]:
                mult = 1.5 if p.roster_slot == "CPT" else 1.0
                before = p.proj_points
                p.proj_points = round(p.proj_points + pts * mult, 2)
                p.vacated_adj = round(pts, 2)
                p.value_per_1k = round(p.proj_points / (p.salary / 1000.0), 2) if p.salary > 0 else 0.0
                vol = " and ".join(x for x in (f"+{t:.1f} targets" if t >= 0.05 else "", f"+{c:.1f} carries" if c >= 0.05 else "") if x)
                p.proj_notes = p.proj_notes + [
                    f"{', '.join(sorted(src))}, still in Sleeper's projections: {vol} -> +{pts * mult:.1f} "
                    f"({before:.1f} to {p.proj_points:.1f})"]
                if p.ceiling and before > 0:
                    p.ceiling = round(p.ceiling * p.proj_points / before, 1)


def _is_out(p) -> bool:
    return p.injury in NOT_PLAYING or p.injury in ("O", "OUT", "IR")


def top_up(players, hist: dict | None, week: int, traded: dict[str, list[tuple[str, str]]] | None = None) -> None:
    """Raises each regular RB/WR/TE's projection (and ceiling in proportion) when his team's regulars are out or traded away
    and Sleeper has already moved their volume (the redistribute() path above did not apply). hist: app.player_model's
    weekly role history; traded: app.team_changes.traded_away. Regulars only; see the module docstring for why."""
    if not hist:
        return
    from app import player_model as pm
    regs = pm.fresh_regulars(hist, week)
    rows: dict[tuple[str, str], list] = {}
    for p in players:
        if p.position in SKILL:
            rows.setdefault((p.team, pm.key(p.name, p.position)), []).append(p)
    for team, reg in regs.items():
        gone = {pm.key(n, pos) for n, pos in (traded or {}).get(team, [])}
        gone |= {k for (t, k), rs in rows.items() if t == team and _is_out(rs[0])}
        v = pm.vacated(reg, lambda k: k in gone)
        vac_wrte = v["ts_by_pos"].get("WR", 0.0) + v["ts_by_pos"].get("TE", 0.0)
        vac_rb = v["cs_by_pos"].get("RB", 0.0)
        names = sorted(k.split("|")[0].title() for k in v["out"])
        for k, pos, _ts, _cs in reg:
            if k in gone or (team, k) not in rows:
                continue
            first = rows[(team, k)][0]
            if _is_out(first) or first.vacated_adj or (first.proj_points or 0) < MIN_PROJ:
                continue
            if pos in ("WR", "TE") and vac_wrte >= MIN_VAC_TS:
                pts, vac, what = TOP_UP_SHRINK * TOP_UP_WRTE * vac_wrte, vac_wrte, "of the targets"
            elif pos == "RB" and vac_rb >= MIN_VAC_CS:
                pts, vac, what = TOP_UP_SHRINK * TOP_UP_RB_CARRIES * vac_rb, vac_rb, "of the carries"
            else:
                continue
            pts = min(pts, MAX_TOP_UP[pos])
            if pts < MIN_ADJ:
                continue
            for p in rows[(team, k)]:
                mult = 1.5 if p.roster_slot == "CPT" else 1.0
                before = p.proj_points
                p.proj_points = round(p.proj_points + pts * mult, 2)
                p.value_per_1k = round(p.proj_points / (p.salary / 1000.0), 2) if p.salary > 0 else 0.0
                p.proj_notes = p.proj_notes + [
                    f"{', '.join(names)} out or traded away: {vac:.0%} {what} vacated; Sleeper's final projection missed "
                    f"regular teammates by about this much in 2023-2026 -> +{pts * mult:.1f} ({before:.1f} to {p.proj_points:.1f})"]
                if p.ceiling and before > 0:
                    p.ceiling = round(p.ceiling * p.proj_points / before, 1)
