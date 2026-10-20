"""Luck monitor: does fading teams whose recent results ran ahead of their underlying play beat the closing line?

    python -m scripts.late_down_monitor [--season 2026] [--baseline 2023 2024 2025]

Two signals, each compared with how the game finished against nflverse's closing spread:

  late-down gap       each team's late-down gap entering the game (app.trenches late_downs: late-down success minus
                      what early-down success implies, offense minus defense, with last season weighted as
                      PRIOR_GAMES games). Research backtest: r = -0.02 with the line's miss on 2023-2025, -0.14 on
                      2026 Weeks 1-6 (92 games), within noise.
  penalty-drive luck  over each team's last LUCK_GAMES games this season, the share of its drives on which the
                      defense was flagged (accepted penalty) that ended in points, shrunk toward the league rate
                      by LUCK_SHRINK drives, minus the league rate (Week 5 on). Research backtest: fading it went
                      320-277 (53.6%) on 2023-2025, z = 1.76 against a coin flip, positive in each season; its
                      separate effect against the line was t = -1.4 once recent offense was accounted for.

  toxic flag          an offense whose pass protection (sack + QB-hit rate allowed) is 1+ standard deviation worse
                      than the league, facing a defense that blitzes 1+ SD more than the league, with above-
                      average offensive-line penalties (false start, holding, illegal formation per snap); all
                      entering the game, last season weighted as PRIOR_GAMES games. Graded on that team's points
                      against its implied team total from the closing spread and total. Research backtest
                      (2023-2025): 26 team-games, 42% scored 7+ below the implied total (others 21%) and 73% went
                      under it; one of five similar flags tested, so it is watched, not used.

"Fade" picks the team with the lower value; "flagged" (late downs only) is games with a team flagged hot or cold.
Prints only aggregates.
"""
from __future__ import annotations

import argparse
import asyncio
import math
import statistics

from app import nflverse_client as nc, trenches

LUCK_GAMES = 4
LUCK_SHRINK = 10          # drives of league-average results added to each team's recent sample
LUCK_FROM_WEEK = 5
TOXIC_Z = 1.0             # protection and opponent blitz thresholds; OL penalties only need to be above average
OL_PEN_MIN_SNAPS = 100


def _z(values: dict[str, float]) -> dict[str, float]:
    if len(values) < 10:
        return {}
    mu, sd = statistics.fmean(values.values()), statistics.pstdev(values.values())
    return {t: (v - mu) / sd if sd else 0.0 for t, v in values.items()}


def toxic_offenses(teams: dict, pen_cur: dict, pen_prev: dict, week: int) -> set[str]:
    """Offenses entering `week` with weak protection and above-average OL penalties ({team}); the opponent's
    blitz rate is checked per game (toxic_vs)."""
    prot = _z({t: p["off"]["pressure_rate"] for t, p in teams.items() if p["off"].get("pressure_rate") is not None})
    rates = {}
    for t in teams:
        c, _, _ = trenches.blend({"off": pen_cur}, {"off": pen_prev}, t, "off", week)
        if c.get("snaps", 0) >= OL_PEN_MIN_SNAPS:
            rates[t] = c["ol_pen"] / c["snaps"]
    pen = _z(rates)
    return {t for t in prot if prot[t] > TOXIC_Z and pen.get(t, 0.0) > 0}


def blitz_z(teams: dict) -> dict[str, float]:
    return _z({t: p["def"]["blitz"] for t, p in teams.items() if p["def"].get("blitz") is not None})


def league_flag_score_rate(pen_by_season: dict[int, dict]) -> float:
    """Share of drives with an accepted defensive penalty that ended in points, across the given seasons."""
    n = sum(c["flag_drives"] for pen in pen_by_season.values() for c in pen.values())
    s = sum(c["flag_scored"] for pen in pen_by_season.values() for c in pen.values())
    return s / n if n else 0.0


def penalty_luck(pen: dict, team: str, week: int, league: float) -> float | None:
    """Penalty-drive luck entering `week` from this season's counts ({"week|team": {...}})."""
    played = sorted(int(k.split("|")[0]) for k in pen if k.endswith(f"|{team}") and int(k.split("|")[0]) < week)
    recent = [pen[f"{w}|{team}"] for w in played[-LUCK_GAMES:]]
    if len(recent) < LUCK_GAMES:
        return None
    n = sum(c["flag_drives"] for c in recent)
    s = sum(c["flag_scored"] for c in recent)
    return (s + LUCK_SHRINK * league) / (n + LUCK_SHRINK) - league


