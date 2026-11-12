"""When a regular RB/WR/TE misses a game, how much of his volume do his teammates absorb -- and do the projections
already account for it?

    python -m scripts.test_vacated_opportunity [--data DIR]

A regular: a target share of 12%+ or a carry share of 25%+ over the team's last three games (playing two or more,
including the last one). Out: his team played and he had no offensive snap -- the first game he misses, the case
before the projections catch up; later absences are already in his teammates' recent shares. Vacated share: the out regulars' recent target (carry) share.

1. Absorption, 2019-2026: the remaining regulars' target (carry) share that week minus their recent share, against
   the same in weeks with no regular out (regulars drift down from a high recent share either way), per unit of
   vacated share; and how it splits among them (in proportion to their recent share or evenly).
2. Projections, 2023-2026: actual minus Sleeper's projection for the remaining regulars, with 15%+ of the targets
   (25%+ of the carries) vacated vs none -- Sleeper's archived projections are its last, after the news, so a gap here
   is what it leaves on the table even once it has caught up.
3. As correction-model inputs (app.player_model: vac_ts / vac_cs, the team's vacated shares, or vac_ts_same / vac_cs_rb,
   the shares vacated at the player's own position): each of 2023-2025 held out, and 2026, against the current inputs.
Writes data/vacated_opportunity_tests.json.
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path

from app import dk_scoring, projections
from app.matching import normalize_name
from scripts.train_game_model import REL, fetch
from scripts.train_player_model import TEAM_FIX, sleeper_week

OUT = Path(__file__).resolve().parent.parent / "data" / "vacated_opportunity_tests.json"
SEASONS = (2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026)
PROJ_SEASONS = (2023, 2024, 2025, 2026)
SKILL = ("RB", "WR", "TE")
REG_TS, REG_CS = 0.12, 0.25
BIG_TS, BIG_CS = 0.15, 0.25


def mean(xs, default=None):
    xs = list(xs)
    return statistics.fmean(xs) if xs else default


def se(xs):
    xs = list(xs)
    return statistics.pstdev(xs) / len(xs) ** 0.5 if len(xs) > 1 else None


def f(x) -> float:
    try:
        return float(x or 0)
    except ValueError:
        return 0.0


def season_rows(d: Path, s: int) -> list[dict]:
    """One row per (week, team, regular RB/WR/TE): his recent shares, whether he played, his share that week,
    and his team's vacated shares."""
    stats = [r for r in csv.DictReader(open(fetch(f"{REL}/stats_player/stats_player_week_{s}.csv",
                                                  d / f"stats_player_week_{s}.csv"), newline=""))
             if r.get("season_type", "REG") == "REG" and r.get("week")]
    snaps = defaultdict(float)
    team_weeks = set()
    for r in csv.DictReader(open(fetch(f"{REL}/snap_counts/snap_counts_{s}.csv", d / f"snap_counts_{s}.csv"), newline="")):
        if r.get("game_type", "REG") == "REG" and r.get("week"):
            snaps[(int(r["week"]), r["team"], normalize_name(r["player"]))] += f(r.get("offense_snaps"))
            team_weeks.add((int(r["week"]), r["team"]))
    team_tgt, team_car = defaultdict(float), defaultdict(float)
    games = defaultdict(dict)          # (team, name, pos) -> week -> (targets, carries, points)
    for r in stats:
        w, t = int(r["week"]), r["team"]
        team_tgt[(w, t)] += f(r.get("targets"))
        team_car[(w, t)] += f(r.get("carries"))
        if r.get("position") in SKILL:
            games[(t, r["player_display_name"], r["position"])][w] = (f(r.get("targets")), f(r.get("carries")),
                                                                       dk_scoring.dk_offense_points(r))
    rows = []
    weeks = sorted({w for w, _t in team_weeks})
    for (t, name, pos), g in games.items():
        nn = normalize_name(name)
        for w in weeks:
            if (w, t) not in team_weeks:
                continue
            team_prev = [x for x in weeks if x < w and (x, t) in team_weeks][-3:]
            prior = [x for x in team_prev if x in g and snaps.get((x, t, nn), 0) > 0]
            if len(prior) < 2 or team_prev[-1] not in prior:
                continue            # not part of the team's last three games, or already missing last week
            tt, tc = sum(team_tgt[(x, t)] for x in prior), sum(team_car[(x, t)] for x in prior)
            ts = sum(g[x][0] for x in prior) / tt if tt else 0.0
            cs = sum(g[x][1] for x in prior) / tc if tc else 0.0
            regular = ts >= REG_TS or cs >= REG_CS
            played = snaps.get((w, t, nn), 0) > 0
            now = g.get(w, (0.0, 0.0, 0.0))
            rows.append({"season": s, "week": w, "team": t, "name": name, "pos": pos, "ts_l3": ts, "cs_l3": cs, "regular": regular,
                         "played": played, "ts": now[0] / team_tgt[(w, t)] if team_tgt[(w, t)] else 0.0,
                         "cs": now[1] / team_car[(w, t)] if team_car[(w, t)] else 0.0, "pts": now[2]})
    vac = defaultdict(lambda: [0.0, 0.0])
    out_pos = defaultdict(set)
    for r in rows:
        if r["regular"] and not r["played"]:
            out_pos[(r["week"], r["team"])].add(r["pos"])
            vac[(r["week"], r["team"])][0] += r["ts_l3"]
            vac[(r["week"], r["team"])][1] += r["cs_l3"]
    for r in rows:
        r["vac_ts"], r["vac_cs"] = vac[(r["week"], r["team"])]
        r["out_pos"] = out_pos[(r["week"], r["team"])]
    return rows


