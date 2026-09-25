"""Field-lineup simulator for duplication (SIMULATED numbers).

A field lineup is drawn slot by slot from the posterior ownership, with the
correlations real fields show:

  QB        drawn in proportion to QB ownership
  RB/WR/TE  drawn in proportion to ownership, tilted up for the QB's own
            pass catchers (stack), the opposing team's players (bring-back)
  FLEX      from RB/WR/TE, split by the position's FLEX share
  DST       tilted up when the lineup's RB is on that team (RB/DST
            correlation) and down when it faces the lineup's QB
  valid     nine different players, salary between the field's minimum
            spend and the $50,000 cap (invalid draws are rejected)

Each batch of lineups uses a fresh draw from the posterior, so ownership
uncertainty flows into duplication. Because the sampler is explicit, the
exact probability that a random field entry equals a given lineup is
computable: P(L) = P(QB) x 2! prod P(RB) x 3! prod P(WR) x P(TE) x P(FLEX) x
P(DST | RBs), summed over which player sits in FLEX, averaged over posterior
draws, divided by P(valid). Expected duplicates = (contest size - 1) x P(L).

The tilts and minimum spend are assumptions until actual field lineups
(DraftKings contest standings) have been uploaded; then
app.ownership_learning fits them.
"""
from __future__ import annotations

import math

import numpy as np

FIELD_DEFAULTS = {"stack": 1.5, "bring_back": 0.3, "rb_dst": 0.4, "dst_vs_qb": 0.3, "min_salary": 46000}
CAP = 50000
BATCHES = 20


