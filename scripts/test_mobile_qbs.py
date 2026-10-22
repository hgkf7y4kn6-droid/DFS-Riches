"""Mobile quarterbacks vs pocket passers: does the scoring edge exist, and does the model already price it?

    python -m scripts.test_mobile_qbs [--data DIR]

DraftKings pays rushing at 2.5x passing per yard (0.1 vs 0.04) and 6 points per rushing touchdown vs 4 per
passing touchdown, so a quarterback's legs should lift both his floor and his ceiling. The claims tested:

  1. Mobile quarterbacks outscore pocket passers more often, with a higher floor. Archetype from each QB's
     rushing yards per game in his last 8 starts before the week (this season and last): mobile 25+,
     pocket under 12. Raw scoring, floor and ceiling, weekly QB ranks; then matched on projection (same week,
     projections within 1.5 points), and each archetype's miss against the app's corrected projection.
  2. They exploit man coverage: defenders in man turn their backs to the quarterback, so scramble lanes open.
     Play by play (nflverse participation, 2023-2025): scramble rate and rushing yards per dropback against
     man vs zone, by archetype; and quarterback-weeks against man-heavy defenses (season-to-date man rate)
     vs the projection.
  3. Defenses must respect the legs (a spy, fewer rushers), which opens passing lanes: pass rushers and box
     defenders (FTN charting), pressure and time to throw, and passing yards per attempt, by archetype; and
     whether the mobile quarterbacks' receivers beat their projections.
  4. Model inputs: the QB's rushing average, its interaction with the opponent's man rate, and (for
     receivers) their quarterback's rushing average, in the projection correction (app.player_model) and
     the QB ceiling model -- kept only if they improve out of sample (each of 2023-2025 held out, and 2026).

Writes data/mobile_qb_tests.json.
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import gzip
import io
import json
import statistics
from collections import defaultdict
from pathlib import Path

import numpy as np

from app import ceiling_model as cm, dk_scoring, game_model as gm, player_model as pm, projections
from scripts import test_player_features as tpf, train_ceiling_model as tcm, train_player_model as tpm
from scripts.train_game_model import REL, fetch

OUT = Path(__file__).resolve().parent.parent / "data" / "mobile_qb_tests.json"
TRAIN, TEST = (2023, 2024, 2025), 2026
MOBILE, POCKET = 25.0, 12.0
LAST_STARTS = 8
MAN_PRIOR = 150          # dropbacks of shrinkage toward the league man rate


def f(x) -> float:
    return gm._f(x) or 0.0


def mean(xs, default=0.0):
    xs = list(xs)
    return statistics.fmean(xs) if xs else default


def pass_pts(s) -> float:
    y = f(s.get("passing_yards"))
    return 0.04 * y + 4 * f(s.get("passing_tds")) - f(s.get("passing_interceptions")) + (3 if y >= 300 else 0)


def rush_pts(s) -> float:
    y = f(s.get("rushing_yards"))
    return 0.1 * y + 6 * f(s.get("rushing_tds")) + (3 if y >= 100 else 0)


def stats(d: Path, season: int) -> list[dict]:
    with open(fetch(f"{REL}/stats_player/stats_player_week_{season}.csv", d / f"stats_player_week_{season}.csv"), newline="") as fh:
        return [s for s in csv.DictReader(fh) if s.get("season_type", "REG") == "REG" and s.get("week")]


def archetype(rush_ypg: float | None) -> str | None:
    if rush_ypg is None:
        return None
    return "mobile" if rush_ypg >= MOBILE else "pocket" if rush_ypg < POCKET else "between"


# ------------------------------------------------------------------ play by play
def plays(d: Path, season: int) -> list[dict]:
    """Dropbacks: {week, qb, posteam, defteam, scramble, rush_yds, pass_att, pass_yds, sack, epa, cov, rushers,
    box, pressure, ttt}. Coverage, pressure and time to throw from participation (2023-2025); rushers and box
    from FTN charting."""
    out = {}
    path = fetch(f"{REL}/pbp/play_by_play_{season}.csv.gz", d / f"play_by_play_{season}.csv.gz")
    with gzip.open(path, "rt", newline="") as fh:
        for p in csv.DictReader(fh):
            if p.get("season_type") != "REG" or p.get("qb_dropback") != "1" or not p.get("id"):
                continue
            scr = p.get("qb_scramble") == "1"
            out[(p["game_id"], int(float(p["play_id"])))] = {
                "week": int(p["week"]), "qb": p["id"], "posteam": p["posteam"], "defteam": p["defteam"], "scramble": scr,
                "rush_yds": f(p.get("rushing_yards")) if scr else 0.0, "pass_att": p.get("pass_attempt") == "1" and p.get("sack") != "1",
                "pass_yds": f(p.get("passing_yards")), "sack": p.get("sack") == "1", "epa": f(p.get("epa")),
                "cov": None, "rushers": None, "box": None, "pressure": None, "ttt": None}
    part = d / f"pbp_participation_{season}.csv"
    if part.exists():
        with open(part, newline="") as fh:
            for r in csv.DictReader(fh):
                x = out.get((r["nflverse_game_id"], int(float(r["play_id"] or 0))))
                if not x:
                    continue
                cov = r.get("defense_man_zone_type") or ""
                x["cov"] = "man" if cov == "MAN_COVERAGE" else "zone" if cov == "ZONE_COVERAGE" else None
                x["pressure"] = {"TRUE": True, "FALSE": False}.get(r.get("was_pressure") or "")
                x["ttt"] = f(r.get("time_to_throw")) or None
    ftn = d / f"ftn_charting_{season}.csv"
    if ftn.exists():
        with open(ftn, newline="") as fh:
            for r in csv.DictReader(fh):
                x = out.get((r["nflverse_game_id"], int(float(r["nflverse_play_id"] or 0))))
                if x:
                    x["rushers"] = f(r.get("n_pass_rushers")) or None
                    x["box"] = f(r.get("n_defense_box")) or None
    return list(out.values())


def man_rates(pl: list[dict], weeks) -> tuple[dict[tuple[int, str], float], float]:
    """{(week, defense): man-coverage share of its labeled dropbacks before the week, shrunk toward the league}."""
    by = defaultdict(lambda: [0, 0])
    for p in pl:
        if p["cov"]:
            c = by[(p["week"], p["defteam"])]
            c[0] += p["cov"] == "man"
            c[1] += 1
    tot_m = sum(v[0] for v in by.values())
    tot = sum(v[1] for v in by.values())
    league = tot_m / tot if tot else 0.33
    out = {}
    teams = {t for _, t in by}
    for t in teams:
        m = n = 0
        for w in sorted(weeks):
            out[(w, t)] = (m + MAN_PRIOR * league) / (n + MAN_PRIOR)
            c = by.get((w, t))
            if c:
                m, n = m + c[0], n + c[1]
    return out, league


# ------------------------------------------------------------------ quarterback-weeks
def qb_history(st_prev: list[dict], st: list[dict]) -> dict[str, list[tuple]]:
    """{player id: [(season, week, rushing yards)]} for games he threw 10+ passes."""
    out = defaultdict(list)
    for s in st_prev + st:
        if s.get("position") == "QB" and f(s.get("attempts")) >= 10:
            out[s["player_id"]].append((int(s["season"]), int(s["week"]), f(s.get("rushing_yards"))))
    return {k: sorted(v) for k, v in out.items()}


def rush_ypg(hist: dict, pid: str, season: int, week: int) -> float | None:
    g = [x[2] for x in hist.get(pid, []) if (x[0], x[1]) < (season, week)][-LAST_STARTS:]
    return mean(g) if len(g) >= 3 else None


def season_rows(d: Path, season: int, weeks) -> tuple[list[dict], list[dict], dict]:
    st, st_prev = stats(d, season), stats(d, season - 1)
    by_key = {(int(s["week"]), pm.key(s["player_display_name"], s["position"])): s for s in st}
    hist = qb_history(st_prev, st)
    pl = plays(d, season)
    man, league_man = man_rates(pl, range(1, max(weeks) + 2))
    has_man = any(p["cov"] for p in pl)
    # each team's starting QB by week (Sleeper's top projected passer) -> his rushing average
    starter = {}
    for w in weeks:
        best = {}
        for e in tpm.sleeper_week(d, season, w):
            pl_ = e.get("player") or {}
            if pl_.get("position") != "QB" or not e.get("team"):
                continue
            team = tpm.TEAM_FIX.get(e["team"], e["team"])
            att = f((e.get("stats") or {}).get("pass_att"))
            if att > best.get(team, ("", 0))[1]:
                best[team] = (pm.key(f"{pl_.get('first_name', '')} {pl_.get('last_name', '')}".strip(), "QB"), att)
        starter[w] = {t: k for t, (k, _) in best.items()}
    pid_of = {pm.key(s["player_display_name"], s["position"]): s["player_id"] for s in st_prev + st}
    rows = []
    for r in tpm.player_weeks(d, season, weeks):
        s = by_key.get((r["week"], r["key"]))
        if not s or r["week"] < 2:
            continue
        team, opp = s["team"], s.get("opponent_team") or ""
        qbk = starter.get(r["week"], {}).get(team)
        qb_ypg = rush_ypg(hist, pid_of.get(qbk, ""), season, r["week"]) if qbk else None
        own_ypg = rush_ypg(hist, s["player_id"], season, r["week"]) if r["pos"] == "QB" else None
        man_rate = man.get((r["week"], opp), league_man) if has_man else None
        line = r["line"]
        raw = projections.dk_points_from_line(line, r["pos"]) or r["proj"]
        corrected = r["proj"] + (pm.adjustment(r["pos"], r["f"]) or 0.0)
        is_qb = r["pos"] == "QB"
        x = {**r["f"],
             "qb_rush_ypg": (own_ypg or 0.0) if is_qb else 0.0,
             "qb_mobile_x_man": ((own_ypg or 0.0) * ((man_rate or league_man) - league_man)) if is_qb and has_man else 0.0,
             "rec_qb_rush_ypg": (qb_ypg or 0.0) if r["pos"] in ("WR", "TE") else 0.0}
        rows.append({"season": season, "week": r["week"], "key": r["key"], "pos": r["pos"], "f": x, "proj": r["proj"],
                     "corrected": corrected, "actual": r["actual"], "line": line, "raw": raw, "implied": r["implied"],
                     "spread": r["spread"], "team": team, "opp": opp, "arch": archetype(own_ypg) if is_qb else None,
                     "qb_arch": archetype(qb_ypg), "own_ypg": own_ypg, "man_rate": man_rate, "league_man": league_man,
                     "pass_pts": pass_pts(s) if is_qb else None, "rush_pts": rush_pts(s) if is_qb else None,
                     "rush_yds": f(s.get("rushing_yards")), "attempts": f(s.get("attempts")), "pid": s["player_id"]})
    # play-level archetype: the QB's rushing average entering each week
    for p in pl:
        p["arch"] = archetype(rush_ypg(hist, p["qb"], season, p["week"]))
    return rows, pl, {"league_man_rate": league_man, "has_participation": has_man}


# ------------------------------------------------------------------ tests
def scoring(qbs: list[dict]) -> dict:
    """Raw DK scoring by archetype for starters (Sleeper projected 25+ pass attempts)."""
    out = {}
    week_rank = {}
    by_week = defaultdict(list)
    for r in qbs:
        by_week[(r["season"], r["week"])].append(r)
    for v in by_week.values():
        for i, r in enumerate(sorted(v, key=lambda r: -r["actual"])):
            week_rank[id(r)] = i + 1
    for a in ("mobile", "between", "pocket"):
        sub = [r for r in qbs if r["arch"] == a]
        if not sub:
            continue
        pts = np.array([r["actual"] for r in sub])
        out[a] = {"n": len(sub), "avg_pts": round(float(pts.mean()), 2), "median": round(float(np.median(pts)), 2),
                  "p15_floor": round(float(np.quantile(pts, 0.15)), 2), "p85_ceiling": round(float(np.quantile(pts, 0.85)), 2),
                  "under_12_pts": round(float(np.mean(pts < 12)), 3), "20_plus": round(float(np.mean(pts >= 20)), 3),
                  "25_plus": round(float(np.mean(pts >= 25)), 3),
                  "top5_week": round(mean(week_rank[id(r)] <= 5 for r in sub), 3),
                  "top12_week": round(mean(week_rank[id(r)] <= 12 for r in sub), 3),
                  "avg_rush_pts": round(mean(r["rush_pts"] for r in sub), 2), "avg_pass_pts": round(mean(r["pass_pts"] for r in sub), 2),
                  "avg_projection": round(mean(r["corrected"] for r in sub), 2),
                  "avg_miss_vs_projection": round(mean(r["actual"] - r["corrected"] for r in sub), 2),
                  "beat_projection": round(mean(r["actual"] > r["corrected"] for r in sub), 3),
                  "bust_under_half_projection": round(mean(r["actual"] < 0.5 * r["corrected"] for r in sub), 3),
                  "boom_1_5x_projection": round(mean(r["actual"] >= 1.5 * r["corrected"] for r in sub), 3),
                  "sd_of_actual_over_projection": round(float(np.std([r["actual"] / r["corrected"] for r in sub if r["corrected"] > 0])), 3)}
    return out


def matched(qbs: list[dict], tol=1.5) -> dict:
    """Mobile vs pocket QBs the same week with projections within tol: how often the mobile one scored more."""
    by_week = defaultdict(list)
    for r in qbs:
        by_week[(r["season"], r["week"])].append(r)
    wins, diffs = [], []
    for v in by_week.values():
        mob = [r for r in v if r["arch"] == "mobile"]
        poc = [r for r in v if r["arch"] == "pocket"]
        for m in mob:
            for p in poc:
                if abs(m["corrected"] - p["corrected"]) <= tol and m["actual"] != p["actual"]:
                    wins.append(m["actual"] > p["actual"])
                    diffs.append(m["actual"] - p["actual"])
    n = len(wins)
    return {"pairs": n, "mobile_scored_more": round(mean(wins), 3) if n else None,
            "avg_point_edge_mobile": round(mean(diffs), 2) if n else None,
            "z_vs_50pct": round((mean(wins) - 0.5) / (0.5 / n ** 0.5), 2) if n else None,
            "note": "pairs share players, so the z overstates significance"}


def coverage_plays(pl: list[dict]) -> dict:
    out = {}
    for a in ("mobile", "between", "pocket"):
        out[a] = {}
        for cov in ("man", "zone"):
            sub = [p for p in pl if p["arch"] == a and p["cov"] == cov]
            if not sub:
                continue
            att = [p for p in sub if p["pass_att"]]
            out[a][cov] = {"dropbacks": len(sub), "scramble_rate": round(mean(p["scramble"] for p in sub), 4),
                           "scramble_yds_per_dropback": round(mean(p["rush_yds"] for p in sub), 3),
                           "pass_yds_per_att": round(mean(p["pass_yds"] for p in att), 2) if att else None,
                           "epa_per_dropback": round(mean(p["epa"] for p in sub), 3),
                           "sack_rate": round(mean(p["sack"] for p in sub), 4)}
        if "man" in out[a] and "zone" in out[a]:
            m, z = out[a]["man"], out[a]["zone"]
            out[a]["man_minus_zone"] = {k: round(m[k] - z[k], 4) for k in ("scramble_rate", "scramble_yds_per_dropback", "epa_per_dropback")}
    return out


def defense_respect(pl: list[dict]) -> dict:
    out = {}
    for a in ("mobile", "between", "pocket"):
        sub = [p for p in pl if p["arch"] == a]
        if not sub:
            continue
        rushers = [p["rushers"] for p in sub if p["rushers"]]
        box = [p["box"] for p in sub if p["box"]]
        pres = [p["pressure"] for p in sub if p["pressure"] is not None]
        ttt = [p["ttt"] for p in sub if p["ttt"]]
        att = [p for p in sub if p["pass_att"]]
        out[a] = {"dropbacks": len(sub), "avg_pass_rushers": round(mean(rushers), 3) if rushers else None,
                  "rush_4_or_fewer": round(mean(x <= 4 for x in rushers), 3) if rushers else None,
                  "avg_box": round(mean(box), 2) if box else None,
                  "pressure_rate": round(mean(pres), 3) if pres else None,
                  "time_to_throw": round(mean(ttt), 2) if ttt else None,
                  "sack_rate": round(mean(p["sack"] for p in sub), 4),
                  "pass_yds_per_att": round(mean(p["pass_yds"] for p in att), 2) if att else None,
                  "man_coverage_share": round(mean(p["cov"] == "man" for p in sub if p["cov"]), 3) if any(p["cov"] for p in sub) else None}
    return out


def vs_man_weeks(qbs: list[dict]) -> dict:
    """QB-weeks by archetype vs the opponent's season-to-date man rate (thirds)."""
    withman = [r for r in qbs if r["man_rate"] is not None and r["arch"]]
    if not withman:
        return {}
    lo, hi = np.quantile([r["man_rate"] for r in withman], [1 / 3, 2 / 3])
    out = {"man_rate_cuts": [round(float(lo), 3), round(float(hi), 3)]}
    for a in ("mobile", "pocket"):
        out[a] = {}
        for label, sel in (("zone-heavy third", lambda r: r["man_rate"] <= lo), ("man-heavy third", lambda r: r["man_rate"] >= hi)):
            sub = [r for r in withman if r["arch"] == a and sel(r)]
            out[a][label] = {"n": len(sub), "avg_pts": round(mean(r["actual"] for r in sub), 2),
                             "avg_rush_yds": round(mean(r["rush_yds"] for r in sub), 1),
                             "miss_vs_projection": round(mean(r["actual"] - r["corrected"] for r in sub), 2),
                             "beat_projection": round(mean(r["actual"] > r["corrected"] for r in sub), 3)}
    return out


