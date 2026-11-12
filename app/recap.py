"""Last week's recap: for each finished game, what the result says against what the play says.

A final score is swayed by low-sample events (fumble recoveries, red-zone variance, tipped interceptions, defensive
touchdowns). This module separates, for every team in every game of a week,

  SIGNAL  repeatable execution: early-down success rate, neutral-script EPA per play, neutral-script pass rate
          over expected (PROE), and the pressure the lines gave and took (sack-or-QB-hit rate, and the same on
          four-man rushes where FTN charting is published);
  NOISE   what regresses fastest: turnover margin, fumble recoveries, red-zone touchdown rate, third-and-long
          conversions, defensive and special-teams touchdowns, and production while the game was already decided.

Definitions (every threshold is a constant below, and every sentence is generated from the counts):

  neutral script   win probability for the offense between 20% and 80% (NEUTRAL_MIN / NEUTRAL_MAX)
  competitive      win probability between 10% and 90%; early-down success is counted here for a larger sample
  garbage time     the offense's win probability under 10% (trailing, "empty-calorie" volume)
  pressure         a sack or a QB hit as nflverse records them, over dropbacks. It is not a charted pressure rate
                   (no pass-rush win rate is published), so it understates true pressure; it is compared with the
                   league's own rate this season, never with a fixed line.

A team is "ascending" when it out-played its opponent in the neutral script by at least EPA_GAP EPA per play but
lost, or lost the noise battle; "fragile" when it was out-played by that much but won, or won with the noise on its
side. Everything else is "steady". Counts come from the play-by-play pass in nflverse_client.get_pbp_aggregates
(RecapAccumulator); nothing here is a projection.
"""
from __future__ import annotations

from app import nflverse_client as nc
from app.cache import memoize_async

NEUTRAL_MIN, NEUTRAL_MAX = 0.20, 0.80
COMPETITIVE_MIN, COMPETITIVE_MAX = 0.10, 0.90
GARBAGE_WP = 0.10
RED_ZONE = 20
LONG_TO_GO = 7
EXPLOSIVE_PASS, EXPLOSIVE_RUN = 20, 10

EARLY_DOWN_SOUND = 0.48      # the framework's "structurally sound" early-down success rate
EARLY_DOWN_POOR = 0.40
MIN_NEUTRAL = 12             # neutral-script plays before a team's neutral numbers say anything
MIN_EARLY = 15
EPA_GAP = 0.05               # neutral EPA per play separating two teams
CLOSE_MARGIN = 3             # a score margin this small can be flipped by the bounces
TURNOVER_SWING = 2           # a turnover margin of this size is noise
RZ_TRIPS = 3
RZ_HIGH, RZ_LOW = 0.80, 0.34
LONG_TRIES = 4               # third-and-7+ tries before the conversion rate is called luck
LONG_HIGH = 0.50
GARBAGE_SHARE = 0.20         # share of a team's plays in garbage time before its volume is "inflated"
PRESSURE_GAP = 0.05          # pressure-rate points against the league's before it's called a strength or a weakness
MIN_DROPBACKS = 20

UNAVAILABLE = [
    "Pass-rush win rate and charted pressure (not published): sack-or-QB-hit rate stands in for it.",
    "Turnover-worthy plays and adjusted interceptions (no charting): every interception counts the same.",
    "Route participation, yards per route run and target shares by route (no route data).",
    "Expected score (xScore): not computed. The verdict compares neutral-script EPA with the result instead.",
]


def _f(v) -> float | None:
    return nc._to_float(v)


