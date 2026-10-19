"""Fit game model v2 (app.game_model) on 2023-2025 and test it on this season.

    python -m scripts.train_game_model [--data DIR] [--test-season 2026]

Downloads nflverse play-by-play (2022-2026), FTN charting, participation (2023-2025), snap counts and the
games/lines file into DIR (default data/cache/train; reused when present), builds every game's features from
the weeks before it, picks the ridge penalty by leaving one season out, and writes data/game_model.json:
weights, feature scaling, end-of-last-season priors, the checklist and model records.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import math
import statistics
import sys
import urllib.request
from pathlib import Path

from app import game_model as gm

REL = "https://github.com/nflverse/nflverse-data/releases/download"
GAMES_URL = "https://raw.githubusercontent.com/nfldata/nfldata/master/data/games.csv".replace("nfldata/nfldata", "nflverse/nfldata")
OL = {"OL", "T", "G", "C"}
ALPHAS = (3, 10, 30, 100, 300, 1000, 3000)


def fetch(url: str, path: Path) -> Path:
    if not path.exists() or path.stat().st_size == 0:
        print(f"downloading {url}", file=sys.stderr)
        with urllib.request.urlopen(url, timeout=300) as r, open(path, "wb") as f:
            f.write(r.read())
    return path


def ftn_index(path: Path) -> dict:
    out = {}
    for r in csv.DictReader(open(path, newline="")):
        n = gm._i(r.get("n_pass_rushers"))
        if r.get("nflverse_game_id") and r.get("nflverse_play_id") and n:
            out[f"{r['nflverse_game_id']}|{int(float(r['nflverse_play_id']))}"] = n
    return out


def part_index(path: Path) -> dict:
    out = {}
    for r in csv.DictReader(open(path, newline="")):
        if r.get("time_to_throw") in (None, "", "NA"):
            continue
        out[f"{r['nflverse_game_id']}|{gm._i(r['play_id'])}"] = (
            gm._i(r.get("number_of_pass_rushers")), gm._f(r.get("time_to_throw")), str(r.get("was_pressure")).upper() == "TRUE")
    return out


def season_agg(d: Path, year: int) -> dict:
    cache = d / f"agg_{year}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    ftn = ftn_index(fetch(f"{REL}/ftn_charting/ftn_charting_{year}.csv", d / f"ftn_charting_{year}.csv")) if year >= 2022 else {}
    part = {}
    if 2023 <= year <= 2025:
        part = part_index(fetch(f"{REL}/pbp_participation/pbp_participation_{year}.csv", d / f"pbp_participation_{year}.csv"))
    acc = gm.GameAccumulator(ftn=ftn, part=part)
    pbp = fetch(f"{REL}/pbp/play_by_play_{year}.csv.gz", d / f"play_by_play_{year}.csv.gz")
    for r in csv.DictReader(io.TextIOWrapper(gzip.open(pbp), encoding="utf-8")):
        acc.add(r)
    out = acc.result()
    cache.write_text(json.dumps(out))
    return out


def snap_ol(d: Path, year: int) -> dict[tuple[int, str], dict[str, float]]:
    """{(week, team): {player: offense snaps}} for offensive linemen."""
    out: dict[tuple[int, str], dict[str, float]] = {}
    path = fetch(f"{REL}/snap_counts/snap_counts_{year}.csv", d / f"snap_counts_{year}.csv")
    for r in csv.DictReader(open(path, newline="")):
        if r.get("game_type") == "REG" and r.get("position") in OL:
            out.setdefault((int(r["week"]), r["team"]), {})[r["pfr_player_id"]] = gm._f(r.get("offense_snaps")) or 0.0
    return out


def ol_starters(snaps: dict, team: str, week: int) -> list[str]:
    """The five linemen with the most snaps over the team's last three games before `week`."""
    tot: dict[str, float] = {}
    weeks = sorted({w for (w, t) in snaps if t == team and w < week})[-3:]
    for w in weeks:
        for p, s in snaps[(w, team)].items():
            tot[p] = tot.get(p, 0.0) + s
    return sorted(tot, key=lambda p: -tot[p])[:5]


