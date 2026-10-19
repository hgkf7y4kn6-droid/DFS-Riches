"""Game model v2: totals and spreads as corrections to the closing market line, fit on 2023-2025.

Why a correction to the line: the closing total misses by ~10 points on average, but it already holds most of
what is knowable. The model predicts that miss -- the total's (actual - line) and the home margin's (actual -
spread) -- from what the market may underweight:

  * every team rate starts from last season, regressed halfway to the league, and moves toward this season's
    numbers as plays accumulate (no more one-game samples in week 2);
  * the passing offense is the starting quarterback's own dropback EPA (all teams, last season and this one),
    so a backup starter changes the forecast;
  * offensive-line starters ruled out (the five linemen with the most snaps over the team's last three games),
    alone and against the opponent's pressure;
  * quick pressure: pressure in 2.5 s or less from four or fewer rushers (nflverse participation data, 2023-2025;
    this season falls back on last season's rate plus sacks/hits on four-man rushes from FTN charting);
  * pace, drive length, pass rate over expected, explosive plays, success rates, wind and roof, rest, and the
    share of games each offense scored 24+.

scripts/train_game_model.py builds the same features for every 2023-2025 game, fits ridge regressions (the
penalty chosen by leaving one season out) and writes data/game_model.json: the weights, the feature scaling,
2025 end-of-season priors for live use, and the out-of-sample records. Live, predict() adds the fitted
correction to DraftKings' current line.
"""
from __future__ import annotations

import json
import math
import statistics
from pathlib import Path
from typing import Any

MODEL_FILE = Path(__file__).resolve().parent.parent / "data" / "game_model.json"

# Plays of evidence a team's prior is worth, per denominator.
K = {"plays": 250, "db": 160, "rush": 110, "drives": 45, "neutral": 160, "db4": 110, "qp_db": 160, "games": 4}
QB_K = 220                 # dropbacks a quarterback's prior is worth
REGRESS = 0.5              # last season's distance from the league kept as this season's prior
BACKUP_QB_EPA = -0.12      # a quarterback with no history starts this far below the league's dropback EPA
QUICK_SECS = 2.5


def _f(v) -> float | None:
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _i(v) -> int | None:
    x = _f(v)
    return int(x) if x is not None else None


def _secs(t: str | None) -> int | None:
    if not t or ":" not in t:
        return None
    m, s = t.split(":", 1)
    try:
        return int(m) * 60 + int(s)
    except ValueError:
        return None


def _neutral(r: dict) -> bool:
    q, sd, hs = _f(r.get("qtr")), _f(r.get("score_differential")), _f(r.get("half_seconds_remaining"))
    return q in (1, 2, 3) and sd is not None and abs(sd) <= 14 and hs is not None and hs > 120


