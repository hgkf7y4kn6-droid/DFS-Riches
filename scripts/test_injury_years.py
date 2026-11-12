"""Do years in the league and finer position predict whether a Questionable player plays, beyond his practice status?

nflverse injury reports (final status of the week) + snap counts ("played" = took any snap incl. special teams) +
weekly rosters (years_exp), 2016-2025, all positions. Models are ridge logistic regressions compared by leave-one-season-out
log loss: practice only; + position group; + years in the league; + both.
    python -m scripts.test_injury_years
Needs pandas. Writes data/injury_years_tests.json.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

TRAIN = Path(__file__).resolve().parents[1] / "data" / "cache" / "train"
OUT = Path(__file__).resolve().parents[1] / "data" / "injury_years_tests.json"
SEASONS = list(range(2016, 2026))
GROUPS = {"QB": "QB", "RB": "RB", "FB": "RB", "WR": "WR", "TE": "TE", "T": "OL", "G": "OL", "C": "OL", "OL": "OL",
          "DE": "DL", "DT": "DL", "NT": "DL", "DL": "DL", "LB": "LB", "OLB": "LB", "ILB": "LB", "MLB": "LB",
          "CB": "DB", "S": "DB", "FS": "DB", "SS": "DB", "DB": "DB"}
PRACTICE = {"Did Not Participate In Practice": "dnp", "Limited Participation in Practice": "lp", "Full Participation in Practice": "fp"}
YEARS = [(0, 0, "rookie"), (1, 3, "yr2_4"), (4, 8, "yr5_9"), (9, 99, "yr10_plus")]


def norm(n) -> str:
    return "".join(ch for ch in str(n).lower() if ch.isalnum())


def load() -> pd.DataFrame:
    frames = []
    for s in SEASONS:
        inj = pd.read_csv(TRAIN / f"injuries_{s}.csv", low_memory=False)
        inj = inj[(inj.game_type == "REG") & inj.report_status.isin(["Questionable", "Doubtful", "Out"])].copy()
        snaps = pd.read_csv(TRAIN / f"snap_counts_{s}.csv", usecols=["week", "team", "player", "offense_snaps", "defense_snaps", "st_snaps", "game_type"])
        snaps = snaps[snaps.game_type == "REG"].copy()
        snaps["k"] = snaps.player.map(norm) + "|" + snaps.team + "|" + snaps.week.astype(str)
        played = set(snaps.k[(snaps.offense_snaps + snaps.defense_snaps + snaps.st_snaps) > 0])
        ros = pd.read_csv(TRAIN / f"roster_weekly_{s}.csv", usecols=["gsis_id", "week", "years_exp", "game_type"], low_memory=False)
        ros = ros[ros.game_type == "REG"].drop_duplicates(["gsis_id", "week"])
        inj = inj.merge(ros[["gsis_id", "week", "years_exp"]], on=["gsis_id", "week"], how="left")
        inj["played"] = (inj.full_name.map(norm) + "|" + inj.team + "|" + inj.week.astype(str)).isin(played).astype(int)
        inj["season"] = s
        frames.append(inj)
    d = pd.concat(frames, ignore_index=True)
    d["group"] = d.position.map(GROUPS)
    d["practice"] = d.practice_status.map(PRACTICE)
    return d


def years_bucket(y) -> str | None:
    if pd.isna(y):
        return None
    for lo, hi, name in YEARS:
        if lo <= y <= hi:
            return name
    return None


def X_for(d: pd.DataFrame, use_pos: bool, use_years: bool, cats: dict) -> np.ndarray:
    cols = [np.ones(len(d))]
    for p in cats["practice"][1:]:
        cols.append((d.practice == p).to_numpy(float))
    if use_pos:
        for g in cats["group"][1:]:
            cols.append((d.group == g).to_numpy(float))
    if use_years:
        for y in cats["years"][1:]:
            cols.append((d.yb == y).to_numpy(float))
    return np.column_stack(cols)


def fit_logit(X, y, l2=1.0, iters=30):
    b = np.zeros(X.shape[1])
    pen = np.eye(X.shape[1]) * l2
    pen[0, 0] = 0
    for _ in range(iters):
        p = 1 / (1 + np.exp(-X @ b))
        W = p * (1 - p)
        H = X.T @ (X * W[:, None]) + pen
        g = X.T @ (y - p) - pen @ b
        step = np.linalg.solve(H, g)
        b += step
        if np.abs(step).max() < 1e-8:
            break
    return b


def logloss(y, p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def main() -> None:
    d = load()
    d["yb"] = d.years_exp.map(years_bucket)
    base_rates = {st: {g: {"n": int(len(x)), "played": round(float(x.played.mean()), 3)}
                       for g, x in d[d.report_status == st].groupby("group") if len(x) >= 40}
                  for st in ("Questionable", "Doubtful", "Out")}
    q = d[(d.report_status == "Questionable") & d.practice.notna() & d.group.notna() & d.yb.notna()].copy()
    cats = {"practice": ["fp", "lp", "dnp"], "group": ["QB", "RB", "WR", "TE", "OL", "DL", "LB", "DB"],
            "years": [y[2] for y in YEARS]}
    models = {"practice_only": (False, False), "+position": (True, False), "+years": (False, True), "+position+years": (True, True)}
    res = {"n_questionable": int(len(q)), "base_rates_by_position": base_rates, "loso_logloss": {}}
    for name, (up, uy) in models.items():
        losses, ns = [], []
        for s in SEASONS:
            tr, te = q[q.season != s], q[q.season == s]
            b = fit_logit(X_for(tr, up, uy, cats), tr.played.to_numpy(float))
            p = 1 / (1 + np.exp(-X_for(te, up, uy, cats) @ b))
            losses.append(logloss(te.played.to_numpy(float), p) * len(te))
            ns.append(len(te))
        res["loso_logloss"][name] = round(sum(losses) / sum(ns), 5)
    b = fit_logit(X_for(q, True, True, cats), q.played.to_numpy(float))
    names = ["intercept"] + [f"practice={p}" for p in cats["practice"][1:]] + [f"pos={g}" for g in cats["group"][1:]] + [f"years={y}" for y in cats["years"][1:]]
    res["coefficients_full_model"] = {n: round(float(c), 3) for n, c in zip(names, b)}
    res["played_rate_by_years_questionable"] = {y: round(float(x.played.mean()), 3) for y, x in q.groupby("yb")}
    res["played_rate_by_years_and_practice"] = {f"{y}|{p}": {"n": int(len(x)), "played": round(float(x.played.mean()), 3)}
                                                for (y, p), x in q.groupby(["yb", "practice"])}
    OUT.write_text(json.dumps(res, indent=1))
    print(json.dumps({k: v for k, v in res.items() if k != "base_rates_by_position"}, indent=1))


if __name__ == "__main__":
    main()