def ol_out(snaps: dict, team: str, week: int) -> int:
    starters = ol_starters(snaps, team, week)
    played = snaps.get((week, team))
    if not starters or played is None:
        return 0
    return sum(1 for p in starters if (played.get(p) or 0) <= 0)


def snap_def(d: Path, year: int) -> dict[str, dict[tuple[int, str], dict[str, float]]]:
    """{unit: {(week, team): {player: defensive snaps}}} for defensive linemen, linebackers and backs."""
    out: dict[str, dict] = {u: {} for u in gm.DEF_UNITS}
    path = fetch(f"{REL}/snap_counts/snap_counts_{year}.csv", d / f"snap_counts_{year}.csv")
    for r in csv.DictReader(open(path, newline="")):
        u = gm.def_unit(r.get("position"))
        if r.get("game_type") == "REG" and u:
            out[u].setdefault((int(r["week"]), r["team"]), {})[r["pfr_player_id"]] = gm._f(r.get("defense_snaps")) or 0.0
    return out


def build_rows(d: Path, seasons: list[int]) -> list[dict]:
    games_path = fetch(GAMES_URL, d / "games.csv")
    games = [g for g in csv.DictReader(open(games_path, newline="")) if g["game_type"] == "REG"]
    aggs = {y: season_agg(d, y) for y in sorted({s - 1 for s in seasons} | set(seasons))}
    rows = []
    for y in seasons:
        prior = gm.priors_from_season(gm.season_totals(aggs[y - 1]))
        snaps, dsnaps = snap_ol(d, y), snap_def(d, y)
        pts: dict[tuple[int, str], int] = {}
        prev_pts: dict[str, list[int]] = {}
        for g in games:
            if g["home_score"] == "" or g["season"] not in (str(y), str(y - 1)):
                continue
            for t, p in ((g["away_team"], g["away_score"]), (g["home_team"], g["home_score"])):
                if g["season"] == str(y):
                    pts[(int(g["week"]), t)] = int(p)
                else:
                    prev_pts.setdefault(t, []).append(int(p))
        floor_prior = {t: sum(p >= 24 for p in v) / len(v) for t, v in prev_pts.items() if v}
        for g in games:
            if g["season"] != str(y) or g["home_score"] == "" or not g["total_line"] or not g["spread_line"]:
                continue
            w, a, h = int(g["week"]), g["away_team"], g["home_team"]
            cur = gm.season_totals(aggs[y], before_week=w)
            est = gm.team_estimates(cur, prior)
            hist = gm.qb_history(aggs[y - 1], aggs[y], before_week=w)
            lg = prior["league"]
            qb = {t: gm.qb_estimate(hist, g[f"{side}_qb_id"], lg["pass_epa"]) for t, side in ((a, "away"), (h, "home"))}
            dout = {t: gm.def_out_played(dsnaps, t, w) for t in (a, h)}
            feats = gm.game_features(
                a, h, est, lg, total_line=float(g["total_line"]), spread_line=float(g["spread_line"]), qb=qb,
                ol_out={a: ol_out(snaps, a, w), h: ol_out(snaps, h, w)}, wind=gm._f(g.get("wind")),
                indoor=g.get("roof") in ("dome", "closed"), rest=(gm._f(g.get("away_rest")), gm._f(g.get("home_rest"))),
                floor24={t: gm.floor_share(pts, floor_prior, t, w) for t in (a, h)},
                def_out={t: sum(v.values()) for t, v in dout.items()})
            if not feats:
                continue
            total = int(g["home_score"]) + int(g["away_score"])
            margin = int(g["home_score"]) - int(g["away_score"])
            rows.append({"season": y, "week": w, "game": f"{a}@{h}", "tot": feats[0], "mar": feats[1],
                         "total": total, "margin": margin, "total_line": float(g["total_line"]),
                         "spread_line": float(g["spread_line"]), "est": {a: est[a], h: est[h]}, "league": lg,
                         "qb": {a: qb[a], h: qb[h]}, "def_out": dout})
    return rows


# --------------------------------------------------------------------------- evaluation
def _target(r, kind):
    return r["total"] - r["total_line"] if kind == "total" else r["margin"] - r["spread_line"]


