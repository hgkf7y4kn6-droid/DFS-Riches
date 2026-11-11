"""Would choosing the model lineups by Monte Carlo simulation beat the current rules?

    python -m scripts.test_monte_carlo_lineups --bt DIR [--workers 4] [slate keys...]

DIR holds the rebuilt DraftKings Sunday main slates of the construction backtest (prep_<season>_<week>.pkl: each
player's projection, floor, median, ceiling, large-field ownership and actual points, plus the simulated cash and
large-field GPP fields scored with actual points). Per slate:

1. Outcomes: each player's points drawn from his own floor / median / ceiling (15th / 50th / 85th percentiles: a
   normal below the median and another above it), tied together within each game by a Gaussian copula over team
   roles (QB, RB1-2, WR1-3, TE, DST, for both teams) whose correlations come from the other seasons' slates
   (each season held out in turn), from each player's actual result placed in his range.
2. The fields: the same 10,000 cash and large-field lineups the backtest scores (app.field_ownership's simulation),
   scored in every simulated outcome, so each draw has its own cash line (56th percentile) and top 1% / 0.1%.
3. Candidates: the current Safe (most projected points) and Tournament (QB + 2 pass catchers + an opposing WR, one RB
   per team, $49,000+) lineups, plus the best lineup in each of 150 simulated outcomes, with and without the
   tournament stack -- every lineup the simulation would consider.
4. Picks, on 4,000 fresh draws: Monte Carlo Safe = the candidate most likely to cash; Monte Carlo Tournament = the
   one most likely to finish in the top 1% (ties: the top 0.1%, then the mean).
5. Graded on what happened: actual points, the field percentile, cashing, top 1% / 0.1%.
Writes data/monte_carlo_lineup_tests.json.
"""
from __future__ import annotations

import argparse
import glob
import json
import pickle
import statistics
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
from scipy.stats import norm

from app import dfs_strategy as ds, field_ownership as fo, lineup_builder

OUT = Path(__file__).resolve().parent.parent / "data" / "monte_carlo_lineup_tests.json"
ROLES = ("QB", "RB1", "RB2", "WR1", "WR2", "WR3", "TE", "DST")
Z85 = norm.ppf(0.85)
N_GEN, N_EVAL, N_FIELD = 150, 4000, 10_000
TOP_N = {"QB": 22, "RB": 36, "WR": 54, "TE": 22, "DST": 16}


def roles(rows: list[dict]) -> dict[int, str]:
    """Row index -> team role by projection (extra RBs count as RB2, extra WRs as WR3, extra TEs as TE)."""
    out = {}
    by = defaultdict(list)
    for i, r in enumerate(rows):
        by[(r["team"], r["position"])].append(i)
    for (team, pos), idx in by.items():
        idx.sort(key=lambda i: -rows[i]["final"])
        for k, i in enumerate(idx):
            if pos == "QB":
                out[i] = "QB" if k == 0 else None
            elif pos == "RB":
                out[i] = "RB1" if k == 0 else "RB2"
            elif pos == "WR":
                out[i] = ("WR1", "WR2", "WR3")[min(k, 2)]
            elif pos == "TE":
                out[i] = "TE"
            elif pos == "DST":
                out[i] = "DST"
    return out


def spreads(rows):
    med = np.array([r["median"] for r in rows])
    lo = np.maximum((med - np.array([r["floor"] for r in rows])) / Z85, 0.3)
    hi = np.maximum((np.array([r["ceiling"] for r in rows]) - med) / Z85, 0.3)
    return med, lo, hi


def z_actual(rows) -> np.ndarray:
    med, lo, hi = spreads(rows)
    a = np.array([r["actual"] for r in rows])
    return np.where(a < med, (a - med) / lo, (a - med) / hi)


def game_sides(rows):
    """{game: (home-ish team, other team)} in a fixed order."""
    out = {}
    for r in rows:
        out.setdefault(r["game"], set()).add(r["team"])
    return {g: tuple(sorted(t)) for g, t in out.items() if len(t) == 2}


