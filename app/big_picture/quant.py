"""Betting math and the independent game model.

Everything here is deterministic: the report's agents read these numbers and
never produce their own. The game model:

* Each team's expected points = league points per team + K x (its offense's
  EPA/play above average + the opposing defense's EPA/play allowed above
  average) x its expected plays, +/- half the home-field edge, times the
  weather's scoring multiplier. EPA comes from app.trenches (competitive plays,
  this season with last season blended in as a prior).
* Final margin and combined score are treated as independent normals around
  the model's means (SD 13.5 each, roughly the NFL's historical spread of
  results around the closing line), so each team's score has SD ~9.5. The
  margin distribution is discretized to whole points with extra weight on the
  key numbers (3, 7, ...) and almost none on a tie; that gives push odds on
  whole-number lines.
* The market is a strong prior: a side's "blended" win probability mixes the
  model with the no-vig DraftKings price (BLEND_MODEL = model weight), and only
  the blended expected value can rate an edge as strong.
"""
from __future__ import annotations

import math

import numpy as np

SD_MARGIN = 13.5
SD_TOTAL = 13.5
SD_TEAM = 9.5
HOME_EDGE = 1.6            # points, split +/- half between the teams
K_EPA = 0.35               # points per (EPA/play above average x plays): fit on 2026 Weeks 2-5 (history.backtest)
BLEND_MODEL = 0.35         # model weight when mixing with the no-vig market probability
SHOOTOUT_POINTS = 50       # a "shootout": at least this many combined points
BOTH_TEAMS_POINTS = 24     # "both teams score big": each team reaches this

# Extra weight on NFL key margins (multiplies the smooth normal's mass at that
# exact margin, either team). An approximation of the long-run frequencies.
KEY_MARGINS = {0: 0.08, 1: 0.9, 2: 0.9, 3: 2.1, 4: 1.15, 6: 1.15, 7: 1.5, 8: 1.05, 10: 1.2, 14: 1.15, 17: 1.05}


