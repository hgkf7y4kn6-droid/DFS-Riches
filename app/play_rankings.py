"""Cash and GPP play rankings plus field ownership, for the app's Cash and GPP tabs.

Strength of play is scored within each position from z-scored components:

  Cash  (top 5 QB, 10 RB, 10 WR, 5 TE)
    P(median-to-high outcome)  P(points >= 2.5x salary/$1k), the usual cash
                               target, under each player's two-piece normal
                               (spread from his floor and ceiling)   x 0.35
    floor safety               15th-percentile outcome                x 0.25
    salary                     projected points per $1k               x 0.20
    game environment           team implied total and the game's
                               environment score                      x 0.20
    minus a Questionable penalty (cash can't absorb a late scratch)

  GPP   (same counts)
    P(ceiling outcome)         P(points >= the position's tournament-
                               winning score: QB 28, RB/WR 24, TE 18,
                               DST 14)                                  x 0.40
    ownership leverage         ceiling probability relative to
                               large-field ownership                  x 0.25
    salary                     ceiling per $1k                         x 0.15
    game environment                                                   x 0.20

Tags (per player, per contest), among the position's relevant players
(projected 5+ points, DST 3+):
  cash  Prioritize  a top cash play at his position (the ranked list;
                    top 3 DSTs)
        Fade        expected cash ownership >= 10% on a bottom-half cash
                    play, or Questionable
  GPP   Prioritize  a top GPP play whose ceiling odds outrun his
                    ownership (positive leverage)
        Fade        12%+ large-field ownership with leverage well below
                    the position's average (owned like a top play
                    without the ceiling odds)
  everything else is Neutral.

GPP also returns two cross-position lists for the tab's horizontal cards:
  chalk     the 10 highest large-field ownerships among relevant players
  leverage  the 10 best ceiling-odds-per-ownership ratios (P(ceiling) /
            large-field ownership) among relevant players with real ceiling
            odds (P(ceiling) >= 12%) -- the pivots off the chalk
"""
from __future__ import annotations

import numpy as np

from app import field_ownership as fo

TOP_N = {"QB": 5, "RB": 10, "WR": 10, "TE": 5}
CASH_TARGET_X = 2.5
GPP_CEILING_SCORE = {"QB": 28.0, "RB": 24.0, "WR": 24.0, "TE": 18.0, "DST": 14.0}
TAG_TOP = {**TOP_N, "DST": 3}
RELEVANT_PROJ = {"QB": 5.0, "RB": 5.0, "WR": 5.0, "TE": 5.0, "DST": 3.0}
CROSS_N = 10
ROLE_SHIFTS_N = 40
LEVERAGE_MIN_CEILING = 0.12


def _z(vals: list[float]) -> list[float]:
    a = np.array(vals, dtype=float)
    sd = a.std()
    return list((a - a.mean()) / sd) if sd > 1e-9 else [0.0] * len(vals)


def _round(x, n=2):
    return None if x is None else round(float(x), n)


def build(table: list[dict], games: list[dict], contest: str, season: int, week: int, slate_id: str) -> dict:
    """contest "cash" -> cash rankings + cash ownership; "gpp" -> GPP rankings + small/large-field ownership."""
    rows = fo.engineer(table, games)
    env = fo.env_by_team(games)
    fo.save_features(season, week, slate_id, rows)
    own_contests = ["cash"] if contest == "cash" else ["small_gpp", "large_gpp"]
    owns = {c: fo.contest_ownership(rows, c) for c in own_contests}
    lead_own = owns["cash" if contest == "cash" else "large_gpp"]["own"]

    for i, r in enumerate(rows):
        sd_low, sd_high = fo.player_sd(r["final"], r["floor"], r["ceiling"])
        r["p_cash"] = fo.p_at_least(CASH_TARGET_X * r["salary_k"], r["final"], sd_low, sd_high)
        r["p_ceiling"] = fo.p_at_least(GPP_CEILING_SCORE[r["position"]], r["final"], sd_low, sd_high)
        r["env"] = env.get(r["team"], 0.0)
        r["ceiling_value"] = r["ceiling"] / r["salary_k"]
        for c in own_contests:
            r[f"own_{c}"] = float(owns[c]["own"][i])
            r[f"models_{c}"] = {k: round(float(v[i]) * 100, 1) for k, v in owns[c]["components"].items()}
        r["lead_own"] = float(lead_own[i])

    out_players, rankings = [], {}
    for pos in fo.POSITIONS:
        grp = [r for r in rows if r["position"] == pos]
        if not grp:
            continue
        env_z = [0.6 * a + 0.4 * b for a, b in zip(_z([r["implied"] for r in grp]), _z([r["env"] for r in grp]))]
        if contest == "cash":
            parts = {
                "p_hit": _z([r["p_cash"] for r in grp]),
                "floor": _z([r["floor"] for r in grp]),
                "salary": _z([r["value"] for r in grp]),
                "env": env_z,
            }
            w = {"p_hit": 0.35, "floor": 0.25, "salary": 0.20, "env": 0.20}
        else:
            own_share = np.array([max(r["lead_own"], 0.005) for r in grp])
            lev = np.log(np.array([max(r["p_ceiling"], 1e-4) for r in grp]) / own_share)
            parts = {
                "p_hit": _z([r["p_ceiling"] for r in grp]),
                "leverage": _z(list(lev)),
                "salary": _z([r["ceiling_value"] for r in grp]),
                "env": env_z,
            }
            w = {"p_hit": 0.40, "leverage": 0.25, "salary": 0.15, "env": 0.20}
        for j, r in enumerate(grp):
            score = sum(w[k] * parts[k][j] for k in w)
            if contest == "cash" and r.get("injury") == "Q":
                score -= 0.5
            r["score"] = score
            r["parts"] = {k: round(float(parts[k][j]), 2) for k in w}
        ranked = sorted(grp, key=lambda r: -r["score"])
        relevant = [r for r in ranked if r["final"] >= RELEVANT_PROJ[pos]]
        score_pct = dict(zip((r["id"] for r in relevant), fo.pct_rank([r["score"] for r in relevant])))
        for r in grp:
            rank = next((k for k, x in enumerate(ranked, 1) if x is r), None)
            r["tag"], r["tag_reason"] = _tag(contest, r, rank <= TAG_TOP[pos], score_pct.get(r["id"]))
        if pos in TOP_N:
            rankings[pos] = [_player(r, contest, own_contests, rank) for rank, r in enumerate(ranked[: TOP_N[pos]], 1)]
        out_players += [_player(r, contest, own_contests) for r in ranked]

    out_players.sort(key=lambda p: -(p["ownership"][own_contests[-1]] or 0))
    # Players whose roles are genuinely shifting (app.roles), biggest moves first.
    shifting = [r for r in rows if (r.get("usage_trend") or {}).get("genuine")]
    shifting.sort(key=lambda r: -abs(r["usage_trend"]["snap_delta"]))
    extra = {"role_shifts": [_player(r, contest, own_contests) for r in shifting[:ROLE_SHIFTS_N]]}
    if contest == "gpp":
        relevant = [r for r in rows if r["final"] >= RELEVANT_PROJ[r["position"]]]
        chalk = sorted(relevant, key=lambda r: -r["lead_own"])[:CROSS_N]
        pivots = sorted((r for r in relevant if r["p_ceiling"] >= LEVERAGE_MIN_CEILING),
                        key=lambda r: -_leverage_ratio(r))[:CROSS_N]
        extra |= {"chalk": [_player(r, contest, own_contests, k) for k, r in enumerate(chalk, 1)],
                 "leverage": [_player(r, contest, own_contests, k) for k, r in enumerate(pivots, 1)]}
    return {
        "contest": contest,
        "season": season,
        "week": week,
        "slate_id": slate_id,
        "rankings": rankings,
        "players": out_players,
        "ownership_models": {c: {"label": fo.CONTESTS[c]["label"], "weights": owns[c]["weights"],
                                 "price_per_k": owns[c]["price_per_k"], "training": owns[c]["training"],
                                 "simulated_lineups": fo.N_SIMS} for c in own_contests},
        **extra,
    }