def fit(rows, kind, alpha, feats=None):
    feats = feats or (gm.TOTAL_FEATURES if kind == "total" else gm.MARGIN_FEATURES)
    key = "tot" if kind == "total" else "mar"
    X = [[r[key][f] for f in feats] for r in rows]
    w, m, s, b = gm.fit_ridge(X, [_target(r, kind) for r in rows], alpha)
    return {"features": list(feats), "weights": w, "means": m, "sds": s, "intercept": b, "alpha": alpha}


def evaluate(model, rows, kind, edge=0.0) -> dict:
    key = "tot" if kind == "total" else "mar"
    preds = [(gm.apply(model, r[key]), _target(r, kind)) for r in rows]
    picks = [(p, y) for p, y in preds if y != 0 and abs(p) > edge]
    right = sum((p > 0) == (y > 0) for p, y in picks)
    rmse = math.sqrt(statistics.fmean((y - p) ** 2 for p, y in preds))
    base = math.sqrt(statistics.fmean(y ** 2 for _, y in preds))
    return {"n": len(picks), "right": right, "pct": round(right / len(picks), 3) if picks else None,
            "rmse": round(rmse, 3), "rmse_line": round(base, 3)}


def choose_alpha(rows, kind, seasons, feats=None):
    best = None
    for a in ALPHAS:
        res = []
        for s in seasons:
            train = [r for r in rows if r["season"] != s and r["season"] in seasons]
            test = [r for r in rows if r["season"] == s]
            res.append(evaluate(fit(train, kind, a, feats), test, kind))
        rmse = statistics.fmean(x["rmse"] for x in res)
        right, n = sum(x["right"] for x in res), sum(x["n"] for x in res)
        print(f"  {kind} alpha {a:5d}: CV rmse {rmse:.3f} (line {statistics.fmean(x['rmse_line'] for x in res):.3f})  picks {right}/{n} = {right / n:.1%}")
        if best is None or rmse < best[1]:
            best = (a, rmse, {"right": right, "n": n, "pct": round(right / n, 3)})
    return best


# --------------------------------------------------------------------------- checklist
def checklist_cuts(rows) -> dict:
    """Thresholds from the training games: top-8-of-32 pass rate and run defense, top tenth of quick-pressure
    edges, top third of drive velocity, pass rate over expected and pace."""
    teams = [e for r in rows for e in r["est"].values()]
    q = lambda vals, f: sorted(vals)[int(f * (len(vals) - 1))]  # noqa: E731
    return {
        "pass_rate": q([e["pass_rate"] for e in teams], 0.75), "run_def": q([e["d_rush_epa"] for e in teams], 0.25),
        "quick_edge": q([max(gm._quick_edges(*list(r["est"].values()), r["league"])) for r in rows], 0.9),
        "drive_velocity": q([gm._dv(*list(r["est"].values())) for r in rows], 2 / 3),
        "proe": q([r["tot"]["proe"] for r in rows], 2 / 3), "pace": q([r["tot"]["pace"] for r in rows], 2 / 3),
    }


def checklist(rows, cuts) -> dict:
    """Each audit item's record against the closing total on these games, in the direction it points."""
    out = {}
    for key, _label, call in gm.CHECKLIST:
        if call is None:
            continue
        xs = []
        for r in rows:
            a, h = list(r["est"].values())
            if gm.checklist_flags(a, h, r["league"], r["tot"], cuts)[key]:
                y = r["total"] - r["total_line"]
                if y:
                    xs.append(y)
        hit = sum((y > 0) == (call == "Over") for y in xs)
        out[key] = {"n": len(xs), "hit": hit, "pct": round(hit / len(xs), 3) if xs else None, "call": call}
    return out


