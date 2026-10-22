"""Test three proposed upgrades against the current model before adding any of them.

    python -m scripts.test_backfield_archetypes [--data DIR]

A. Backfield reallocation. When a team's lead running back sits, the proposal splits his vacated rush share
   and target share separately: rushes by depth (75% / 20% / 5% to the first / second / third backup), targets
   by route participation, a passing-down role and target history, 8% of both leaking away from the backfield,
   and backups 10-15% less efficient per touch. Tested on every game a team's lead back (40%+ of team carries
   in his games so far) missed:
     shares   the backups' actual rush and target shares vs four predictions: no change, proportional to
              their shares, the proposal's rules, and Sleeper's projected split of team carries and targets
     leakage  how much of the vacated work the backfield actually absorbed, and the backups' points per touch
     points   the backups' DK points: Sleeper, the app's corrected projection, and a projection built from the
              proposal's shares
     model    the proposal's projected point gain as an input to the correction model (app.player_model)
   Route participation is the share of team dropbacks the back was on the field for (nflverse participation,
   2023-2025; 2026 isn't published, so 2026 uses his target share). Passing-down role: the active backup with
   the most 3rd/4th-down and last-two-minutes targets per game.

B. Archetypes. Pass-catching backs (5+ projected targets, or a high share of the projection from receiving)
   and rushing quarterbacks: does the current projection or ceiling under-rate them? The proposal's RB and QB
   90th-percentile ceilings vs the current ceiling model refit at the 90th percentile, alone and as an extra
   input; floors; and the "grinder back as an underdog -> rushing-yards under" prop claim.

C. Pocket fragility. Pressure deficit = the opponent's four-man pressure rate above league plus the
   quarterback's own line's pressure allowed above league (app.game_model; ESPN's pass-block win rate isn't
   public). Pocket passers vs rushing quarterbacks (20%+ of the projection from rushing): as correction-model
   inputs, in the QB ceiling, and the "pocket passer under pressure -> passing-yards under" prop claim.

Out-of-sample checks: each of 2023-2025 held out in turn (fit on the other two), and 2026 Weeks 2-6 (fit on
2023-2025). Writes data/backfield_archetype_tests.json.
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

from app import ceiling_model as cm, dk_scoring, game_model as gm, player_model as pm, prop_pricer as pp, projections
from scripts import test_player_features as tpf, train_ceiling_model as tcm, train_game_model as tgm
from scripts import train_player_model as tpm
from scripts.train_game_model import GAMES_URL, REL, fetch

OUT = Path(__file__).resolve().parent.parent / "data" / "backfield_archetype_tests.json"
TRAIN, TEST = (2023, 2024, 2025), 2026
LEAD_SHARE = 0.40
LEAKAGE = 0.08
DECAY = 0.875
TAU = 0.90
RUSH_QB = 0.20


def f(x) -> float:
    return gm._f(x) or 0.0


def mean(xs, default=0.0):
    xs = list(xs)
    return statistics.fmean(xs) if xs else default


def rush_pts(s) -> float:
    return 0.1 * f(s.get("rushing_yards")) + 6 * f(s.get("rushing_tds"))


def rec_pts(s) -> float:
    return f(s.get("receptions")) + 0.1 * f(s.get("receiving_yards")) + 6 * f(s.get("receiving_tds"))


# ------------------------------------------------------------------ season data
def pbp_pass(d: Path, season: int, participation: bool):
    """Passing-down targets and inside-10 carries per (week, player id); dropbacks on the field per (week, player
    id) and team dropbacks per (week, team) when participation is published."""
    pd_t, i10 = defaultdict(int), defaultdict(int)
    dropback, team_db = {}, defaultdict(int)
    path = fetch(f"{REL}/pbp/play_by_play_{season}.csv.gz", d / f"play_by_play_{season}.csv.gz")
    with gzip.open(path, "rt", newline="") as fh:
        for p in csv.DictReader(fh):
            if p.get("season_type") != "REG" or not p.get("week"):
                continue
            w = int(p["week"])
            if p.get("qb_dropback") == "1" and p.get("posteam"):
                dropback[(p["game_id"], int(float(p["play_id"])))] = w
                team_db[(w, p["posteam"])] += 1
            if p.get("pass_attempt") == "1" and p.get("receiver_player_id"):
                down, secs = f(p.get("down")), f(p.get("half_seconds_remaining"))
                if down >= 3 or (p.get("half_seconds_remaining") and secs <= 120):
                    pd_t[(w, p["receiver_player_id"])] += 1
            if p.get("rush_attempt") == "1" and p.get("rusher_player_id") and p.get("yardline_100") and f(p["yardline_100"]) <= 10:
                i10[(w, p["rusher_player_id"])] += 1
    on_field = defaultdict(int)
    part = d / f"pbp_participation_{season}.csv"
    if participation and part.exists():
        with open(part, newline="") as fh:
            for r in csv.DictReader(fh):
                w = dropback.get((r["nflverse_game_id"], int(float(r["play_id"] or 0))))
                if w:
                    for pid in (r.get("offense_players") or "").split(";"):
                        if pid:
                            on_field[(w, pid)] += 1
    return pd_t, i10, on_field, team_db


def opponents(d: Path, season: int) -> dict[tuple[int, str], str]:
    out = {}
    with open(fetch(GAMES_URL, d / "games.csv"), newline="") as fh:
        for g in csv.DictReader(fh):
            if g["season"] == str(season) and g["game_type"] == "REG":
                out[(int(g["week"]), g["home_team"])] = g["away_team"]
                out[(int(g["week"]), g["away_team"])] = g["home_team"]
    return out


class Season:
    def __init__(self, d: Path, season: int, weeks):
        self.season = season
        with open(fetch(f"{REL}/stats_player/stats_player_week_{season}.csv", d / f"stats_player_week_{season}.csv"), newline="") as fh:
            self.stats = [s for s in csv.DictReader(fh) if s.get("season_type", "REG") == "REG" and s.get("week")]
        self.by_key = {(int(s["week"]), pm.key(s["player_display_name"], s["position"])): s for s in self.stats}
        self.team_tot = defaultdict(lambda: {"carries": 0.0, "targets": 0.0})
        for s in self.stats:
            t = self.team_tot[(int(s["week"]), s["team"])]
            t["carries"] += f(s.get("carries"))
            t["targets"] += f(s.get("targets"))
        self.pd_t, self.i10, self.on_field, self.team_db = pbp_pass(d, season, participation=season != TEST)
        self.opp = opponents(d, season)
        self.sleeper = {w: tpm.sleeper_week(d, season, w) for w in weeks}
        agg, prev = tgm.season_agg(d, season), tgm.season_agg(d, season - 1)
        self.priors = gm.priors_from_season(gm.season_totals(prev))
        self.est = {w: gm.team_estimates(gm.season_totals(agg, before_week=w), self.priors) for w in weeks}
        hist_games = defaultdict(list)
        with open(fetch(f"{REL}/stats_player/stats_player_week_{season - 1}.csv", d / f"stats_player_week_{season - 1}.csv"), newline="") as fh:
            for s in list(csv.DictReader(fh)) + self.stats:
                if s.get("season_type", "REG") == "REG":
                    hist_games[pm.key(s["player_display_name"], s["position"])].append(
                        (int(s["season"]), int(s["week"]), dk_scoring.dk_offense_points(s)))
        self.hist_games = {k: sorted(v) for k, v in hist_games.items()}

    def pressure_deficit(self, week: int, team: str, opp: str) -> float:
        est, lg = self.est.get(week) or {}, self.priors["league"]
        o, dd = est.get(team), est.get(opp)
        return ((dd["d_pressure4"] - lg["d_pressure4"]) if dd else 0.0) + ((o["pressure4_allowed"] - lg["pressure4_allowed"]) if o else 0.0)


# ------------------------------------------------------------------ A. vacancy events
def team_rbs(S: Season, team: str, weeks) -> dict[int, dict[str, dict]]:
    """{week: {player key: {rs, ts, carries, targets, pid, rush_pts, rec_pts, pd, dbp}}} for the team's RBs."""
    out = {}
    for w in weeks:
        tot = S.team_tot.get((w, team))
        if not tot or not tot["carries"]:
            continue
        out[w] = {}
        db = S.team_db.get((w, team)) or 0
        for s in S.stats:
            if int(s["week"]) != w or s["team"] != team or s["position"] != "RB":
                continue
            pid = s["player_id"]
            out[w][pm.key(s["player_display_name"], "RB")] = {
                "rs": f(s.get("carries")) / tot["carries"], "ts": f(s.get("targets")) / tot["targets"] if tot["targets"] else 0.0,
                "carries": f(s.get("carries")), "targets": f(s.get("targets")), "pid": pid,
                "rush_pts": rush_pts(s), "rec_pts": rec_pts(s), "pd": S.pd_t.get((w, pid), 0),
                "dbp": (S.on_field.get((w, pid), 0) / db) if db and S.on_field else None}
    return out