# --------------------------------------------------------------------------- accumulation
class GameAccumulator:
    """Per team-week counts from nflverse play-by-play rows. team_of maps nflverse team codes to the caller's
    codes; ftn maps 'game_id|play_id' to pass rushers; part maps 'game_id|play_id' to (rushers, time to throw,
    pressure) from participation data."""

    OFF = ("plays", "succ", "db", "db_epa", "rush", "rush_epa", "expl", "drives", "drive_secs", "drive_plays",
           "neutral", "neutral_db", "proe", "proe_n", "db4", "hit4", "qp_db", "qp")

    def __init__(self, team_of=None, ftn: dict | None = None, part: dict | None = None):
        self.team_of = team_of or (lambda t: t)
        self.ftn, self.part = ftn or {}, part or {}
        self.off: dict[str, dict[str, float]] = {}
        self.de: dict[str, dict[str, float]] = {}
        self.qb: dict[str, dict[str, list]] = {}
        self._drives: set = set()

    @staticmethod
    def _bump(side: dict, key: str, counts: dict) -> None:
        d = side.setdefault(key, {})
        for k, v in counts.items():
            if v:
                d[k] = d.get(k, 0.0) + float(v)

    def add(self, r: dict) -> None:
        if r.get("season_type", "REG") != "REG":
            return
        week = _i(r.get("week"))
        team, opp = self.team_of(r.get("posteam") or ""), self.team_of(r.get("defteam") or "")
        if week is None or not team or not opp:
            return
        ok, dk = f"{week}|{team}", f"{week}|{opp}"
        c: dict[str, float] = {}
        drive = (r.get("game_id"), team, r.get("fixed_drive"))
        dt = _secs(r.get("drive_time_of_possession"))
        if r.get("fixed_drive") and dt is not None and drive not in self._drives:
            self._drives.add(drive)
            c.update(drives=1, drive_secs=dt, drive_plays=_f(r.get("drive_play_count")) or 0)
        if r.get("play_type") in ("pass", "run") and r.get("two_point_attempt") != "1" \
                and r.get("qb_kneel") != "1" and r.get("qb_spike") != "1":
            epa = _f(r.get("epa")) or 0.0
            c.update(plays=1, succ=r.get("success") == "1")
            if r.get("qb_dropback") == "1":
                sack, hit = r.get("sack") == "1", r.get("sack") == "1" or r.get("qb_hit") == "1"
                c.update(db=1, db_epa=epa, expl=(not sack) and (_f(r.get("yards_gained")) or 0) >= 20)
                key = f"{r.get('game_id')}|{_i(r.get('play_id'))}"
                rushers = self.ftn.get(key)
                if rushers is not None and 0 < rushers <= 4:
                    c.update(db4=1, hit4=hit)
                p = self.part.get(key)
                if p is not None:
                    pr, ttt, pressured = p
                    c.update(qp_db=1, qp=bool(pressured and ttt is not None and ttt <= QUICK_SECS and 0 < (pr or 0) <= 4))
                qid = r.get("id") or r.get("passer_player_id") or r.get("rusher_player_id")
                if qid:
                    q = self.qb.setdefault(ok, {}).setdefault(qid, [0, 0.0, r.get("name") or r.get("passer_player_name") or ""])
                    q[0] += 1
                    q[1] += epa
            elif r.get("rush") == "1":
                c.update(rush=1, rush_epa=epa)
            if _neutral(r):
                proe = _f(r.get("pass_oe"))
                c.update(neutral=1, neutral_db=r.get("qb_dropback") == "1",
                         proe=(proe or 0.0) / 100, proe_n=proe is not None)
        if not c:
            return
        self._bump(self.off, ok, c)
        self._bump(self.de, dk, {k: v for k, v in c.items() if k not in ("proe", "proe_n", "neutral", "neutral_db")})

    def result(self) -> dict:
        rnd = lambda side: {k: {m: round(v, 4) for m, v in d.items()} for k, d in side.items()}  # noqa: E731
        qb = {k: {q: [v[0], round(v[1], 3), v[2]] for q, v in d.items()} for k, d in self.qb.items()}
        return {"off": rnd(self.off), "def": rnd(self.de), "qb": qb}


# --------------------------------------------------------------------------- team rates
RATES = {  # name: (side, numerator, denominator)
    "pass_epa": ("off", "db_epa", "db"), "rush_epa": ("off", "rush_epa", "rush"), "success": ("off", "succ", "plays"),
    "explosive": ("off", "expl", "db"), "sec_per_drive": ("off", "drive_secs", "drives"),
    "sec_per_play": ("off", "drive_secs", "drive_plays"), "pass_rate": ("off", "neutral_db", "neutral"),
    "proe": ("off", "proe", "proe_n"), "pressure4_allowed": ("off", "hit4", "db4"), "quick_allowed": ("off", "qp", "qp_db"),
    "d_pass_epa": ("def", "db_epa", "db"), "d_rush_epa": ("def", "rush_epa", "rush"), "d_success": ("def", "succ", "plays"),
    "d_explosive": ("def", "expl", "db"), "d_pressure4": ("def", "hit4", "db4"), "d_quick": ("def", "qp", "qp_db"),
}
_K_FOR = {"plays": K["plays"], "db": K["db"], "rush": K["rush"], "drives": K["drives"], "drive_plays": K["plays"],
          "neutral": K["neutral"], "proe_n": K["neutral"], "db4": K["db4"], "qp_db": K["qp_db"]}


def season_totals(agg: dict, before_week: int | None = None) -> dict[str, dict[str, dict[str, float]]]:
    """{team: {"off": counts, "def": counts}} summed over the weeks before `before_week` (all weeks if None)."""
    out: dict[str, dict[str, dict[str, float]]] = {}
    for side in ("off", "def"):
        for key, counts in (agg.get(side) or {}).items():
            wk, team = key.split("|")
            if before_week is not None and int(wk) >= before_week:
                continue
            d = out.setdefault(team, {"off": {}, "def": {}})[side]
            for k, v in counts.items():
                d[k] = d.get(k, 0.0) + v
    return out