def recipients(rows: list[dict], share: str, vac: str, big: float, positions) -> dict:
    """Who takes a vacated share, per unit vacated: the out player's position-mates ranked by recent share (1 = the
    top remaining one), and the other positions. Team-weeks with one position's regulars out."""
    teams = defaultdict(list)
    for r in rows:
        if r["pos"] in positions:
            teams[(r["season"], r["week"], r["team"])].append(r)
    base = defaultdict(list)
    for grp in teams.values():
        if grp[0][vac] > 0:
            continue
        for pos in positions:
            mates = sorted([r for r in grp if r["pos"] == pos and r["played"]], key=lambda r: -r[f"{share}_l3"])
            for i, r in enumerate(mates):
                base[(pos, min(i + 1, 4))].append(r[share] - r[f"{share}_l3"])
    drift = {k: mean(v, 0.0) for k, v in base.items()}
    gains = defaultdict(list)
    for grp in teams.values():
        v = grp[0][vac]
        if v < big or len(grp[0]["out_pos"]) != 1:
            continue
        out_pos = next(iter(grp[0]["out_pos"]))
        if out_pos not in positions:
            continue
        for pos in positions:
            mates = sorted([r for r in grp if r["pos"] == pos and r["played"]], key=lambda r: -r[f"{share}_l3"])
            for i, r in enumerate(mates):
                rank = min(i + 1, 4)
                label = f"same position, #{rank}{'+' if rank == 4 else ''} remaining" if pos == out_pos else "other positions (all)"
                gains[(label, pos == out_pos, rank)].append((r[share] - r[f"{share}_l3"] - drift.get((pos, rank), 0.0)) / v)
    out = {}
    for (label, same, rank), g in sorted(gains.items(), key=lambda kv: (not kv[0][1], kv[0][2])):
        if same:
            out[label] = {"n": len(g), "absorbs": round(mean(g), 3), "se": round(se(g) or 0, 3)}
    other = [x for (label, same, _r), g in gains.items() if not same for x in g]
    if other:
        # per team-week: summed over the other positions' players
        out["other positions (each player)"] = {"n": len(other), "absorbs": round(mean(other), 3), "se": round(se(other) or 0, 3)}
    return out


def absorption(rows: list[dict], share: str, vac: str, big: float) -> dict:
    """Per unit of vacated share, the remaining regulars' combined gain (over the no-vacancy drift), and whether
    each one's gain tracks his recent share (proportional) or not (even)."""
    teams = defaultdict(list)
    for r in rows:
        if r["played"]:
            teams[(r["season"], r["week"], r["team"])].append(r)
    base_gain = [r[share] - r[f"{share}_l3"] for r in rows if r["played"] and r[vac] == 0 and r[f"{share}_l3"] > 0]
    drift = mean(base_gain, 0.0)
    combined, per_player, ratios = [], [], []
    for grp in teams.values():
        v = grp[0][vac]
        if v < big:
            continue
        mates = [r for r in grp if r[f"{share}_l3"] > 0]
        if not mates:
            continue
        gain = sum(r[share] - r[f"{share}_l3"] - drift for r in mates)
        combined.append(gain / v)
        tot = sum(r[f"{share}_l3"] for r in mates)
        for r in mates:
            per_player.append((r[f"{share}_l3"] / tot, (r[share] - r[f"{share}_l3"] - drift) / v))
            ratios.append(r[share] / r[f"{share}_l3"])
    # slope of each one's absorbed fraction on his part of the remaining group's recent share: 1 = proportional
    xs, ys = [a for a, _ in per_player], [b for _, b in per_player]
    mx, my = mean(xs, 0.0), mean(ys, 0.0)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs) if len(xs) > 2 else None
    return {"team_weeks": len(combined), "drift_without_vacancy": round(drift, 4),
            "absorbed_share_of_vacated": round(mean(combined, 0.0), 3), "se": round(se(combined) or 0, 3),
            "by_recent_share_slope": round(slope, 3) if slope is not None else None,
            "share_ratio_with_vacancy": round(mean(ratios, 0.0), 3)}