def team_game_vectors(P) -> list[np.ndarray]:
    """One 16-vector per game (team A's roles then team B's, NaN where missing) of the starters' z's."""
    rows = P["rows"]
    rl, z = roles(rows), z_actual(rows)
    vecs = []
    for g, (a, b) in game_sides(rows).items():
        v = np.full(2 * len(ROLES), np.nan)
        for side, team in enumerate((a, b)):
            for i, r in enumerate(rows):
                if r["team"] == team and rl.get(i) and (r["final"] >= 3 or r["position"] == "DST"):
                    k = side * len(ROLES) + ROLES.index(rl[i])
                    if np.isnan(v[k]):          # the top player in each role
                        v[k] = z[i]
        vecs.append(v)
    return vecs


def correlation(vecs: list[np.ndarray]) -> np.ndarray:
    """Pairwise correlations by role (both orientations of each game pooled, so A/B is symmetric), made positive
    definite."""
    X = np.array(vecs + [np.concatenate([v[len(ROLES):], v[:len(ROLES)]]) for v in vecs])
    n = X.shape[1]
    C = np.eye(n)
    for i in range(n):
        for j in range(i + 1, n):
            m = ~np.isnan(X[:, i]) & ~np.isnan(X[:, j])
            if m.sum() > 30:
                C[i, j] = C[j, i] = np.corrcoef(np.clip(X[m, i], -4, 4), np.clip(X[m, j], -4, 4))[0, 1]
    w, V = np.linalg.eigh(C)
    C = V @ np.diag(np.maximum(w, 1e-3)) @ V.T
    d = np.sqrt(np.diag(C))
    return C / np.outer(d, d)


def simulate(rows, C, S, rng) -> np.ndarray:
    """S x players simulated DK points."""
    med, lo, hi = spreads(rows)
    rl = roles(rows)
    Z = rng.standard_normal((S, len(rows)))           # independent for players without a role
    L = np.linalg.cholesky(C)
    for g, (a, b) in game_sides(rows).items():
        G = rng.standard_normal((S, C.shape[0])) @ L.T
        for i, r in enumerate(rows):
            if r["game"] == g and rl.get(i):
                Z[:, i] = G[:, (0 if r["team"] == a else 1) * len(ROLES) + ROLES.index(rl[i])]
    pts = np.where(Z < 0, med + Z * lo, med + Z * hi)
    floor = np.array([-4.0 if r["position"] == "DST" else -1.0 for r in rows])
    return np.maximum(pts, floor)


def field_picks(rows, contest, seed):
    """The backtest's simulated field (run.field_scores): (picks matrix over `keep`, keep)."""
    cfg = fo.CONTESTS[contest]
    keep = []
    for pos, k in fo.SIM_POOL.items():
        idx = [i for i, r in enumerate(rows) if r["position"] == pos]
        keep += sorted(idx, key=lambda i: -(rows[i]["final"] + 0.5 * rows[i]["ceiling"]))[:k]
    keep.sort()
    pool = fo._pool([rows[i] for i in keep])
    rng = np.random.default_rng(seed)
    out = []
    for start in range(0, N_FIELD, fo.SIM_CHUNK):
        S = min(fo.SIM_CHUNK, N_FIELD - start)
        n = len(pool.final)
        base = pool.final + cfg["ceiling_w"] * (pool.ceiling - pool.final) - cfg["floor_w"] * (pool.final - pool.floor)
        z = rng.standard_normal((S, n))
        sd = np.where(z >= 0, pool.sd_high, pool.sd_low)
        team_z = rng.standard_normal((S, len(pool.teams)))[:, pool.team_idx]
        shock = cfg["team_shock"] * team_z * (pool.sd_high + pool.sd_low) / 2
        scores = base[None, :] + cfg["noise"] * (np.sqrt(1 - cfg["team_shock"] ** 2) * z * sd) + cfg["noise"] * shock
        sal_k = pool.salary / 1000
        lo, hi = np.zeros(S), np.full(S, 12.0)
        for _ in range(15):
            mid = (lo + hi) / 2
            picks = fo._pick(scores - mid[:, None] * sal_k[None, :], pool)
            fits = (picks * pool.salary[None, :]).sum(axis=1) <= fo.CAP
            hi, lo = np.where(fits, mid, hi), np.where(fits, lo, mid)
        out.append(fo._pick(scores - hi[:, None] * sal_k[None, :], pool).astype(np.float32))
    return np.concatenate(out), keep