def raw_rates(totals: dict) -> tuple[dict[str, dict[str, float]], dict[str, float]]:
    """Each team's plain rates and the league's (pooled) rates."""
    teams: dict[str, dict[str, float]] = {}
    pooled: dict[str, list[float]] = {}
    for name, (side, num, den) in RATES.items():
        n = d = 0.0
        for team, t in totals.items():
            c = t[side]
            if c.get(den):
                teams.setdefault(team, {})[name] = c.get(num, 0.0) / c[den]
                n += c.get(num, 0.0)
                d += c[den]
        if d:
            pooled[name] = [n / d]
    return teams, {k: v[0] for k, v in pooled.items()}


# League rates for stats a season lacks (participation data starts in 2023): 2023-2025 averages.
DEFAULT_LEAGUE = {"quick_allowed": 0.041, "d_quick": 0.041, "pressure4_allowed": 0.136, "d_pressure4": 0.136}


def priors_from_season(totals: dict) -> dict:
    """End-of-season priors for next season: each team's rates regressed halfway to the league."""
    teams, league = raw_rates(totals)
    for k, v in DEFAULT_LEAGUE.items():
        league.setdefault(k, v)
    pri = {t: {k: league[k] + REGRESS * (v - league[k]) for k, v in r.items() if k in league} for t, r in teams.items()}
    return {"teams": pri, "league": league}


def team_estimates(cur: dict, priors: dict) -> dict[str, dict[str, float]]:
    """Shrunk rates: (prior x K + this season's numerator) / (K + this season's denominator)."""
    league = priors["league"]
    out = {}
    for team in set(cur) | set(priors["teams"]):
        c = cur.get(team) or {"off": {}, "def": {}}
        p = priors["teams"].get(team, {})
        est = {}
        for name, (side, num, den) in RATES.items():
            if name not in league:
                continue
            k = _K_FOR.get(den, 150)
            prior = p.get(name, league[name])
            est[name] = (prior * k + c[side].get(num, 0.0)) / (k + c[side].get(den, 0.0))
        out[team] = est
    return out


def qb_history(*aggs: dict, before_week: int | None = None) -> dict[str, list[float]]:
    """{qb_id: [dropbacks, epa]} over whole seasons (earlier aggs) plus the last agg's weeks before `before_week`."""
    out: dict[str, list[float]] = {}
    for i, agg in enumerate(aggs):
        last = i == len(aggs) - 1
        for key, qbs in (agg.get("qb") or {}).items():
            if last and before_week is not None and int(key.split("|")[0]) >= before_week:
                continue
            for q, (n, e, _name) in qbs.items():
                h = out.setdefault(q, [0.0, 0.0])
                h[0] += n
                h[1] += e
    return out


def qb_estimate(hist: dict, qb_id: str | None, league_pass_epa: float) -> tuple[float, float]:
    """(shrunk dropback EPA, dropbacks of evidence) for a starter; an unknown QB starts at backup level."""
    n, e = hist.get(qb_id or "", (0.0, 0.0))
    prior = league_pass_epa + BACKUP_QB_EPA
    return (prior * QB_K + e) / (QB_K + n), n


# --------------------------------------------------------------------------- game features
TOTAL_FEATURES = ("line", "qb_epa", "rush_epa", "d_pass_epa", "d_rush_epa", "success", "explosive", "pace",
                  "drive_secs", "proe", "pressure4", "quick_pressure", "ol_out", "ol_out_x_pressure", "wind",
                  "indoor", "floor24", "qb_unknown")
MARGIN_FEATURES = ("line", "qb_epa", "rush_epa", "d_pass_epa", "d_rush_epa", "success", "pressure4",
                   "quick_pressure", "ol_out", "ol_out_x_pressure", "rest", "qb_unknown", "floor24")