def proposed_shares(active: list[dict], vac_r: float, vac_t: float, leakage=LEAKAGE) -> list[tuple[float, float]]:
    """The proposal's BackfieldReallocationModel.reallocate, row for row."""
    if not active:
        return []
    order = sorted({a["depth"] for a in active})
    rank = [order.index(a["depth"]) + 1 for a in active]
    rw = np.array([0.75 if k == 1 else 0.20 if k == 2 else 0.05 for k in rank])
    rw = rw / rw.sum()
    aff = np.array([a["rp"] * 1.5 + (0.40 if a["spec"] else 0.0) + a["ts"] for a in active])
    tw = aff / aff.sum() if aff.sum() else np.ones(len(active)) / len(active)
    er, et = vac_r * (1 - leakage), vac_t * (1 - leakage)
    return [(min(0.95, max(0.0, a["rs"] + er * r)), min(0.35, max(0.0, a["ts"] + et * t))) for a, r, t in zip(active, rw, tw)]


def proportional_shares(active, vac_r, vac_t, leakage=0.0):
    sr, st = sum(a["rs"] for a in active), sum(a["ts"] for a in active)
    n = len(active)
    return [(a["rs"] + vac_r * (1 - leakage) * (a["rs"] / sr if sr else 1 / n),
             a["ts"] + vac_t * (1 - leakage) * (a["ts"] / st if st else 1 / n)) for a in active]


