"""Bayesian DFS ownership engine: P(true ownership | everything known).

Every player's field ownership theta is a Beta distribution. Three models
feed it, each as an *effective sample size* N (how much it's worth), never a
plain average:

  Model C  behavioral / contextual (the prior)
           A multinomial-logit (softmax) allocation within each position,
           from value, projection, implied team total, ceiling, salary and
           injury status. The field's slots are a hard fact -- every Classic
           lineup has 1 QB, 2 RB, 3 WR, 1 TE, 1 DST and a FLEX -- so each
           position's ownership sums to its slot count (QB 100%, RB 200% +
           the FLEX share...). Untrained, its coefficients are weak defaults
           and it's worth N = 8 (very wide intervals). Once actual ownership
           has been uploaded, app.ownership_learning fits the coefficients
           (L2-regularized) and N from the residuals.
  Model A  ownership sources (projections pasted from named sources)
           Bias-corrected, weighted by 1 / (MAE + 0.01), each worth
           N = mu(1 - mu) / sigma^2 - 1 from its historical error; sources
           whose errors are correlated are discounted:
           N_eff = sum N / (1 + (k - 1) rho).
  Model B  crowdsourced submissions
           Each contributor weighted by 1 / (MAE + 0.01) (shrunk toward a
           newcomer MAE until they have a graded history) and their stated
           confidence; crowd N = sum of reliability, discounted for herding.

Posterior: alpha = sum(mu_m N_m), beta = sum((1 - mu_m) N_m) -- the
conjugate Beta update. Observations decay with age (half-life 12h early,
6h mid-slate, 2h in the last 3 hours, ~20 min in the last 30) and nothing
after lock is used. Confirmed news (DraftKings OUT / Doubtful / IR)
overrides everything; Questionable widens the interval.

Contest types: a hierarchical structure -- each contest's posterior uses
every contest's information, translated by a learned logit adjustment and
worth half as much when it came from a different contest, so large-field
GPP ownership informs cash without forcing them to be equal.

Calibration: once enough actual ownership exists, an isotonic curve maps
posterior means to what actually happened.

Monte Carlo: 10,000 draws per player give the credible intervals,
threshold probabilities, ownership-rank distribution and spike tests.

Every number carries a label: ACTUAL, PROJECTED (a source), CROWDSOURCED,
BAYESIAN POSTERIOR or SIMULATED.
"""
from __future__ import annotations

import math
import statistics
from datetime import datetime, timezone

import numpy as np
from scipy import special

from app import ownership_store as store

EPS = 0.01
PLAYABLE = {"Healthy", "Q"}
OUT_STATUSES = {"O", "OUT", "D", "IR", "PUP", "NFI", "SUSP"}
CLASSIC_POS = ("QB", "RB", "WR", "TE", "DST")
BASE_SLOTS = {"QB": 1.0, "RB": 2.0, "WR": 3.0, "TE": 1.0, "DST": 1.0}
DEFAULT_FLEX = {"RB": 0.40, "WR": 0.50, "TE": 0.10}           # assumption until learned from actuals
FEATURES = ("value", "final", "implied", "ceiling", "salary", "q")
DEFAULT_COEF = {"value": 1.0, "final": 0.9, "implied": 0.25, "ceiling": 0.1, "salary": 0.0, "q": -0.6}
N_BEHAVIORAL_UNTRAINED = 8.0
SOURCE_SIGMA_DEFAULT = 0.05       # an unscored source is assumed to miss by ~5 points
SOURCE_RHO_DEFAULT = 0.5          # DFS ownership sources often share inputs
CROWD_MAE_DEFAULT = 0.06
CROWD_SHRINK_N = 20
CROWD_RHO_DEFAULT = 0.3
TRANSFER = 0.5                    # information from a different contest type counts half
UNLEARNED_CONTEST_SHRINK = 0.6    # contest adjustment not learned yet -> wider
Q_SHRINK = 0.6
OUT_BETA = (0.4, 199.6)           # confirmed out: ~0.2%
N_SIMS = 10_000
SIM_MIN_MEAN = 0.002              # players under 0.2% posterior ownership get exact Beta summaries instead
THRESHOLDS = (0.10, 0.20, 0.30, 0.40)
DISPERSION_FLAG = 0.05
SPIKE_DELTA = 0.05
MIN_MU, MAX_MU = 0.0005, 0.97
SHOWDOWN_SLOTS = {"CPT": 1.0, "FLEX": 5.0}
# Untrained prior only: the most-owned player's share by group (assumed typical field concentration).
TOP_OWNED_ANCHOR = {"QB": 0.15, "RB": 0.25, "WR": 0.25, "TE": 0.18, "DST": 0.15, "CPT": 0.25, "FLEX": 0.60}