# --------------------------------------------------------------------------- counting
class RecapAccumulator:
    """Feed nflverse play-by-play rows through add(); result() gives {"week|team": counts} for each offense
    (a defense's numbers are its opponent's offense in the same week). Scrimmage plays only, except
    non-offensive touchdowns, which are credited to the team that scored them."""

    def __init__(self):
        self.t: dict[str, dict[str, float]] = {}
        self.rz: dict[tuple, str] = {}

    def _bump(self, week: int, team: str, **counts: float) -> None:
        d = self.t.setdefault(f"{week}|{team}", {})
        for k, v in counts.items():
            d[k] = d.get(k, 0.0) + float(v)

    def add(self, r: dict) -> None:
        week = nc._to_int(r.get("week"))
        if week is None:
            return
        team = nc.to_app_team(r.get("posteam", ""))
        if r.get("touchdown") == "1":
            scorer = nc.to_app_team(r.get("td_team", ""))
            if scorer and scorer != team:
                self._bump(week, scorer, nonoff_td=1)
        if r.get("play_type") not in ("pass", "run") or r.get("qb_kneel") == "1" or r.get("qb_spike") == "1" or not team:
            return
        wp = _f(r.get("wp"))
        epa = _f(r.get("epa")) or 0.0
        succ = r.get("success") == "1"
        yards = _f(r.get("yards_gained")) or 0.0
        dropback = r.get("qb_dropback") == "1"
        sack = r.get("sack") == "1"
        hit = sack or r.get("qb_hit") == "1"
        c: dict[str, float] = {"plays": 1, "epa": epa, "succ": succ, "db": dropback, "sack": sack and dropback,
                               "hit": hit and dropback,
                               "expl": (not sack and yards >= EXPLOSIVE_PASS) if dropback else yards >= EXPLOSIVE_RUN,
                               "int": r.get("interception") == "1", "fum": r.get("fumble") == "1",
                               "fum_lost": r.get("fumble_lost") == "1"}
        down, to_go = nc._to_int(r.get("down")), _f(r.get("ydstogo"))
        if down == 3:
            c.update(t3=1, t3c=r.get("third_down_converted") == "1")
            if to_go is not None and to_go >= LONG_TO_GO:
                c.update(t3l=1, t3lc=r.get("third_down_converted") == "1")
        elif down == 4:
            c.update(t4=1, t4c=r.get("fourth_down_converted") == "1")
        if wp is not None:
            if COMPETITIVE_MIN <= wp <= COMPETITIVE_MAX and down in (1, 2):
                c.update(ed=1, ed_succ=succ)
            if NEUTRAL_MIN <= wp <= NEUTRAL_MAX:
                c.update(n=1, n_epa=epa, n_succ=succ)
                pass_oe = _f(r.get("pass_oe"))
                if pass_oe is not None:
                    c.update(n_oe=pass_oe, n_oe_n=1)
            if wp < GARBAGE_WP:
                c.update(g=1, g_db=dropback, g_pass_yds=0.0 if sack or not dropback else yards)
        if dropback and not sack:
            c["pass_yds"] = yards
        self._bump(week, team, **c)
        yardline = _f(r.get("yardline_100"))
        drive = r.get("fixed_drive")
        if yardline is not None and yardline <= RED_ZONE and drive:
            self.rz[(week, team, drive)] = r.get("fixed_drive_result", "")

    def result(self) -> dict:
        for (week, team, _drive), outcome in self.rz.items():
            self._bump(week, team, rz_trips=1, rz_td=outcome == "Touchdown")
        return {k: {m: round(v, 3) for m, v in d.items()} for k, d in self.t.items()}


# --------------------------------------------------------------------------- per-team numbers
def _rate(num: float, den: float) -> float | None:
    return num / den if den else None


def line(c: dict | None) -> dict:
    """One offense's derived rates for a game (None where there is no sample)."""
    c = c or {}
    def g(k: str) -> float:
        return c.get(k, 0.0)

    return {
        "plays": int(g("plays")), "neutral_plays": int(g("n")), "early_plays": int(g("ed")), "dropbacks": int(g("db")),
        "early_success": _rate(g("ed_succ"), g("ed")) if g("ed") >= MIN_EARLY else None,
        "neutral_epa": _rate(g("n_epa"), g("n")) if g("n") >= MIN_NEUTRAL else None,
        "neutral_success": _rate(g("n_succ"), g("n")) if g("n") >= MIN_NEUTRAL else None,
        "proe": _rate(g("n_oe"), g("n_oe_n")) if g("n_oe_n") >= MIN_NEUTRAL else None,
        "pressure_allowed": _rate(g("hit"), g("db")) if g("db") >= MIN_DROPBACKS else None,
        "sacks": int(g("sack")), "pressures": int(g("hit")),
        "turnovers": int(g("int") + g("fum_lost")), "interceptions": int(g("int")),
        "fumbles": int(g("fum")), "fumbles_lost": int(g("fum_lost")),
        "third_long": int(g("t3l")), "third_long_conv": int(g("t3lc")),
        "third": int(g("t3")), "third_conv": int(g("t3c")),
        "rz_trips": int(g("rz_trips")), "rz_td": int(g("rz_td")),
        "nonoff_td": int(g("nonoff_td")),
        "garbage_plays": int(g("g")), "garbage_share": _rate(g("g"), g("plays")),
        "garbage_pass_yds": g("g_pass_yds"), "pass_yds": g("pass_yds"),
    }