def receivers(rows: list[dict]) -> dict:
    out = {}
    for a in ("mobile", "between", "pocket"):
        sub = [r for r in rows if r["pos"] in ("WR", "TE") and r["qb_arch"] == a]
        if sub:
            out[a] = {"n": len(sub), "miss_vs_projection": round(mean(r["actual"] - r["corrected"] for r in sub), 2),
                      "beat_projection": round(mean(r["actual"] > r["corrected"] for r in sub), 3)}
    return out


def quiet(fn, *a):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a)


def subset_mae(train, test, feats, seasons, sel):
    models = quiet(tpm.fit_all, train, feats, seasons)
    sub = [r for r in test if sel(r)]
    adj = [pm.adjustment(r["pos"], r["f"], {"positions": models}) or 0.0 for r in sub]
    return {"n": len(sub), "mae": round(mean(abs(r["actual"] - r["proj"] - a) for r, a in zip(sub, adj)), 3),
            "bias": round(mean(r["proj"] + a - r["actual"] for r, a in zip(sub, adj)), 3)}


def model_test(train, test, extra, seasons, subsets, with_2026=True) -> dict:
    out = {}
    for label, feats in (("current", pm.FEATURES), ("+" + "+".join(extra), pm.FEATURES + tuple(extra))):
        res = {"loso": tpf.loso(train, feats, seasons)}
        if with_2026:
            res["test_2026"] = tpf.check(train, test, feats, seasons)
        for name, sel in subsets.items():
            per = [subset_mae([r for r in train if r["season"] != s], [r for r in train if r["season"] == s], feats,
                              [x for x in seasons if x != s], sel) for s in seasons]
            n = sum(p["n"] for p in per)
            res[f"loso_{name}"] = {"n": n, "mae": round(sum(p["n"] * p["mae"] for p in per) / n, 3),
                                   "bias": round(sum(p["n"] * p["bias"] for p in per) / n, 3)}
            if with_2026:
                res[f"test_2026_{name}"] = subset_mae(train, test, feats, seasons, sel)
        out[label] = res
    k = list(out)
    print(k[1], {m: (out[k[0]][m].get("mae_corrected", out[k[0]][m].get("mae")), out[k[1]][m].get("mae_corrected", out[k[1]][m].get("mae")))
                 for m in out[k[0]]})
    return out