def _clip(mu: float) -> float:
    return min(MAX_MU, max(MIN_MU, mu))


def _logit(p: float) -> float:
    p = _clip(p)
    return math.log(p / (1 - p))


def _expit(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def n_from_sigma(sigma: float, mu: float) -> float:
    """Effective sample size of an estimate that misses by sigma (Beta variance match)."""
    mu = _clip(mu)
    return float(min(400.0, max(2.0, mu * (1 - mu) / max(sigma, 1e-4) ** 2 - 1)))


def half_life_hours(hours_to_lock: float) -> float:
    if hours_to_lock > 24:
        return 12.0
    if hours_to_lock > 3:
        return 6.0
    if hours_to_lock > 0.5:
        return 2.0
    return 0.375


def decay(age_hours: float, hours_to_lock: float) -> float:
    return math.exp(-math.log(2) / half_life_hours(hours_to_lock) * max(0.0, age_hours))


# ------------------------------------------------------------ Model C
def _z(vals: list[float]) -> list[float]:
    if len(vals) < 2:
        return [0.0] * len(vals)
    m = statistics.fmean(vals)
    sd = statistics.pstdev(vals) or 1.0
    return [(v - m) / sd for v in vals]


def feature_rows(players: list[dict], group_of) -> dict[str, dict]:
    """Within-group z-scored behavioral features (what the field reacts to)."""
    out = {}
    groups: dict[str, list[dict]] = {}
    for p in players:
        if p["injury"] in PLAYABLE and p["salary"] > 0:
            groups.setdefault(group_of(p), []).append(p)
    for g, ps in groups.items():
        imp_mean = statistics.fmean([p["implied"] for p in ps if p.get("implied") is not None] or [21.0])
        cols = {
            "value": _z([p.get("value") or 0 for p in ps]),
            "final": _z([p.get("final") or 0 for p in ps]),
            "implied": _z([p["implied"] if p.get("implied") is not None else imp_mean for p in ps]),
            "ceiling": _z([p.get("ceiling") or 0 for p in ps]),
            "salary": _z([p["salary"] for p in ps]),
        }
        for i, p in enumerate(ps):
            out[p["key"]] = {"group": g, **{k: round(cols[k][i], 4) for k in cols}, "q": 1.0 if p["injury"] == "Q" else 0.0}
    return out


def _shares(items: list[tuple[str, float]], scale: float, slot: float) -> list[tuple[str, float]]:
    mx = max(u for _, u in items)
    ex = [(k, math.exp(scale * (u - mx))) for k, u in items]
    tot = sum(e for _, e in ex)
    return [(k, slot * e / tot) for k, e in ex]


def softmax_allocation(feats: dict[str, dict], coef: dict, slots: dict[str, float],
                       anchor: dict[str, float] | None = None) -> dict[str, float]:
    """Multinomial-logit allocation of each group's slots. With `anchor`
    (untrained model only), each group's temperature is set so its most-owned
    player lands at the anchored level -- an explicit assumption about typical
    field concentration, replaced by fitted coefficients once actual ownership
    exists."""
    by_group: dict[str, list[tuple[str, float]]] = {}
    for key, f in feats.items():
        u = sum(coef.get(k, 0.0) * f[k] for k in FEATURES)
        by_group.setdefault(f["group"], []).append((key, u))
    out = {}
    for g, items in by_group.items():
        slot = slots.get(g, 1.0)
        scale = 1.0
        target = (anchor or {}).get(g)
        if target and len(items) > 1 and target * len(items) > slot:
            lo, hi = 0.01, 8.0
            for _ in range(40):
                mid = (lo + hi) / 2
                top = max(v for _, v in _shares(items, mid, slot))
                lo, hi = (mid, hi) if top < target else (lo, mid)
            scale = (lo + hi) / 2
        for k, v in _shares(items, scale, slot):
            out[k] = _clip(v)
    return out


def flex_shares(learning: dict) -> dict[str, float]:
    flex = learning.get("flex_shares") or {}
    return flex if sum(flex.values()) > 0.5 else DEFAULT_FLEX


def classic_slots(learning: dict) -> dict[str, float]:
    flex = flex_shares(learning)
    return {pos: BASE_SLOTS[pos] + flex.get(pos, 0.0) for pos in CLASSIC_POS}


# ------------------------------------------------------ observations
def latest_observations(obs: list[dict], kind: str, lock: datetime | None, now: datetime) -> dict[tuple, dict]:
    """Latest observation per (player key, contest, source/user) up to lock."""
    out: dict[tuple, dict] = {}
    for o in obs:
        if o["kind"] != kind:
            continue
        ts = store.parse_iso(o["timestamp"])
        if ts > now or (kind != "actual" and lock is not None and ts > lock):
            continue
        who = o.get("source") if kind == "source" else (o.get("user_id") if kind == "crowd" else "actual")
        k = (o["key"], o["contest"], who)
        if k not in out or store.parse_iso(out[k]["timestamp"]) <= ts:
            out[k] = o
    return out


def _delta(learning: dict, contest: str) -> tuple[float, bool]:
    d = (learning.get("contest_adjust") or {}).get(contest)
    if contest == "gpp":
        return 0.0, True
    if d and d.get("n", 0) >= 30:
        return float(d["delta"]), True
    return 0.0, False


def model_a(key: str, contest: str, src_obs: list[dict], learning: dict, now: datetime, hours_to_lock: float) -> dict | None:
    """Sources -> {mu, n, parts}. src_obs: latest observations for this player (all contests)."""
    if not src_obs:
        return None
    stats_by = learning.get("sources") or {}
    dc, _ = _delta(learning, contest)
    parts, wsum, nsum, mu_acc = [], 0.0, 0.0, 0.0
    for o in src_obs:
        st = stats_by.get(o["source"]) or {}
        bias = st.get("bias", 0.0) if st.get("n", 0) >= 20 else 0.0
        mae = st.get("mae", SOURCE_SIGMA_DEFAULT * 0.8) if st.get("n", 0) >= 20 else SOURCE_SIGMA_DEFAULT * 0.8
        sigma = st.get("sd", SOURCE_SIGMA_DEFAULT) if st.get("n", 0) >= 20 else SOURCE_SIGMA_DEFAULT
        raw = o["pct"] / 100
        adj = _clip(raw - bias)
        do, _ = _delta(learning, o["contest"])
        est = _expit(_logit(adj) - do + dc)
        age = (now - store.parse_iso(o["timestamp"])).total_seconds() / 3600
        w_time = decay(age, hours_to_lock)
        transfer = 1.0 if o["contest"] == contest else TRANSFER
        w = (1 / (mae + EPS)) * w_time * transfer
        n = n_from_sigma(sigma, est) * w_time * transfer
        parts.append({"source": o["source"], "contest": o["contest"], "reported": round(raw * 100, 2),
                      "bias_adjusted": round(adj * 100, 2), "estimate": round(est * 100, 2), "weight": round(w, 3),
                      "n": round(n, 1), "age_h": round(age, 2), "scored": st.get("n", 0) >= 20, "timestamp": o["timestamp"]})
        wsum += w
        nsum += n
        mu_acc += w * est
    k = len({p["source"] for p in parts})
    rho = _avg_rho(learning, [p["source"] for p in parts])
    n_eff = nsum / (1 + (k - 1) * rho) if k > 1 else nsum
    return {"mu": mu_acc / wsum if wsum else None, "n": n_eff, "k": k, "rho": rho, "parts": parts,
            "dispersion": statistics.pstdev([p["estimate"] / 100 for p in parts]) if len(parts) > 1 else 0.0}


def _avg_rho(learning: dict, sources: list[str]) -> float:
    uniq = sorted(set(sources))
    if len(uniq) < 2:
        return 0.0
    corr = learning.get("source_corr") or {}
    vals = []
    for i, a in enumerate(uniq):
        for b in uniq[i + 1:]:
            v = corr.get(f"{a}|{b}") or corr.get(f"{b}|{a}")
            vals.append(v["rho"] if v and v.get("n", 0) >= 20 else SOURCE_RHO_DEFAULT)
    return max(0.0, statistics.fmean(vals))


def user_mae(learning: dict, user_id: str) -> tuple[float, int]:
    u = (learning.get("users") or {}).get(user_id) or {}
    n = u.get("n", 0)
    mae = ((u.get("mae", CROWD_MAE_DEFAULT) * n) + CROWD_MAE_DEFAULT * CROWD_SHRINK_N) / (n + CROWD_SHRINK_N)
    return mae, n


def model_b(contest: str, crowd_obs: list[dict], learning: dict, now: datetime, hours_to_lock: float) -> dict | None:
    if not crowd_obs:
        return None
    dc, _ = _delta(learning, contest)
    wsum = nsum = acc = 0.0
    ests = []
    for o in crowd_obs:
        mae, n_graded = user_mae(learning, o.get("user_id", ""))
        r = 1 / (mae + EPS)
        conf = 0.5 + 0.1 * (o.get("confidence") or 3)
        age = (now - store.parse_iso(o["timestamp"])).total_seconds() / 3600
        transfer = 1.0 if o["contest"] == contest else TRANSFER
        do, _ = _delta(learning, o["contest"])
        est = _expit(_logit(o["pct"] / 100) - do + dc)
        w = r * conf * decay(age, hours_to_lock) * transfer
        wsum += w
        acc += w * est
        ests.append(est)
        nsum += w
    k = len({o.get("user_id") for o in crowd_obs})
    rho = (learning.get("crowd") or {}).get("rho", CROWD_RHO_DEFAULT)
    return {"mu": acc / wsum, "n": nsum / (1 + (k - 1) * rho) if k > 1 else nsum, "users": k,
            "mean": statistics.fmean(ests), "median": statistics.median(ests),
            "sd": statistics.pstdev(ests) if len(ests) > 1 else 0.0}


# ------------------------------------------------------ calibration
def calibrate(mu: float, learning: dict) -> float:
    cal = learning.get("calibration") or {}
    xs, ys = cal.get("x") or [], cal.get("y") or []
    if len(xs) < 2 or cal.get("n", 0) < 100:
        return mu
    return _clip(float(np.interp(mu, xs, ys)))


# ---------------------------------------------------------- posterior
def posterior(players: list[dict], obs: list[dict], learning: dict, *, now: datetime, lock: datetime | None,
              contests: tuple[str, ...], group_of, slots: dict[str, float], contest_of_group=None) -> dict:
    """{contest: {key: detail}} for every player and contest."""
    hours_to_lock = (lock - now).total_seconds() / 3600 if lock else 48.0
    feats = feature_rows(players, group_of)
    trained = (learning.get("behavioral") or {}).get("n_rows", 0) >= 150
    coef = (learning.get("behavioral") or {}).get("coef") if trained else DEFAULT_COEF
    n_c = float((learning.get("behavioral") or {}).get("n_eff", N_BEHAVIORAL_UNTRAINED)) if trained else N_BEHAVIORAL_UNTRAINED
    mu_c = softmax_allocation(feats, coef, slots, None if trained else TOP_OWNED_ANCHOR)
    src = latest_observations(obs, "source", lock, now)
    crowd = latest_observations(obs, "crowd", lock, now)
    actual = latest_observations(obs, "actual", None, now)
    src_by: dict[str, list] = {}
    for (key, _c, _w), o in src.items():
        src_by.setdefault(key, []).append(o)
    crowd_by: dict[str, list] = {}
    for (key, _c, _w), o in crowd.items():
        crowd_by.setdefault(key, []).append(o)
    act_by = {(key, c): o for (key, c, _w), o in actual.items()}

    out: dict[str, dict] = {c: {} for c in contests}
    for p in players:
        key = p["key"]
        for c in contests:
            if contest_of_group and contest_of_group(p) != c:
                continue
            dc, learned = _delta(learning, c)
            base = mu_c.get(key)
            det = {"key": key, "news": None}
            if p["injury"] not in PLAYABLE:
                a, b = OUT_BETA
                det.update(alpha=a, beta=b, news=f"Confirmed news: DraftKings lists him {p['injury']} (overrides everything else)",
                           models={"C": None, "A": None, "B": None})
            else:
                if base is None:
                    base = MIN_MU
                muc = _clip(_expit(_logit(base) + dc))
                nc = n_c * (1.0 if learned else UNLEARNED_CONTEST_SHRINK)
                ma = model_a(key, c, src_by.get(key, []), learning, now, hours_to_lock)
                mb = model_b(c, crowd_by.get(key, []), learning, now, hours_to_lock)
                a = muc * nc
                b = (1 - muc) * nc
                for m in (ma, mb):
                    if m and m["mu"] is not None and m["n"] > 0:
                        a += m["mu"] * m["n"]
                        b += (1 - m["mu"]) * m["n"]
                if p["injury"] == "Q":
                    a, b = a * Q_SHRINK, b * Q_SHRINK
                    det["news"] = "Questionable (DraftKings): interval widened"
                mean = a / (a + b)
                cal = calibrate(mean, learning)
                if cal != mean:
                    n = a + b
                    a, b = cal * n, (1 - cal) * n
                det.update(alpha=a, beta=b, calibrated=cal != mean,
                           models={"C": {"mu": muc, "n": nc, "trained": trained},
                                   "A": ma and {k: ma[k] for k in ("mu", "n", "k", "rho", "dispersion", "parts")},
                                   "B": mb and {k: mb[k] for k in ("mu", "n", "users", "mean", "median", "sd")}})
            act = act_by.get((key, c))
            det["actual"] = act["pct"] if act else None
            out[c][key] = det
    return {"by_contest": out, "features": feats, "trained": trained, "coef": coef, "n_behavioral": n_c,
            "hours_to_lock": hours_to_lock}


# ------------------------------------------------------ Monte Carlo
def simulate(details: dict[str, dict], keys: list[str], seed: int = 7) -> dict:
    """N_SIMS posterior draws per player -> summaries and ownership-rank odds (vectorized)."""
    rng = np.random.default_rng(seed)
    a = np.array([details[k]["alpha"] for k in keys], dtype=float)
    b = np.array([details[k]["beta"] for k in keys], dtype=float)
    draws = rng.beta(a, b, size=(N_SIMS, len(keys))).astype(np.float32)
    order = np.argsort(-draws, axis=1)
    ranks = np.empty(order.shape, dtype=np.int32)
    ranks[np.arange(N_SIMS)[:, None], order] = np.arange(1, len(keys) + 1, dtype=np.int32)[None, :]
    q = np.percentile(draws, [2.5, 10, 25, 50, 75, 90, 97.5], axis=0)
    mean, sd = draws.mean(axis=0), draws.std(axis=0)
    over = {t: (draws > t).mean(axis=0) for t in THRESHOLDS}
    top = {k: (ranks <= k).mean(axis=0) for k in (1, 3, 5, 10)}
    rank_mean = ranks.mean(axis=0)
    mode = np.where((a > 1) & (b > 1), (a - 1) / np.maximum(a + b - 2, 1e-9), np.where(a <= 1, 0.0, 1.0))
    out = {}
    for j, k in enumerate(keys):
        out[k] = {
            "mean": float(mean[j]), "median": float(q[3, j]), "mode": float(mode[j]), "sd": float(sd[j]),
            "ci50": [float(q[2, j]), float(q[4, j])], "ci80": [float(q[1, j]), float(q[5, j])], "ci95": [float(q[0, j]), float(q[6, j])],
            "p_over": {f"{int(t * 100)}": float(over[t][j]) for t in THRESHOLDS},
            "rank_mean": float(rank_mean[j]),
            "rank_probs": {"1": float(top[1][j]), "2-3": float(top[3][j] - top[1][j]), "4-5": float(top[5][j] - top[3][j]),
                           "6-10": float(top[10][j] - top[5][j]), "11+": float(1 - top[10][j])},
            "p_top5": float(top[5][j]), "p_top10": float(top[10][j]),
        }
    return {"stats": out, "draws": draws, "keys": keys}


def beta_summary(a: float, b: float) -> dict:
    lo, hi = special.betaincinv(a, b, [0.10, 0.90])
    return {"mean": a / (a + b), "ci80": [float(lo), float(hi)]}


def analytic_stats(details: dict[str, dict], keys: list[str]) -> dict[str, dict]:
    """Exact Beta summaries for players not worth simulating (near-zero
    ownership); they're never in the top 10, so their rank odds are 11+."""
    if not keys:
        return {}
    a = np.array([details[k]["alpha"] for k in keys], dtype=float)
    b = np.array([details[k]["beta"] for k in keys], dtype=float)
    qs = {p: special.betaincinv(a, b, p) for p in (0.025, 0.10, 0.25, 0.50, 0.75, 0.90, 0.975)}
    mean = a / (a + b)
    sd = np.sqrt(a * b / ((a + b) ** 2 * (a + b + 1)))
    over = {t: 1 - special.betainc(a, b, t) for t in THRESHOLDS}
    out = {}
    for j, k in enumerate(keys):
        mode = (a[j] - 1) / (a[j] + b[j] - 2) if a[j] > 1 and b[j] > 1 else 0.0
        out[k] = {"mean": float(mean[j]), "median": float(qs[0.50][j]), "mode": float(mode), "sd": float(sd[j]),
                  "ci50": [float(qs[0.25][j]), float(qs[0.75][j])], "ci80": [float(qs[0.10][j]), float(qs[0.90][j])],
                  "ci95": [float(qs[0.025][j]), float(qs[0.975][j])],
                  "p_over": {f"{int(t * 100)}": float(over[t][j]) for t in THRESHOLDS},
                  "rank_mean": None, "rank_probs": {"1": 0.0, "2-3": 0.0, "4-5": 0.0, "6-10": 0.0, "11+": 1.0},
                  "p_top5": 0.0, "p_top10": 0.0}
    return out


def spikes(sim: dict, prev: dict[str, list] | None, seed: int = 11) -> dict[str, dict]:
    """P(theta_now > theta_prev + 5 pts) and the reverse, vs the previous snapshot."""
    if not prev:
        return {}
    rng = np.random.default_rng(seed)
    out = {}
    for j, k in enumerate(sim["keys"]):
        if k not in prev:
            continue
        pa, pb = prev[k]
        prev_draws = rng.beta(pa, pb, size=N_SIMS)
        cur = sim["draws"][:, j]
        up = float((cur > prev_draws + SPIKE_DELTA).mean())
        down = float((cur < prev_draws - SPIKE_DELTA).mean())
        flag = None
        if up > 0.95:
            flag = "VERY HIGH-CONFIDENCE OWNERSHIP SPIKE"
        elif up > 0.80:
            flag = "HIGH-PROBABILITY OWNERSHIP SPIKE"
        elif down > 0.95:
            flag = "VERY HIGH-CONFIDENCE OWNERSHIP DROP"
        elif down > 0.80:
            flag = "HIGH-PROBABILITY OWNERSHIP DROP"
        out[k] = {"p_up": up, "p_down": down, "flag": flag}
    return out


def info_quality(det: dict) -> tuple[str, list[str]]:
    why = []
    if det.get("actual") is not None:
        return "VERY HIGH", ["Actual contest ownership available"]
    m = det.get("models") or {}
    a, b = m.get("A") or {}, m.get("B") or {}
    if det.get("news", "") and det["news"].startswith("Confirmed news"):
        return "HIGH", ["Confirmed injury news"]
    k = a.get("k", 0) if a else 0
    scored = sum(1 for p in (a.get("parts") or []) if p["scored"]) if a else 0
    na = a.get("n", 0) if a else 0
    nb = b.get("n", 0) if b else 0
    users = b.get("users", 0) if b else 0
    disp = a.get("dispersion", 0) if a else 0
    if k:
        why.append(f"{k} source{'s' if k != 1 else ''} ({scored} with a graded history), effective N {na:.0f}")
    if users:
        why.append(f"{users} crowd contributor{'s' if users != 1 else ''}, effective N {nb:.0f}")
    if not k and not users:
        return "VERY LOW", ["Behavioral model only (no ownership sources or crowd data yet)"]
    if disp > DISPERSION_FLAG:
        return "LOW", why + [f"Sources disagree (SD {disp * 100:.1f} pts)"]
    if (k >= 2 and na >= 50 and nb >= 20) or (k >= 3 and na >= 80):
        return "HIGH", why
    if k >= 1 or nb >= 20:
        return "MEDIUM", why
    return "LOW", why


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