def sleeper_split(S: Season, week: int, team: str) -> dict[str, tuple[float, float]]:
    """{RB key: (projected share of team carries, of team targets)} from Sleeper's lines for the team."""
    lines = []
    for e in S.sleeper.get(week, []):
        if tpm.TEAM_FIX.get(e.get("team") or "", e.get("team")) != team:
            continue
        pl = e.get("player") or {}
        if pl.get("position") in pm.POSITIONS:
            lines.append((pm.key(f"{pl.get('first_name', '')} {pl.get('last_name', '')}".strip(), pl["position"]), e.get("stats") or {}))
    tr, tt = sum(f(s.get("rush_att")) for _, s in lines), sum(f(s.get("rec_tgt")) for _, s in lines)
    return {k: (f(s.get("rush_att")) / tr if tr else 0.0, f(s.get("rec_tgt")) / tt if tt else 0.0)
            for k, s in lines if k.endswith("|RB")}


def vacancy_events(S: Season, weeks, league_pp) -> list[dict]:
    """One dict per active backup in each game a team's lead back missed."""
    teams = {s["team"] for s in S.stats}
    out = []
    for team in teams:
        rbw = team_rbs(S, team, range(1, max(weeks) + 1))
        played = sorted(rbw)
        for w in weeks:
            if w not in rbw:
                continue
            prior = [x for x in played if x < w]
            if len(prior) < 2:
                continue
            games = defaultdict(list)
            for x in prior:
                for k, v in rbw[x].items():
                    games[k].append((x, v))
            lead = max((k for k in games if len(games[k]) >= 2), key=lambda k: mean(v["rs"] for _, v in games[k]), default=None)
            if not lead or mean(v["rs"] for _, v in games[lead]) < LEAD_SHARE or lead in rbw[w]:
                continue
            if (w, lead) in S.by_key:          # playing for another team now (traded / released)
                continue
            with_lead = [x for x, _ in games[lead]][-6:]
            first_absence = with_lead[-1] == prior[-1]

            def base(k):
                g = [v for x, v in games.get(k, []) if x in with_lead]
                return {"rs": sum(v["rs"] for v in g) / len(with_lead), "ts": sum(v["ts"] for v in g) / len(with_lead),
                        "pd": sum(v["pd"] for v in g) / len(with_lead),
                        "dbp": mean([v["dbp"] for v in g if v["dbp"] is not None], None) if g else None,
                        "carries": sum(v["carries"] for v in g), "targets": sum(v["targets"] for v in g),
                        "rush_pts": sum(v["rush_pts"] for v in g), "rec_pts": sum(v["rec_pts"] for v in g), "games": len(g)}
            suppressed = [k for k in games if k not in rbw[w] and any(x in with_lead for x, _ in games[k])]
            bl = {k: base(k) for k in suppressed}
            vac_r, vac_t = sum(b["rs"] for b in bl.values()), sum(b["ts"] for b in bl.values())
            lb = bl[lead]
            active = []
            for k, v in rbw[w].items():
                b = base(k)
                rp = b["dbp"] if b["dbp"] is not None else min(1.0, b["ts"] / 0.10 * 0.5)
                active.append({"key": k, **b, "rp": rp, "actual": v})
            for i, a in enumerate(sorted(active, key=lambda a: (-a["rs"], -a["ts"]))):
                a["depth"] = i + 1
            spec = max((a for a in active if a["games"]), key=lambda a: a["pd"], default=None)
            for a in active:
                a["spec"] = bool(spec is a and spec["pd"] * len(with_lead) / max(spec["games"], 1) >= 0.5)
            prop = proposed_shares(active, vac_r, vac_t)
            prop0 = proposed_shares(active, vac_r, vac_t, leakage=0.0)
            pro = proportional_shares(active, vac_r, vac_t)
            pro8 = proportional_shares(active, vac_r, vac_t, leakage=LEAKAGE)
            slp = sleeper_split(S, w, team)
            tot = [S.team_tot[(x, team)] for x in prior[-6:]]
            exp_c, exp_t = mean(t["carries"] for t in tot), mean(t["targets"] for t in tot)
            lead_opp = lb["carries"] + lb["targets"]
            for a, p, p0, q, q8 in zip(active, prop, prop0, pro, pro8):
                ppc = (a["rush_pts"] + 30 * league_pp["carry"]) / (a["carries"] + 30)
                ppt = (a["rec_pts"] + 15 * league_pp["target"]) / (a["targets"] + 15)
                out.append({
                    "season": S.season, "week": w, "team": team, "key": a["key"], "depth": a["depth"], "spec": a["spec"],
                    "first_absence": first_absence, "has_participation": a["dbp"] is not None,
                    "vac_rush": vac_r, "vac_tgt": vac_t,
                    "base_rs": a["rs"], "base_ts": a["ts"], "act_rs": a["actual"]["rs"], "act_ts": a["actual"]["ts"],
                    "prop_rs": p[0], "prop_ts": p[1], "prop0_rs": p0[0], "prop0_ts": p0[1],
                    "pro_rs": q[0], "pro_ts": q[1], "pro8_rs": q8[0], "pro8_ts": q8[1],
                    "slp_rs": slp.get(a["key"], (None, None))[0], "slp_ts": slp.get(a["key"], (None, None))[1],
                    "realloc_pts": p[0] * exp_c * ppc + p[1] * exp_t * ppt,
                    "base_pts": a["rs"] * exp_c * ppc + a["ts"] * exp_t * ppt,
                    "act_pts": a["actual"]["rush_pts"] + a["actual"]["rec_pts"],
                    "act_opp": a["actual"]["carries"] + a["actual"]["targets"],
                    "prior_ppo": ((a["rush_pts"] + a["rec_pts"]) / (a["carries"] + a["targets"])) if a["carries"] + a["targets"] >= 10 else None,
                    "lead_ppo": (lb["rush_pts"] + lb["rec_pts"]) / lead_opp if lead_opp else None,
                })
    return out


