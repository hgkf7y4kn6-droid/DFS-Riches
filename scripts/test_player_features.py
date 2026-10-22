"""Test candidate inputs for the projection correction (app.player_model) before adding any of them.

    python -m scripts.test_player_features [--data DIR]

Candidates, each from games before the one projected:
  ays_l3      air-yard share over the last three games (nflverse weekly stats)
  wopr_l3     weighted opportunity rating (1.5 x target share + 0.7 x air-yard share), last three games
  ez_share    the player's share of his team's end-zone targets (air yards reaching the end zone, play-by-play),
              season to date
  ez_l3       end-zone targets per game, last three games
  plays_l3    the team's offensive plays per game (pass attempts + sacks + carries), last three games, vs 62
  dbp_l3      share of the team's dropbacks the player was on the field for (pbp_participation, a route
              participation stand-in) -- research only: nflverse hasn't published participation for 2026

Each candidate is added on its own, then all together, then the ones that helped in cross-validation. Out-of-sample
checks: each of 2023-2025 held out in turn (fit on the other two), and 2026 (fit on 2023-2025). A candidate is kept
only when it lowers error and doesn't hurt ranking in both. Writes data/player_feature_tests.json.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import statistics
from collections import defaultdict
from pathlib import Path

from app import game_model as gm, player_model as pm
from scripts import train_player_model as tpm
from scripts.train_game_model import REL, fetch

OUT = Path(__file__).resolve().parent.parent / "data" / "player_feature_tests.json"
CANDIDATES = ("ays_l3", "wopr_l3", "ez_share", "ez_l3", "plays_l3")
LEAGUE_PLAYS = 62.0


def f(x) -> float:
    return gm._f(x) or 0.0


def pbp_extras(d: Path, season: int, with_participation: bool):
    """({(week, player_id): end-zone targets}, {(week, team): dropbacks}, {(week, player_id): dropbacks on field})."""
    ez: dict[tuple[int, str], int] = defaultdict(int)
    dropback: dict[tuple[str, int], tuple[int, str]] = {}
    team_db: dict[tuple[int, str], int] = defaultdict(int)
    path = fetch(f"{REL}/pbp/play_by_play_{season}.csv.gz", d / f"play_by_play_{season}.csv.gz")
    with gzip.open(path, "rt", newline="") as fh:
        for p in csv.DictReader(fh):
            if p.get("season_type") != "REG" or not p.get("week"):
                continue
            w = int(p["week"])
            if p.get("qb_dropback") == "1" and p.get("posteam"):
                dropback[(p["game_id"], int(float(p["play_id"])))] = (w, p["posteam"])
                team_db[(w, p["posteam"])] += 1
            if p.get("pass_attempt") == "1" and p.get("receiver_player_id") and p.get("air_yards") and p.get("yardline_100"):
                if f(p["air_yards"]) >= f(p["yardline_100"]):
                    ez[(w, p["receiver_player_id"])] += 1
    on_field: dict[tuple[int, str], int] = defaultdict(int)
    if with_participation:
        part = d / f"pbp_participation_{season}.csv"
        if part.exists():
            for r in csv.DictReader(open(part, newline="")):
                k = (r["nflverse_game_id"], int(float(r["play_id"] or 0)))
                if k in dropback:
                    w, _ = dropback[k]
                    for pid in (r.get("offense_players") or "").split(";"):
                        if pid:
                            on_field[(w, pid)] += 1
    return ez, team_db, on_field


def extras_history(d: Path, season: int, with_participation: bool) -> dict[str, dict[int, dict]]:
    """{player key: {week: {ays, wopr, ez, ez_team, plays, dbp}}} for the candidate features."""
    stats = [r for r in csv.DictReader(open(fetch(f"{REL}/stats_player/stats_player_week_{season}.csv",
                                                  d / f"stats_player_week_{season}.csv"), newline=""))
             if r.get("season_type", "REG") == "REG" and r.get("week")]
    ez, team_db, on_field = pbp_extras(d, season, with_participation)
    plays: dict[tuple[int, str], float] = defaultdict(float)
    ez_team: dict[tuple[int, str], int] = defaultdict(int)
    for r in stats:
        w, t = int(r["week"]), r.get("team") or ""
        plays[(w, t)] += f(r.get("attempts")) + f(r.get("sacks_suffered")) + f(r.get("carries"))
        ez_team[(w, t)] += ez.get((w, r.get("player_id")), 0)
    out: dict[str, dict[int, dict]] = {}
    for r in stats:
        pos = r.get("position")
        if pos not in pm.POSITIONS:
            continue
        w, t, pid = int(r["week"]), r.get("team") or "", r.get("player_id")
        db = team_db.get((w, t)) or 0
        out.setdefault(pm.key(r["player_display_name"], pos), {})[w] = {
            "ays": f(r.get("air_yards_share")), "wopr": f(r.get("wopr")), "ez": ez.get((w, pid), 0),
            "ez_team": ez_team[(w, t)], "plays": plays[(w, t)],
            "dbp": (on_field.get((w, pid), 0) / db) if db and with_participation else None}
    return out


def candidate_features(h: dict[int, dict] | None, week: int) -> dict:
    g = [h[w] for w in sorted(h or {}) if w < week]
    l3 = g[-3:]
    mean = lambda xs: statistics.fmean(xs) if xs else 0.0  # noqa: E731
    ez_team = sum(x["ez_team"] for x in g)
    dbp = [x["dbp"] for x in l3 if x.get("dbp") is not None]
    return {"ays_l3": mean([x["ays"] for x in l3]), "wopr_l3": mean([x["wopr"] for x in l3]),
            "ez_share": sum(x["ez"] for x in g) / ez_team if ez_team else 0.0,
            "ez_l3": mean([x["ez"] for x in l3]),
            "plays_l3": (mean([x["plays"] for x in l3]) - LEAGUE_PLAYS) if l3 else 0.0,
            "dbp_l3": mean(dbp)}


def rows(d: Path, season: int, weeks, with_participation=False) -> list[dict]:
    ex = extras_history(d, season, with_participation)
    out = []
    for r in tpm.rows_for(d, season, weeks):
        if r["week"] < 2:
            continue
        r["f"] = {**r["f"], **candidate_features(ex.get(r["key"]), r["week"])}
        out.append(r)
    return out


def quiet_fit(train, features, seasons):
    import contextlib
    import io
    with contextlib.redirect_stdout(io.StringIO()):
        return tpm.fit_all(train, features, seasons)


def check(train_rows, test_rows, features, seasons) -> dict:
    return tpm.evaluate(test_rows, quiet_fit(train_rows, features, seasons))


def loso(all_rows, features, seasons) -> dict:
    """Each season held out in turn; MAE and ranking pooled over the held-out rows."""
    per = []
    for s in seasons:
        tr = [r for r in all_rows if r["season"] != s]
        te = [r for r in all_rows if r["season"] == s]
        per.append((len(te), check(tr, te, features, [x for x in seasons if x != s])))
    n = sum(k for k, _ in per)
    w = lambda key: round(sum(k * e[key] for k, e in per) / n, 3)  # noqa: E731
    return {"n": n, "mae_sleeper": w("mae_sleeper"), "mae_corrected": w("mae_corrected"),
            "rank_rho_sleeper": w("rank_rho_sleeper"), "rank_rho_corrected": w("rank_rho_corrected"),
            "adj_vs_miss_rho": w("adj_vs_miss_rho")}


def by_position(test_rows, models) -> dict:
    return {p: {k: v for k, v in tpm.evaluate([r for r in test_rows if r["pos"] == p], models).items()
                if k in ("n", "mae_sleeper", "mae_corrected", "rank_rho_sleeper", "rank_rho_corrected")}
            for p in pm.POSITIONS}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/cache/train")
    ap.add_argument("--test-season", type=int, default=2026)
    ap.add_argument("--test-weeks", type=int, default=6)
    args = ap.parse_args()
    d = Path(args.data)
    seasons = [args.test_season - 3, args.test_season - 2, args.test_season - 1]
    train = [r for s in seasons for r in rows(d, s, range(1, 19), with_participation=True)]
    test = rows(d, args.test_season, range(1, args.test_weeks + 1))
    print(f"train {len(train)}, test {len(test)}")
    base = pm.FEATURES
    res: dict = {"train_seasons": seasons, "test_season": args.test_season, "test_weeks": args.test_weeks,
                 "n_train": len(train), "n_test": len(test), "sets": {}}

    def run(name, feats):
        r = {"features": list(feats), "loso": loso(train, feats, seasons), "test": check(train, test, feats, seasons)}
        res["sets"][name] = r
        print(name, "LOSO mae", r["loso"]["mae_corrected"], "rho", r["loso"]["rank_rho_corrected"],
              "| 2026 mae", r["test"]["mae_corrected"], "rho", r["test"]["rank_rho_corrected"])
        return r

    cur = run("current", base)
    better = lambda a, b: a["mae_corrected"] < b["mae_corrected"] and a["rank_rho_corrected"] >= b["rank_rho_corrected"]  # noqa: E731
    helped, kept = [], []
    for c in CANDIDATES:
        r = run(f"+{c}", base + (c,))
        if better(r["loso"], cur["loso"]):
            helped.append(c)
            if better(r["test"], cur["test"]):
                kept.append(c)
    run("+all candidates", base + CANDIDATES)
    if helped:
        best = run("+helped (" + ", ".join(helped) + ")", base + tuple(helped))
        res["helped_cross_validation"] = helped
        res["by_position_current"] = by_position(test, quiet_fit(train, base, seasons))
        res["by_position_helped"] = by_position(test, quiet_fit(train, base + tuple(helped), seasons))
        res["helped_test"] = best["test"]

    res["kept"] = kept
    print("kept", kept)

    # Route participation stand-in: fit 2023-2024, test 2025 (no 2026 participation data).
    tr = [r for r in train if r["season"] != seasons[-1]]
    te = [r for r in train if r["season"] == seasons[-1]]
    res["participation_2025"] = {
        "current": check(tr, te, base, seasons[:-1]),
        "+dbp_l3": check(tr, te, base + ("dbp_l3",), seasons[:-1]),
    }
    print("dbp 2025", res["participation_2025"])
    OUT.write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