def trim(rows, value):
    keep = []
    for pos, k in TOP_N.items():
        idx = sorted([i for i, r in enumerate(rows) if r["position"] == pos and (r["final"] >= 3 or pos == "DST")],
                     key=lambda i: -value[i])
        keep += idx[:k]
    return sorted(keep)


def build(rows, idx, values, tournament: bool):
    pool = [rows[i] for i in idx]
    vals = [values[i] for i in idx]
    if tournament:
        for kw in (dict(stack=(2, 1), bring_back_pos=("WR",), min_salary=ds.GPP_MIN_SALARY), dict(stack=(2, 1)), dict(stack=(1, 0)), {}):
            lu = lineup_builder.build(pool, vals, one_rb_per_team=True, **kw)
            if lu:
                break
    else:
        lu = lineup_builder.build(pool, vals)
    if not lu:
        return None
    ids = {p["id"] for p in lu}
    return tuple(sorted(i for i in idx if rows[i]["id"] in ids))


def run_slate(args) -> dict:
    path, C = args
    P = pickle.load(open(path, "rb"))
    rows = P["rows"]
    seed = P["season"] * 100 + P["week"]
    rng = np.random.default_rng(seed)
    final = [r["final"] for r in rows]
    tour_vals = [r["final"] + (ds.WR_FLEX_BONUS if r["position"] == "WR" else 0) for r in rows]
    safe = build(rows, trim(rows, final), final, False)
    tour = build(rows, trim(rows, tour_vals), tour_vals, True)
    cands = {safe, tour}
    gen = simulate(rows, C, N_GEN, rng)
    for k in range(N_GEN):
        v = list(gen[k])
        idx = trim(rows, v)
        cands.add(build(rows, idx, v, False))
        cands.add(build(rows, idx, v, True))
    cands.discard(None)
    cands = sorted(cands)
    ev = simulate(rows, C, N_EVAL, rng)
    out = {"season": P["season"], "week": P["week"], "candidates": len(cands)}
    thresholds = {}
    for contest, seed_mult in (("large_gpp", 7), ("cash", 11)):
        picks, keep = field_picks(rows, contest, seed=P["week"] * seed_mult + P["season"])
        fs = picks @ ev[:, keep].T.astype(np.float32)          # field x draws
        if contest == "cash":
            thresholds["cash"] = np.quantile(fs, 0.56, axis=0)
        else:
            thresholds["top1"], thresholds["top01"] = np.quantile(fs, 0.99, axis=0), np.quantile(fs, 0.999, axis=0)
    M = np.zeros((len(cands), len(rows)), dtype=np.float32)
    for c, lu in enumerate(cands):
        M[c, list(lu)] = 1
    sim = M @ ev.T                                              # candidates x draws
    p_cash = (sim >= thresholds["cash"][None, :]).mean(axis=1)
    p_top1 = (sim >= thresholds["top1"][None, :]).mean(axis=1)
    p_top01 = (sim >= thresholds["top01"][None, :]).mean(axis=1)
    mean = sim.mean(axis=1)
    actual = np.array([r["actual"] for r in rows])
    gf, cf = P["gpp_field"], P["cash_field"]
    cash_line, top1, top01 = float(np.quantile(cf, 0.56)), float(np.quantile(gf, 0.99)), float(np.quantile(gf, 0.999))

    def grade(c):
        pts = float(actual[list(cands[c])].sum())
        return {"proj": round(float(sum(final[i] for i in cands[c])), 2), "actual": round(pts, 2),
                "own": round(float(sum(rows[i]["ownership"] for i in cands[c])), 1),
                "gpp_pct": round(float(np.searchsorted(gf, pts) / len(gf)), 4), "cashed": pts >= cash_line,
                "top1": pts >= top1, "top01": pts >= top01, "sim_p_cash": round(float(p_cash[c]), 4),
                "sim_p_top1": round(float(p_top1[c]), 4), "sim_p_top01": round(float(p_top01[c]), 5),
                "sim_mean": round(float(mean[c]), 2)}
    out["safe"] = grade(cands.index(safe))
    out["tournament"] = grade(cands.index(tour))
    out["mc_safe"] = grade(int(np.lexsort((mean, p_cash))[-1]))
    out["mc_tournament"] = grade(int(np.lexsort((mean, p_top01, p_top1))[-1]))
    out["mc_mean"] = grade(int(np.argmax(mean)))
    print(P["season"], P["week"], {k: (v["actual"], v["gpp_pct"]) for k, v in out.items() if isinstance(v, dict)}, flush=True)
    return out


