"""Postgame summaries for the Week Breakdown: how a finished game actually
played out, which matchups were exploited or held, and how predictable the
result was from what was known before kickoff.

Everything is computed from real data and every sentence is generated here:

  result      nflverse final score vs the closing spread, total and implied totals
  game flow   nflverse play-by-play for the game: success rate, EPA/play,
              explosive plays, sacks; box-score turnovers and yards/play
  matchups    each pregame trench matchup (app.trenches, entering the week, so
              no hindsight) vs what happened on the game's competitive plays
  predictable the closing line's win probability for the winner (logistic fit
              on every 2010+ game), the same line adjusted by the pregame
              matchup metrics (fit only on games played before this week), how
              far the margin and total landed from the line vs history, and how
              many flagged matchups played out as called
  DFS         top DraftKings scorers and how the pregame targets did
"""
from __future__ import annotations

import bisect
import csv
import io
import math

import numpy as np

from app import nflverse_client as nc
from app import trenches
from app.cache import cached_fetch, memoize_async
from app.config import NFLVERSE_GAMES_CSV_URL, TTL_NFLVERSE_PBP_PAST

HISTORY_FIRST_SEASON = 2010
MIN_ATTEMPTS = 8           # fewer competitive dropbacks/runs than this: no matchup verdict
Z_VERDICT = 1.0            # standard errors from expectation before a side "won" a matchup
MIN_CALIBRATION_GAMES = 60
RIDGE = 1.0

# key -> (offense counts num/den, pregame metric, +1 if higher is better for the offense,
#         offense unit, defense unit, what happened, what happened when the defense won)
MATCHUP_METRICS = {
    "protection": ("hit", "db", "pressure_rate", -1, "protection", "pass rush",
                   "sacked or hit on {rate:.0%} of dropbacks", "{off} was sacked or hit on {rate:.0%} of dropbacks"),
    "run": ("rush_succ", "rush", "rush_success", 1, "run game", "run defense",
            "{rate:.0%} rush success", "held {off} to {rate:.0%} rush success"),
    "pass": ("db_succ", "db", "db_success", 1, "dropback game", "pass defense",
             "{rate:.0%} dropback success", "held {off} to {rate:.0%} dropback success"),
}


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def fit_logistic(X: np.ndarray, y: np.ndarray, offset: np.ndarray | None = None, ridge: float = RIDGE) -> np.ndarray:
    """Ridge-penalized logistic regression by Newton's method (no penalty on
    column 0 when it is the intercept column of ones)."""
    n, k = X.shape
    off = np.zeros(n) if offset is None else offset
    beta = np.zeros(k)
    pen = np.full(k, ridge)
    if np.allclose(X[:, 0], 1.0):
        pen[0] = 0.0
    for _ in range(50):
        p = 1.0 / (1.0 + np.exp(-(X @ beta + off)))
        grad = X.T @ (y - p) - pen * beta
        hess = (X * (p * (1 - p))[:, None]).T @ X + np.diag(pen)
        step = np.linalg.solve(hess, grad)
        beta += step
        if np.max(np.abs(step)) < 1e-8:
            break
    return beta


def share_at_least(sorted_values: list[float], x: float) -> float:
    """Fraction of sorted_values >= x."""
    if not sorted_values:
        return 0.0
    return (len(sorted_values) - bisect.bisect_left(sorted_values, x - 1e-9)) / len(sorted_values)


