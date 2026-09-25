"""What the ownership engine learns from actual contest ownership.

Run after every actual-ownership upload (and callable any time); it rebuilds
data/ownership/learning.json from every slate that has actual ownership,
always grading the *timestamped pre-lock* numbers -- historical predictions
are never altered.

  sources         per source: n, MAE, RMSE, bias, error SD, correlation with
                  actual; pairwise correlation of errors (for de-duplicating
                  sources that copy each other)
  users / crowd   per crowd contributor: n, MAE, bias; crowd MAE and how
                  correlated contributors' errors are (herding)
  model           posterior accuracy by contest and position: MAE, RMSE,
                  bias, 80%-interval coverage, Brier score for P(>10/20/30%)
  calibration     isotonic curve (posterior mean -> actual), used once 100+
                  graded player-contests exist
  contest_adjust  per contest type, the logit shift from large-field GPP
  flex_shares     how the field fills FLEX (RB/WR/TE), from full contest
                  ownership
  behavioral      Model C coefficients, fit by L2-regularized least squares on
                  the softmax allocation, and its effective N from residuals
  field           the duplication simulator's stack / bring-back / RB-DST
                  tilts and minimum spend, matched to real field lineups
"""
from __future__ import annotations

import json
import math
import statistics

import numpy as np
from scipy import optimize, stats

from app import ownership_model as om
from app import ownership_store as store

MIN_ACTUAL_PLAYERS = 20
RIDGE = 0.5
COMPLETE_TOTAL = 8.5    # FLEX shares are learned only from (near-)complete ownership: 850%+ of the 900% total


def _pearson(xs, ys):
    if len(xs) < 3:
        return None
    r = np.corrcoef(xs, ys)[0, 1]
    return None if np.isnan(r) else float(r)


def isotonic(xs: list[float], ys: list[float]) -> tuple[list[float], list[float]]:
    """Pool-adjacent-violators: non-decreasing fit of y on x."""
    pts = sorted(zip(xs, ys))
    blocks = [[x, y, 1.0] for x, y in pts]   # [x_sum, y_sum, weight]
    merged: list[list[float]] = []
    for b in blocks:
        merged.append(b)
        while len(merged) >= 2 and merged[-2][1] / merged[-2][2] > merged[-1][1] / merged[-1][2]:
            x2, y2, w2 = merged.pop()
            merged[-1][0] += x2
            merged[-1][1] += y2
            merged[-1][2] += w2
    return [m[0] / m[2] for m in merged], [m[1] / m[2] for m in merged]


def _pre_lock_snapshot(data: dict) -> dict | None:
    lock = data.get("lock")
    hist = data.get("history") or []
    if lock:
        hist = [h for h in hist if store.parse_iso(h["timestamp"]) <= store.parse_iso(lock)]
    return hist[-1] if hist else None


def _latest_pre_lock(obs: list[dict], kind: str, contest: str, lock: str | None) -> dict[tuple, float]:
    out: dict[tuple, tuple] = {}
    for o in obs:
        if o["kind"] != kind or o["contest"] != contest:
            continue
        if lock and store.parse_iso(o["timestamp"]) > store.parse_iso(lock):
            continue
        who = o.get("source") if kind == "source" else o.get("user_id")
        k = (who, o["key"])
        if k not in out or out[k][0] <= o["timestamp"]:
            out[k] = (o["timestamp"], o["pct"] / 100)
    return {k: v[1] for k, v in out.items()}


def fit_behavioral(rows: list[dict], slots_by_slate: dict) -> dict | None:
    """rows: {slate, group, feats{...}, actual}. Minimizes squared allocation
    error + RIDGE * ||coef||^2 over the softmax coefficients."""
    if len(rows) < 150:
        return None
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        groups.setdefault((r["slate"], r["group"]), []).append(r)
    feats = list(om.FEATURES)

    def loss(c):
        total = 0.0
        for (slate, g), rs in groups.items():
            u = np.array([sum(c[i] * r["feats"][f] for i, f in enumerate(feats)) for r in rs])
            e = np.exp(u - u.max())
            pred = slots_by_slate.get(slate, {}).get(g, 1.0) * e / e.sum()
            total += float(((pred - np.array([r["actual"] for r in rs])) ** 2).sum())
        return total + RIDGE * float(np.dot(c, c))

    x0 = np.array([om.DEFAULT_COEF[f] for f in feats])
    res = optimize.minimize(loss, x0, method="L-BFGS-B")
    coef = {f: round(float(v), 4) for f, v in zip(feats, res.x)}
    resid, var = [], []
    for (slate, g), rs in groups.items():
        u = np.array([sum(coef[f] * r["feats"][f] for f in feats) for r in rs])
        e = np.exp(u - u.max())
        pred = slots_by_slate.get(slate, {}).get(g, 1.0) * e / e.sum()
        for p_, r in zip(pred, rs):
            resid.append((r["actual"] - p_) ** 2)
            var.append(min(0.97, max(0.0005, p_)) * (1 - min(0.97, max(0.0005, p_))))
    n_eff = max(3.0, min(200.0, statistics.fmean(var) / max(statistics.fmean(resid), 1e-6) - 1))
    return {"coef": coef, "n_eff": round(n_eff, 1), "n_rows": len(rows), "loss": round(float(res.fun), 4)}


