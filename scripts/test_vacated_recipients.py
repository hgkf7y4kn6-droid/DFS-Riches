"""Does Sleeper's final projection leave points on the table for ANY teammate of an absent regular -- not just other regulars?

    python -m scripts.test_vacated_recipients [--data DIR]

scripts.test_vacated_opportunity measured actual minus Sleeper's projection for the remaining *regulars* (12%+ of targets or
25%+ of carries). Players like a backup receiver who becomes the starter are not regulars, so they were never in that
sample. Here every remaining RB/WR/TE with a projection of at least 3 points is a recipient, split into regulars and others,
and the miss is regressed on how much the team's out regulars vacated (their last-three-game shares, the first game missed;
a player traded away is absent from his old team the same way, so trades are in the sample).

For each recipient class the slope (DK points per 100% of the vacated share), its team-season clustered t, the sign by season,
and a leave-one-season-out test: does Sleeper + slope x vacated beat Sleeper alone? Writes data/vacated_recipient_tests.json.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import numpy as np

from app import projections
from app.matching import normalize_name
from scripts.test_vacated_opportunity import PROJ_SEASONS, SEASONS, SKILL, season_rows
from scripts.train_player_model import TEAM_FIX, sleeper_week

OUT = Path(__file__).resolve().parents[1] / "data" / "vacated_recipient_tests.json"
MIN_PROJ = 3.0


def attach_projections(d: Path, rows: list[dict]) -> None:
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
                    proj[(w, TEAM_FIX.get(e["team"], e["team"]), normalize_name(name))] = projections.dk_points_from_line(e.get("stats") or {}, pl["position"])
        for r in rows:
            if r["season"] == s and r["played"]:
                r["proj"] = proj.get((r["week"], r["team"], normalize_name(r["name"])))


def vacated_by_position(rows: list[dict]) -> None:
    """Per team-week: target share vacated by out WR/TE regulars, by out RB regulars, and carry share vacated by out RBs."""
    v = defaultdict(lambda: [0.0, 0.0, 0.0])
    for r in rows:
        if r["regular"] and not r["played"]:
            k = (r["season"], r["week"], r["team"])
            if r["pos"] == "RB":
                v[k][1] += r["ts_l3"]
                v[k][2] += r["cs_l3"]
            else:
                v[k][0] += r["ts_l3"]
    for r in rows:
        r["v_wrte"], r["v_rb_ts"], r["v_rb_cs"] = v[(r["season"], r["week"], r["team"])]


def cluster_slope(x: np.ndarray, y: np.ndarray, groups: np.ndarray) -> tuple[float, float, float]:
    X = np.column_stack([np.ones(len(x)), x])
    A = np.linalg.inv(X.T @ X)
    beta = A @ X.T @ y
    e = y - X @ beta
    meat = np.zeros((2, 2))
    for g in np.unique(groups):
        m = groups == g
        s = X[m].T @ e[m]
        meat += np.outer(s, s)
    se = np.sqrt(np.diag(A @ meat @ A))
    return float(beta[1]), float(beta[1] / se[1]), float(beta[0])


def analyse(rows: list[dict], label: str, sel, xcol: str, regular: bool | None) -> dict:
    use = [r for r in rows if r["played"] and sel(r) and (r.get("proj") or 0) >= MIN_PROJ and (regular is None or r["regular"] == regular)]
    if len(use) < 200:
        return {"n": len(use)}
    x = np.array([r[xcol] for r in use])
    y = np.array([r["pts"] - r["proj"] for r in use])
    g = np.array([f"{r['team']}{r['season']}" for r in use])
    slope, t, icpt = cluster_slope(x, y, g)
    vac = x >= 0.15 if xcol != "v_rb_cs" else x >= 0.25
    seasons = np.array([r["season"] for r in use])
    by = {}
    for s in PROJ_SEASONS:
        m = seasons == s
        if m.sum() > 50 and (m & (x > 0)).sum() > 15:
            by[int(s)] = round(float(np.polyfit(x[m], y[m], 1)[0]), 2)
    # leave one season out: Sleeper alone vs Sleeper + (a + b x), fit on the other seasons
    se_base = se_fix = 0.0
    n = 0
    for s in PROJ_SEASONS:
        tr, te = seasons != s, seasons == s
        if te.sum() == 0 or tr.sum() < 100:
            continue
        b, a = np.polyfit(x[tr], y[tr], 1)
        se_base += float(((y[te]) ** 2).sum())
        se_fix += float(((y[te] - (a + b * x[te])) ** 2).sum())
        n += int(te.sum())
    return {"n": len(use), "n_vacated_15pct": int(vac.sum()), "miss_when_nothing_vacated": round(float(y[x == 0].mean()), 2),
            "miss_when_15pct_vacated": round(float(y[vac].mean()), 2) if vac.any() else None,
            "slope_per_100pct_vacated": round(slope, 2), "t": round(t, 1), "intercept": round(icpt, 2), "slope_by_season": by,
            "loso_rmse_sleeper": round(float(np.sqrt(se_base / n)), 3), "loso_rmse_with_correction": round(float(np.sqrt(se_fix / n)), 3),
            "loso_change_pct": round(100 * (np.sqrt(se_fix / n) / np.sqrt(se_base / n) - 1), 2)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/cache/train")
    args = ap.parse_args()
    d = Path(args.data)
    rows = [r for s in SEASONS for r in season_rows(d, s)]
    attach_projections(d, rows)
    vacated_by_position(rows)
    res = {"seasons": list(PROJ_SEASONS), "rows": len(rows), "min_projection": MIN_PROJ, "classes": {}}
    wrte = lambda r: r["pos"] in ("WR", "TE")                                            # noqa: E731
    rb = lambda r: r["pos"] == "RB"                                                      # noqa: E731
    for name, sel, xcol in (("WR/TE recipients, targets vacated by out WR/TE", wrte, "v_wrte"),
                            ("RB recipients, carries vacated by out RB", rb, "v_rb_cs"),
                            ("RB recipients, targets vacated by out RB", rb, "v_rb_ts"),
                            ("WR/TE recipients, targets vacated by out RB", wrte, "v_rb_ts"),
                            ("RB recipients, targets vacated by out WR/TE", rb, "v_wrte")):
        for reg, tag in ((True, "regulars"), (False, "non-regulars"), (None, "all")):
            res["classes"][f"{name} | {tag}"] = analyse(rows, name, sel, xcol, reg)
    OUT.write_text(json.dumps(res, indent=1) + "\n")
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