def projection_gap(d: Path, rows: list[dict]) -> dict:
    out = {}
    for s in PROJ_SEASONS:
        proj = {}
        for w in sorted({r["week"] for r in rows if r["season"] == s}):
            try:
                entries = sleeper_week(d, s, w)
            except Exception:
                continue
            for e in entries:
                pl = e.get("player") or {}
                if pl.get("position") in SKILL and e.get("team"):
                    name = f"{pl.get('first_name', '')} {pl.get('last_name', '')}".strip()
                    proj[(w, TEAM_FIX.get(e["team"], e["team"]), normalize_name(name))] = projections.dk_points_from_line(
                        e.get("stats") or {}, pl["position"])
        for r in rows:
            if r["season"] == s and r["played"]:
                r["proj"] = proj.get((r["week"], r["team"], normalize_name(r["name"])))
    for label, sel, vac, big in (("WR/TE, targets vacated", lambda r: r["pos"] in ("WR", "TE"), "vac_ts", BIG_TS),
                                 ("RB, carries vacated", lambda r: r["pos"] == "RB", "vac_cs", BIG_CS),
                                 ("RB, targets vacated", lambda r: r["pos"] == "RB", "vac_ts", BIG_TS)):
        use = [r for r in rows if r["season"] in PROJ_SEASONS and r["played"] and sel(r) and (r.get("proj") or 0) >= 3]
        hit = [r["pts"] - r["proj"] for r in use if r[vac] >= big]
        none = [r["pts"] - r["proj"] for r in use if r[vac] == 0]
        if not hit or not none:
            continue
        gap = mean(hit) - mean(none)
        s_ = (statistics.pvariance(none) / len(hit) + statistics.pvariance(none) / len(none)) ** 0.5
        out[label] = {"n_vacated": len(hit), "miss_vacated": round(mean(hit), 2), "miss_none": round(mean(none), 2),
                      "gap": round(gap, 2), "z": round(gap / s_, 2),
                      "by_season": {s: round(mean(r["pts"] - r["proj"] for r in use if r["season"] == s and r[vac] >= big) -
                                             mean(r["pts"] - r["proj"] for r in use if r["season"] == s and r[vac] == 0), 2)
                                    for s in PROJ_SEASONS if any(r["season"] == s and r[vac] >= big for r in use)}}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/cache/train")
    ap.add_argument("--model", action="store_true", help="also test the vacated shares as correction-model inputs")
    ap.add_argument("--test-weeks", type=int, default=6)
    args = ap.parse_args()
    d = Path(args.data)
    everyone = [r for s in SEASONS for r in season_rows(d, s)]
    rows = [r for r in everyone if r["regular"]]
    res = {"regular": f"target share {REG_TS:.0%}+ or carry share {REG_CS:.0%}+ over his last 3 games",
           "regulars": len(rows), "out": sum(1 for r in rows if not r["played"]),
           "absorption_2019_2026": {
               "targets (RB/WR/TE)": absorption(rows, "ts", "vac_ts", BIG_TS),
               "targets (WR/TE)": absorption([r for r in rows if r["pos"] != "RB"], "ts", "vac_ts", BIG_TS),
               "carries (RB)": absorption([r for r in rows if r["pos"] == "RB"], "cs", "vac_cs", BIG_CS)},
           "who_absorbs_2019_2026": {
               "targets (WR out)": recipients([r for r in everyone if r["out_pos"] == {"WR"} or not r["out_pos"]], "ts", "vac_ts", BIG_TS, SKILL),
               "targets (TE out)": recipients([r for r in everyone if r["out_pos"] == {"TE"} or not r["out_pos"]], "ts", "vac_ts", BIG_TS, SKILL),
               "targets (RB out)": recipients([r for r in everyone if r["out_pos"] == {"RB"} or not r["out_pos"]], "ts", "vac_ts", 0.08, SKILL),
               "carries (RB out)": recipients([r for r in everyone if r["out_pos"] == {"RB"} or not r["out_pos"]], "cs", "vac_cs", BIG_CS, ("RB",))},
           "projection_gap_2023_2026": projection_gap(d, rows)}
    if args.model:
        from scripts import test_defensive_injuries as tdi
        from scripts import train_player_model as tpm
        train = [r for s_ in (2023, 2024, 2025) for r in tpm.rows_for(d, s_, range(1, 19)) if r["week"] >= 2]
        test = [r for r in tpm.rows_for(d, 2026, range(1, args.test_weeks + 1)) if r["week"] >= 2]
        hit = lambda r: r["f"].get("vac_ts", 0) > 0 or r["f"].get("vac_cs", 0) > 0  # noqa: E731
        res["model"] = {"rows_with_a_vacancy": {"train": sum(map(hit, train)), "test": sum(map(hit, test))},
                        "team shares": tdi.feature_test(train, test, ("vac_ts", "vac_cs"), hit),
                        "own position": tdi.feature_test(train, test, ("vac_ts_same", "vac_cs_rb"), hit)}
    OUT.write_text(json.dumps(res, indent=1))
    print(json.dumps({k: v for k, v in res.items() if k != "model"}, indent=1))


if __name__ == "__main__":
    main()