def share_accuracy(ev: list[dict]) -> dict:
    out = {}
    for label, sel in (("all backups", ev), ("first backup (depth 1)", [e for e in ev if e["depth"] == 1]),
                       ("passing-down back", [e for e in ev if e["spec"]]),
                       ("depth 2+", [e for e in ev if e["depth"] >= 2])):
        withs = [e for e in sel if e["slp_rs"] is not None]
        if not sel:
            continue
        row = {"n": len(sel), "n_with_sleeper": len(withs)}
        for share in ("rs", "ts"):
            for m in ("base", "pro", "pro8", "prop", "prop0"):
                row[f"{share}_mae_{m}"] = round(mean(abs(e[f"{m}_{share}"] - e[f"act_{share}"]) for e in sel), 4)
            row[f"{share}_mae_sleeper"] = round(mean(abs(e[f"slp_{share}"] - e[f"act_{share}"]) for e in withs), 4) if withs else None
            row[f"{share}_mae_prop_same_rows"] = round(mean(abs(e[f"prop_{share}"] - e[f"act_{share}"]) for e in withs), 4) if withs else None
            row[f"{share}_bias_prop"] = round(mean(e[f"prop_{share}"] - e[f"act_{share}"] for e in sel), 4)
            row[f"{share}_actual_mean"] = round(mean(e[f"act_{share}"] for e in sel), 4)
        out[label] = row
    return out


def absorption(ev: list[dict]) -> dict:
    """Share of the vacated rush / target share the active backs took, per event, pooled."""
    by = defaultdict(list)
    for e in ev:
        by[(e["season"], e["week"], e["team"])].append(e)
    vr = sum(g[0]["vac_rush"] for g in by.values())
    vt = sum(g[0]["vac_tgt"] for g in by.values())
    gr = sum(sum(e["act_rs"] - e["base_rs"] for e in g) for g in by.values())
    gt = sum(sum(e["act_ts"] - e["base_ts"] for e in g) for g in by.values())
    first = [g for g in by.values() if any(e["depth"] == 1 for e in g)]
    top_take = [max(g, key=lambda e: e["act_rs"] - e["base_rs"]) for g in first]
    d1 = sum(1 for e in top_take if e["depth"] == 1)
    spec_g = [g for g in by.values() if any(e["spec"] for e in g) and len(g) >= 2]
    spec_top_t = sum(1 for g in spec_g if max(g, key=lambda e: e["act_ts"] - e["base_ts"])["spec"])
    d1_rush = [sum(e["act_rs"] - e["base_rs"] for e in g if e["depth"] == 1) / g[0]["vac_rush"] for g in first if g[0]["vac_rush"]]
    ppo = [(e["act_pts"] / e["act_opp"], e["prior_ppo"], e["lead_ppo"]) for e in ev if e["act_opp"] >= 5 and e["prior_ppo"] and e["lead_ppo"]]
    return {"events": len(by), "rush_absorbed": round(gr / vr, 3) if vr else None, "targets_absorbed": round(gt / vt, 3) if vt else None,
            "first_backup_takes_most_new_rushes": round(d1 / len(first), 3) if first else None,
            "first_backup_share_of_vacated_rushes_median": round(float(np.median(d1_rush)), 3) if d1_rush else None,
            "passing_down_back_takes_most_new_targets": round(spec_top_t / len(spec_g), 3) if spec_g else None,
            "events_with_passing_down_back_and_2plus_backs": len(spec_g),
            "points_per_touch": {"n": len(ppo), "backup_in_vacancy": round(mean(p[0] for p in ppo), 3),
                                 "same_backup_before": round(mean(p[1] for p in ppo), 3),
                                 "lead_back_before": round(mean(p[2] for p in ppo), 3)}}


