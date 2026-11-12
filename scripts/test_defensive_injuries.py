"""Do offensive archetypes beat their projections when the opposing defense is missing starters at a position group?

    python -m scripts.test_defensive_injuries [--data DIR]

Defensive starters per group from nflverse snap counts: the 2 corners, 2 safeties, 2 linebackers and 4 linemen
with the most defensive snaps over the team's previous three games; a starter is out when he played no
defensive snaps in the game (inactive, or ruled out before it -- what the app reads from injury news live).
Offensive archetypes as in scripts.test_wr_te_dst_archetypes. For each archetype and group: the miss against
the app's corrected projection with the starter(s) out vs not, flagged only at 2.5+ standard errors and the same
direction in 2023-2024 and 2025-2026. Then the groups out as correction-model inputs (each of 2023-2025 held
out, and 2026). Writes data/defensive_injury_tests.json.
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import io
import json
import statistics
from collections import defaultdict
from pathlib import Path

import numpy as np

from app import player_model as pm
from scripts import test_player_features as tpf, test_wr_te_dst_archetypes as twd, train_dst_model as tdm
from scripts import train_player_model as tpm
from scripts.train_game_model import REL, fetch

OUT = Path(__file__).resolve().parent.parent / "data" / "defensive_injury_tests.json"
TRAIN, TEST = (2023, 2024, 2025), 2026
GROUPS = {"CB": (("CB",), 2), "S": (("S", "SS", "FS"), 2), "LB": (("LB", "ILB", "OLB", "MLB"), 2),
          "DL": (("DE", "DT", "DL", "NT"), 4)}
FLAG_Z = 2.5


def mean(xs, default=0.0):
    xs = list(xs)
    return statistics.fmean(xs) if xs else default


def groups_out(d: Path, season: int) -> dict[tuple[int, str], dict[str, int]]:
    """{(week, team): {group: starters out}}."""
    snaps = defaultdict(lambda: defaultdict(dict))          # group -> (week, team) -> player -> snaps
    with open(fetch(f"{REL}/snap_counts/snap_counts_{season}.csv", d / f"snap_counts_{season}.csv"), newline="") as fh:
        for r in csv.DictReader(fh):
            if r.get("game_type", "REG") != "REG" or not r.get("week"):
                continue
            g = next((k for k, (poss, _) in GROUPS.items() if r.get("position") in poss), None)
            if g:
                snaps[g][(int(r["week"]), r["team"])][r["player"]] = float(r.get("defense_snaps") or 0)
    out = defaultdict(dict)
    teams = {t for g in snaps.values() for (_, t) in g}
    for g, (_, n) in GROUPS.items():
        for t in teams:
            weeks = sorted(w for (w, tt) in snaps[g] if tt == t)
            for w in weeks:
                prev = [x for x in weeks if x < w][-3:]
                if not prev:
                    continue
                tot = defaultdict(float)
                for x in prev:
                    for p, s in snaps[g][(x, t)].items():
                        tot[p] += s
                starters = sorted(tot, key=lambda p: -tot[p])[:n]
                played = snaps[g][(w, t)]
                out[(w, t)][g] = sum(1 for p in starters if played.get(p, 0) <= 0)
    return out


def cells(rows: list[dict]) -> tuple[dict, list]:
    out, flags = {}, []
    for a in sorted({r["arch"] for r in rows if r["arch"]}):
        base = [r for r in rows if r["arch"] == a and r["out"] is not None]
        if len(base) < 150:
            continue
        res_all = np.array([r["actual"] - r["corrected"] for r in base])
        out[a] = {"n": len(base), "avg_miss": round(float(res_all.mean()), 2)}
        for g in GROUPS:
            k = 2 if g == "DL" else 1
            sub = [r for r in base if r["out"].get(g, 0) >= k]
            rest = [r for r in base if r["out"].get(g, 0) < k]
            if len(sub) < 30:
                continue
            res = np.array([r["actual"] - r["corrected"] for r in sub])
            res_rest = np.array([r["actual"] - r["corrected"] for r in rest])
            se = (res_all.var() / len(sub) + res_all.var() / len(rest)) ** 0.5
            z = (res.mean() - res_rest.mean()) / se
            halves = []
            for early in (True, False):
                s1 = [r["actual"] - r["corrected"] for r in sub if (r["season"] <= 2024) == early]
                s0 = [r["actual"] - r["corrected"] for r in rest if (r["season"] <= 2024) == early]
                halves.append(round(mean(s1) - mean(s0), 2) if s1 and s0 else None)
            label = f"{k}+ {g} starter{'s' if k > 1 else ''} out"
            c = {"n_out": len(sub), "miss_with_out": round(float(res.mean()), 2), "miss_without": round(float(res_rest.mean()), 2),
                 "gap": round(float(res.mean() - res_rest.mean()), 2), "z": round(float(z), 2),
                 "boom_with_out": round(mean(r["actual"] >= 1.5 * r["corrected"] for r in sub), 3),
                 "boom_without": round(mean(r["actual"] >= 1.5 * r["corrected"] for r in rest), 3),
                 "gap_2023_24": halves[0], "gap_2025_26": halves[1]}
            out[a][label] = c
            if abs(z) >= FLAG_Z and halves[0] is not None and halves[1] is not None and np.sign(halves[0]) == np.sign(halves[1]) == np.sign(z):
                flags.append({"archetype": a, "defense": label, **c})
    return out, sorted(flags, key=lambda x: -abs(x["z"]))


def quiet(fn, *a):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a)


def feature_test(train, test, feats_extra, sel) -> dict:
    seasons = list(TRAIN)
    out = {}
    for label, feats in (("current", pm.FEATURES), ("+" + "+".join(feats_extra), pm.FEATURES + tuple(feats_extra))):
        res = {"loso": quiet(tpf.loso, train, feats, seasons), "test_2026": quiet(tpf.check, train, test, feats, seasons)}
        sub = []
        for s in seasons:
            m = quiet(tpm.fit_all, [r for r in train if r["season"] != s], feats, [x for x in seasons if x != s])
            sub += [abs(r["actual"] - r["proj"] - (pm.adjustment(r["pos"], r["f"], {"positions": m}) or 0)) for r in train if r["season"] == s and sel(r)]
        m = quiet(tpm.fit_all, train, feats, seasons)
        s26 = [abs(r["actual"] - r["proj"] - (pm.adjustment(r["pos"], r["f"], {"positions": m}) or 0)) for r in test if sel(r)]
        res["loso_subset_mae"], res["test_2026_subset_mae"] = round(mean(sub), 3), round(mean(s26), 3)
        out[label] = res
    k = list(out)
    print(k[1], "LOSO", out[k[0]]["loso"]["mae_corrected"], "->", out[k[1]]["loso"]["mae_corrected"],
          "rho", out[k[0]]["loso"]["rank_rho_corrected"], "->", out[k[1]]["loso"]["rank_rho_corrected"],
          "| 2026", out[k[0]]["test_2026"]["mae_corrected"], "->", out[k[1]]["test_2026"]["mae_corrected"],
          "| subset LOSO", out[k[0]]["loso_subset_mae"], "->", out[k[1]]["loso_subset_mae"],
          "2026", out[k[0]]["test_2026_subset_mae"], "->", out[k[1]]["test_2026_subset_mae"], flush=True)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/cache/train")
    ap.add_argument("--test-weeks", type=int, default=6)
    args = ap.parse_args()
    d = Path(args.data)
    sd = tdm.pa_sd(d, list(TRAIN))
    rows = {}
    for s in (*TRAIN, TEST):
        weeks = list(range(1, 19)) if s in TRAIN else list(range(1, args.test_weeks + 1))
        players, _ = twd.season(d, s, weeks, sd)
        out = groups_out(d, s)
        for r in players:
            o = out.get((r["week"], r["opp"]))
            r["out"] = o
            o = o or {}
            pos = r["pos"]
            r["f"] = {**r["f"],
                      "cb_out_x_wr": float(o.get("CB", 0)) if pos == "WR" else 0.0,
                      "s_out_x_te": float(o.get("S", 0)) if pos == "TE" else 0.0,
                      "lb_out_x_te_rb": float(o.get("LB", 0)) if pos in ("TE", "RB") else 0.0,
                      "db_out_x_qb": float(o.get("CB", 0) + o.get("S", 0)) if pos == "QB" else 0.0,
                      "cb_out_x_alpha": float(o.get("CB", 0)) if r["arch"] == "alpha WR" else 0.0,
                      "cb_out_x_deep": float(o.get("CB", 0)) if r["arch"] == "deep threat WR" else 0.0}
        rows[s] = players
        print(s, len(players), flush=True)
    train = [r for s in TRAIN for r in rows[s]]
    test = rows[TEST]
    allr = train + test
    res: dict = {"groups": {g: f"{n} starters ({', '.join(p)})" for g, (p, n) in GROUPS.items()}}
    res["share_of_games_with_starters_out"] = {
        g: round(mean((r["out"] or {}).get(g, 0) >= (2 if g == "DL" else 1) for r in allr if r["out"] is not None), 3) for g in GROUPS}
    res["cells_2023_2026"], res["flags"] = cells(allr)
    wr = lambda r: r["pos"] == "WR"  # noqa: E731
    te = lambda r: r["pos"] == "TE"  # noqa: E731
    res["model"] = {
        "cb_out_x_wr": feature_test(train, test, ("cb_out_x_wr",), wr),
        "cb_out by WR type": feature_test(train, test, ("cb_out_x_alpha", "cb_out_x_deep"), wr),
        "s_out_x_te": feature_test(train, test, ("s_out_x_te",), te),
        "lb_out_x_te_rb": feature_test(train, test, ("lb_out_x_te_rb",), lambda r: r["pos"] in ("TE", "RB")),
        "db_out_x_qb": feature_test(train, test, ("db_out_x_qb",), lambda r: r["pos"] == "QB"),
    }
    OUT.write_text(json.dumps(res, indent=1))
    print(json.dumps({k: v for k, v in res.items() if k != "model"}, indent=1))


if __name__ == "__main__":
    main()