# ------------------------------------------------------------ history + fits
async def line_history(season: int) -> dict:
    """Every final game from 2010 through last season: how far margins and
    totals land from the closing line, and a logistic fit of P(home win) on
    the closing spread (nflverse spread_line: + = home favored)."""

    async def fetch() -> dict:
        text = await nc._fetch_csv_text(NFLVERSE_GAMES_CSV_URL)
        spreads, wins, margin_miss, total_miss = [], [], [], []
        for r in csv.DictReader(io.StringIO(text)):
            try:
                szn = int(r["season"])
                result, spread = float(r["result"]), float(r["spread_line"])
                total, total_line = float(r["total"]), float(r["total_line"])
            except (KeyError, ValueError):
                continue
            if not HISTORY_FIRST_SEASON <= szn < season:
                continue
            margin_miss.append(abs(result - spread))
            total_miss.append(abs(total - total_line))
            if result != 0:
                spreads.append(spread)
                wins.append(1.0 if result > 0 else 0.0)
        if len(spreads) < 200:
            raise ValueError("not enough history")
        X = np.column_stack([np.ones(len(spreads)), np.array(spreads) / 10])
        b = fit_logistic(X, np.array(wins), ridge=0.0)
        fav = [w == (s > 0) for s, w in zip(spreads, wins) if s != 0]
        return {"seasons": [HISTORY_FIRST_SEASON, season - 1], "games": len(margin_miss),
                "coef": [round(float(v), 5) for v in b], "favorite_win_rate": round(sum(fav) / len(fav), 3),
                "margin_miss": sorted(margin_miss), "total_miss": sorted(total_miss)}

    try:
        return await cached_fetch(f"postgame_line_history_v1_{season}", TTL_NFLVERSE_PBP_PAST, fetch)
    except Exception:
        return {}


def line_home_win_prob(hist: dict, spread_line: float) -> float | None:
    """P(home win) from the closing spread (+ = home favored)."""
    if not hist.get("coef"):
        return None
    b0, b1 = hist["coef"]
    return _sigmoid(b0 + b1 * spread_line / 10)


def net_edge(tw: dict | None, team: str, opp: str) -> float | None:
    """Sum of `team`'s offensive matchup edges vs `opp`'s defense minus `opp`'s
    vs `team`'s defense (league z-score units; + favors `team`)."""
    a, b = trenches.matchup(tw, team, opp)["edges"], trenches.matchup(tw, opp, team)["edges"]
    if not a or not b:
        return None
    return round(sum(e["edge"] for e in a.values()) - sum(e["edge"] for e in b.values()), 2)


@memoize_async(1800, max_entries=8)
async def calibration(season: int, week: int) -> dict:
    """How much the pregame matchup metrics add to the closing line, fit only
    on games played before (season, week): last season plus this season's
    earlier weeks. Each game uses the metrics as they stood entering its week."""
    hist = await line_history(season)
    if not hist.get("coef"):
        return {}
    spreads, nets, wins = [], [], []
    for szn, before in ((season - 1, 99), (season, week)):
        cur, prev = await nc.get_pbp_aggregates(szn, season), await nc.get_pbp_aggregates(szn - 1, season)
        cur_i, prev_i = trenches.index_counts(cur.get("trenches")), trenches.index_counts(prev.get("trenches"))
        if not cur_i.get("off"):
            continue
        games = await nc.get_games(szn)
        by_week: dict[int, list] = {}
        for (w, away, home), g in games.items():
            if w < before and g["is_final"] and g["spread_line"] is not None and g["home_score"] != g["away_score"]:
                by_week.setdefault(w, []).append((away, home, g))
        for w in sorted(by_week):
            tw = {"teams": trenches.build_teams(w, cur_i, prev_i), "league": {}}
            for away, home, g in by_week[w]:
                n = net_edge(tw, home, away)
                if n is None:
                    continue
                spreads.append(g["spread_line"])
                nets.append(n)
                wins.append(1.0 if g["home_score"] > g["away_score"] else 0.0)
    if len(wins) < MIN_CALIBRATION_GAMES:
        return {"games": len(wins)}
    y, s, n = np.array(wins), np.array(spreads), np.array(nets)
    b0, b1 = hist["coef"]
    line_logit = b0 + b1 * s / 10
    c = float(fit_logistic(n[:, None], y, offset=line_logit)[0])
    p_line = 1 / (1 + np.exp(-line_logit))
    p_both = 1 / (1 + np.exp(-(line_logit + c * n)))

    def logloss(p):
        return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))

    fav = s != 0
    lean = n != 0
    return {
        "games": len(wins), "seasons": [season - 1, season], "coef": round(c, 4),
        "logloss_line": round(logloss(p_line), 4), "logloss_with_metrics": round(logloss(p_both), 4),
        "vegas_favorite_win_rate": round(float(np.mean((s[fav] > 0) == (y[fav] == 1))), 3),
        "metrics_favorite_win_rate": round(float(np.mean((n[lean] > 0) == (y[lean] == 1))), 3),
    }


# ----------------------------------------------------------------- summaries
def _pct(x: float) -> str:
    return f"{x:.0%}"