def game_features(away: str, home: str, est: dict, league: dict, *, total_line: float | None, spread_line: float | None,
                  qb: dict[str, tuple[float, float]], ol_out: dict[str, int], wind: float | None, indoor: bool,
                  rest: tuple[float | None, float | None], floor24: dict[str, float]) -> tuple[dict, dict] | None:
    """(total features, margin features) for one game. spread_line: the home team's expected margin."""
    a, h = est.get(away), est.get(home)
    if not a or not h:
        return None
    lg = league
    qa, qh = qb.get(away, (a["pass_epa"], 0)), qb.get(home, (h["pass_epa"], 0))

    def press(o, d, key_o, key_d):
        return (d[key_d] - lg[key_d]) + (o[key_o] - lg[key_o])

    p4a, p4h = press(a, h, "pressure4_allowed", "d_pressure4"), press(h, a, "pressure4_allowed", "d_pressure4")
    qpa, qph = press(a, h, "quick_allowed", "d_quick"), press(h, a, "quick_allowed", "d_quick")
    ola, olh = ol_out.get(away, 0), ol_out.get(home, 0)
    unk = lambda t, q: 1.0 if q[1] < 100 else 0.0  # noqa: E731
    tot = {
        "line": total_line or 0.0,
        "qb_epa": qa[0] + qh[0], "rush_epa": a["rush_epa"] + h["rush_epa"],
        "d_pass_epa": a["d_pass_epa"] + h["d_pass_epa"], "d_rush_epa": a["d_rush_epa"] + h["d_rush_epa"],
        "success": a["success"] + h["success"] + a["d_success"] + h["d_success"],
        "explosive": a["explosive"] + h["explosive"] + a["d_explosive"] + h["d_explosive"],
        "pace": -(a["sec_per_play"] + h["sec_per_play"]), "drive_secs": -(a["sec_per_drive"] + h["sec_per_drive"]),
        "proe": a["proe"] + h["proe"], "pressure4": p4a + p4h, "quick_pressure": qpa + qph,
        "ol_out": ola + olh, "ol_out_x_pressure": ola * max(qpa, 0) + olh * max(qph, 0),
        "wind": 0.0 if indoor else (wind or 0.0), "indoor": 1.0 if indoor else 0.0,
        "floor24": floor24.get(away, 0.0) * floor24.get(home, 0.0), "qb_unknown": unk(away, qa) + unk(home, qh),
    }
    mar = {
        "line": spread_line or 0.0,
        "qb_epa": (qh[0] - a["d_pass_epa"]) - (qa[0] - h["d_pass_epa"]),
        "rush_epa": h["rush_epa"] - a["rush_epa"], "d_pass_epa": a["d_pass_epa"] - h["d_pass_epa"],
        "d_rush_epa": a["d_rush_epa"] - h["d_rush_epa"],
        "success": (h["success"] - h["d_success"]) - (a["success"] - a["d_success"]),
        "pressure4": p4a - p4h, "quick_pressure": qpa - qph, "ol_out": ola - olh,
        "ol_out_x_pressure": ola * max(qpa, 0) - olh * max(qph, 0),
        "rest": (rest[1] or 7) - (rest[0] or 7), "qb_unknown": unk(away, qa) - unk(home, qh),
        "floor24": floor24.get(home, 0.0) - floor24.get(away, 0.0),
    }
    return tot, mar


# --------------------------------------------------------------------------- ridge
def fit_ridge(X: list[list[float]], y: list[float], alpha: float) -> tuple[list[float], list[float], list[float], float]:
    """Standardized ridge: (weights, means, sds, intercept). Pure Python (small problems only)."""
    n, p = len(X), len(X[0])
    means = [statistics.fmean(r[j] for r in X) for j in range(p)]
    sds = [statistics.pstdev([r[j] for r in X]) or 1.0 for j in range(p)]
    Z = [[(r[j] - means[j]) / sds[j] for j in range(p)] for r in X]
    ym = statistics.fmean(y)
    A = [[sum(Z[i][a] * Z[i][b] for i in range(n)) + (alpha if a == b else 0.0) for b in range(p)] for a in range(p)]
    bvec = [sum(Z[i][a] * (y[i] - ym) for i in range(n)) for a in range(p)]
    w = _solve(A, bvec)
    return w, means, sds, ym


def _solve(A: list[list[float]], b: list[float]) -> list[float]:
    n = len(b)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for c in range(n):
        piv = max(range(c, n), key=lambda r: abs(M[r][c]))
        M[c], M[piv] = M[piv], M[c]
        for r in range(n):
            if r != c and M[c][c]:
                f = M[r][c] / M[c][c]
                M[r] = [x - f * y for x, y in zip(M[r], M[c])]
    return [M[i][n] / M[i][i] if M[i][i] else 0.0 for i in range(n)]