# ------------------------------------------------------------------ player-week rows
def rows(S: Season, d: Path, weeks, realloc: dict) -> list[dict]:
    out = []
    for r in tpm.player_weeks(d, S.season, weeks):
        st = S.by_key.get((r["week"], r["key"]))
        if not st or r["week"] < 2:
            continue
        team, line, pos = st["team"], r["line"], r["pos"]
        opp = S.opp.get((r["week"], team), "")
        raw = projections.dk_points_from_line(line, pos) or r["proj"]
        corrected = r["proj"] + (pm.adjustment(pos, r["f"]) or 0.0)
        hist = [g[2] for g in S.hist_games.get(r["key"], []) if (g[0], g[1]) < (S.season, r["week"])][-12:]
        g = lambda k: f(line.get(k))  # noqa: E731
        rec_share = (g("rec") + 0.1 * g("rec_yd") + 6 * g("rec_td")) / raw if raw else 0.0
        rush_share = (0.1 * g("rush_yd") + 6 * g("rush_td")) / raw if raw else 0.0
        deficit = S.pressure_deficit(r["week"], team, opp) if pos == "QB" else 0.0
        rush_qb = pos == "QB" and rush_share >= RUSH_QB
        pid = st["player_id"]
        i10 = mean([S.i10.get((x, pid), 0) for x in range(max(1, r["week"] - 4), r["week"])])
        ev = realloc.get((r["week"], r["key"]))
        x = {**r["f"],
             "rb_rec_share": rec_share if pos == "RB" else 0.0,
             "rb_tgt5": float(pos == "RB" and g("rec_tgt") >= 5),
             "qb_rush_share": rush_share if pos == "QB" else 0.0,
             "pressure_deficit": deficit,
             "pfi_pocket": deficit * (0.0 if rush_qb else 1.0) if pos == "QB" else 0.0,
             "pfi_rush": deficit * (1.0 if rush_qb else 0.0),
             "grinder_spread": (r["spread"] or 0.0) if pos == "RB" and g("rec_tgt") <= 2 and g("rush_att") >= 12 else 0.0,
             "realloc_gain": (ev["realloc_pts"] - ev["base_pts"]) if ev else 0.0,
             "realloc_gain_ratio": ((ev["realloc_pts"] - ev["base_pts"]) / max(r["proj"], 3.0)) if ev else 0.0}
        # the proposal's ceilings (90th percentile), from Sleeper's line moved with the correction
        k = corrected / raw if raw else 1.0
        prop_ceiling = None
        if pos == "RB":
            car, tgt = g("rush_att") * k, g("rec_tgt") * k
            ypc = g("rush_yd") / g("rush_att") if g("rush_att") else 4.2
            cr = g("rec") / g("rec_tgt") if g("rec_tgt") else 0.75
            ypr = g("rec_yd") / g("rec") if g("rec") else 7.5
            hvt = tgt * 1.65 + i10 * 1.20
            prop_ceiling = (car * ypc * 0.1 + tgt * cr + tgt * cr * ypr * 0.1 + hvt * 0.65) * (1.25 if tgt >= 5 else 1.0)
        elif pos == "QB":
            pfi = -min(max(deficit * 0.35, 0), 0.20) if rush_qb else min(max(deficit * 0.75, 0), 0.40)
            prop_ceiling = (g("pass_yd") * 0.04 + g("pass_td") * 4) * k * (1 - pfi) + (g("rush_yd") * 0.1 + g("rush_td") * 6) * k * 1.35
        cin = cm.inputs(pos, corrected, hist, line, r["implied"], r["spread"], r["f"]["ts_l3"], r["f"]["snap_l3"])
        out.append({"season": S.season, "week": r["week"], "key": r["key"], "pos": pos, "f": x, "proj": r["proj"],
                    "corrected": corrected, "actual": r["actual"], "line": line, "ratio": k, "spread": r["spread"],
                    "rec_share": rec_share, "rush_share": rush_share, "rush_qb": rush_qb, "deficit": deficit,
                    "cin": cin, "prop_ceiling": prop_ceiling, "stat": st, "realloc": ev})
    return out


# ------------------------------------------------------------------ helpers for the model tests
def quiet(fn, *a):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a)


def mae_subset(train, test, feats, seasons, sel) -> dict:
    models = quiet(tpm.fit_all, train, feats, seasons)
    sub = [r for r in test if sel(r)]
    adj = [pm.adjustment(r["pos"], r["f"], {"positions": models}) or 0.0 for r in sub]
    return {"n": len(sub), "mae_corrected": round(mean(abs(r["actual"] - r["proj"] - a) for r, a in zip(sub, adj)), 3),
            "bias": round(mean(r["proj"] + a - r["actual"] for r, a in zip(sub, adj)), 3)}