def fit_field(slates: list[tuple[list[dict], dict[str, float], list[list[str]]]]) -> dict | None:
    """Match the simulator's tilts to observed field lineups (moment matching on a grid)."""
    from app import ownership_field as of

    obs_rates, sims = [], []
    for roster, actual, lineups in slates:
        if len(lineups) < 200:
            continue
        by_key = {p["key"]: p for p in roster}
        stack = bb = rbdst = 0
        sal = []
        for lu in lineups:
            ps = [by_key[k] for k in lu if k in by_key]
            if len(ps) < 9:
                continue
            qb = next((p for p in ps if p["position"] == "QB"), None)
            dst = next((p for p in ps if p["position"] == "DST"), None)
            if not qb or not dst:
                continue
            stack += any(p["team"] == qb["team"] and p["position"] in ("WR", "TE") for p in ps)
            bb += any(p["team"] == qb["opponent"] and p["position"] in ("RB", "WR", "TE") for p in ps)
            rbdst += any(p["team"] == dst["team"] and p["position"] == "RB" for p in ps)
            sal.append(sum(p["salary"] for p in ps))
        if not sal:
            continue
        n = len(sal)
        obs_rates.append({"stack": stack / n, "bring_back": bb / n, "rb_dst": rbdst / n,
                          "min_salary": float(np.percentile(sal, 5))})
        sims.append((roster, actual))
    if not obs_rates:
        return None
    target = {k: statistics.fmean(r[k] for r in obs_rates) for k in obs_rates[0]}
    params = dict(of.FIELD_DEFAULTS, min_salary=round(target["min_salary"], -2))

    def rate(pname, value):
        rates = []
        for roster, actual in sims:
            a = np.array([max(0.5, actual.get(p["key"], 0.001) * 400) for p in roster])
            b = np.array([max(0.5, (1 - actual.get(p["key"], 0.001)) * 400) for p in roster])
            m = of.FieldModel(roster, a, b, om.DEFAULT_FLEX, {**params, pname: value}, seed=1)
            acc, _pv, _own = m.sample(2000)
            by_i = roster
            hits = 0
            for lu in acc:
                ps = [by_i[i] for i in lu]
                qb = next(p for p in ps if p["position"] == "QB")
                dst = next(p for p in ps if p["position"] == "DST")
                if pname == "stack":
                    hits += any(p["team"] == qb["team"] and p["position"] in ("WR", "TE") for p in ps)
                elif pname == "bring_back":
                    hits += any(p["team"] == qb["opponent"] and p["position"] in ("RB", "WR", "TE") for p in ps)
                else:
                    hits += any(p["team"] == dst["team"] and p["position"] == "RB" for p in ps)
            rates.append(hits / max(1, len(acc)))
        return statistics.fmean(rates)

    grids = {"stack": [0, 0.5, 1, 1.5, 2, 3, 4, 6], "bring_back": [0, 0.15, 0.3, 0.6, 1.0, 1.5], "rb_dst": [0, 0.2, 0.4, 0.8, 1.5]}
    for pname, grid in grids.items():
        best = min(grid, key=lambda v: abs(rate(pname, v) - target[pname]))
        params[pname] = best
    return {**params, "observed": {k: round(v, 3) for k, v in target.items()}, "slates": len(obs_rates)}