def summarize(results: list[dict]) -> dict:
    out = {}
    for k in ("safe", "mc_safe", "mc_mean", "tournament", "mc_tournament"):
        g = [r[k] for r in results]
        out[k] = {"slates": len(g), "avg_actual": round(statistics.fmean(x["actual"] for x in g), 2),
                  "avg_proj": round(statistics.fmean(x["proj"] for x in g), 2),
                  "avg_ownership_sum": round(statistics.fmean(x["own"] for x in g), 1),
                  "avg_gpp_pct": round(statistics.fmean(x["gpp_pct"] for x in g), 3),
                  "cash_rate": round(statistics.fmean(x["cashed"] for x in g), 3),
                  "top1_hits": sum(x["top1"] for x in g), "top01_hits": sum(x["top01"] for x in g),
                  "sim_expected_top1": round(sum(x["sim_p_top1"] for x in g), 2),
                  "sim_expected_cash_rate": round(statistics.fmean(x["sim_p_cash"] for x in g), 3)}
    for a, b in (("mc_safe", "safe"), ("mc_tournament", "tournament"), ("mc_mean", "safe")):
        d = [r[a]["actual"] - r[b]["actual"] for r in results]
        dp = [r[a]["gpp_pct"] - r[b]["gpp_pct"] for r in results]
        dc = [r[a]["cashed"] - r[b]["cashed"] for r in results]
        same = sum(1 for r in results if r[a]["actual"] == r[b]["actual"] and r[a]["proj"] == r[b]["proj"])
        out[f"{a} vs {b}"] = {"points": round(statistics.fmean(d), 2),
                              "points_se": round(statistics.pstdev(d) / len(d) ** 0.5, 2),
                              "gpp_pct": round(statistics.fmean(dp), 3), "cash_rate": round(statistics.fmean(dc), 3),
                              "same_lineup": same, "better": sum(x > 0 for x in d), "worse": sum(x < 0 for x in d)}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bt", required=True)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("keys", nargs="*")
    args = ap.parse_args()
    paths = sorted(glob.glob(str(Path(args.bt) / "prep_*.pkl")))
    if args.keys:
        paths = [p for p in paths if Path(p).stem.replace("prep_", "") in args.keys]
    allp = sorted(glob.glob(str(Path(args.bt) / "prep_*.pkl")))
    vecs = {p: team_game_vectors(pickle.load(open(p, "rb"))) for p in allp}
    season = lambda p: int(Path(p).stem.split("_")[1])  # noqa: E731
    corr = {s: correlation([v for p in allp if season(p) != s for v in vecs[p]]) for s in {season(p) for p in allp}}
    with ProcessPoolExecutor(args.workers) as ex:
        results = list(ex.map(run_slate, [(p, corr[season(p)]) for p in paths]))
    res = {"slates": len(results), "draws": N_EVAL, "candidates_per_slate": round(statistics.fmean(r["candidates"] for r in results), 1),
           "correlations_all_seasons": {f"{a}~{b}": round(float(c), 3) for (a, b), c in _named(correlation([v for p in allp for v in vecs[p]])).items()},
           "summary": summarize(results), "by_slate": results}
    OUT.write_text(json.dumps(res, indent=1, default=lambda o: bool(o) if isinstance(o, np.bool_) else float(o)))
    print(json.dumps(res["summary"], indent=1))


def _named(C):
    names = [f"{r}" for r in ROLES] + [f"opp {r}" for r in ROLES]
    return {(names[i], names[j]): C[i, j] for i in range(len(ROLES)) for j in range(i + 1, len(names))
            if abs(C[i, j]) >= 0.05}


if __name__ == "__main__":
    main()