def feature_test(train, test, name, extra, seasons, subsets) -> dict:
    base = pm.FEATURES
    res = {"features": list(extra)}
    for label, feats in (("current", base), (name, base + tuple(extra))):
        res[label] = {"loso": tpf.loso(train, feats, seasons), "test_2026": tpf.check(train, test, feats, seasons)}
        for sl, sel in subsets.items():
            per = []
            for s in seasons:
                tr = [r for r in train if r["season"] != s]
                te = [r for r in train if r["season"] == s]
                per.append(mae_subset(tr, te, feats, [x for x in seasons if x != s], sel))
            n = sum(p["n"] for p in per)
            res[label][f"loso_{sl}"] = {"n": n, "mae_corrected": round(sum(p["n"] * p["mae_corrected"] for p in per) / n, 3) if n else None,
                                        "bias": round(sum(p["n"] * p["bias"] for p in per) / n, 3) if n else None}
            res[label][f"test_2026_{sl}"] = mae_subset(train, test, feats, seasons, sel)
    c, n_ = res["current"], res[name]
    print(name, "LOSO", c["loso"]["mae_corrected"], "->", n_["loso"]["mae_corrected"], "| 2026", c["test_2026"]["mae_corrected"],
          "->", n_["test_2026"]["mae_corrected"], {k: (c[k]["mae_corrected"], n_[k]["mae_corrected"]) for k in c if k.startswith(("loso_", "test_2026_"))})
    return res


def pinball(y, q, tau=TAU) -> float:
    dd = np.asarray(y) - np.asarray(q)
    return float(np.mean(np.maximum(tau * dd, (tau - 1) * dd)))