def _signed(x: float, digits: int = 2) -> str:
    return f"{x:+.{digits}f}"


def _team_game(counts: dict | None, box: dict | None) -> dict | None:
    if not counts and not box:
        return None
    c, b = counts or {}, box or {}
    plays = c.get("plays") or 0
    return {
        "plays": int(plays) if plays else (int(b["plays"]) if b.get("plays") else None),
        "success": round(c["succ"] / plays, 3) if plays else None,
        "epa_play": round(c["epa"] / plays, 3) if plays else None,
        "db_epa": round(c["db_epa"] / c["db"], 3) if c.get("db") else None,
        "rush_epa": round(c["rush_epa"] / c["rush"], 3) if c.get("rush") else None,
        "explosive": int(c["explosive"]) if plays else None,
        "sacks_taken": int(c["sack"]) if plays else (int(b["sacks_taken"]) if b.get("sacks_taken") is not None else None),
        "turnovers": int(b["giveaways"]) if b.get("giveaways") is not None else None,
        "yards_per_play": b.get("yards_per_play"),
    }


def matchup_review(tw: dict | None, competitive: dict | None, offense: str, defense: str) -> list[dict]:
    """Each pregame matchup vs what happened on the game's competitive plays.
    Expected rate = offense's pregame rate + defense's pregame rate allowed -
    league rate; the verdict needs Z_VERDICT standard errors either way."""
    teams = (tw or {}).get("teams") or {}
    o, d = teams.get(offense), teams.get(defense)
    if not o or not d or not competitive:
        return []
    pre = trenches.matchup(tw, offense, defense)["edges"]
    league = (tw.get("league") or {}).get("off") or {}
    out = []
    for key, (num, den, metric, better, ounit, dunit, what, held) in MATCHUP_METRICS.items():
        n = competitive.get(den) or 0
        rate_o, rate_d, lg = o["off"].get(metric), d["def"].get(metric), league.get(metric)
        if n < MIN_ATTEMPTS or None in (rate_o, rate_d, lg):
            continue
        actual = competitive.get(num, 0.0) / n
        expected = min(0.98, max(0.02, rate_o + rate_d - lg))
        z = (actual - expected) / math.sqrt(expected * (1 - expected) / n)
        verdict = "exploited" if better * z >= Z_VERDICT else "held" if better * z <= -Z_VERDICT else "to form"
        e = pre.get(key)
        call = None
        if e and e["strength"] != "neutral":
            offense_did_better = better * (actual - lg) > 0
            call = "hit" if (e["edge"] > 0) == offense_did_better else "miss"
        desc = what.format(rate=actual)
        if verdict == "exploited":
            text = f"{offense}'s {ounit} won the matchup: {desc} vs {_pct(expected)} expected (league {_pct(lg)})."
        elif verdict == "held":
            text = (f"{defense}'s {dunit} won the matchup: {held.format(off=offense, rate=actual)} "
                    f"vs {_pct(expected)} expected (league {_pct(lg)}).")
        else:
            text = f"{offense}'s {ounit} vs {defense}'s {dunit} played to form: {desc} vs {_pct(expected)} expected."
        if call == "hit":
            text += f" The pregame metrics called this ({e['strength']} edge toward {offense if e['edge'] > 0 else defense})."
        elif call == "miss":
            text += f" The pregame metrics had leaned {offense if e['edge'] > 0 else defense} ({e['strength']} edge)."
        out.append({"key": key, "offense": offense, "defense": defense, "label": f"{offense} {ounit} vs {defense} {dunit}",
                    "attempts": int(n), "actual": round(actual, 3), "expected": round(expected, 3), "league": round(lg, 3),
                    "z": round(z, 2), "better": better, "verdict": verdict, "call": call,
                    "pregame": {"edge": e["edge"], "strength": e["strength"]} if e else None, "text": text})
    return out