def _leverage_ratio(r: dict) -> float:
    """Ceiling odds per unit of large-field ownership (1.0 = owned in line with the ceiling odds)."""
    return r["p_ceiling"] / max(r["lead_own"], 0.005)


def _tag(contest: str, r: dict, top: bool, score_pct: float | None) -> tuple[str, str]:
    if score_pct is None:
        return "neutral", "Too small a projected role to matter"
    if contest == "cash":
        if r.get("injury") == "Q":
            return "fade", "Questionable: a late scratch zeroes a cash lineup"
        if top:
            return "prioritize", "A top cash play at his position: floor, hit rate, price and game environment"
        if r["lead_own"] >= 0.10 and score_pct < 0.5:
            return "fade", f"{r['lead_own']:.0%} expected cash ownership on a bottom-half cash play"
        return "neutral", "Playable, but not a standout cash spot"
    lev = r["parts"]["leverage"]
    if top and lev > 0:
        return "prioritize", f"Top GPP play whose ceiling odds outrun his {r['lead_own']:.0%} ownership"
    if r["lead_own"] >= 0.12 and lev <= -0.5:
        return "fade", f"Owned like a top play ({r['lead_own']:.0%}) without the ceiling odds to match"
    return "neutral", "Ownership roughly matches his ceiling odds"


def _player(r: dict, contest: str, own_contests: list[str], rank: int | None = None) -> dict:
    return {
        "rank": rank,
        "id": r["id"],
        "name": r["name"],
        "position": r["position"],
        "team": r["team"],
        "opponent": r["opponent"],
        "salary": r["salary"],
        "injury": r.get("injury"),
        "role": r.get("role"),
        "snap_pct": r.get("snap_pct"),
        "usage_trend": r.get("usage_trend"),
        "team_share": r.get("team_share"),
        "final": _round(r["final"]),
        "floor": _round(r["floor"]),
        "ceiling": _round(r["ceiling"]),
        "value": _round(r["value"]),
        "implied": _round(r["implied"], 1),
        "p_hit": _round(r["p_cash"] if contest == "cash" else r["p_ceiling"], 3),
        "score": _round(r["score"], 3),
        "parts": r["parts"],
        "leverage_ratio": _round(_leverage_ratio(r)) if contest == "gpp" else None,
        "ownership": {c: _round(r[f"own_{c}"] * 100, 1) for c in own_contests},
        # each model's own estimate (percent) before the blend
        "ownership_models": {c: r[f"models_{c}"] for c in own_contests},
        "tag": r["tag"],
        "tag_reason": r["tag_reason"],
        "features": {
            "value_ratio": _round(r["value"]),
            "position_value_rank": int(r["pos_value_rank"]),
            "salary_delta_vs_average": round(r["salary_delta_k"] * 1000),
            "team_implied_total": _round(r["implied"], 1),
            "position_scarcity_index": _round(r["scarcity"], 3),
            "is_backup_injury_start": bool(r["backup"]),
        },
    }