async def season_rows(season: int, current: int, league: float | None = None) -> tuple[list[dict], dict]:
    cur, prev = await nc.get_pbp_aggregates(season, current), await nc.get_pbp_aggregates(season - 1, current)
    cur_t, prev_t = trenches.index_counts(cur.get("trenches")), trenches.index_counts(prev.get("trenches"))
    pen = cur.get("penalty_drives") or {}
    pen_prev = prev.get("penalty_drives") or {}
    league = league_flag_score_rate({season: pen}) if league is None else league
    games = await nc.get_games(season)
    rows, by_week, toxic = [], {}, {}
    for (week, away, home), g in sorted(games.items()):
        if week > 18 or not g["is_final"] or g["spread_line"] is None:
            continue
        if week not in by_week:
            by_week[week] = trenches.build_teams(week, cur_t, prev_t)
            toxic[week] = (toxic_offenses(by_week[week], pen, pen_prev, week), blitz_z(by_week[week]))
        row = {"season": season, "week": week, "miss": (g["home_score"] - g["away_score"]) - g["spread_line"]}
        if g["total_line"] is not None:
            # each offense's points against its implied team total, flagged when the toxic conjunction holds
            offenses, blitz = toxic[week]
            implied = {home: (g["total_line"] + g["spread_line"]) / 2, away: (g["total_line"] - g["spread_line"]) / 2}
            row["teams"] = [{"toxic": off in offenses and blitz.get(de, 0.0) > TOXIC_Z, "dev": pts - implied[off]}
                            for off, de, pts in ((home, away, g["home_score"]), (away, home, g["away_score"]))]
        a, h = (by_week[week].get(t, {}).get("late_downs") for t in (away, home))
        if a and h:
            row.update(gap=h["net"] - a["net"], flagged=bool(a.get("flag") or h.get("flag")))
        if week >= LUCK_FROM_WEEK:
            la, lh = penalty_luck(pen, away, week, league), penalty_luck(pen, home, week, league)
            if la is not None and lh is not None:
                row["luck"] = lh - la
        rows.append(row)
    return rows, pen


def summarize(rows: list[dict], key: str, flagged: bool = False) -> dict:
    rows = [r for r in rows if key in r]
    out: dict = {"games": len(rows)}
    if len(rows) >= 3:
        out["corr_with_line_miss"] = round(statistics.correlation([r[key] for r in rows], [r["miss"] for r in rows]), 3)
        out["noise_band"] = round(2 / math.sqrt(len(rows)), 3)
    sets = [("fade_ats", rows)] + ([("fade_ats_flagged", [r for r in rows if r.get("flagged")])] if flagged else [])
    for name, sel in sets:
        picks = [r for r in sel if r["miss"] != 0 and r[key] != 0]
        wins = sum((r[key] < 0) == (r["miss"] > 0) for r in picks)    # fade the higher value: home when home's is lower
        out[name] = f"{wins}-{len(picks) - wins} ({wins / len(picks):.1%})" if picks else "no games"
    return out


def summarize_toxic(rows: list[dict]) -> dict:
    sides = [t for r in rows for t in r.get("teams", [])]
    out = {}
    for name, sel in (("toxic", [t for t in sides if t["toxic"]]), ("others", [t for t in sides if not t["toxic"]])):
        decided = [t for t in sel if t["dev"] != 0]
        out[name] = {"team_games": len(sel)} | ({
            "scored_7_below_implied": f"{sum(t['dev'] <= -7 for t in sel) / len(sel):.1%}",
            "under_team_total": f"{sum(t['dev'] < 0 for t in decided)}-{sum(t['dev'] > 0 for t in decided)}",
            "avg_vs_implied": round(statistics.fmean(t["dev"] for t in sel), 1)} if sel else {})
    return out


async def main() -> None:
    from app.sleeper_client import get_nfl_state
    state = await get_nfl_state()
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=int(state.get("league_season") or state.get("season")))
    ap.add_argument("--baseline", type=int, nargs="*", default=None)
    args = ap.parse_args()
    baseline = args.baseline if args.baseline is not None else [args.season - 3, args.season - 2, args.season - 1]
    pens = {s: (await nc.get_pbp_aggregates(s, args.season)).get("penalty_drives") or {} for s in baseline}
    league = league_flag_score_rate(pens)          # the baseline's rate, also used for the current season
    rows = {s: (await season_rows(s, args.season, league))[0] for s in [*baseline, args.season]}
    base = [r for s in baseline for r in rows[s]]
    print("Luck monitor (break-even against -110 is 52.4%)")
    print(f"  league: {league:.1%} of drives with an accepted defensive penalty ended in points ({baseline})")
    for key, label, flagged in (("gap", "late-down gap", True), ("luck", "penalty-drive luck", False)):
        print(f"  {label}")
        print(f"    baseline {baseline}: {summarize(base, key, flagged)}")
        print(f"    {args.season}: {summarize(rows[args.season], key, flagged)}")
    print("  toxic flag (team points vs implied team total)")
    print(f"    baseline {baseline}: {summarize_toxic(base)}")
    print(f"    {args.season}: {summarize_toxic(rows[args.season])}")


if __name__ == "__main__":
    asyncio.run(main())