def _flow(game, away_s: dict | None, home_s: dict | None) -> list[str]:
    ctx = game.context
    a, h = game.away, game.home
    lines: list[str] = []
    winner = a if ctx.away_score > ctx.home_score else h if ctx.home_score > ctx.away_score else None
    if ctx.away_implied_total is not None and ctx.home_implied_total is not None:
        lines.append(f"{a} scored {ctx.away_score} (implied {ctx.away_implied_total:g}); "
                     f"{h} scored {ctx.home_score} (implied {ctx.home_implied_total:g}).")
    if not (away_s and home_s):
        return lines
    ws, ls = (away_s, home_s) if winner == a else (home_s, away_s)
    loser = h if winner == a else a
    if winner and ws.get("success") is not None and ls.get("success") is not None:
        why = []
        if (ws.get("turnovers") or 0) < (ls.get("turnovers") or 0):
            why.append(f"turnovers ({loser} {ls['turnovers']}, {winner} {ws['turnovers']})")
        if (ws.get("explosive") or 0) > (ls.get("explosive") or 0):
            why.append(f"explosive plays ({winner} {ws['explosive']}, {loser} {ls['explosive']})")
        edge = f" {winner} also won on {' and '.join(why)}." if why else ""
        better_epa, better_sr = ws["epa_play"] >= ls["epa_play"], ws["success"] >= ls["success"]
        if better_epa and better_sr:
            lines.append(f"{winner} won the efficiency battle: {_pct(ws['success'])} success and {_signed(ws['epa_play'])} EPA/play "
                         f"vs {loser}'s {_pct(ls['success'])} and {_signed(ls['epa_play'])}.{edge}")
        elif not better_epa and not better_sr:
            lines.append(f"{loser} was the more efficient offense ({_pct(ls['success'])} success, {_signed(ls['epa_play'])} EPA/play vs "
                         f"{_pct(ws['success'])}, {_signed(ws['epa_play'])}) but lost."
                         + (f" {winner} won on {' and '.join(why)}." if why else " The scoreboard didn't follow the per-play numbers."))
        else:
            (epa_t, e1, e2), (sr_t, s1, s2) = (((winner, ws, ls), (loser, ls, ws)) if better_epa else ((loser, ls, ws), (winner, ws, ls)))
            lines.append(f"Efficiency was split: {epa_t} had the better EPA/play ({_signed(e1['epa_play'])} vs {_signed(e2['epa_play'])}), "
                         f"{sr_t} the higher success rate ({_pct(s1['success'])} vs {_pct(s2['success'])}).{edge}")
    bits = []
    for label, key in (("Turnovers", "turnovers"), ("Explosive plays", "explosive"), ("Sacks taken", "sacks_taken")):
        if away_s.get(key) is not None and home_s.get(key) is not None:
            bits.append(f"{label}: {a} {away_s[key]}, {h} {home_s[key]}")
    if bits:
        lines.append("; ".join(bits) + ".")
    return lines


def _lines_result(game, hist: dict) -> tuple[list[str], dict]:
    ctx = game.context
    a, h = game.away, game.home
    out, info = [], {}
    if ctx.home_spread is not None and ctx.spread_result is not None:
        fav, line = (h, -ctx.home_spread) if ctx.home_spread < 0 else (a, ctx.home_spread)
        home_margin = ctx.home_score - ctx.away_score
        miss = abs(home_margin + ctx.home_spread)
        if abs(ctx.home_spread) < 0.5:
            ats = "The line was a pick'em."
        elif ctx.spread_result == 0:
            ats = f"{fav} (-{line:g}) pushed."
        else:
            coverer = h if ctx.spread_result > 0 else a
            ats = f"{coverer} covered ({fav} -{line:g}) by {abs(ctx.spread_result):g}."
        info["margin_miss"] = round(miss, 1)
        if hist.get("margin_miss"):
            info["margin_miss_share"] = round(share_at_least(hist["margin_miss"], miss), 3)
        out.append(ats)
    if ctx.total_line is not None and ctx.total_result is not None:
        total = ctx.away_score + ctx.home_score
        side = "over" if ctx.total_result > 0 else "under" if ctx.total_result < 0 else "exactly on"
        out.append(f"{total} total points: {side} the {ctx.total_line:g} total" + (f" by {abs(ctx.total_result):g}." if ctx.total_result else "."))
        info["total_miss"] = round(abs(ctx.total_result), 1)
        if hist.get("total_miss"):
            info["total_miss_share"] = round(share_at_least(hist["total_miss"], abs(ctx.total_result)), 3)
    return out, info


def _verdict(p: float | None) -> str:
    """How expected the winner was, from its pregame win probability."""
    if p is None:
        return "No line"
    if p >= 0.65:
        return "Expected"
    if p >= 0.52:
        return "Favorite won"
    if p >= 0.48:
        return "Coin flip"
    return "Mild upset" if p >= 0.35 else "Upset"


