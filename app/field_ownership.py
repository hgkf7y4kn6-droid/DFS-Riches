"""Contest-specific field ownership (cash, small-field GPP, large-field GPP)
from four models, blended in logit space.

  1. Field simulation (the gold standard). 10,000 opponent lineups per
     contest, each from a basic optimizer run on projections randomized by
     each player's own standard deviation (from his floor/ceiling), with a
     shared team-level shock so the field stacks. The optimizer is a
     Lagrangian relaxation of the salary cap: every simulated entrant picks
     the best QB, 2 RB, 3 WR, TE, DST and FLEX by (points - price x salary),
     and the price of $1k is binary-searched per lineup until the lineup
     fits under $50,000. Ownership = how often each player appears. Contest
     types differ in what the field optimizes and how much it disagrees:
       cash         median + floor, little disagreement, light stacking
       small GPP    median + some ceiling, moderate disagreement
       large GPP    median + more ceiling, wide disagreement, heavier stacks
  2. Bradley-Terry / Luce choice model. The slate is a marketplace: within
     a position each player has a strength s = exp(utility) built from
     projection, value, implied total, ceiling/floor and the salary priced at
     the simulation's own shadow price of $1k; P(A picked over B) =
     s_A / (s_A + s_B), and a position's slots are shared in proportion to
     s (Luce's choice axiom), so ownership sums to the slot count.
  3. Fractional logit (Papke-Wooldridge quasi-likelihood). Ownership is a
     share in [0, 1], so it's fit on the logit scale with a Bernoulli
     quasi-likelihood -- never predicting below 0% or above 100% -- on the
     engineered features. Trained on stored actual ownership; untrained
     (weight 0) until enough slates have actual results.
  4. Gradient-boosted trees (LightGBM). Same features and training data;
     used once enough history exists and LightGBM is installed.

Engineered features (per player, slate-relative): Salary, Projected_Points,
Value_Ratio (points per $1k), Position_Value_Rank, Salary_Delta_vs_Average
(vs the position's mean), Team_Implied_Total, Position_Scarcity_Index (how
few viable value plays the position has), Is_Backup_Injury_Start (the
position's top-salaried teammate is out, so the next man up starts),
Ceiling and Floor.

Every contest's blended ownership is rescaled within each position to the
field's slot count (QB 1, RB 2 + FLEX share, ...), so the numbers add up the
way real ownership does. Engineered features are saved per slate, so once
actual ownership is uploaded the fractional logit and LightGBM models train
on them.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import optimize, special

from app import ownership_store as store

N_SIMS = 10_000
CAP = 50_000
POSITIONS = ("QB", "RB", "WR", "TE", "DST")
FLEX_POS = ("RB", "WR", "TE")
PLAYABLE = {"Healthy", "Q"}
OUT = {"O", "OUT", "D", "IR", "PUP", "NFI", "SUSP"}
MIN_PROJ = 1.0
Z15 = 1.036          # floor/ceiling are the 15th/85th percentiles

# What each contest's field optimizes and how much it disagrees.
CONTESTS = {
    "cash": {"label": "Cash", "ceiling_w": 0.0, "floor_w": 0.35, "noise": 0.2, "team_shock": 0.15, "temp": 1.1,
             "store": ("cash",)},
    "small_gpp": {"label": "Small-field GPP", "ceiling_w": 0.25, "floor_w": 0.0, "noise": 0.45, "team_shock": 0.35,
                  "temp": 0.9, "store": ("se", "3max", "20max")},
    "large_gpp": {"label": "Large-field GPP", "ceiling_w": 0.5, "floor_w": 0.0, "noise": 0.7, "team_shock": 0.5,
                  "temp": 0.75, "store": ("gpp", "150max")},
}
# Bradley-Terry utility weights per contest (on z-scored features), plus the
# salary priced at the simulation's shadow price of $1k.
BT_WEIGHTS = {
    "cash": {"final": 1.0, "value": 0.9, "floor": 0.5, "implied": 0.3, "ceiling": 0.0, "backup": 0.4},
    "small_gpp": {"final": 1.0, "value": 0.7, "floor": 0.1, "implied": 0.35, "ceiling": 0.3, "backup": 0.3},
    "large_gpp": {"final": 0.9, "value": 0.6, "floor": 0.0, "implied": 0.4, "ceiling": 0.5, "backup": 0.3},
}
BLEND = {"sim": 0.55, "bt": 0.25, "frac_logit": 0.12, "gbm": 0.08}   # untrained models drop out; the rest renormalize
FEATURES = ("salary_k", "final", "value", "pos_value_rank", "salary_delta_k", "implied", "scarcity", "backup",
            "ceiling", "floor")
MIN_TRAIN_SLATES = 3
# Fields rarely FLEX a tight end: a TE needs this many more points than an
# RB/WR to take the FLEX slot.
TE_FLEX_PENALTY = 4.0
# Players the simulation considers, per position (by projection + ceiling); the
# rest are long shots the field almost never plays (they still get a
# Bradley-Terry share).
SIM_POOL = {"QB": 24, "RB": 40, "WR": 60, "TE": 24, "DST": 20}
SIM_CHUNK = 2_000
EPS = 1e-4


@dataclass
class Pool:
    players: list[dict]
    pos: np.ndarray        # position per player
    salary: np.ndarray     # dollars
    final: np.ndarray
    floor: np.ndarray
    ceiling: np.ndarray
    sd_low: np.ndarray
    sd_high: np.ndarray
    team_idx: np.ndarray   # index into teams
    teams: list[str]


# ----------------------------------------------------------------- features
def player_sd(final: float, floor: float | None, ceiling: float | None) -> tuple[float, float]:
    """Two-piece normal around the projection: below from the floor, above from the ceiling."""
    lo = (final - floor) / Z15 if floor is not None and floor < final else 0.35 * final + 1
    hi = (ceiling - final) / Z15 if ceiling is not None and ceiling > final else 0.45 * final + 1
    return max(lo, 0.5), max(hi, 0.5)


def p_at_least(target: float, final: float, sd_low: float, sd_high: float) -> float:
    """P(score >= target) under the two-piece normal."""
    sd = sd_high if target >= final else sd_low
    return float(1 - special.ndtr((target - final) / sd))


def implied_by_team(games: list[dict]) -> dict[str, float]:
    out = {}
    for g in games:
        if g.get("away_implied") is not None:
            out[g["away"]] = g["away_implied"]
        if g.get("home_implied") is not None:
            out[g["home"]] = g["home_implied"]
    return out


def env_by_team(games: list[dict]) -> dict[str, float]:
    return {t: g.get("env_score", 0.0) for g in games for t in (g["away"], g["home"])}


def engineer(table: list[dict], games: list[dict]) -> list[dict]:
    """Playable players with the engineered features (slate-relative)."""
    implied = implied_by_team(games)
    # Is_Backup_Injury_Start: the top-salaried player at a team/position is out,
    # so the highest-salaried healthy teammate there starts in his place.
    by_team_pos: dict[tuple, list[dict]] = {}
    for p in table:
        by_team_pos.setdefault((p["team"], p["position"]), []).append(p)
    backups: set[int] = set()
    for (_team, pos), group in by_team_pos.items():
        if pos == "DST":
            continue
        group = sorted(group, key=lambda p: -p["salary"])
        if group and group[0].get("injury") in OUT:
            nxt = next((p for p in group[1:] if p.get("injury") in PLAYABLE), None)
            if nxt is not None:
                backups.add(nxt["id"])

    pool = [p for p in table if p.get("injury", "Healthy") in PLAYABLE and (p.get("final") or 0) >= MIN_PROJ
            and p["salary"] > 0 and p["position"] in POSITIONS]
    rows = []
    for p in pool:
        rows.append({
            **p,
            "salary_k": p["salary"] / 1000,
            "value": p["final"] / (p["salary"] / 1000),
            "implied": implied.get(p["team"], 21.0),
            "backup": 1.0 if p["id"] in backups else 0.0,
            "floor": p.get("floor") if p.get("floor") is not None else 0.6 * p["final"],
            "ceiling": p.get("ceiling") if p.get("ceiling") is not None else 1.6 * p["final"],
        })
    for pos in POSITIONS:
        grp = [r for r in rows if r["position"] == pos]
        if not grp:
            continue
        mean_sal = sum(r["salary_k"] for r in grp) / len(grp)
        order = sorted(grp, key=lambda r: -r["value"])
        for rank, r in enumerate(order, 1):
            r["pos_value_rank"] = float(rank)
            r["salary_delta_k"] = r["salary_k"] - mean_sal
        # Position_Scarcity_Index: field slots for the position per viable value
        # play (value >= 2.5x and a real projection) -- higher = scarcer.
        viable = sum(1 for r in grp if r["value"] >= 2.5 and r["final"] >= (6 if pos != "DST" else 4))
        slots = {"QB": 1, "RB": 2.4, "WR": 3.5, "TE": 1.1, "DST": 1}[pos]
        for r in grp:
            r["scarcity"] = slots / max(viable, 1)
    return rows


def _z(x: np.ndarray) -> np.ndarray:
    sd = x.std()
    return (x - x.mean()) / sd if sd > 1e-9 else np.zeros_like(x)


# --------------------------------------------------------- field simulation
def _pool(rows: list[dict]) -> Pool:
    teams = sorted({r["team"] for r in rows})
    tix = {t: i for i, t in enumerate(teams)}
    sds = [player_sd(r["final"], r["floor"], r["ceiling"]) for r in rows]
    return Pool(
        players=rows,
        pos=np.array([r["position"] for r in rows]),
        salary=np.array([r["salary"] for r in rows], dtype=float),
        final=np.array([r["final"] for r in rows], dtype=float),
        floor=np.array([r["floor"] for r in rows], dtype=float),
        ceiling=np.array([r["ceiling"] for r in rows], dtype=float),
        sd_low=np.array([s[0] for s in sds]),
        sd_high=np.array([s[1] for s in sds]),
        team_idx=np.array([tix[r["team"]] for r in rows]),
        teams=teams,
    )


def _pick(adj: np.ndarray, pool: Pool) -> np.ndarray:
    """Per row of adjusted scores, the best QB, 2 RB, 3 WR, TE, DST and FLEX -> (S, n) 0/1 picks."""
    S, n = adj.shape
    picks = np.zeros((S, n), dtype=bool)
    rows = np.arange(S)[:, None]
    for pos, k in (("QB", 1), ("RB", 2), ("WR", 3), ("TE", 1), ("DST", 1)):
        idx = np.flatnonzero(pool.pos == pos)
        if len(idx) < k:
            continue
        sub = adj[:, idx]
        top = np.argpartition(-sub, k - 1, axis=1)[:, :k] if k < len(idx) else np.tile(np.arange(len(idx)), (S, 1))
        picks[rows, idx[top]] = True
    flex = np.flatnonzero(np.isin(pool.pos, FLEX_POS))
    penalty = np.where(pool.pos[flex] == "TE", TE_FLEX_PENALTY, 0.0)
    sub = np.where(picks[:, flex], -np.inf, adj[:, flex] - penalty[None, :])
    best = np.argmax(sub, axis=1)
    picks[np.arange(S), flex[best]] = True
    return picks


def simulate_field(rows: list[dict], contest: str, n_sims: int = N_SIMS, seed: int = 17) -> tuple[np.ndarray, float]:
    """Fraction of simulated lineups each player appears in, and the median shadow price of $1k."""
    cfg = CONTESTS[contest]
    keep = []
    for pos, k in SIM_POOL.items():
        idx = [i for i, r in enumerate(rows) if r["position"] == pos]
        keep += sorted(idx, key=lambda i: -(rows[i]["final"] + 0.5 * rows[i]["ceiling"]))[:k]
    keep.sort()
    pool = _pool([rows[i] for i in keep])
    rng = np.random.default_rng(seed)
    counts = np.zeros(len(keep))
    prices = []
    # Simulated in chunks so peak memory stays small on a 512 MB host.
    for start in range(0, n_sims, SIM_CHUNK):
        c, hi = _simulate_chunk(pool, cfg, rng, min(SIM_CHUNK, n_sims - start))
        counts += c
        prices.append(hi)
    own = np.zeros(len(rows))
    own[keep] = counts / n_sims
    return own, float(np.median(np.concatenate(prices)))


def _simulate_chunk(pool: Pool, cfg: dict, rng: np.random.Generator, S: int) -> tuple[np.ndarray, np.ndarray]:
    """S simulated entrants: per-player pick counts and each entrant's shadow price of $1k."""
    n = len(pool.final)
    base = pool.final + cfg["ceiling_w"] * (pool.ceiling - pool.final) - cfg["floor_w"] * (pool.final - pool.floor)
    # Player noise from his own spread (upside skew above the projection), plus a
    # team shock shared by teammates so the field stacks.
    z = rng.standard_normal((S, n))
    sd = np.where(z >= 0, pool.sd_high, pool.sd_low)
    team_z = rng.standard_normal((S, len(pool.teams)))[:, pool.team_idx]
    shock = cfg["team_shock"] * team_z * (pool.sd_high + pool.sd_low) / 2
    scores = base[None, :] + cfg["noise"] * (np.sqrt(1 - cfg["team_shock"] ** 2) * z * sd) + cfg["noise"] * shock
    del z, sd, team_z, shock
    sal_k = pool.salary / 1000

    lo = np.zeros(S)
    hi = np.full(S, 12.0)          # points per $1k: high enough that any lineup fits
    for _ in range(15):
        mid = (lo + hi) / 2
        picks = _pick(scores - mid[:, None] * sal_k[None, :], pool)
        fits = (picks * pool.salary[None, :]).sum(axis=1) <= CAP
        hi = np.where(fits, mid, hi)
        lo = np.where(fits, lo, mid)
    picks = _pick(scores - hi[:, None] * sal_k[None, :], pool)
    return picks.sum(axis=0), hi