def apply(model: dict, feats: dict) -> float:
    x = [feats[k] for k in model["features"]]
    return model["intercept"] + sum(w * (v - m) / s for w, v, m, s in zip(model["weights"], x, model["means"], model["sds"]))


# --------------------------------------------------------------------------- live use
_MODEL: dict | None = None


def load() -> dict | None:
    global _MODEL
    if _MODEL is None and MODEL_FILE.exists():
        _MODEL = json.loads(MODEL_FILE.read_text())
    return _MODEL


def predict(tot_feats: dict, mar_feats: dict) -> dict | None:
    """{"total_adj", "margin_adj"}: the fitted corrections (points) to the market total and home margin."""
    m = load()
    if not m:
        return None
    return {"total_adj": round(apply(m["total"], tot_feats), 2), "margin_adj": round(apply(m["margin"], mar_feats), 2)}


def floor_share(points: dict[tuple[int, str], int], prior: dict[str, float], team: str, week: int,
                k: int = K["games"]) -> float:
    """Share of games a team scored 24+, last season's share as a prior worth k games."""
    games = [p for (w, t), p in points.items() if t == team and w < week]
    return (prior.get(team, 0.4) * k + sum(p >= 24 for p in games)) / (k + len(games))


def records_summary(m: dict | None = None) -> dict[str, Any] | None:
    m = m or load()
    return m and {k: m.get(k) for k in ("trained_on", "records", "checklist")}


# --------------------------------------------------------------------------- weekly audit checklist
CHECKLIST = (
    ("trench", "Trench check: neither defense has a quick-pressure edge over the opposing line", "Under"),
    ("funnel", "Funnel check: a pass-heavy offense faces a top-8 run defense", "Over"),
    ("drive_velocity", "Drive velocity: explosive pass rates vs seconds per drive in the top third", "Over"),
    ("playcaller", "Playcaller audit: combined pass rate over expected in the top third", "Over"),
    ("separation", "Skill separation: WR route win rate vs boundary CBs", None),
    ("scoring_floor", "Scoring floor: both offenses score 24+ in 60%+ of games", "Over"),
    ("pace", "Pace filter: combined seconds per snap in the fastest third", "Over"),
)


def _dv(a: dict, h: dict) -> float:
    return (a["explosive"] + h["explosive"]) / (a["sec_per_drive"] + h["sec_per_drive"])


def _quick_edges(a: dict, h: dict, lg: dict) -> tuple[float, float]:
    """(home defense vs away line, away defense vs home line): quick-pressure rate above league plus the
    line's quick pressure allowed above league."""
    return ((h["d_quick"] - lg["d_quick"]) + (a["quick_allowed"] - lg["quick_allowed"]),
            (a["d_quick"] - lg["d_quick"]) + (h["quick_allowed"] - lg["quick_allowed"]))


def checklist_flags(a: dict, h: dict, lg: dict, tot: dict, cuts: dict) -> dict[str, bool | None]:
    """Which audit items a game triggers (None = no data). cuts come from the training seasons."""
    funnel = any(o["pass_rate"] >= cuts["pass_rate"] and d["d_rush_epa"] <= cuts["run_def"] for o, d in ((a, h), (h, a)))
    return {
        "trench": max(_quick_edges(a, h, lg)) >= cuts["quick_edge"],
        "funnel": funnel,
        "drive_velocity": _dv(a, h) >= cuts["drive_velocity"],
        "playcaller": tot["proe"] >= cuts["proe"],
        "separation": None,
        "scoring_floor": tot["floor24"] >= 0.36,
        "pace": tot["pace"] >= cuts["pace"],
    }


def checklist(a: dict, h: dict, lg: dict, tot: dict, model: dict | None = None) -> list[dict] | None:
    """The audit for one game: each item, whether it fires, which way it points and its record."""
    m = model or load()
    if not m or "checklist_cuts" not in m:
        return None
    flags = checklist_flags(a, h, lg, tot, m["checklist_cuts"])
    rec = (m.get("checklist") or {}).get("train", {})
    out = []
    for key, label, call in CHECKLIST:
        r = rec.get(key) or {}
        out.append({"id": key, "label": label, "flag": flags[key], "call": call,
                    "record": {"hit": r.get("hit"), "n": r.get("n"), "pct": r.get("pct")} if r else None})
    return out


# --------------------------------------------------------------------------- live
BREAK_EVEN = 0.524          # a side has to win this often at -110 to pay
OL_POSITIONS = ("OL", "T", "G", "C")