def league_baselines(counts: dict[str, dict], through_week: int) -> dict:
    """Season-to-date league rates through `through_week`, from every team-game's offense counts."""
    s: dict[str, float] = {}
    for key, c in counts.items():
        if int(key.split("|")[0]) > through_week:
            continue
        for k, v in c.items():
            s[k] = s.get(k, 0.0) + v
    return {"pressure": _rate(s.get("hit", 0), s.get("db", 0)), "early_success": _rate(s.get("ed_succ", 0), s.get("ed", 0)),
            "rz_td": _rate(s.get("rz_td", 0), s.get("rz_trips", 0)), "third_long": _rate(s.get("t3lc", 0), s.get("t3l", 0))}


def _pct(v: float | None, d: int = 0) -> str:
    return "-" if v is None else f"{v * 100:.{d}f}%"


# --------------------------------------------------------------------------- one game
def _noise(team: str, opp: str, t: dict, o: dict, lg: dict) -> list[tuple[int, str, str]]:
    """(+1 helped `team` / -1 hurt / 0 inflated its numbers, short label, sentence) for each situational swing."""
    out: list[tuple[int, str, str]] = []
    margin = o["turnovers"] - t["turnovers"]
    if abs(margin) >= TURNOVER_SWING:
        tail = "a swing that rarely repeats" if margin > 0 else "costly, and it regresses"
        out.append((1 if margin > 0 else -1, "turnover margin",
                    f"Turnover margin {margin:+d} for {team} ({t['turnovers']} giveaways, {o['turnovers']} takeaways): {tail}."))
    if t["fumbles"] >= 2 and (t["fumbles_lost"] == t["fumbles"] or t["fumbles_lost"] == 0):
        lost = t["fumbles_lost"] == t["fumbles"]
        verb = "lost all" if lost else "recovered all"
        out.append((-1 if lost else 1, "fumble recoveries",
                    f"{team} {verb} {t['fumbles']} of its own fumbles; recoveries are close to a coin flip."))
    if o["fumbles"] >= 2 and (o["fumbles_lost"] == o["fumbles"] or o["fumbles_lost"] == 0):
        got = o["fumbles_lost"] == o["fumbles"]
        out.append((1 if got else -1, "fumble recoveries", f"{opp} fumbled {o['fumbles']} times and {team} recovered {o['fumbles_lost']}: luck of the bounce."))
    if t["nonoff_td"]:
        out.append((1, "a defensive or special-teams touchdown", f"{team} scored {t['nonoff_td']} defensive or special-teams touchdown{'s' if t['nonoff_td'] > 1 else ''} -- points the offense didn't earn."))
    if o["nonoff_td"]:
        out.append((-1, "a defensive or special-teams touchdown against", f"{opp} scored {o['nonoff_td']} defensive or special-teams touchdown{'s' if o['nonoff_td'] > 1 else ''} against {team}'s offense."))
    if t["rz_trips"] >= RZ_TRIPS:
        rate = t["rz_td"] / t["rz_trips"]
        if rate >= RZ_HIGH or rate <= RZ_LOW:
            out.append((1 if rate >= RZ_HIGH else -1, "red-zone variance",
                        f"Red-zone touchdowns on {t['rz_td']} of {t['rz_trips']} trips ({_pct(rate)}; league {_pct(lg.get('rz_td'))}): red-zone rates swing hard week to week."))
    if t["third_long"] >= LONG_TRIES:
        rate = t["third_long_conv"] / t["third_long"]
        if rate >= LONG_HIGH or t["third_long_conv"] == 0:
            out.append((1 if rate >= LONG_HIGH else -1, "third-and-long conversions",
                        f"Converted {t['third_long_conv']} of {t['third_long']} third downs needing {LONG_TO_GO}+ yards (league {_pct(lg.get('third_long'))}): the stat that regresses fastest."))
    if (t["garbage_share"] or 0) >= GARBAGE_SHARE and t["garbage_plays"] >= 8:
        yards = f", including {t['garbage_pass_yds']:.0f} of its {t['pass_yds']:.0f} passing yards" if t["pass_yds"] else ""
        sentence = (f"{t['garbage_plays']} of {team}'s {t['plays']} plays ({_pct(t['garbage_share'])}) came with under "
                    f"{GARBAGE_WP:.0%} win probability{yards}: empty-calorie volume.")
        out.append((0, "garbage-time volume", sentence))
    return out