# --------------------------------------------------------- Bradley-Terry
def bradley_terry(rows: list[dict], contest: str, price_per_k: float, slot_totals: dict[str, float]) -> np.ndarray:
    """Luce-choice shares within each position, scaled to the position's slot total."""
    w = BT_WEIGHTS[contest]
    out = np.zeros(len(rows))
    for pos in POSITIONS:
        idx = [i for i, r in enumerate(rows) if r["position"] == pos]
        if not idx:
            continue
        g = [rows[i] for i in idx]
        f = {k: _z(np.array([r[k] for r in g], dtype=float)) for k in ("final", "value", "floor", "implied", "ceiling")}
        surplus = _z(np.array([r["final"] - price_per_k * r["salary_k"] for r in g]))   # points above the field's $1k price
        util = sum(w[k] * f[k] for k in f) + w["backup"] * np.array([r["backup"] for r in g]) + 0.6 * surplus
        # Defenses are closer substitutes than skill players, so the field spreads out more there.
        temp = CONTESTS[contest]["temp"] * (0.6 if pos == "DST" else 1.0)
        s = np.exp(temp * (util - util.max()))   # strength; P(A over B) = s_A / (s_A + s_B)
        out[idx] = slot_totals.get(pos, 1.0) * s / s.sum()
    return out