# ------------------------------------------------------------------ odds
def american(value) -> int | None:
    """An American price from DraftKings' text ("−110", "+150") or a number."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    s = str(value).strip().replace("−", "-").replace("+", "")
    if s.upper() == "EVEN":
        return 100
    try:
        return int(float(s))
    except ValueError:
        return None


def implied(odds: int) -> float:
    """Implied probability of an American price (the break-even win rate when there's no push)."""
    return abs(odds) / (abs(odds) + 100) if odds < 0 else 100 / (odds + 100)


def profit(odds: int) -> float:
    """Net profit per 1 unit risked when the bet wins."""
    return odds / 100 if odds > 0 else 100 / abs(odds)


def no_vig(odds_a: int, odds_b: int) -> tuple[float, float]:
    """Both sides' probabilities with the bookmaker's margin removed (proportional method)."""
    a, b = implied(odds_a), implied(odds_b)
    return a / (a + b), b / (a + b)


def ev(p_win: float, p_push: float, odds: int) -> float:
    """Expected net profit per unit risked. A push returns the stake: it adds nothing."""
    p_loss = max(0.0, 1.0 - p_win - p_push)
    return p_win * profit(odds) - p_loss


def fair_american(p: float) -> int | None:
    """The price at which a bet with win probability p (pushes excluded) breaks even."""
    if not 0 < p < 1:
        return None
    return round(-100 * p / (1 - p)) if p >= 0.5 else round(100 * (1 - p) / p)


# ------------------------------------------------------------------ distributions
def _norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _discrete(mean: float, sd: float, lo: int, hi: int, weights: dict[int, float] | None = None) -> dict[int, float]:
    """P(X = k) for whole k: normal mass on [k-0.5, k+0.5], reweighted on |k| in `weights`, renormalized."""
    mass = {k: _norm_cdf((k + 0.5 - mean) / sd) - _norm_cdf((k - 0.5 - mean) / sd) for k in range(lo, hi + 1)}
    if weights:
        for k in mass:
            mass[k] *= weights.get(abs(k), 1.0)
    s = sum(mass.values())
    return {k: v / s for k, v in mass.items()}


def margin_dist(mean: float) -> dict[int, float]:
    """Home margin (home minus away) in whole points."""
    return _discrete(mean, SD_MARGIN, -75, 75, KEY_MARGINS)


def total_dist(mean: float) -> dict[int, float]:
    return _discrete(mean, SD_TOTAL, 0, 130)


def team_dist(mean: float) -> dict[int, float]:
    return _discrete(mean, SD_TEAM, 0, 80)


def cover(dist: dict[int, float], line: float, sign: int = 1) -> tuple[float, float]:
    """(P(win), P(push)) for a side that wins when sign*X + line > 0 (sign=-1: the other team's view of a margin)."""
    win = push = 0.0
    for k, p in dist.items():
        r = sign * k + line
        if r > 1e-9:
            win += p
        elif abs(r) <= 1e-9:
            push += p
    return win, push


def over(dist: dict[int, float], line: float) -> tuple[float, float]:
    """(P(over), P(push))."""
    win = sum(p for k, p in dist.items() if k > line + 1e-9)
    push = sum(p for k, p in dist.items() if abs(k - line) <= 1e-9)
    return win, push


def joint(mu_home: float, mu_away: float, n: int = 40_000, seed: int = 7) -> dict[str, float]:
    """Shootout and both-teams-score odds from simulated (total, margin) -> team scores."""
    rng = np.random.default_rng(seed)
    t = rng.normal(mu_home + mu_away, SD_TOTAL, n)
    m = rng.normal(mu_home - mu_away, SD_MARGIN, n)
    h, a = (t + m) / 2, (t - m) / 2
    return {
        "p_shootout": round(float(np.mean(t >= SHOOTOUT_POINTS)), 3),
        "p_both_24": round(float(np.mean((h >= BOTH_TEAMS_POINTS) & (a >= BOTH_TEAMS_POINTS))), 3),
        "p_one_score": round(float(np.mean(np.abs(m) <= 8)), 3),
        "p_blowout": round(float(np.mean(np.abs(m) >= 17)), 3),
    }


# ------------------------------------------------------------------ team model
def _above(value, avg) -> float:
    return (value - avg) if isinstance(value, (int, float)) and isinstance(avg, (int, float)) else 0.0


def team_points(off: dict, opp_def: dict, league: dict, plays: float, league_points: float) -> tuple[float, dict]:
    """Expected points for one offense against one defense (before home field and weather), with the inputs used."""
    lg_off, lg_def = (league.get("off") or {}).get("epa_play"), (league.get("def") or {}).get("epa_play")
    o, d = off.get("epa_play"), opp_def.get("epa_play")
    edge = _above(o, lg_off) + _above(d, lg_def)
    pts = league_points + K_EPA * edge * plays
    return pts, {"off_epa": o, "opp_def_epa_allowed": d, "league_epa": lg_off, "epa_edge": round(edge, 3), "plays": round(plays, 1)}


def rating_se(games_now: float, prior_games: float, plays: float) -> float:
    """Rough standard error (points) of one team's expected score: per-game EPA/play varies ~0.17 around a team's true level."""
    n = max(1.0, games_now + prior_games)
    se_unit = 0.17 / math.sqrt(n)
    return K_EPA * plays * se_unit * math.sqrt(2)      # offense + opposing defense


def project_game(home_off: dict, home_def: dict, away_off: dict, away_def: dict, league: dict, *,
                 home_plays: float, away_plays: float, league_points: float, weather_points: float = 1.0,
                 home_games: float = 0, away_games: float = 0, prior_games: float = 3) -> dict:
    """Model means and fair lines for one game."""
    h, h_in = team_points(home_off, away_def, league, home_plays, league_points)
    a, a_in = team_points(away_off, home_def, league, away_plays, league_points)
    h, a = (h + HOME_EDGE / 2) * weather_points, (a - HOME_EDGE / 2) * weather_points
    h, a = max(h, 3.0), max(a, 3.0)
    se_h = rating_se(home_games, prior_games, home_plays)
    se_a = rating_se(away_games, prior_games, away_plays)
    margin = h - a
    m = margin_dist(margin)
    p_home = sum(p for k, p in m.items() if k > 0) / max(1e-9, 1 - m.get(0, 0.0))
    return {
        "home_points": round(h, 1), "away_points": round(a, 1),
        "fair_home_spread": round(-margin, 1), "fair_total": round(h + a, 1),
        "fair_home_ml": fair_american(p_home), "fair_away_ml": fair_american(1 - p_home),
        "p_home_win": round(p_home, 3),
        "spread_se": round(math.hypot(se_h, se_a), 1), "total_se": round(math.hypot(se_h, se_a), 1),
        "inputs": {"home": h_in, "away": a_in, "home_edge": HOME_EDGE, "weather_points": weather_points},
        **joint(h, a),
    }


# ------------------------------------------------------------------ market comparison
def _prob_pair(model_dist, line, sign, kind):
    return cover(model_dist, line, sign) if kind == "spread" else over(model_dist, line) if sign > 0 else _under(model_dist, line)


def _under(dist, line):
    win = sum(p for k, p in dist.items() if k < line - 1e-9)
    push = sum(p for k, p in dist.items() if abs(k - line) <= 1e-9)
    return win, push


def evaluate(kind: str, dist: dict[int, float], line: float, sign: int, odds: int | None,
             other_odds: int | None) -> dict:
    """One side of one market against the model.

    kind "spread": the side wins when sign*margin + line > 0 (margin = home - away; sign=+1 home, -1 away).
    kind "total"/"team_total": sign=+1 over, -1 under."""
    p_win, p_push = _prob_pair(dist, line, sign, kind)
    p_loss = max(0.0, 1 - p_win - p_push)
    p_cond = p_win / (p_win + p_loss) if p_win + p_loss else 0.5
    out = {"line": line, "price": odds, "model_win": round(p_win, 3), "model_push": round(p_push, 3),
           "model_cond": round(p_cond, 3), "model_fair_price": fair_american(p_cond)}
    if odds is None:
        out.update(price_available=False)
        return out
    out.update(price_available=True, break_even=round(implied(odds), 3), ev_model=round(ev(p_win, p_push, odds), 4))
    if other_odds is not None:
        mkt = no_vig(odds, other_odds)[0]
        blend = BLEND_MODEL * p_cond + (1 - BLEND_MODEL) * mkt
        out.update(market_novig=round(mkt, 3), blend_cond=round(blend, 3),
                   ev_blend=round(ev(blend * (1 - p_push), p_push, odds), 4),
                   breakeven_price=fair_american(blend))
    # The number where the model alone stops clearing break-even at this price.
    out["model_breakeven_line"] = breakeven_line(kind, dist, line, sign, odds)
    return out


def breakeven_line(kind: str, dist: dict[int, float], line: float, sign: int, odds: int) -> float | None:
    """The worst line (same price) at which the model alone still expects a profit on this side:
    walked against the side in half points (fewer points for a spread side, a higher number for an
    over, a lower one for an under). None when the model doesn't like the current line either."""
    step = -0.5 if kind == "spread" else (0.5 if sign > 0 else -0.5)
    last, cur = None, line
    for _ in range(40):
        w, p = _prob_pair(dist, cur, sign, kind)
        if ev(w, p, odds) < 0:
            return last
        last, cur = cur, round(cur + step, 1)
    return last


STRONG_EV, SMALL_EV, WATCH_EV = 0.025, 0.005, 0.03
MIN_POINTS = {"spread": 1.5, "team_total": 1.5, "total": 2.0}


def classify(side: dict, kind: str, points_edge: float, unresolved_news: bool, trusted: bool = True) -> str:
    """strongest | price_sensitive | watchlist | none (analysis buckets, not guarantees).

    trusted=False (the backtest shows the model doing worse than the market for this kind of market)
    caps a side at watchlist: an untested signal is never presented as an edge."""
    if not side.get("price_available") or side.get("ev_blend") is None:
        return "watchlist" if side.get("model_cond", 0.5) >= 0.56 else "none"
    big_enough = abs(points_edge) >= MIN_POINTS.get(kind, 1.5)
    if side["ev_blend"] >= STRONG_EV and big_enough:
        cls = "strongest"
    elif side["ev_blend"] >= SMALL_EV:
        cls = "price_sensitive"
    elif side.get("ev_model", 0) >= WATCH_EV:
        return "watchlist"
    else:
        return "none"
    return "watchlist" if unresolved_news or not trusted else cls