def _predictability(game, tw, hist, calib, matchups, line_info) -> dict:
    ctx = game.context
    a, h = game.away, game.home
    if ctx.away_score == ctx.home_score:
        return {"verdict": "Tie", "text": ["The game ended in a tie."], "calls_hit": 0, "calls_made": 0}
    winner, loser = (h, a) if ctx.home_score > ctx.away_score else (a, h)
    spread_line = -ctx.home_spread if ctx.home_spread is not None else None   # + = home favored
    p_home = line_home_win_prob(hist, spread_line) if spread_line is not None else None
    p_line = None if p_home is None else (p_home if winner == h else 1 - p_home)
    net_home = net_edge(tw, h, a)
    p_model = None
    if p_home is not None and net_home is not None and calib.get("coef") is not None:
        logit = math.log(p_home / (1 - p_home)) + calib["coef"] * net_home
        p_model = _sigmoid(logit) if winner == h else 1 - _sigmoid(logit)
    text = []
    if p_line is not None:
        fav = h if spread_line > 0 else a if spread_line < 0 else None
        role = "favored" if winner == fav else "an underdog" if fav else "in a pick'em"
        text.append(f"{winner} was {role}: the closing line gave {winner} a {_pct(p_line)} chance to win "
                    f"(fit on {hist['games']:,} games, {hist['seasons'][0]}-{hist['seasons'][1]}).")
    if net_home is not None and abs(net_home) >= 0.25:
        lean = h if net_home > 0 else a
        text.append(f"The pregame matchup metrics leaned {lean} (net edge {abs(net_home):.1f}) -- "
                    + ("the right side." if lean == winner else "the wrong side."))
    elif net_home is not None:
        text.append("The pregame matchup metrics saw the trenches as even.")
    if p_model is not None:
        helped = calib["logloss_with_metrics"] < calib["logloss_line"] - 0.001
        record = (f"Vegas favorites won {_pct(calib['vegas_favorite_win_rate'])} of {calib['games']} earlier games; "
                  f"the side the matchup metrics favored won {_pct(calib['metrics_favorite_win_rate'])}")
        if helped:
            text.append(f"Line + matchup metrics: {_pct(p_model)} for {winner} ({record}, and adding the metrics sharpened the line).")
        else:
            text.append(f"Adding the matchup metrics to the line didn't improve its predictions over those games, so the line's "
                        f"number is the best pregame estimate ({record}).")
    calls = [m for m in matchups if m["call"]]
    hits = sum(1 for m in calls if m["call"] == "hit")
    if calls:
        text.append(f"{hits} of {len(calls)} flagged matchups played out as called.")
    if "margin_miss_share" in line_info:
        text.append(f"The margin landed {line_info['margin_miss']:g} points from the spread; "
                    f"{_pct(line_info['margin_miss_share'])} of games miss by at least that much.")
    if "total_miss_share" in line_info:
        text.append(f"The total missed by {line_info['total_miss']:g}; {_pct(line_info['total_miss_share'])} of games miss by that much or more.")
    p = p_model if p_model is not None else p_line
    surprises = []
    if line_info.get("margin_miss_share") is not None and line_info["margin_miss_share"] < 0.10:
        surprises.append("Margin surprise")
    if line_info.get("total_miss_share") is not None and line_info["total_miss_share"] < 0.10:
        surprises.append("Total surprise")
    return {"surprises": surprises, "winner": winner, "loser": loser, "line_win_prob": None if p_line is None else round(p_line, 3),
            "model_win_prob": None if p_model is None else round(p_model, 3), "net_edge_home": net_home,
            "verdict": _verdict(p), "calls_hit": hits, "calls_made": len(calls), **line_info, "text": text}