def bt_head_to_head(strength_a: float, strength_b: float) -> float:
    return strength_a / (strength_a + strength_b)


# ------------------------------------------------- trained models (history)
def _matrix(rows: list[dict]) -> np.ndarray:
    return np.array([[float(r.get(k, 0.0)) for k in FEATURES] for r in rows])


def training_rows(contest: str) -> tuple[np.ndarray, np.ndarray, int]:
    """Engineered features saved before lock, joined to actual ownership, from every slate that has both."""
    X, y, slates = [], [], 0
    wanted = CONTESTS[contest]["store"]
    for path in store.all_slate_files():
        try:
            data = store.load(*_parse_slate_path(path))
        except Exception:
            continue
        feats = data.get("engineered_features") or {}
        actual = {}
        for o in data.get("observations", []):
            if o.get("kind") == "actual" and o.get("contest") in wanted:
                actual[o["key"]] = o["pct"] / 100
        if not feats or not actual:
            continue
        hit = 0
        for key, f in feats.items():
            if key in actual:
                X.append([float(f.get(k, 0.0)) for k in FEATURES])
                y.append(min(max(actual[key], 0.0), 1.0))
                hit += 1
        slates += 1 if hit else 0
    return np.array(X), np.array(y), slates


def _parse_slate_path(path) -> tuple[int, int, str]:
    stem = path.stem                      # "2026_w4_classic_sunday"
    season, rest = stem.split("_w", 1)
    week, slate = rest.split("_", 1)
    return int(season), int(week), slate