def _signal(team: str, opp: str, t: dict, o: dict, lg: dict) -> list[str]:
    out: list[str] = []
    if t["early_success"] is not None:
        verdict = ("structurally sound" if t["early_success"] >= EARLY_DOWN_SOUND
                   else "poor" if t["early_success"] < EARLY_DOWN_POOR else "middling")
        out.append(f"Early-down success {_pct(t['early_success'])} on {t['early_plays']} plays ({verdict}; {_pct(EARLY_DOWN_SOUND)}+ is sound, league {_pct(lg.get('early_success'))}).")
    if t["neutral_epa"] is not None:
        vs = f" vs {o['neutral_epa']:+.2f} for {opp}" if o["neutral_epa"] is not None else ""
        out.append(f"Neutral-script EPA per play {t['neutral_epa']:+.2f}{vs} ({t['neutral_plays']} plays at 20-80% win probability).")
    if t["proe"] is not None:
        out.append(f"Passed {t['proe']:+.1f} points {'over' if t['proe'] >= 0 else 'under'} expectation when the game was undecided.")
    if t["pressure_allowed"] is not None and lg.get("pressure") is not None:
        gap = t["pressure_allowed"] - lg["pressure"]
        feel = "a weakness" if gap >= PRESSURE_GAP else "a strength" if gap <= -PRESSURE_GAP else "about average"
        out.append(f"Line allowed a sack or QB hit on {_pct(t['pressure_allowed'])} of dropbacks (league {_pct(lg['pressure'])}): {feel}. "
                   f"{t['sacks']} sack{'s' if t['sacks'] != 1 else ''} on {t['pressures']} pressures.")
    if o["pressure_allowed"] is not None and lg.get("pressure") is not None:
        gap = o["pressure_allowed"] - lg["pressure"]
        if abs(gap) >= PRESSURE_GAP:
            out.append(f"Pass rush got to {opp}'s QB on {_pct(o['pressure_allowed'])} of dropbacks (league {_pct(lg['pressure'])}): "
                       f"{'sustained pressure' if gap > 0 else 'little pressure'}, {o['sacks']} sack{'s' if o['sacks'] != 1 else ''} on {o['pressures']} pressures"
                       f"{' -- the sacks will follow' if gap > 0 and o['sacks'] == 0 else ''}.")
    return out


def game_recap(game, counts: dict, lg: dict) -> dict | None:
    """One finished game's audit, or None without play-by-play counts for both teams."""
    ctx = game.context
    wk = game.week
    ca, ch = counts.get(f"{wk}|{game.away}"), counts.get(f"{wk}|{game.home}")
    if not ca or not ch or not ctx or ctx.away_score is None or ctx.home_score is None:
        return None
    la, lh = line(ca), line(ch)
    scores = {game.away: ctx.away_score, game.home: ctx.home_score}
    lines = {game.away: la, game.home: lh}
    opp = {game.away: game.home, game.home: game.away}
    teams: dict[str, dict] = {}
    for team in (game.away, game.home):
        t, o = lines[team], lines[opp[team]]
        margin = scores[team] - scores[opp[team]]
        nm = t["neutral_epa"] - o["neutral_epa"] if t["neutral_epa"] is not None and o["neutral_epa"] is not None else None
        noise = _noise(team, opp[team], t, o, lg)
        luck = sum(sign for sign, _, _ in noise)
        tag, reason = "steady", ""
        if nm is not None:
            if nm >= EPA_GAP and (margin <= 0 or (margin <= CLOSE_MARGIN and luck <= -1)):
                tag = "ascending"
                reason = (f"{'Lost' if margin < 0 else 'Tied' if margin == 0 else 'Won'} {scores[team]}-{scores[opp[team]]} but led the neutral-script EPA "
                          f"per play by {nm:+.2f}" + (f", with the bounces against it ({', '.join(label for sign, label, _ in noise if sign < 0)})" if luck <= -1 else "") + ".")
            elif nm <= -EPA_GAP and (margin >= 0 or (margin >= -CLOSE_MARGIN and luck >= 1)):
                tag = "fragile"
                reason = (f"{'Won' if margin > 0 else 'Tied' if margin == 0 else 'Lost'} {scores[team]}-{scores[opp[team]]} while trailing the neutral-script EPA "
                          f"per play by {nm:+.2f}" + (f", helped by the bounces ({', '.join(label for sign, label, _ in noise if sign > 0)})" if luck >= 1 else "") + ".")
        teams[team] = {
            "score": scores[team], "tag": tag, "reason": reason, "neutral_margin": None if nm is None else round(nm, 3), "luck": luck,
            "signal": _signal(team, opp[team], t, o, lg),
            "noise": [sentence for _, _, sentence in noise],
            "stats": {k: (round(v, 3) if isinstance(v, float) else v) for k, v in t.items()
                      if k in ("early_success", "neutral_epa", "proe", "pressure_allowed", "turnovers", "rz_trips", "rz_td", "third_long", "third_long_conv", "garbage_share")},
        }
    winner = max(scores, key=scores.get) if scores[game.away] != scores[game.home] else None
    verdict, tone = "Tied", "neutral"
    if winner:
        loser = opp[winner]
        nm = teams[winner]["neutral_margin"]
        if nm is None:
            verdict, tone = "Result stands (thin sample)", "neutral"
        elif nm >= EPA_GAP:
            verdict, tone = "Earned it", "good"
        elif nm <= -EPA_GAP:
            verdict, tone = ("Won on luck", "warn") if teams[winner]["luck"] >= 1 else ("Won despite worse play", "warn")
        else:
            verdict, tone = "Toss-up game", "neutral"
        teams[winner]["won"], teams[loser]["won"] = True, False
    return {"game_id": game.game_id, "away": game.away, "home": game.home, "kickoff_et": game.kickoff_et,
            "away_score": ctx.away_score, "home_score": ctx.home_score,
            "home_spread": ctx.home_spread, "total_line": ctx.total_line,
            "verdict": verdict, "tone": tone, "teams": teams}