def _dfs(game, actuals: dict | None, players: list, targets: dict[str, list]) -> dict | None:
    """Top DraftKings scorers (salaries when the slate is still published) and
    how the pregame targets did."""
    if not actuals or not {game.away, game.home} & set(actuals.get("teams") or []):
        return None
    salary = {(p.team, nc.player_key(p.name, p.position)): p.salary for p in players if p.roster_slot in ("", None)}
    scored = []
    for team in (game.away, game.home):
        for name, position, pts in (actuals.get("by_team") or {}).get(team, []):
            if position == "K":
                continue
            sal = salary.get((team, nc.player_key(name, position)))
            scored.append({"name": name, "team": team, "position": position, "points": pts, "salary": sal,
                           "value": round(pts / (sal / 1000), 2) if sal else None})
        if team in actuals.get("dst", {}):
            pts = actuals["dst"][team]
            sal = next((p.salary for p in players if p.team == team and p.position == "DST"), None)
            scored.append({"name": f"{team} DST", "team": team, "position": "DST", "points": pts, "salary": sal,
                           "value": round(pts / (sal / 1000), 2) if sal else None})
    top = sorted(scored, key=lambda x: -x["points"])[:5]
    graded = []
    for team, picks in targets.items():
        for t in picks:
            pts = nc.actual_points(actuals, name=t.name, position=t.position, team=team)
            if t.ceiling is not None and pts >= t.ceiling:
                result = "Hit ceiling"
            elif t.proj_points is not None and pts >= t.proj_points:
                result = "Beat projection"
            else:
                result = "Missed"
            graded.append({"name": t.name, "team": team, "position": t.position, "salary": t.salary, "points": pts,
                           "proj": t.proj_points, "ceiling": t.ceiling, "role": t.role, "result": result})
    parts = []
    if top:
        best = top[0]
        who = best["name"] if best["position"] == "DST" else f"{best['name']} ({best['position']}, {best['team']})"
        parts.append(f"Top DK score: {who} with {best['points']:.1f}"
                     + (f" at ${best['salary']:,}." if best["salary"] else "."))
    if graded:
        good = sum(1 for g in graded if g["result"] != "Missed")
        ceil = [g["name"] for g in graded if g["result"] == "Hit ceiling"]
        parts.append(f"Pregame targets: {good} of {len(graded)} beat their projection"
                     + (f"; {', '.join(ceil)} hit the ceiling." if ceil else "."))
    return {"top_scorers": top, "targets": graded, "text": " ".join(parts) or None,
            "note": None if players else "DraftKings no longer lists this week's salaries, so values and target grades are unavailable."}


def summarize(game, *, tw: dict | None, competitive: dict, full_game: dict, box: dict, actuals: dict | None,
              players: list, targets: dict[str, list], hist: dict, calib: dict) -> dict | None:
    """The postgame summary for one game, or None if it isn't final."""
    ctx = game.context
    if ctx is None or not ctx.is_final or ctx.away_score is None or ctx.home_score is None:
        return None
    a, h, w = game.away, game.home, game.week
    away_s = _team_game(full_game.get(f"{w}|{a}"), box.get((w, a)))
    home_s = _team_game(full_game.get(f"{w}|{h}"), box.get((w, h)))
    pbp = bool(full_game.get(f"{w}|{a}") and full_game.get(f"{w}|{h}"))
    if ctx.away_score == ctx.home_score:
        headline = f"{a} and {h} tied {ctx.away_score}-{ctx.home_score}."
    else:
        (win, ws), (lose, ls) = sorted(((a, ctx.away_score), (h, ctx.home_score)), key=lambda x: -x[1])
        headline = f"{win} beat {lose} {ws}-{ls}."
    lines, line_info = _lines_result(game, hist)
    matchups = (matchup_review(tw, competitive.get(f"{w}|{a}"), a, h) + matchup_review(tw, competitive.get(f"{w}|{h}"), h, a)) if pbp else []
    matchups.sort(key=lambda m: -abs(m["z"]))
    pred = _predictability(game, tw, hist, calib, matchups, line_info)
    return {
        "headline": headline, "result": lines, "flow": _flow(game, away_s, home_s),
        "team_stats": {a: away_s, h: home_s}, "pbp_available": pbp,
        "matchups": matchups,
        "exploited": [m["text"] for m in matchups if m["verdict"] == "exploited"][:3],
        "struggled": [m["text"] for m in matchups if m["verdict"] == "held"][:3],
        "predictability": pred,
        "dfs": _dfs(game, actuals, players, targets),
        "note": None if pbp else "Play-by-play for this game isn't published yet (nflverse updates within a day); "
                                 "efficiency and matchup review will appear once it is.",
    }