def ceiling_test(train, test) -> dict:
    """The QB ceiling model (85th percentile) refit with and without the rushing average."""
    def cin(r):
        hist = r.get("hist") or []
        return cm.inputs("QB", r["corrected"], hist, r["line"], r["implied"], r["spread"], r["f"]["ts_l3"], r["f"]["snap_l3"])

    def fit_pred(a, b, extra):
        feats = tcm.FEATURES["QB"]
        X = lambda rs: np.array([[cin(r)[k] for k in feats] + [r["own_ypg"] or 0.0 for _ in extra] for r in rs])  # noqa: E731
        m = tcm.fit_qr(X(a), np.array([r["actual"] for r in a]), 0.85)
        q = np.array(m["b"][0]) + ((X(b) - np.array(m["mu"])) / np.array(m["sd"])) @ np.array(m["b"][1:])
        return [max(r["corrected"], v) for r, v in zip(b, q)]

    def metrics(rs, q):
        y = np.array([r["actual"] for r in rs])
        dd = y - np.array(q)
        mob = [i for i, r in enumerate(rs) if r["arch"] == "mobile"]
        return {"n": len(rs), "pinball_85": round(float(np.mean(np.maximum(0.85 * dd, -0.15 * dd))), 3),
                "beat_ceiling": round(float(np.mean(dd > 0)), 3),
                "beat_ceiling_mobile": round(float(np.mean(dd[mob] > 0)), 3) if mob else None}
    tr = [r for r in train if r["pos"] == "QB" and cin(r)]
    te = [r for r in test if r["pos"] == "QB" and cin(r)]
    seasons = sorted({r["season"] for r in tr})
    out = {}
    for label, extra in (("current", ()), ("+qb_rush_ypg", ("own_ypg",))):
        held, q = [], []
        for s in seasons:
            a, b = [r for r in tr if r["season"] != s], [r for r in tr if r["season"] == s]
            held += b
            q += fit_pred(a, b, extra)
        out[label] = {"loso": metrics(held, q), "test_2026": metrics(te, fit_pred(tr, te, extra))}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/cache/train")
    ap.add_argument("--test-weeks", type=int, default=6)
    args = ap.parse_args()
    d = Path(args.data)
    weeks = {s: list(range(1, 19)) for s in TRAIN} | {TEST: list(range(1, args.test_weeks + 1))}
    rows, pls, meta = {}, {}, {}
    for s in (*TRAIN, TEST):
        rows[s], pls[s], meta[s] = season_rows(d, s, weeks[s])
        print(s, len(rows[s]), "rows", len(pls[s]), "dropbacks")
    # DK points history for the ceiling model's inputs
    for s in rows:
        games = defaultdict(list)
        for y in (s - 1, s):
            for st in stats(d, y):
                if st.get("position") == "QB":
                    games[st["player_id"]].append((int(st["season"]), int(st["week"]), dk_scoring.dk_offense_points(st)))
        for r in rows[s]:
            if r["pos"] == "QB":
                r["hist"] = [g[2] for g in sorted(games.get(r["pid"], [])) if (g[0], g[1]) < (s, r["week"])][-12:]
    train = [r for s in TRAIN for r in rows[s]]
    test = rows[TEST]
    starters = lambda rs: [r for r in rs if r["pos"] == "QB" and f(r["line"].get("pass_att")) >= 25 and r["arch"]]  # noqa: E731
    res: dict = {"archetypes": {"mobile": f"{MOBILE:g}+ rushing yards per game, last {LAST_STARTS} starts",
                                "pocket": f"under {POCKET:g}"}, "meta": meta}
    res["1_scoring"] = {"2023-2025": scoring(starters(train)), "2026": scoring(starters(test))}
    res["1_matched_on_projection"] = {"2023-2025": matched(starters(train)), "2026": matched(starters(test))}
    tr_pl = [p for s in TRAIN for p in pls[s]]
    res["2_coverage_play_level_2023_2025"] = coverage_plays(tr_pl)
    res["2_vs_man_heavy_defenses_2023_2025"] = vs_man_weeks(starters(train))
    res["3_defense_respect"] = {"2023-2025": defense_respect(tr_pl), "2026": defense_respect(pls[TEST])}
    res["3_receivers_by_qb_type"] = {"2023-2025": receivers(train), "2026": receivers(test)}
    seasons = list(TRAIN)
    mob = lambda r: r["pos"] == "QB" and r["arch"] == "mobile"  # noqa: E731
    res["4_model_qb_rush_ypg"] = model_test(train, test, ("qb_rush_ypg",), seasons, {"mobile_qbs": mob})
    res["4_model_mobile_x_man"] = model_test(train, test, ("qb_rush_ypg", "qb_mobile_x_man"), seasons, {"mobile_qbs": mob}, with_2026=False)
    res["4_model_receivers_qb_rush"] = model_test(train, test, ("rec_qb_rush_ypg",), seasons,
                                                  {"receivers_of_mobile_qbs": lambda r: r["pos"] in ("WR", "TE") and r["qb_arch"] == "mobile"})
    res["4_ceiling_qb"] = ceiling_test(train, test)
    OUT.write_text(json.dumps(res, indent=1))
    print(json.dumps({k: v for k, v in res.items() if not k.startswith("4_model")}, indent=1))


if __name__ == "__main__":
    main()