class FieldModel:
    def __init__(self, players: list[dict], alpha: np.ndarray, beta: np.ndarray, flex: dict[str, float],
                 params: dict | None = None, seed: int = 3):
        self.p = players
        self.n = len(players)
        self.params = {**FIELD_DEFAULTS, **(params or {})}
        self.flex = flex
        self.rng = np.random.default_rng(seed)
        self.pos = np.array([p["position"] for p in players])
        self.team = np.array([p["team"] for p in players])
        self.opp = np.array([p["opponent"] for p in players])
        self.salary = np.array([p["salary"] for p in players], dtype=float)
        self.index = {p["key"]: i for i, p in enumerate(players)}
        self.theta = self.rng.beta(alpha, beta, size=(BATCHES, self.n))
        self.idx = {pos: np.where(self.pos == pos)[0] for pos in ("QB", "RB", "WR", "TE", "DST")}

    # ---------------------------------------------------------- weights
    def slot_weights(self, theta: np.ndarray, q: int) -> dict[str, np.ndarray]:
        pr = self.params
        qt, qo = self.team[q], self.opp[q]
        w = {}
        for pos in ("RB", "WR", "TE"):
            ids = self.idx[pos]
            tilt = np.ones(len(ids))
            if pos in ("WR", "TE"):
                tilt[self.team[ids] == qt] *= 1 + pr["stack"]
            tilt[self.team[ids] == qo] *= 1 + pr["bring_back"]
            w[pos] = theta[ids] * tilt
        flex_parts = []
        for pos in ("RB", "WR", "TE"):
            tot = w[pos].sum()
            flex_parts.append(w[pos] / tot * self.flex.get(pos, 0.0) if tot > 0 else w[pos] * 0)
        w["FLEX"] = np.concatenate(flex_parts)
        dst = self.idx["DST"]
        dw = theta[dst].copy()
        dw[self.opp[dst] == qt] *= pr["dst_vs_qb"]
        w["DST"] = dw
        return {k: v / v.sum() if v.sum() > 0 else v for k, v in w.items()}

    # ------------------------------------------------------------- sample
    def sample(self, k: int = 10000, max_rounds: int = 8) -> tuple[list[tuple], float, np.ndarray]:
        """Draw until k valid lineups (or max_rounds x k attempts): (accepted lineups as
        sorted index tuples, P(valid), simulated ownership per player)."""
        accepted, total = [], 0
        counts = np.zeros(self.n)
        per_batch = max(1, k // BATCHES)
        qb_ids = self.idx["QB"]
        flex_ids = np.concatenate([self.idx["RB"], self.idx["WR"], self.idx["TE"]])
        rounds = 0
        while len(accepted) < k and rounds < max_rounds:
            rounds += 1
            total = self._round(accepted, counts, total, per_batch, qb_ids, flex_ids)
        p_valid = len(accepted) / total if total else 0.0
        sim_own = counts / max(1, len(accepted))
        return accepted, p_valid, sim_own

    def _round(self, accepted, counts, total, per_batch, qb_ids, flex_ids) -> int:
        for b in range(BATCHES):
            theta = self.theta[b]
            pq = theta[qb_ids] / theta[qb_ids].sum()
            qs = self.rng.choice(qb_ids, size=per_batch, p=pq)
            for q in np.unique(qs):
                m = int((qs == q).sum())
                w = self.slot_weights(theta, q)
                rb = self.idx["RB"][self.rng.choice(len(self.idx["RB"]), size=(m, 2), p=w["RB"])]
                wr = self.idx["WR"][self.rng.choice(len(self.idx["WR"]), size=(m, 3), p=w["WR"])]
                te = self.idx["TE"][self.rng.choice(len(self.idx["TE"]), size=(m, 1), p=w["TE"])]
                fx = flex_ids[self.rng.choice(len(flex_ids), size=(m, 1), p=w["FLEX"])]
                dst_ids = self.idx["DST"]
                rbs = np.concatenate([rb, np.where(self.pos[fx] == "RB", fx, -1)], axis=1)
                rb_teams = np.where(rbs >= 0, self.team[np.maximum(rbs, 0)], "")
                match = (rb_teams[:, :, None] == self.team[dst_ids][None, None, :]).sum(axis=1)
                dw = w["DST"][None, :] * (1 + self.params["rb_dst"] * match)
                dw = dw / dw.sum(axis=1, keepdims=True)
                u = self.rng.random((m, 1))
                dst = dst_ids[(np.cumsum(dw, axis=1) < u).sum(axis=1).clip(max=len(dst_ids) - 1)][:, None]
                lus = np.concatenate([np.full((m, 1), q), rb, wr, te, fx, dst], axis=1)
                total += m
                srt = np.sort(lus, axis=1)
                distinct = (np.diff(srt, axis=1) != 0).all(axis=1)
                sal = self.salary[lus].sum(axis=1)
                ok = distinct & (sal <= CAP) & (sal >= self.params["min_salary"])
                for row in srt[ok]:
                    accepted.append(tuple(int(x) for x in row))
                    counts[row] += 1
        return total

    # ------------------------------------------------------ exact P(L)
    def lineup_prob(self, lineup: list[int], theta: np.ndarray) -> float:
        qs = [i for i in lineup if self.pos[i] == "QB"]
        if len(qs) != 1:
            return 0.0
        q = qs[0]
        w = self.slot_weights(theta, q)
        pos_index = {pos: {int(pid): j for j, pid in enumerate(self.idx[pos])} for pos in ("RB", "WR", "TE", "DST")}
        flex_index = {int(pid): j for j, pid in enumerate(np.concatenate([self.idx["RB"], self.idx["WR"], self.idx["TE"]]))}
        groups = {pos: [i for i in lineup if self.pos[i] == pos] for pos in ("RB", "WR", "TE", "DST")}
        if len(groups["DST"]) != 1:
            return 0.0
        pq = theta[self.idx["QB"]]
        p_qb = theta[q] / pq.sum()
        need = {"RB": 2, "WR": 3, "TE": 1}
        extra = [pos for pos in need if len(groups[pos]) == need[pos] + 1]
        if len(extra) != 1 or any(len(groups[pos]) < need[pos] for pos in need):
            return 0.0
        d = groups["DST"][0]
        rb_teams = [self.team[i] for i in groups["RB"]]
        dst_ids = self.idx["DST"]
        match = np.array([sum(1 for t in rb_teams if t == self.team[x]) for x in dst_ids])
        dw = w["DST"] * (1 + self.params["rb_dst"] * match)
        p_dst = dw[pos_index["DST"][d]] / dw.sum()
        total = 0.0
        for f in groups[extra[0]]:
            prod = w["FLEX"][flex_index[f]]
            for pos, k in need.items():
                members = [i for i in groups[pos] if not (pos == extra[0] and i == f)]
                prod *= math.factorial(k) * np.prod([w[pos][pos_index[pos][i]] for i in members])
            total += prod
        return float(p_qb * total * p_dst)

    def expected_prob(self, lineup: list[int]) -> float:
        return float(np.mean([self.lineup_prob(lineup, self.theta[b]) for b in range(BATCHES)]))


def duplication(model: FieldModel, lineups: dict[str, list[str]], contest_size: int, sims: int = 5000,
                percentile_sample: int = 1500) -> dict:
    accepted, p_valid, sim_own = model.sample(sims)
    if not accepted or p_valid <= 0:
        return {"error": "The simulated field produced no valid lineups", "lineups": {}}
    mean_theta = model.theta.mean(axis=0)
    rng = np.random.default_rng(5)
    sample_idx = rng.choice(len(accepted), size=min(percentile_sample, len(accepted)), replace=False)
    field_probs = np.array([model.lineup_prob(list(accepted[i]), mean_theta) for i in sample_idx])
    acc_sets = [set(a) for a in accepted]
    out = {}
    for label, keys in lineups.items():
        ids = [model.index.get(k) for k in keys]
        if any(i is None for i in ids):
            out[label] = {"error": "Lineup has a player outside the simulated field pool"}
            continue
        p = model.expected_prob(ids) / p_valid
        e_dup = (contest_size - 1) * p
        s = set(ids)
        overlaps = np.array([len(s & a) for a in acc_sets])
        p_mean = model.lineup_prob(ids, mean_theta) / p_valid
        out[label] = {
            "p_lineup": p, "expected_duplicates": e_dup, "p_duplicated": 1 - math.exp(-e_dup),
            "expected_share_5": float((overlaps >= 5).mean() * (contest_size - 1)),
            "expected_share_6": float((overlaps >= 6).mean() * (contest_size - 1)),
            "expected_share_7": float((overlaps >= 7).mean() * (contest_size - 1)),
            "uniqueness_pct": float((field_probs > p_mean * p_valid).mean() * 100),
        }
    return {"lineups": out, "p_valid": p_valid, "simulated_lineups": len(accepted), "sim_own": sim_own,
            "contest_size": contest_size, "params": model.params}