async def _ol_snaps(season: int) -> dict[tuple[int, str], dict[str, float]]:
    """{(week, nflverse team): {lineman: offense snaps}} from nflverse snap counts."""
    import csv
    import io

    from app import nflverse_client as nc
    from app.cache import cached_fetch
    from app.config import NFLVERSE_SNAP_COUNTS_URL_TMPL, TTL_NFLVERSE_TEAM_STATS

    async def fetch() -> list[list]:
        text = await nc._fetch_csv_text(NFLVERSE_SNAP_COUNTS_URL_TMPL.format(season=season))
        return [[int(r["week"]), r["team"], r["player"], _f(r.get("offense_snaps")) or 0.0]
                for r in csv.DictReader(io.StringIO(text)) if r.get("position") in OL_POSITIONS and r.get("game_type", "REG") == "REG"]

    try:
        rows = await cached_fetch(f"nflverse_snap_ol_{season}", TTL_NFLVERSE_TEAM_STATS, fetch)
    except Exception:
        rows = []
    out: dict[tuple[int, str], dict[str, float]] = {}
    for w, t, p, s in rows:
        out.setdefault((w, t), {})[p] = s
    return out


def ol_starters(snaps: dict, team: str, week: int) -> list[str]:
    """The five linemen with the most snaps over the team's last three games before `week`."""
    tot: dict[str, float] = {}
    for w in sorted({w for (w, t) in snaps if t == team and w < week})[-3:]:
        for p, s in snaps[(w, team)].items():
            tot[p] = tot.get(p, 0.0) + s
    return sorted(tot, key=lambda p: -tot[p])[:5]


def ol_out_played(snaps: dict, team: str, week: int) -> int:
    starters, played = ol_starters(snaps, team, week), snaps.get((week, team))
    return sum(1 for p in starters if (played.get(p) or 0) <= 0) if starters and played is not None else 0


async def week_games(season: int, week: int, lines: dict[str, tuple[float | None, float | None]] | None = None,
                     wind: dict[str, float | None] | None = None, injuries: bool = True) -> dict[str, dict]:
    """{"AWAY@HOME" (app codes): forecast} for a week's games. lines: {"AWAY@HOME": (total, home expected margin)}
    to price against (default: nflverse's consensus line); wind: {"AWAY@HOME": mph} from the forecast.
    Linemen are 'out' when they played no snaps (finished games) or ESPN lists them Out/IR/Doubtful (upcoming)."""
    from app import injury_news
    from app import nflverse_client as nc
    from app.matching import normalize_name

    m = load()
    if not m:
        return {}
    agg = (await nc.get_pbp_aggregates(season)).get("game") or {}
    raw = await nc.get_games_raw(season)
    priors, lg = m["priors"], m["priors"]["league"]
    est = team_estimates(season_totals(agg, week), priors)
    hist = {q: list(v) for q, v in (m.get("qb_prior") or {}).items()}
    for q, (n, e) in qb_history(agg, before_week=week).items():
        h = hist.setdefault(q, [0.0, 0.0])
        h[0] += n
        h[1] += e
    snaps = await _ol_snaps(season)
    news = await injury_news.espn_statuses() if injuries else {}
    points = {}
    for r in raw:
        if r.get("game_type") == "REG" and r.get("home_score") not in (None, ""):
            points[(int(r["week"]), r["away_team"])] = int(r["away_score"])
            points[(int(r["week"]), r["home_team"])] = int(r["home_score"])
    out = {}
    for r in raw:
        if r.get("game_type") != "REG" or _i(r.get("week")) != week:
            continue
        a, h = r["away_team"], r["home_team"]
        key = f"{nc.to_app_team(a)}@{nc.to_app_team(h)}"
        total, margin = (lines or {}).get(key, (None, None))
        total = total if total is not None else _f(r.get("total_line"))
        margin = margin if margin is not None else _f(r.get("spread_line"))
        if total is None or margin is None or a not in est or h not in est:
            continue
        ol = {}
        for t in (a, h):
            if (week, t) in snaps:
                ol[t] = ol_out_played(snaps, t, week)
            else:
                ol[t] = sum(1 for p in ol_starters(snaps, t, week)
                            if (news.get((nc.to_app_team(t), normalize_name(p))) or {}).get("code") in ("OUT", "IR", "D"))
        qb = {t: qb_estimate(hist, r.get(f"{side}_qb_id"), lg["pass_epa"]) for t, side in ((a, "away"), (h, "home"))}
        w_mph = (wind or {}).get(key)
        feats = game_features(a, h, est, lg, total_line=total, spread_line=margin, qb=qb, ol_out=ol,
                              wind=w_mph if w_mph is not None else _f(r.get("wind")),
                              indoor=r.get("roof") in ("dome", "closed"), rest=(_f(r.get("away_rest")), _f(r.get("home_rest"))),
                              floor24={t: floor_share(points, m.get("floor_prior") or {}, t, week) for t in (a, h)})
        if not feats:
            continue
        p = predict(*feats)
        out[key] = {
            "total_line": total, "home_margin_line": margin, **p,
            "fair_total": round(total + p["total_adj"], 1), "fair_home_margin": round(margin + p["margin_adj"], 1),
            "qbs": {nc.to_app_team(t): {"name": r.get(f"{side}_qb_name"), "dropback_epa": round(qb[t][0], 3),
                                        "dropbacks": int(qb[t][1])} for t, side in ((a, "away"), (h, "home"))},
            "ol_out": {nc.to_app_team(t): n for t, n in ol.items()},
            # each offense's opponent: four-man sack + QB-hit rate above the league (shrunk toward last season)
            "opp_pressure": {nc.to_app_team(a): round(est[h]["d_pressure4"] - lg["d_pressure4"], 4),
                             nc.to_app_team(h): round(est[a]["d_pressure4"] - lg["d_pressure4"], 4)},
            "checklist": checklist(est[a], est[h], lg, feats[0], m),
            "final": None if r.get("home_score") in (None, "") else
            {"total": int(r["home_score"]) + int(r["away_score"]), "home_margin": int(r["home_score"]) - int(r["away_score"])},
        }
    return out