def fit_fractional_logit(X: np.ndarray, y: np.ndarray, l2: float = 1.0) -> dict | None:
    """Papke-Wooldridge fractional logit: maximize sum y log p + (1-y) log(1-p), p = expit(Xb)."""
    if len(y) < 50:
        return None
    mu, sd = X.mean(axis=0), X.std(axis=0) + 1e-9
    Z = np.hstack([np.ones((len(X), 1)), (X - mu) / sd])

    def loss(b):
        p = np.clip(special.expit(Z @ b), EPS, 1 - EPS)
        return -(y * np.log(p) + (1 - y) * np.log(1 - p)).sum() + l2 * (b[1:] ** 2).sum()

    def grad(b):
        p = special.expit(Z @ b)
        g = Z.T @ (p - y)
        g[1:] += 2 * l2 * b[1:]
        return g

    res = optimize.minimize(loss, np.zeros(Z.shape[1]), jac=grad, method="L-BFGS-B")
    return {"coef": res.x.tolist(), "mu": mu.tolist(), "sd": sd.tolist(), "n": int(len(y))}


def predict_fractional_logit(model: dict, X: np.ndarray) -> np.ndarray:
    Z = np.hstack([np.ones((len(X), 1)), (X - np.array(model["mu"])) / np.array(model["sd"])])
    return special.expit(Z @ np.array(model["coef"]))


