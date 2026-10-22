"""WR, TE and DST archetypes: do they improve the model, and do offensive archetypes vary differently against
certain kinds of defenses?

    python -m scripts.test_wr_te_dst_archetypes [--data DIR]

Archetypes, all known before the game:
  WR   alpha: 24%+ target share over his last 8 games (this season and last, 3+ games); deep threat: 13+ air yards
       per target; short / YAC: under 8.5; intermediate: the rest
  TE   receiving: 17%+ target share; secondary: 9-17%; blocking: under 9%
  QB / RB  as in scripts.test_archetype_distributions (Sleeper's projected line)
  DST  each defense's season-to-date profile (app.game_model estimates, shrunk toward last season), in thirds of the
       league: four-man pressure rate, dropback EPA allowed (coverage), rushing EPA allowed (run defense),
       explosive-play rate allowed; and its takeaway rate (app.dst_model)

Part 1, the model (each of 2023-2025 held out in turn, and 2026 Weeks 2-6):
  a. projection-correction inputs for WR/TE (app.player_model): aDOT, target share x spread (target hogs when
     trailing), aDOT x the opponent's explosive-play and pressure rates
  b. floor / median / ceiling multiples by WR/TE archetype vs the position-and-range multiples
  c. aDOT as a WR/TE ceiling-model input (85th percentile)
  d. DST model inputs (app.dst_model): the opposing QB's type (mobile / pocket), pass rush x pocket QB, the
     defense's own pressure and explosive-play rates
Part 2, variance by matchup (2023-2026): each offensive archetype's miss against the app's corrected projection,
its spread and boom / bust rates, against each third of each defensive dimension, flagged only when the gap from
the archetype's own average is 2.5+ standard errors and points the same way in 2023-2024 and 2025-2026; and how
each archetype's misses correlate with the opposing DST's misses (actual minus the DST model, seasons held out).
Writes data/wr_te_dst_archetype_tests.json.
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

from app import ceiling_model as cm, dk_scoring, dst_model as dm, game_model as gm, player_model as pm, projections
from scripts import test_archetype_distributions as tad, test_player_features as tpf, train_ceiling_model as tcm
from scripts import train_dst_model as tdm, train_game_model as tgm, train_player_model as tpm
from scripts.train_game_model import REL, fetch

OUT = Path(__file__).resolve().parent.parent / "data" / "wr_te_dst_archetype_tests.json"
TRAIN, TEST = (2023, 2024, 2025), 2026
LAST = 8
DEF_DIMS = {"pass rush": ("d_pressure4", +1), "coverage": ("d_pass_epa", -1), "run defense": ("d_rush_epa", -1),
            "big plays allowed": ("d_explosive", +1), "takeaways": ("own_take_rate", +1)}


def f(x) -> float:
    return gm._f(x) or 0.0


def mean(xs, default=0.0):
    xs = list(xs)
    return statistics.fmean(xs) if xs else default


def quiet(fn, *a):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a)


def stats(d: Path, season: int) -> list[dict]:
    with open(fetch(f"{REL}/stats_player/stats_player_week_{season}.csv", d / f"stats_player_week_{season}.csv"), newline="") as fh:
        return [s for s in csv.DictReader(fh) if s.get("season_type", "REG") == "REG" and s.get("week")]


def receiving_profile(hist: list[dict]) -> dict | None:
    if len(hist) < 3:
        return None
    tg = sum(f(s.get("targets")) for s in hist)
    return {"ts": mean(f(s.get("target_share")) for s in hist),
            "adot": sum(f(s.get("receiving_air_yards")) for s in hist) / tg if tg else 0.0}


def wr_te_archetype(pos: str, prof: dict | None) -> str | None:
    if not prof:
        return None
    if pos == "WR":
        if prof["ts"] >= 0.24:
            return "alpha WR"
        return "deep threat WR" if prof["adot"] >= 13 else "short/YAC WR" if prof["adot"] < 8.5 else "intermediate WR"
    if pos == "TE":
        return "receiving TE" if prof["ts"] >= 0.17 else "secondary TE" if prof["ts"] >= 0.09 else "blocking TE"
    return None


# ------------------------------------------------------------------ rows
def season(d: Path, year: int, weeks, sd: float) -> tuple[list[dict], list[dict]]:
    st, st_prev = stats(d, year), stats(d, year - 1)
    by_key = {(int(s["week"]), pm.key(s["player_display_name"], s["position"])): s for s in st}
    games = defaultdict(list)
    for s in st_prev + st:
        games[s["player_id"]].append(s)
    for v in games.values():
        v.sort(key=lambda s: (int(s["season"]), int(s["week"])))
    agg, prev = tgm.season_agg(d, year), tgm.season_agg(d, year - 1)
    priors = gm.priors_from_season(gm.season_totals(prev))
    lg = priors["league"]
    est = {w: gm.team_estimates(gm.season_totals(agg, before_week=w), priors) for w in weeks}
    cur_t, prev_t = tdm.team_rows(d, year), tdm.team_rows(d, year - 1)
    take = {w: dm.team_rates(cur_t, prev_t, w) for w in weeks}
    league_take = mean(v.get("own_take_rate", 0) for v in take[max(weeks)].values()) if take else 0.0

    def defense(week: int, team: str) -> dict:
        e = (est.get(week) or {}).get(team) or {}
        out = {k: (e[k] - lg[k]) if k in e else 0.0 for k in ("d_pressure4", "d_pass_epa", "d_rush_epa", "d_explosive")}
        out["own_take_rate"] = ((take.get(week) or {}).get(team) or {}).get("own_take_rate", league_take) - league_take
        return out

    # each team's starter QB type by week (Sleeper's top projected passer)
    qb_type = {}
    for w in weeks:
        best = {}
        for e in tpm.sleeper_week(d, year, w):
            pl = e.get("player") or {}
            if pl.get("position") == "QB" and e.get("team"):
                t = tpm.TEAM_FIX.get(e["team"], e["team"])
                s_ = e.get("stats") or {}
                if f(s_.get("pass_att")) > best.get(t, (0, None))[0]:
                    raw = projections.dk_points_from_line(s_, "QB")
                    best[t] = (f(s_.get("pass_att")), tad.archetype("QB", s_, raw))
        qb_type[w] = {t: a for t, (_, a) in best.items()}

    players = []
    for r in tpm.player_weeks(d, year, weeks):
        s = by_key.get((r["week"], r["key"]))
        if not s or r["week"] < 2:
            continue
        team, opp = s["team"], s.get("opponent_team") or ""
        hist = [g for g in games[s["player_id"]] if (int(g["season"]), int(g["week"])) < (year, r["week"])][-LAST:]
        prof = receiving_profile(hist) if r["pos"] in ("WR", "TE") else None
        raw = projections.dk_points_from_line(r["line"], r["pos"]) or r["proj"]
        arch = wr_te_archetype(r["pos"], prof) if r["pos"] in ("WR", "TE") else tad.archetype(r["pos"], r["line"], raw)
        dd = defense(r["week"], opp)
        adot = (prof["adot"] - 10.0) if prof else 0.0
        x = {**r["f"],
             "adot": adot if r["pos"] in ("WR", "TE") else 0.0,
             "ts_x_spread": (prof["ts"] * (r["spread"] or 0.0)) if prof else 0.0,
             "adot_x_opp_explosive": adot * dd["d_explosive"] * 100 if prof else 0.0,
             "adot_x_opp_pressure": adot * dd["d_pressure4"] * 100 if prof else 0.0}
        corrected = max(0.5, r["proj"] + (pm.adjustment(r["pos"], r["f"]) or 0.0))
        cin = cm.inputs(r["pos"], corrected, [dk_scoring.dk_offense_points(g) for g in hist[-12:]], r["line"], r["implied"],
                        r["spread"], r["f"]["ts_l3"], r["f"]["snap_l3"])
        players.append({"season": year, "week": r["week"], "key": r["key"], "pos": r["pos"], "team": team, "opp": opp,
                        "f": x, "proj": r["proj"], "corrected": corrected, "actual": r["actual"], "arch": arch,
                        "def": dd, "cin": cin, "adot_raw": prof["adot"] if prof else None})

    # DST rows with the extra candidate inputs
    dst = tdm.rows_for(d, year, weeks, sd)
    for r in dst:
        r["def"] = defense(r["week"], r["team"])
    # opponent of each DST row: from the games file via its team-week
    opp_of = {}
    with open(fetch(tdm.GAMES_URL, d / "games.csv"), newline="") as fh:
        for g in csv.DictReader(fh):
            if g["season"] == str(year) and g["game_type"] == "REG":
                opp_of[(int(g["week"]), g["home_team"])] = g["away_team"]
                opp_of[(int(g["week"]), g["away_team"])] = g["home_team"]
    for r in dst:
        opp = opp_of.get((r["week"], r["team"]), "")
        r["opp"] = opp
        qt = (qb_type.get(r["week"]) or {}).get(opp)
        r["opp_qb_type"] = qt
        pocket = 1.0 if qt == "pocket QB" else 0.0
        r["f"] = {**r["f"], "opp_qb_mobile": 1.0 if qt == "mobile QB" else 0.0, "opp_qb_pocket": pocket,
                  "rush_x_pocket": r["def"]["d_pressure4"] * 100 * pocket,
                  "own_pressure": r["def"]["d_pressure4"] * 100, "own_explosive": r["def"]["d_explosive"] * 100}
    return players, dst


# ------------------------------------------------------------------ part 1
def feature_test(train, test, extra, seasons, sel) -> dict:
    out = {}
    for label, feats in (("current", pm.FEATURES), ("+" + "+".join(extra), pm.FEATURES + tuple(extra))):
        res = {"loso": quiet(tpf.loso, train, feats, seasons), "test_2026": quiet(tpf.check, train, test, feats, seasons)}
        sub = []
        for s in seasons:
            tr = [r for r in train if r["season"] != s]
            m = quiet(tpm.fit_all, tr, feats, [x for x in seasons if x != s])
            sub += [abs(r["actual"] - r["proj"] - (pm.adjustment(r["pos"], r["f"], {"positions": m}) or 0)) for r in train if r["season"] == s and sel(r)]
        m = quiet(tpm.fit_all, train, feats, seasons)
        sub26 = [abs(r["actual"] - r["proj"] - (pm.adjustment(r["pos"], r["f"], {"positions": m}) or 0)) for r in test if sel(r)]
        res["loso_wr_te_mae"], res["test_2026_wr_te_mae"] = round(mean(sub), 3), round(mean(sub26), 3)
        out[label] = res
    k = list(out)
    print(k[1], "LOSO", out[k[0]]["loso"]["mae_corrected"], "->", out[k[1]]["loso"]["mae_corrected"],
          "rho", out[k[0]]["loso"]["rank_rho_corrected"], "->", out[k[1]]["loso"]["rank_rho_corrected"],
          "| 2026", out[k[0]]["test_2026"]["mae_corrected"], "->", out[k[1]]["test_2026"]["mae_corrected"],
          "| WR/TE LOSO", out[k[0]]["loso_wr_te_mae"], "->", out[k[1]]["loso_wr_te_mae"],
          "2026", out[k[0]]["test_2026_wr_te_mae"], "->", out[k[1]]["test_2026_wr_te_mae"])
    return out


def ceiling_test(train, test) -> dict:
    out = {}
    for pos in ("WR", "TE"):
        tr = [r for r in train if r["pos"] == pos and r["cin"] and r["adot_raw"] is not None]
        te = [r for r in test if r["pos"] == pos and r["cin"] and r["adot_raw"] is not None]
        feats = tcm.FEATURES[pos]

        def pred(a, b, extra):
            X = lambda rs: np.array([[r["cin"][k] for k in feats] + ([r["adot_raw"]] if extra else []) for r in rs])  # noqa: E731
            m = tcm.fit_qr(X(a), np.array([r["actual"] for r in a]), 0.85)
            q = np.array(m["b"][0]) + ((X(b) - np.array(m["mu"])) / np.array(m["sd"])) @ np.array(m["b"][1:])
            return [max(r["corrected"], v) for r, v in zip(b, q)]

        def met(rs, q):
            y = np.array([r["actual"] for r in rs])
            dd = y - np.array(q)
            deep = [i for i, r in enumerate(rs) if r["arch"] == "deep threat WR"]
            return {"n": len(rs), "pinball_85": round(float(np.mean(np.maximum(0.85 * dd, -0.15 * dd))), 3),
                    "beat_ceiling": round(float(np.mean(dd > 0)), 3),
                    "beat_ceiling_deep_threats": round(float(np.mean(dd[deep] > 0)), 3) if deep else None}
        seasons = sorted({r["season"] for r in tr})
        out[pos] = {}
        for label, extra in (("current", False), ("+adot", True)):
            held, q = [], []
            for s in seasons:
                a, b = [r for r in tr if r["season"] != s], [r for r in tr if r["season"] == s]
                held += b
                q += pred(a, b, extra)
            out[pos][label] = {"loso": met(held, q), "test_2026": met(te, pred(tr, te, extra))}
    return out


def dst_test(train, test, extra) -> dict:
    feats = dm.FEATURES + tuple(extra)

    def fit(rows, a):
        X = [[r["f"][k] for k in feats] for r in rows]
        w, m, s, b = gm.fit_ridge(X, [r["actual"] for r in rows], a)
        return {"features": list(feats), "weights": w, "means": m, "sds": s, "intercept": b}
    seasons = sorted({r["season"] for r in train})

    def cv(a):
        e = []
        for s in seasons:
            m = fit([r for r in train if r["season"] != s], a)
            e += [abs(r["actual"] - gm.apply(m, r["f"])) for r in train if r["season"] == s]
        return mean(e)
    alpha = min(tdm.ALPHAS, key=cv)
    held = {}
    for s in seasons:
        m = fit([r for r in train if r["season"] != s], alpha)
        held.update({id(r): gm.apply(m, r["f"]) for r in train if r["season"] == s})
    m = fit(train, alpha)
    return {"alpha": alpha, "held_out_seasons": tdm.evaluate(train, lambda r: held[id(r)]),
            "test_2026": tdm.evaluate(test, lambda r: gm.apply(m, r["f"])), "held_pred": held, "model": m}


# ------------------------------------------------------------------ part 2
def terciles(rows, dim_key, sign):
    vals = [sign * r["def"][dim_key] for r in rows]
    return np.quantile(vals, [1 / 3, 2 / 3])


def matchup_variance(rows: list[dict]) -> dict:
    out, flags = {}, []
    arches = sorted({r["arch"] for r in rows if r["arch"]})
    for dim, (k, sign) in DEF_DIMS.items():
        lo, hi = terciles(rows, k, sign)
        out[dim] = {}
        for a in arches:
            base = [r for r in rows if r["arch"] == a]
            if len(base) < 150:
                continue
            res_all = np.array([r["actual"] - r["corrected"] for r in base])
            cell = {}
            for label, sel in (("weak third", lambda v: v <= lo), ("strong third", lambda v: v >= hi)):
                sub = [r for r in base if sel(sign * r["def"][k])]
                if len(sub) < 40:
                    continue
                res = np.array([r["actual"] - r["corrected"] for r in sub])
                ratio = np.array([r["actual"] / r["corrected"] for r in sub])
                se = res_all.std() / len(sub) ** 0.5
                z = (res.mean() - res_all.mean()) / se
                halves = [np.mean([r["actual"] - r["corrected"] for r in sub if (r["season"] <= 2024) == h]) - res_all.mean()
                          for h in (True, False)]
                c = {"n": len(sub), "miss_vs_projection": round(float(res.mean()), 2),
                     "vs_archetype_avg": round(float(res.mean() - res_all.mean()), 2), "z": round(float(z), 2),
                     "sd_of_miss": round(float(res.std()), 2), "archetype_sd_of_miss": round(float(res_all.std()), 2),
                     "boom_1_5x": round(float(np.mean(ratio >= 1.5)), 3), "bust_half": round(float(np.mean(ratio < 0.5)), 3),
                     "2023_24_vs_avg": round(float(halves[0]), 2), "2025_26_vs_avg": round(float(halves[1]), 2)}
                cell[label] = c
                if abs(z) >= 2.5 and np.sign(halves[0]) == np.sign(halves[1]) == np.sign(z):
                    flags.append({"archetype": a, "defense": f"{label} at {dim}", **c})
            if cell:
                cell["archetype_avg_miss"] = round(float(res_all.mean()), 2)
                cell["archetype_boom_1_5x"] = round(float(np.mean([r["actual"] / r["corrected"] >= 1.5 for r in base])), 3)
                out[dim][a] = cell
    return {"cells": out, "flags": sorted(flags, key=lambda x: -abs(x["z"]))}


def dst_correlation(players: list[dict], dst: list[dict], held: dict, test_pred) -> dict:
    dres = {}
    for r in dst:
        p = held.get(id(r))
        if p is None:
            p = test_pred(r)
        dres[(r["season"], r["week"], r["team"])] = r["actual"] - p
    out = {}
    for a in sorted({r["arch"] for r in players if r["arch"]}):
        pairs = [(r["actual"] - r["corrected"], dres[(r["season"], r["week"], r["opp"])]) for r in players
                 if r["arch"] == a and (r["season"], r["week"], r["opp"]) in dres]
        if len(pairs) >= 100:
            x, y = np.array(pairs).T
            rho = float(np.corrcoef(x, y)[0, 1])
            out[a] = {"pairs": len(pairs), "corr_with_opposing_dst_miss": round(rho, 3),
                      "se": round(1 / (len(pairs) - 3) ** 0.5, 3)}
    return dict(sorted(out.items(), key=lambda kv: kv[1]["corr_with_opposing_dst_miss"]))


def dst_by_opp_qb(dst: list[dict], held: dict, test_pred) -> dict:
    out = {}
    for qt in ("mobile QB", "some legs QB", "pocket QB"):
        sub = [r for r in dst if r["opp_qb_type"] == qt]
        if not sub:
            continue
        res = [r["actual"] - (held.get(id(r)) if id(r) in held else test_pred(r)) for r in sub]
        out[qt] = {"n": len(sub), "avg_dst_pts": round(mean(r["actual"] for r in sub), 2), "miss_vs_dst_model": round(mean(res), 2)}
        for dim in ("pass rush",):
            k = DEF_DIMS[dim][0]
            hi = np.quantile([r["def"][k] for r in dst], 2 / 3)
            s2 = [(r, x) for r, x in zip(sub, res) if r["def"][k] >= hi]
            out[qt][f"vs strong {dim}"] = {"n": len(s2), "avg_dst_pts": round(mean(r["actual"] for r, _ in s2), 2),
                                           "miss_vs_dst_model": round(mean(x for _, x in s2), 2)}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/cache/train")
    ap.add_argument("--test-weeks", type=int, default=6)
    args = ap.parse_args()
    d = Path(args.data)
    sd = tdm.pa_sd(d, list(TRAIN))
    data = {s: season(d, s, list(range(1, 19)) if s in TRAIN else list(range(1, args.test_weeks + 1)), sd) for s in (*TRAIN, TEST)}
    train = [r for s in TRAIN for r in data[s][0]]
    test = data[TEST][0]
    dst_train = [r for s in TRAIN for r in data[s][1]]
    dst_test_rows = data[TEST][1]
    print("players", len(train), len(test), "dst", len(dst_train), len(dst_test_rows))
    seasons = list(TRAIN)
    wrte = lambda r: r["pos"] in ("WR", "TE")  # noqa: E731
    res: dict = {"archetype_counts": dict(sorted(defaultdict(int, {a: sum(r["arch"] == a for r in train + test)
                                                                   for a in {r["arch"] for r in train + test if r["arch"]}}).items()))}
    res["1a_correction_inputs"] = {name: feature_test(train, test, feats, seasons, wrte) for name, feats in (
        ("adot", ("adot",)), ("ts_x_spread", ("ts_x_spread",)), ("adot_x_opp_explosive", ("adot_x_opp_explosive",)),
        ("adot_x_opp_pressure", ("adot_x_opp_pressure",)))}
    groups = {a: (lambda a: lambda r: r["arch"] == a)(a) for a in sorted({r["arch"] for r in train if r["pos"] in ("WR", "TE") and r["arch"]})}
    groups["all WR/TE"] = wrte
    res["1b_floor_median_ceiling"] = tad.quantile_test([r for r in train if wrte(r) and r["arch"]], [r for r in test if wrte(r) and r["arch"]], groups)
    res["1c_ceiling_model"] = ceiling_test(train, test)
    base = dst_test(dst_train, dst_test_rows, ())
    res["1d_dst_model"] = {"current": {k: base[k] for k in ("alpha", "held_out_seasons", "test_2026")}}
    for name, extra in (("opp QB type", ("opp_qb_mobile", "opp_qb_pocket")), ("pass rush x pocket QB", ("rush_x_pocket",)),
                        ("own pressure + explosive", ("own_pressure", "own_explosive"))):
        t = dst_test(dst_train, dst_test_rows, extra)
        res["1d_dst_model"][name] = {k: t[k] for k in ("alpha", "held_out_seasons", "test_2026")}
        print("DST", name, t["held_out_seasons"], t["test_2026"])
    print("DST current", base["held_out_seasons"], base["test_2026"])
    allp = train + test
    res["2_matchup_variance_2023_2026"] = matchup_variance([r for r in allp if r["arch"]])
    pred26 = lambda r: gm.apply(base["model"], r["f"])  # noqa: E731
    res["2_corr_with_opposing_dst_2023_2026"] = dst_correlation(allp, dst_train + dst_test_rows, base["held_pred"], pred26)
    res["2_dst_by_opposing_qb_type_2023_2026"] = dst_by_opp_qb(dst_train + dst_test_rows, base["held_pred"], pred26)
    OUT.write_text(json.dumps(res, indent=1))
    print(json.dumps({k: v for k, v in res.items() if k not in ("1a_correction_inputs", "2_matchup_variance_2023_2026")}, indent=1))
    print(json.dumps(res["2_matchup_variance_2023_2026"]["flags"], indent=1))


if __name__ == "__main__":
    main()