async def team_context(season: int, week: int) -> dict[str, dict]:
    """{app team: {"opp_pressure", "ol_out"}} for this week's offenses (app.player_model inputs)."""
    out = {}
    for g in (await _week_games_cached(season, week)).values():
        for t, n in g["ol_out"].items():
            out[t] = {"ol_out": n, "opp_pressure": g["opp_pressure"].get(t, 0.0)}
    return out


async def _week_games_impl(season: int, week: int) -> dict:
    return await week_games(season, week)


def _cached():
    from app.cache import memoize_async
    return memoize_async(600)(_week_games_impl)


_week_games_cached = _cached()


async def season_record(season: int, week: int) -> dict:
    """This season's out-of-sample record through `week` - 1 against nflverse's closing lines."""
    tot = mar = 0
    rt = rm = 0
    e_line_t, e_mod_t, e_line_m, e_mod_m = [], [], [], []
    for w in range(2, week):
        for g in (await week_games(season, w, injuries=False)).values():
            f = g["final"]
            if not f:
                continue
            yt, ym = f["total"] - g["total_line"], f["home_margin"] - g["home_margin_line"]
            e_line_t.append(abs(yt)); e_mod_t.append(abs(yt - g["total_adj"]))
            e_line_m.append(abs(ym)); e_mod_m.append(abs(ym - g["margin_adj"]))
            if yt and g["total_adj"]:
                tot += 1; rt += (g["total_adj"] > 0) == (yt > 0)
            if ym and g["margin_adj"]:
                mar += 1; rm += (g["margin_adj"] > 0) == (ym > 0)
    mean = lambda xs: round(statistics.fmean(xs), 2) if xs else None  # noqa: E731
    return {"games": len(e_line_t),
            "totals": {"right": rt, "n": tot, "pct": round(rt / tot, 3) if tot else None,
                       "mae_model": mean(e_mod_t), "mae_line": mean(e_line_t)},
            "spreads": {"right": rm, "n": mar, "pct": round(rm / mar, 3) if mar else None,
                        "mae_model": mean(e_mod_m), "mae_line": mean(e_line_m)}}


def trusted(m: dict | None = None) -> dict[str, bool]:
    """A market type is rated (beyond watchlist) only when the model's out-of-sample picks beat break-even."""
    m = m or load() or {}
    rec = m.get("records") or {}
    ok = lambda k: bool(((rec.get(k) or {}).get("cv") or {}).get("pct") and rec[k]["cv"]["pct"] >= BREAK_EVEN)  # noqa: E731
    return {"total": ok("total"), "spread": ok("margin")}