def ceiling_metrics(rs, q) -> dict:
    y = [r["actual"] for r in rs]
    groups = defaultdict(list)
    for r, c in zip(rs, q):
        groups[(r["season"], r["week"])].append((c, r["actual"]))
    rho = mean(tpm.spearman([a for a, _ in v], [b for _, b in v]) for v in groups.values() if len(v) >= 8)
    cap = []
    for v in groups.values():
        if len(v) >= 10:
            k = max(1, len(v) // 10)
            top = set(sorted(range(len(v)), key=lambda i: -v[i][0])[:2 * k])
            cap.append(sum(i in top for i in sorted(range(len(v)), key=lambda i: -v[i][1])[:k]) / k)
    return {"n": len(rs), "pinball_90": round(pinball(y, q), 3), "beat_ceiling": round(float(np.mean(np.array(y) > np.array(q))), 3),
            "rank_rho": round(rho, 3), "top10_in_top20": round(mean(cap), 3)}


def qr_ceiling(train, test, pos, extra=()) -> list[float]:
    feats = tcm.FEATURES[pos]

    def X(rs):
        return np.array([[r["cin"][k] for k in feats] + [r[e] or 0.0 for e in extra] for r in rs])
    tr = [r for r in train if r["pos"] == pos and r["cin"]]
    m = tcm.fit_qr(X(tr), np.array([r["actual"] for r in tr]), TAU)
    Z = (X(test) - np.array(m["mu"])) / np.array(m["sd"])
    q = np.array(m["b"][0]) + Z @ np.array(m["b"][1:])
    return [max(r["corrected"], v) for r, v in zip(test, q)]


def ceiling_test(train, test, pos, buckets) -> dict:
    """The current ceiling model's inputs refit at the 90th percentile; plus the proposal's ceiling as an input;
    and the proposal's ceiling alone (scaled on training to a 10% beat rate)."""
    tr = [r for r in train if r["pos"] == pos and r["cin"] and r["prop_ceiling"] is not None]
    te = [r for r in test if r["pos"] == pos and r["cin"] and r["prop_ceiling"] is not None]
    seasons = sorted({r["season"] for r in tr})
    out = {}
    for label, split in [("2026", [(tr, te)])] + [("loso", [([r for r in tr if r["season"] != s], [r for r in tr if r["season"] == s]) for s in seasons])]:
        preds = defaultdict(list)
        held = []
        for a, b in split:
            held += b
            preds["current_refit_90"] += qr_ceiling(a, b, pos)
            preds["current_plus_proposal"] += qr_ceiling(a, b, pos, extra=("prop_ceiling",))
            k = float(np.quantile([r["actual"] / max(r["prop_ceiling"], 1.0) for r in a], TAU))
            preds["proposal_scaled"] += [max(r["prop_ceiling"], 1.0) * k for r in b]
            preds["proposal_as_written"] += [r["prop_ceiling"] for r in b]
        out[label] = {m: ceiling_metrics(held, q) for m, q in preds.items()}
        out[label]["by_archetype_beat_rate"] = {
            name: {m: round(float(np.mean([r["actual"] > c for r, c in zip(held, q) if sel(r)])), 3) for m, q in preds.items()}
            | {"n": sum(1 for r in held if sel(r))} for name, sel in buckets.items() if any(sel(r) for r in held)}
    return out


def archetype_bias(rs, buckets) -> dict:
    out = {}
    for name, sel in buckets.items():
        sub = [r for r in rs if sel(r)]
        if not sub:
            continue
        out[name] = {"n": len(sub), "mean_error_corrected": round(mean(r["corrected"] - r["actual"] for r in sub), 2),
                     "actual_over_proj": round(mean(r["actual"] > r["corrected"] for r in sub), 3),
                     "bust_rate": round(mean(r["actual"] < 0.5 * r["corrected"] for r in sub), 3),
                     "boom_rate": round(mean(r["actual"] >= 1.5 * r["corrected"] for r in sub), 3),
                     "cv_actual_over_proj": round(float(np.std([r["actual"] / r["corrected"] for r in sub if r["corrected"] > 0])), 3)}
    return out


def prop_median_check(rs, stat, sel_groups) -> dict:
    out = {}
    actual_col = {"rush_yd": "rushing_yards", "pass_yd": "passing_yards"}[stat]
    for name, sel in sel_groups.items():
        sub = []
        for r in rs:
            p = pp.params(stat, r["pos"])
            proj = f(r["line"].get(stat)) * r["ratio"]
            if not p or proj < 8 or not sel(r):
                continue
            sub.append(f(r["stat"].get(actual_col)) > pp.median(proj, p))
        if sub:
            out[name] = {"n": len(sub), "share_above_median": round(mean(sub), 3)}
    return out


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/cache/train")
    ap.add_argument("--test-weeks", type=int, default=6)
    args = ap.parse_args()
    d = Path(args.data)
    weeks = {s: list(range(1, 19)) for s in TRAIN} | {TEST: list(range(1, args.test_weeks + 1))}
    seasons = {s: Season(d, s, weeks[s]) for s in (*TRAIN, TEST)}
    print("seasons loaded")
    # league RB points per carry / target (training seasons)
    rbs = [s for y in TRAIN for s in seasons[y].stats if s["position"] == "RB"]
    league_pp = {"carry": sum(rush_pts(s) for s in rbs) / sum(f(s.get("carries")) for s in rbs),
                 "target": sum(rec_pts(s) for s in rbs) / sum(f(s.get("targets")) for s in rbs)}
    events = {y: vacancy_events(S, [w for w in weeks[y] if w >= 3], league_pp) for y, S in seasons.items()}
    ev_all = [e for v in events.values() for e in v]
    print("vacancy backups", len(ev_all))
    res: dict = {"league_rb_points_per": league_pp}
    tr_ev = [e for y in TRAIN for e in events[y]]
    res["A_shares"] = {"2023-2025 (participation)": share_accuracy(tr_ev),
                       "2023-2025 first game without the lead back": share_accuracy([e for e in tr_ev if e["first_absence"]]),
                       "2026": share_accuracy(events[TEST])}
    res["A_absorption"] = {"2023-2026": absorption(ev_all), "first games": absorption([e for e in ev_all if e["first_absence"]])}

    realloc = {y: {(e["week"], e["key"]): e for e in events[y]} for y in seasons}
    rows_by = {y: rows(seasons[y], d, weeks[y], realloc[y]) for y in seasons}
    train = [r for y in TRAIN for r in rows_by[y]]
    test = rows_by[TEST]
    print("rows", len(train), len(test))

    # A. points for backups in vacancy games
    pts = {}
    for label, rs in (("2023-2025", [r for r in train if r["realloc"]]), ("2026", [r for r in test if r["realloc"]]),
                      ("2023-2026 first games", [r for r in train + test if r["realloc"] and r["realloc"]["first_absence"]])):
        if not rs:
            continue
        ra = [r["realloc"]["realloc_pts"] for r in rs]
        # the backups' non-rushing/receiving points (fumbles, 2-pt) are tiny; compare on full DK points
        pts[label] = {"n": len(rs)}
        for m, pred in (("sleeper", [r["proj"] for r in rs]), ("current", [r["corrected"] for r in rs]),
                        ("proposal_shares", ra), ("proposal_shares_with_decay", [x * DECAY for x in ra]),
                        ("blend_current_proposal", [(r["corrected"] + x) / 2 for r, x in zip(rs, ra)])):
            pts[label][m] = {"mae": round(mean(abs(p - r["actual"]) for p, r in zip(pred, rs)), 2),
                             "bias": round(mean(p - r["actual"] for p, r in zip(pred, rs)), 2)}
    res["A_points"] = pts

    tr_seasons = list(TRAIN)
    vac = lambda r: r["realloc"] is not None  # noqa: E731
    res["A_model"] = feature_test(train, test, "+realloc_gain", ("realloc_gain",), tr_seasons, {"vacancy_backups": vac})
    res["A_model_ratio"] = feature_test(train, test, "+realloc_gain_ratio", ("realloc_gain_ratio",), tr_seasons, {"vacancy_backups": vac})

    # B. archetypes
    rb_buckets = {
        "RB 5+ projected targets": lambda r: r["pos"] == "RB" and f(r["line"].get("rec_tgt")) >= 5,
        "RB 3-5 projected targets": lambda r: r["pos"] == "RB" and 3 <= f(r["line"].get("rec_tgt")) < 5,
        "RB under 3 projected targets": lambda r: r["pos"] == "RB" and f(r["line"].get("rec_tgt")) < 3,
        "RB grinder (12+ carries, 2 or fewer targets)": lambda r: r["pos"] == "RB" and f(r["line"].get("rush_att")) >= 12 and f(r["line"].get("rec_tgt")) <= 2,
        "RB receiving 40%+ of projection": lambda r: r["pos"] == "RB" and r["rec_share"] >= 0.40,
    }
    qb_buckets = {
        "QB rushing 30%+ of projection": lambda r: r["pos"] == "QB" and r["rush_share"] >= 0.30,
        "QB rushing 20-30%": lambda r: r["pos"] == "QB" and 0.20 <= r["rush_share"] < 0.30,
        "QB pocket (under 20%)": lambda r: r["pos"] == "QB" and r["rush_share"] < 0.20,
        "Pocket QB, pressure deficit top quartile": None, "Rushing QB, pressure deficit top quartile": None,
    }
    qd = float(np.quantile([r["deficit"] for r in train if r["pos"] == "QB"], 0.75))
    qb_buckets["Pocket QB, pressure deficit top quartile"] = lambda r: r["pos"] == "QB" and not r["rush_qb"] and r["deficit"] >= qd
    qb_buckets["Rushing QB, pressure deficit top quartile"] = lambda r: r["pos"] == "QB" and r["rush_qb"] and r["deficit"] >= qd
    qb_buckets["Pocket QB, pressure deficit bottom quartile"] = lambda r: (
        r["pos"] == "QB" and not r["rush_qb"] and r["deficit"] <= float(np.quantile([x["deficit"] for x in train if x["pos"] == "QB"], 0.25)))
    res["pressure_deficit_top_quartile_cut"] = round(qd, 4)
    res["B_projection_by_archetype"] = {"2023-2025 (correction in-sample)": archetype_bias(train, rb_buckets | qb_buckets),
                                        "2026": archetype_bias(test, rb_buckets | qb_buckets)}
    res["B_model_rb"] = feature_test(train, test, "+rb archetype", ("rb_rec_share", "rb_tgt5"), tr_seasons,
                                     {"rb_5plus_targets": rb_buckets["RB 5+ projected targets"]})
    res["B_model_qb_rush"] = feature_test(train, test, "+qb_rush_share", ("qb_rush_share",), tr_seasons,
                                          {"rushing_qbs": qb_buckets["QB rushing 30%+ of projection"]})
    res["B_model_grinder"] = feature_test(train, test, "+grinder_spread", ("grinder_spread",), tr_seasons,
                                          {"grinders": rb_buckets["RB grinder (12+ carries, 2 or fewer targets)"]})
    res["B_ceiling_rb"] = ceiling_test(train, test, "RB", rb_buckets)
    res["B_ceiling_qb"] = ceiling_test(train, test, "QB", qb_buckets)
    grind = rb_buckets["RB grinder (12+ carries, 2 or fewer targets)"]
    res["B_prop_grinder_rush_yards"] = {
        "2023-2025": prop_median_check(train, "rush_yd", {
            "grinder, underdog": lambda r: grind(r) and (r["spread"] or 0) < 0,
            "grinder, underdog by 3+": lambda r: grind(r) and (r["spread"] or 0) <= -3,
            "grinder, favorite": lambda r: grind(r) and (r["spread"] or 0) > 0,
            "other RBs, underdog": lambda r: r["pos"] == "RB" and not grind(r) and (r["spread"] or 0) < 0}),
        "2026": prop_median_check(test, "rush_yd", {
            "grinder, underdog": lambda r: grind(r) and (r["spread"] or 0) < 0,
            "grinder, favorite": lambda r: grind(r) and (r["spread"] or 0) > 0})}

    # C. pocket fragility
    res["C_model_pressure_deficit"] = feature_test(train, test, "+pressure_deficit", ("pressure_deficit",), tr_seasons,
                                                   {"pocket_qb_high_deficit": qb_buckets["Pocket QB, pressure deficit top quartile"]})
    res["C_model_pfi"] = feature_test(train, test, "+pfi split", ("pfi_pocket", "pfi_rush"), tr_seasons,
                                      {"pocket_qb_high_deficit": qb_buckets["Pocket QB, pressure deficit top quartile"],
                                       "rushing_qb_high_deficit": qb_buckets["Rushing QB, pressure deficit top quartile"]})
    pq = {k: v for k, v in qb_buckets.items() if "deficit" in k}
    res["C_prop_pass_yards"] = {"2023-2025": prop_median_check(train, "pass_yd", pq), "2026": prop_median_check(test, "pass_yd", pq)}

    OUT.write_text(json.dumps(res, indent=1, default=str))
    print(json.dumps({k: v for k, v in res.items() if not k.endswith(("_model", "_model_ratio"))}, indent=1, default=str)[:20000])


if __name__ == "__main__":
    main()