def fit_gbm(X: np.ndarray, y: np.ndarray):
    """LightGBM regressor on logit(ownership); None without enough data or without LightGBM."""
    if len(y) < 200:
        return None
    try:
        import lightgbm as lgb
    except Exception:
        return None
    target = special.logit(np.clip(y, 0.002, 0.998))
    params = {"objective": "regression", "learning_rate": 0.05, "num_leaves": 15, "min_data_in_leaf": 20,
              "bagging_fraction": 0.8, "bagging_freq": 1, "feature_fraction": 0.8, "verbose": -1, "seed": 7}
    return lgb.train(params, lgb.Dataset(X, label=target, feature_name=list(FEATURES)), num_boost_round=300)


_TRAINED: dict[tuple, dict] = {}


def trained_models(contest: str) -> dict:
    """Fractional logit + LightGBM for a contest, refit when the stored data changes."""
    version = store.data_version()
    cached = _TRAINED.get((contest, version))
    if cached is not None:
        return cached
    X, y, slates = training_rows(contest)
    out = {"slates": slates, "rows": int(len(y)), "frac_logit": None, "gbm": None}
    if slates >= MIN_TRAIN_SLATES:
        out["frac_logit"] = fit_fractional_logit(X, y)
        out["gbm"] = fit_gbm(X, y)
    for stale in [k for k in _TRAINED if k[1] != version]:
        del _TRAINED[stale]
    _TRAINED[(contest, version)] = out
    return out


# ------------------------------------------------------------------ blend
def _slot_totals(sim: np.ndarray, rows: list[dict]) -> dict[str, float]:
    return {pos: float(sum(sim[i] for i, r in enumerate(rows) if r["position"] == pos)) for pos in POSITIONS}


def _rescale(own: np.ndarray, rows: list[dict], totals: dict[str, float]) -> np.ndarray:
    out = own.copy()
    for pos in POSITIONS:
        idx = [i for i, r in enumerate(rows) if r["position"] == pos]
        s = own[idx].sum()
        if idx and s > 0:
            out[idx] = own[idx] * totals[pos] / s
    return np.clip(out, 0.0, 1.0)


def contest_ownership(rows: list[dict], contest: str, n_sims: int = N_SIMS) -> dict:
    """Blended field ownership for one contest type, with each model's number."""
    sim, price = simulate_field(rows, contest, n_sims)
    totals = _slot_totals(sim, rows)
    bt = bradley_terry(rows, contest, price, totals)
    comps = {"sim": sim, "bt": bt}
    trained = trained_models(contest)
    X = _matrix(rows)
    if trained["frac_logit"]:
        comps["frac_logit"] = _rescale(predict_fractional_logit(trained["frac_logit"], X), rows, totals)
    if trained["gbm"] is not None:
        comps["gbm"] = _rescale(special.expit(trained["gbm"].predict(X)), rows, totals)
    weights = {k: BLEND[k] for k in comps}
    total_w = sum(weights.values())
    logit = sum(weights[k] / total_w * special.logit(np.clip(v, EPS, 1 - EPS)) for k, v in comps.items())
    blended = _rescale(special.expit(logit), rows, totals)
    return {
        "own": blended,
        "components": comps,
        "weights": {k: round(w / total_w, 3) for k, w in weights.items()},
        "price_per_k": round(price, 3),
        "training": {"slates": trained["slates"], "rows": trained["rows"],
                     "frac_logit": bool(trained["frac_logit"]), "gbm": trained["gbm"] is not None},
    }


def save_features(season: int, week: int, slate_id: str, rows: list[dict]) -> None:
    """Keeps the engineered features with the slate so they train the models once actuals arrive."""
    feats = {store.player_key(r["name"], r["team"], r["position"]): {k: round(float(r[k]), 4) for k in FEATURES}
             for r in rows}
    try:
        with store._lock:
            data = store.load(season, week, slate_id)
            data["engineered_features"] = feats
            store.save(data)
    except Exception:
        pass   # read-only disk: ownership still computes, it just won't be trained on later


def pct_rank(values: list[float]) -> list[float]:
    """Percentile rank 0-1 (ties averaged)."""
    n = len(values)
    if n <= 1:
        return [1.0] * n
    order = sorted(range(n), key=lambda i: values[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        r = (i + j) / 2 / (n - 1)
        for k in range(i, j + 1):
            ranks[order[k]] = r
        i = j + 1
    return ranks