def relearn() -> dict:
    src_err: dict[str, list] = {}
    usr_err: dict[str, list] = {}
    pair_err: dict[tuple, float] = {}
    model_rows: list[dict] = []
    cal_x, cal_y = [], []
    deltas: dict[str, list[float]] = {}
    flex_est: dict[str, list[float]] = {}
    beh_rows, slots_by_slate = [], {}
    field_slates = []
    slates_used = 0

    for path in store.all_slate_files():
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        lock = data.get("lock")
        actual_by_c: dict[str, dict[str, float]] = {}
        full_by_c: dict[str, bool] = {}
        for o in data.get("observations", []):
            if o["kind"] == "actual":
                actual_by_c.setdefault(o["contest"], {})[o["key"]] = o["pct"] / 100
                if o.get("source") == "dk_standings":
                    full_by_c[o["contest"]] = True
        actual_by_c = {c: a for c, a in actual_by_c.items() if len(a) >= MIN_ACTUAL_PLAYERS}
        if not actual_by_c:
            continue
        slates_used += 1
        snap = _pre_lock_snapshot(data)
        roster = data.get("features", {}).get("roster", {})
        slate_tag = path.stem
        for c, actual in actual_by_c.items():
            for kind, bucket in (("source", src_err), ("crowd", usr_err)):
                for (who, key), pred in _latest_pre_lock(data.get("observations", []), kind, c, lock).items():
                    if key in actual:
                        e = pred - actual[key]
                        bucket.setdefault(who, []).append(e)
                        if kind == "source":
                            pair_err[(who, slate_tag, c, key)] = e
            ab = ((snap or {}).get("contests") or {}).get(c) or {}
            for key, (a, b) in ab.items():
                if key not in actual:
                    continue
                mean = a / (a + b)
                y = actual[key]
                lo, hi = stats.beta(a, b).ppf([0.10, 0.90])
                pos = (roster.get(key) or ["?"])[0]
                model_rows.append({"contest": c, "position": pos, "err": mean - y, "covered": lo <= y <= hi,
                                   "brier": {t: (float(stats.beta(a, b).sf(t)) - (1.0 if y > t else 0.0)) ** 2
                                             for t in om.THRESHOLDS}})
                cal_x.append(mean)
                cal_y.append(y)
            gpp = ((snap or {}).get("contests") or {}).get("gpp") or {}
            if c != "gpp":
                for key, y in actual.items():
                    if key in gpp:
                        a, b = gpp[key]
                        deltas.setdefault(c, []).append(om._logit(y) - om._logit(a / (a + b)))
            if full_by_c.get(c) and roster and sum(actual.values()) >= COMPLETE_TOTAL:
                sums: dict[str, float] = {}
                for key, y in actual.items():
                    pos = (roster.get(key) or [None])[0]
                    if pos:
                        sums[pos] = sums.get(pos, 0.0) + y
                for pos in ("RB", "WR", "TE"):
                    if pos in sums:
                        flex_est.setdefault(pos, []).append(max(0.0, sums[pos] - om.BASE_SLOTS[pos]))
            feats = data.get("features", {}).get("z") or {}
            if c == "gpp" and feats:
                slots_by_slate[slate_tag] = data.get("features", {}).get("slots") or {}
                for key, f in feats.items():
                    if key in actual:
                        beh_rows.append({"slate": slate_tag, "group": f["group"], "feats": f, "actual": actual[key]})
            lus = (data.get("field_lineups") or {}).get(c)
            if lus and roster:
                ros = [{"key": k, "position": v[0], "team": v[1], "opponent": v[2], "salary": v[3]} for k, v in roster.items()]
                field_slates.append((ros, actual, lus))

    def summarize(errs):
        n = len(errs)
        return {"n": n, "mae": round(statistics.fmean(abs(e) for e in errs), 4), "bias": round(statistics.fmean(errs), 4),
                "rmse": round(math.sqrt(statistics.fmean(e * e for e in errs)), 4),
                "sd": round(statistics.pstdev(errs), 4) if n > 1 else None}

    learning: dict = {"generated_at": store.now_iso(), "slates_with_actuals": slates_used}
    learning["sources"] = {s: summarize(e) for s, e in src_err.items() if e}
    names = sorted(src_err)
    corr = {}
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            common = [(pair_err[k], pair_err[(b,) + k[1:]]) for k in pair_err if k[0] == a and (b,) + k[1:] in pair_err]
            if len(common) >= 20:
                r = _pearson([x for x, _ in common], [y for _, y in common])
                if r is not None:
                    corr[f"{a}|{b}"] = {"rho": round(r, 3), "n": len(common)}
    learning["source_corr"] = corr
    learning["users"] = {u: summarize(e) for u, e in usr_err.items() if e}
    all_crowd = [e for es in usr_err.values() for e in es]
    learning["crowd"] = {"mae": round(statistics.fmean(abs(e) for e in all_crowd), 4) if all_crowd else None,
                         "rho": om.CROWD_RHO_DEFAULT, "n": len(all_crowd)}
    by_c: dict[str, list] = {}
    by_p: dict[str, list] = {}
    for r in model_rows:
        by_c.setdefault(r["contest"], []).append(r)
        by_p.setdefault(r["position"], []).append(r)

    def model_summary(rows):
        errs = [r["err"] for r in rows]
        out = summarize(errs)
        out["coverage80"] = round(statistics.fmean(1.0 if r["covered"] else 0.0 for r in rows), 3)
        out["brier"] = {str(int(t * 100)): round(statistics.fmean(r["brier"][t] for r in rows), 4) for t in om.THRESHOLDS}
        return out

    learning["model"] = {"by_contest": {c: model_summary(rs) for c, rs in by_c.items()},
                         "by_position": {p: model_summary(rs) for p, rs in by_p.items()}}
    if len(cal_x) >= 100:
        xs, ys = isotonic(cal_x, cal_y)
        learning["calibration"] = {"x": [round(x, 4) for x in xs], "y": [round(y, 4) for y in ys], "n": len(cal_x)}
    else:
        learning["calibration"] = {"n": len(cal_x)}
    learning["contest_adjust"] = {c: {"delta": round(statistics.fmean(d) * len(d) / (len(d) + 50), 4), "n": len(d)}
                                  for c, d in deltas.items() if d}
    if flex_est:
        raw = {p: statistics.fmean(v) for p, v in flex_est.items()}
        tot = sum(raw.values())
        if tot > 0.5:
            learning["flex_shares"] = {p: round(v / tot, 3) for p, v in raw.items()}
    beh = fit_behavioral(beh_rows, slots_by_slate)
    learning["behavioral"] = beh or {"n_rows": len(beh_rows)}
    field = fit_field(field_slates) if field_slates else None
    if field:
        learning["field"] = field
    store.save_learning(learning)
    return learning