# --------------------------------------------------------------------------- the week
def _all_games(sched) -> list:
    """Every game of a week once (an isolated game is listed in both lists)."""
    return list({g.game_id: g for g in list(sched.games) + list(sched.isolated_games)}.values())


def _next_game(sched, team: str) -> dict | None:
    """This week's game for `team`: opponent, side, the team's spread, kickoff, and the score if it's already final."""
    for g in _all_games(sched):
        if team in (g.away, g.home):
            home = g.home == team
            ctx = g.context
            spread = (ctx.home_spread if home else ctx.away_spread) if ctx else None
            final = bool(ctx and ctx.is_final and ctx.away_score is not None and ctx.home_score is not None)
            return {"opponent": g.away if home else g.home, "home": home, "spread": spread, "kickoff_et": g.kickoff_et,
                    "final": final, "team_score": (ctx.home_score if home else ctx.away_score) if final else None,
                    "opponent_score": (ctx.away_score if home else ctx.home_score) if final else None}
    return None


@memoize_async(600)
async def week_recap(season: int, week: int) -> dict:
    """The recap of `week` (finished games only), with this week's opponent for each flagged team."""
    from app import slates
    out: dict = {"season": season, "week": week, "available": False, "games": [], "ascending": [], "fragile": [],
                 "unavailable": UNAVAILABLE}
    sched, _ = await slates.list_slates(season, week)
    finals = [g for g in _all_games(sched) if g.context and g.context.is_final]
    if not finals:
        out["note"] = f"No Week {week} games are final yet."
        return out
    agg = await nc.get_pbp_aggregates(season)
    counts = agg.get("recap") or {}
    if not counts:
        out["note"] = "Play-by-play for these games isn't published yet (nflverse updates within a day)."
        return out
    lg = league_baselines(counts, week)
    games = [r for g in sorted(finals, key=lambda g: g.kickoff_utc) if (r := game_recap(g, counts, lg))]
    try:
        nxt, _ = await slates.list_slates(season, week + 1)
    except Exception:
        nxt = None
    flagged = {"ascending": [], "fragile": []}
    for r in games:
        for team, d in r["teams"].items():
            if d["tag"] in flagged:
                entry = {"team": team, "opponent": r["home" if team == r["away"] else "away"], "reason": d["reason"],
                         "neutral_margin": d["neutral_margin"], "game_id": r["game_id"], "next": _next_game(nxt, team) if nxt else None}
                flagged[d["tag"]].append(entry)
    for entries in flagged.values():
        entries.sort(key=lambda e: -abs(e["neutral_margin"] or 0))
    out.update(available=bool(games), games=games, ascending=flagged["ascending"], fragile=flagged["fragile"],
               games_final=len(finals), games_total=len(_all_games(sched)))
    return out