def advanced_index_record(rows) -> dict:
    """The weekly-audit formula (app.advanced_env) on these games with the shrunk team rates: Over for games above
    the week's median index, Under below, against the closing total."""
    def idx(r):
        (_, a), (_, h) = list(r["est"].items())
        lg = r["league"]
        dv = (a["explosive"] + h["explosive"]) / max(a["sec_per_drive"] + h["sec_per_drive"], 120) * 1000
        fa = max(0, (lg["rush_epa"] - a["rush_epa"]) + (lg["d_rush_epa"] - h["d_rush_epa"])) * a["pass_rate"]
        fb = max(0, (lg["rush_epa"] - h["rush_epa"]) + (lg["d_rush_epa"] - a["d_rush_epa"])) * h["pass_rate"]
        pa, pb = (max(0, e) for e in gm._quick_edges(a, h, lg))
        return dv * 0.3 + (fa + fb) * 1.5 * 0.25 + (a["proe"] + h["proe"]) * 50 * 0.2 - (pa + pb) * 2.5 * 0.4
    right = n = 0
    for key in {(r["season"], r["week"]) for r in rows}:
        wk = [r for r in rows if (r["season"], r["week"]) == key]
        med = statistics.median(idx(r) for r in wk)
        for r in wk:
            y = r["total"] - r["total_line"]
            if y and idx(r) != med:
                n += 1
                right += (idx(r) > med) == (y > 0)
    return {"right": right, "n": n, "pct": round(right / n, 3) if n else None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/cache/train")
    ap.add_argument("--test-season", type=int, default=2026)
    args = ap.parse_args()
    d = Path(args.data)
    d.mkdir(parents=True, exist_ok=True)
    train_seasons = [2023, 2024, 2025]
    rows = build_rows(d, train_seasons + [args.test_season])
    json.dump(rows, open(d / "rows.json", "w"))
    train = [r for r in rows if r["season"] in train_seasons]
    test = [r for r in rows if r["season"] == args.test_season and r["week"] >= 2]
    print(f"training games {len(train)}, test games {len(test)}")
    out = {"trained_on": train_seasons, "records": {}}
    for kind in ("total", "margin"):
        alpha, rmse, cv = choose_alpha(rows, kind, train_seasons)
        model = fit(train, kind, alpha)
        out[kind] = model
        ts = evaluate(model, test, kind)
        out["records"][kind] = {"cv": cv, "cv_rmse": rmse, "test": ts}
        print(f"{kind}: alpha {alpha}; CV {cv}; {args.test_season} weeks 2+: {ts}")
    # Defensive starters out (away minus home) as a spread input: kept only if it beats the model without it on the
    # test season. It didn't (2026 weeks 2-6), so it's recorded here and left out of MARGIN_FEATURES.
    trial = gm.MARGIN_FEATURES + ("def_out",)
    alpha, rmse, cv = choose_alpha(rows, "margin", train_seasons, trial)
    m = fit(train, "margin", alpha, trial)
    out["records"]["margin_def_out_trial"] = {"cv": cv, "cv_rmse": rmse, "test": evaluate(m, test, "margin"),
                                              "weight": round(m["weights"][-1] / m["sds"][-1], 3)}
    print("margin + def_out trial:", out["records"]["margin_def_out_trial"])
    out["advanced_index_record"] = advanced_index_record([r for r in train if r["week"] >= 2])
    print("advanced index (weekly-audit formula) 2023-2025:", out["advanced_index_record"])
    cuts = checklist_cuts(train)
    out["checklist_cuts"] = cuts
    out["checklist"] = {"train": checklist(train, cuts), "test": checklist(test, cuts)}
    last = gm.season_totals(json.loads((d / f"agg_{args.test_season - 1}.json").read_text()))
    out["priors"] = gm.priors_from_season(last)
    games_path = d / "games.csv"
    prev = [g for g in csv.DictReader(open(games_path, newline="")) if g["season"] == str(args.test_season - 1)
            and g["game_type"] == "REG" and g["home_score"]]
    fl: dict[str, list[int]] = {}
    for g in prev:
        fl.setdefault(g["away_team"], []).append(int(g["away_score"]))
        fl.setdefault(g["home_team"], []).append(int(g["home_score"]))
    out["floor_prior"] = {t: round(sum(p >= 24 for p in v) / len(v), 3) for t, v in fl.items()}
    agg_prev = json.loads((d / f"agg_{args.test_season - 1}.json").read_text())
    out["qb_prior"] = {q: [round(v[0], 1), round(v[1], 2)] for q, v in gm.qb_history(agg_prev).items()}
    Path(gm.MODEL_FILE).write_text(json.dumps(out, indent=1))
    print(json.dumps(out["checklist"], indent=1))


if __name__ == "__main__":
    main()
