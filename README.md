# DFSRiches

A DraftKings DFS explorer for the NFL, built with Python (FastAPI). It merges
**real DraftKings salaries** with **real Sleeper schedule/projection data**
for every Week 1 game, and automatically builds a **DraftKings Showdown
Captain Mode** slate for each isolated single-game broadcast window --
Wednesday Night, Thursday Night, Sunday Night, and Monday Night -- alongside
a **Classic Sunday Main** slate (DraftKings' Sunday 1:00 + afternoon games)
and a **Full Week** slate covering every game. A "Lines & Performance" table shows
each game's **real closing spread, over/under, and implied team totals**
(nflverse), plus each team's **pace of play vs. their own season baseline**
-- each with its own **trailing 3/6/9-game trend** -- and, once a game is
final, exactly how far the result landed above or below each of those
lines. The player table carries the same idea down to individual players:
alongside DraftKings' season FPPG, an **L3/L6/L9 trailing DK-style FPPG**
computed from real box-score history.

Inspired by [dk.ff-dashboard.com](https://dk.ff-dashboard.com/).

## How it works

```
Sleeper (schedule + projections)     DraftKings (draft groups + salaries)
        |                                       |
        v                                       v
  app/schedule.py                        app/dk_client.py
  - real kickoff time per game           - discovers the live "Upcoming"
  - classifies each game into a            Classic + Showdown draft groups
    day-part (SUN_EARLY, SUN_LATE,        for the week, matched to the
    WED_NIGHT, THU_NIGHT, SUN_NIGHT,       schedule by kickoff window
    MON_NIGHT, ...)                       - falls back to data/dk_overrides.json
  - flags a game "isolated" when it's       for slates that already started
    the only game in one of the             (see "Why the override file exists")
    Wed/Thu/Sun/Mon night windows          - parses Classic vs. Showdown
                                              (CPT @ 1.5x salary/points + FLEX)
        \                                       /
         \                                     /
          v                                   v
                    app/slates.py
        - Classic Sunday Main (Sunday 1:00 + afternoon games)
        - Full Week slate (every game, Thu-Mon)
        - one Showdown slate per isolated game
        - merges DK salaries with Sleeper player metadata by
          name (app/matching.py), since the two providers use
          unrelated id systems
        - Value = proj points / (salary / 1000)
                    |
                    v
              app/main.py (FastAPI)  -->  templates/index.html + static/app.js
```

### Data sources (all real, no fabricated data)

- **DraftKings** (`app/dk_client.py`): `GET /draftgroups/v1/` (live contest
  discovery) and `GET /draftgroups/v1/draftgroups/{id}/draftables` (salaries,
  positions, DK's own Fantasy-Points-Per-Game). Public, unauthenticated,
  undocumented -- the same endpoints DraftKings' own lobby uses.
- **Sleeper** (`app/sleeper_client.py`): `/v1/players/nfl` (player
  metadata), `/v1/state/nfl` (current season/week), `/scores/nfl/{type}/{season}/{week}`
  (real kickoff time + broadcaster per game, used to build the schedule).
  Also public and unauthenticated.
- **nflverse** (`app/nflverse_client.py`): `nflverse/nfldata`'s `games.csv`
  (real closing sportsbook spread/total lines and final scores, one row per
  game, every season) and `nflverse/nflverse-data`'s
  `stats_team_week_{season}.csv` (real per-team, per-game box-score stats,
  used for the pace-of-play baseline). Free, public, no API key, maintained
  by the open-source nfl-data community and updated within hours of each game.

### Why the override file exists

DraftKings' `/draftgroups/v1/` listing only returns contests that are still
"Upcoming" -- once a slate's games kick off, its `draftGroupId` disappears
from that listing, even though the `.../draftables` endpoint for that same
id keeps serving the (now-frozen) salary data. So live discovery works
perfectly for a slate that hasn't started yet, but a slate that already
started needs its `draftGroupId` remembered somewhere.

`data/dk_overrides.json` is that memory. The app tries live discovery
first, and only falls back to the override file when discovery comes up
empty. Each week is added by:

```bash
python -m scripts.record_draft_groups                 # Sleeper's current week
python -m scripts.record_draft_groups --season 2026 --week 4
```

It runs live discovery, checks that each group DraftKings lists actually has
salaried players (so a no-salary "Tournament"/"W3-W17" group can't slip
in), and records the Classic + Showdown ids for that week. Re-running is
safe: it leaves existing entries alone unless DraftKings' id changed. It has
to run after salaries post and before the week's first kickoff. A scheduled
job does this every Wednesday and Thursday (along with saving optimal
lineups, below) and commits the result, so each
new deploy carries every past week. 2026 Week 2 is missing because its
slates had already started before this was set up.

### Name matching

DraftKings and Sleeper use unrelated player-id systems, so `app/matching.py`
merges them by normalized name (`app.matching.normalize_name` strips
punctuation, hyphens, and suffixes like Jr./III), disambiguating collisions
by team and position, and special-casing team defenses (Sleeper keys those
by team abbreviation, not a person's name). A small manual alias map
(`data/name_aliases.json`) bridges the rare case where DraftKings' display
name and Sleeper's on-file name genuinely don't normalize to the same
string (e.g. DraftKings shows "Hollywood Brown" where Sleeper has him on
file as "Marquise Brown"). Players DraftKings lists that Sleeper has no
record of at all (backup/practice-squad players, mostly) show up in the
site's "unmatched" banner rather than being silently guessed at.

### Projections

**Proj** (`app/projections.py`) is DraftKings points from each player's
projected stat line for the week, in two steps:

1. **The line.** Sleeper's week-specific projection (rushing and receiving
   yards, receptions, TDs, passing, turnovers; sacks, takeaways and points
   allowed for DSTs) run through DraftKings' scoring. The 100/300-yard
   bonuses are left out: applied to a projected average they made
   projections run high.
2. **A slight matchup adjustment.** For each defense and position, it
   compares how many DK points opposing players actually scored against it
   earlier this season with what their lines projected. If a defense's RBs
   have beaten their projections, this week's RB projections go up a
   little, and vice versa. The adjustment is shrunk for small samples and
   capped at +/-5%.

Hover a Proj value to see the line and any adjustment. Players without a
line (kickers, deep backups) fall back to DraftKings' season FPPG, still
shown in its own column. Showdown Captain rows show salary and projections
at DraftKings' 1.5x multiplier.

Backtested against actual DK points (mean absolute error; lower is better):

| Projection | Players (2,950 player-games) | DSTs (416 team-games) |
|---|---|---|
| Proj: stat line -> DK points | **5.83** (bias +0.06) | **4.01** |
| Trailing 8-game DK average | 6.18 | 4.36 |
| Trailing 3-game DK average | 6.54 | - |

- **The matchup adjustment only helps when kept light.** On 2025, using only
  weeks before each game, the light version moved error from 5.716 to 5.709;
  stronger versions made it worse.
- **A player's own record is not used.** Adjusting on a player's own
  performance vs his projections made projections worse in every setting,
  because streaks mostly regress, so it isn't applied.

**Projected role:** a QB/RB/WR/TE projected under 3 DK points has no real
role this week (a backup or inactive), whatever last season's numbers say.
Their Ceiling is halved with the reason shown, and they're never picked as
targets or for optimal lineups.

The **Sleeper Proj** column is still Sleeper's own PPR total, from
`api.sleeper.com/projections` (the endpoint Sleeper's own app uses; the
public `api.sleeper.app/v1/projections` returns empty stats).

### Hiding injured players

The **Injury status** menu above the player table filters the pool: **All players**, **Hide Out, IR & Doubtful** (keeps Questionable players, who usually play), or **Healthy only**. It shows how many players are hidden, combines with the position and search filters, and is remembered in your browser. Players already in one of your lineups stay there even if hidden.

### Tempo and pass rate (checked against Sharp Football)

"Pace" on the Week Breakdown page and in the Ceiling is **neutral tempo**:
seconds of game clock from snap to snap, from nflverse play-by-play. It only
counts gaps where the previous play kept the clock running (a run or
completed pass that stayed in bounds, no penalty or timeout), adjusted for
the league's typical gap after a run vs a completion. Neutral means quarters
1-3, within 14 points, outside the last two minutes of the half, which is
Sharp Football's definition. **Neutral pass rate** is the dropback rate (sacks and
scrambles count as passes) in the same situations. For defenses, the same
rate for the offenses they faced drives the pass/rush funnel flags. Both use
season-to-date numbers once a team has played 2 games, since schemes change
with coordinators, and the last 8 games before that. Plays/game is still
shown, but as volume: it also reflects possessions, defense and game script.

Checked against Sharp Football's 2026 Week 3 team pace and matchup pages:

| Metric | Match with Sharp |
|---|---|
| Neutral pass rate | 0.98 rank correlation, within 0.7 pts on average (NO 65.8% in both) |
| Neutral tempo | 0.84 rank correlation with Sharp's neutral play clock used (NO 1st, CAR 3rd vs 2nd) |
| Plays/game | 0.99, within 1 play/game (we count sacks as plays) |
| Yards/play (offense / defense) | 0.66-0.83 / 0.65-0.69 vs Sharp's opponent-adjusted efficiency ranks |

Sharp's play clock comes from tracking data that nflverse doesn't publish
(its `play_clock` column is always 0), hence game-clock tempo. The old
plays/game "pace" matched Sharp's tempo at only 0.28. For example,
Carolina and Las Vegas play fast but run few plays per game. The Lines &
Performance table's plays-vs-baseline column is labeled as volume for the
same reason.

### Ceiling

The **Ceiling** column estimates each player's 85th-percentile DraftKings
score this week, a score they'd reach or beat about one game in seven
(`app/ceiling.py`). Hover a value to see exactly how it was built:

- **History:** the player's last 12 games (nflverse box scores through DK
  scoring), recency-weighted so each older game counts 15% less, as mean +
  1.04 x spread. Small samples are pulled toward the position's typical
  game-to-game variability, measured from the same data.
- **Matchup:** DK points the opponent allowed to that position over its last
  8 games vs the league average. For DSTs, it's the opponent offense's
  points scored instead.
- **Game environment:** the team's implied total vs the slate average (for
  DSTs, the opponent's implied total, inverted).
- **Week Breakdown flags:** the same signals the breakdown page raises: pass
  funnel (QB/WR/TE), rush funnel (RB), both offenses top-10 pace, and a
  yards/play efficiency mismatch.
- **Team utilization:** the player's share of team targets + carries over
  the last 3 games vs the last 8 (RB/WR/TE), so a growing role raises the
  ceiling.

Each factor is shrunk toward neutral and capped at about ±15%. Their
combined effect is capped at -20%/+25%, since matchup and implied total
partly measure the same thing. Showdown Captain ceilings are 1.5x. Early in
the season a hot starter's "Proj" (DK's season FPPG over just a couple of
games) can sit slightly above their Ceiling. Lineup cards also total each
lineup's ceiling.

### Optimal lineups

Every slate shows two **optimal lineups** above your own in the lineup
builder: one maximizing total Proj and one maximizing total Ceiling. They
come from an exact integer-program solver (`app/optimizer.py`, SciPy/HiGHS)
under DraftKings' real rules:

- **Classic:** QB, 2-3 RB, 3-4 WR, 1-2 TE, DST, $50,000 cap, at least 2
  games.
- **Showdown:** CPT + 5 FLEX, $50,000 cap, no player in both slots, both
  teams.

Only players who are Healthy or Questionable and have played this season
are eligible. "Copy to my lineups" turns one into an editable lineup.

They're saved for later reference in `data/optimal_lineups.json`
(`app/optimal.py`):

- **Before kickoff:** until a slate's first game starts, they're
  recalculated live and the saved copy is updated whenever they change.
- **After kickoff:** the slate shows the frozen pre-kickoff copy, labeled
  with when it was saved. Live numbers after kickoff would already include
  the results, so they're never used.
- **After the games:** once every game in the slate is final and nflverse
  has posted its box scores, the saved record is scored. Each pre-kickoff
  lineup gets its actual DraftKings points (shown next to each player's
  projection, plus an Actual total), and a **Best possible (actual)**
  lineup is added: the optimal lineup on actual points, from the same
  salaries. Kickers in Showdown use DraftKings' kicker scoring (+1 PAT,
  +3/+4/+5 per field goal by distance).

The weekly job runs `python -m scripts.save_optimal_lineups` right after
recording the week's DraftKings ids and commits the file. Each run saves
the current week's pre-kickoff optimal lineups and scores the previous
week's results, so every week keeps both.
- **Weeks 1-2 of 2026:** no pre-kickoff lineups (they started before this
  existed). Week 1 still has best-possible lineups for its Full Week and
  Showdown slates. Week 2 and Week 1's Sunday Main have nothing, since
  their DraftKings ids were never recorded.
- **Late-week Showdowns:** Sunday and Monday night slates are saved as of
  the job's Wednesday/Thursday run. If the app is opened closer to those
  kickoffs, it also updates the copy on the running server, but only the
  committed file survives a redeploy.

### Lineup builder

On any slate, click a player row (or its **+** button) to add them to the
lineup you're editing; click again to remove them. Players drop into the
first open slot they're eligible for, following DraftKings' roster rules:

- **Classic:** QB, RB, RB, WR, WR, WR, TE, FLEX (RB/WR/TE), DST. A third RB,
  fourth WR, or second TE goes to FLEX.
- **Showdown:** CPT + 5 FLEX. A CPT row can only go in the CPT slot, and the
  same player can't be both CPT and FLEX.

You can build up to **5 lineups** per slate. They show side by side so you
can compare salary used, salary remaining, average salary per open slot,
total Proj, and total Sleeper Proj, with a "Top proj" tag on the
highest-projected one. Each lineup is checked against the $50,000 cap and
DraftKings' multi-game rule (Classic: at least 2 games; Showdown: both
teams). Click a lineup card to edit it. Each player row shows how many of
your lineups include them (e.g. "2/3"). Lineups are saved in your browser's
local storage per season/week/slate, so they survive a reload but aren't
shared across devices.

### Lines, implied totals, and pace of play

`app/game_context.py` attaches real betting/pace context to every game in
the schedule (nothing here is estimated or fabricated):

- **Spread**: nflverse's `spread_line`, which is published from the away
  team's perspective (negative = away favored). Sleeper's own schedule feed
  also carries a spread, but it disagreed with nflverse by 11.5 points on
  one 2026 Week 1 game while every other game matched within a point --
  nflverse is used as the source of truth since it's internally consistent
  across the whole slate.
- **Over/under**: nflverse's `total_line` directly.
- **Implied team total**: the total split around its midpoint by the
  spread, e.g. a 3-point favorite in a 44.5 total is implied for 23.8, the
  underdog for 20.8.
- **Pace of play**: a team's offensive plays run (pass attempts + rush
  attempts + sacks taken -- the standard simple "plays" pace stat) this
  game, compared against their own **season-to-date average** entering that
  week, or their **prior season's full-year average** in Week 1 when there's
  no current-season history yet.

Once a game is final, the table also shows:

- **ATS result**: `(home_score - away_score) + home_spread` -- positive
  means the home team beat the spread by that many points, negative means
  the away team did (0 is a push). It's shown with the covering team's
  actual line, e.g. "ATL +4.5 covered by 25.5" for a 4.5-point underdog
  that won 35-14, so the margin never reads like a spread. Hover for the
  score.
- **O/U result**: `(home_score + away_score) - total_line` -- positive
  means the game went over, negative means it went under. Shown as e.g.
  "Over by 5.5 (49 pts)".
- **Pace delta**: `actual_plays - baseline_plays` per team -- positive means
  they played faster (more plays) than their own baseline, negative means
  slower.

A game that hasn't kicked off (or finished) yet shows the pre-game lines
with the result columns blank rather than guessing.

### Trends: L3/L6/L9 everywhere

Every metric above -- spread, total, implied total, and pace -- also shows
a trailing 3/6/9-game trend as small text under the current value, in
away/home order (`app.nflverse_client.get_team_context_trailing_index` +
`team_trend`). These are a team's own history, independent of this specific
matchup, so they're shown whether or not the game has been played yet: "this
team has averaged being a 4-point favorite over their last 6 games" is
useful pre-game context, not a post-game grade. `_trailing_avg` (in
`app/nflverse_client.py`) is the shared piece: given a team's full
[season, week, value] history, it averages the N most recent entries
strictly before the target week, reaching back into the prior season if the
current one doesn't have N games yet, and just averaging what's available
if there's fewer than N games anywhere in the history.

The player table applies the identical idea to individual players: **L3 /
L6 / L9** columns next to DK FPPG, computed as a real DraftKings-style
fantasy score (`app/dk_scoring.py`, implementing DK's actual Classic scoring
rules -- yardage bonuses, PPR, points-allowed tiers for DST, etc.) from
nflverse's real box-score history (`stats_player_week_{season}.csv` for
offense, `stats_team_week_{season}.csv` + points allowed for DST), then run
through the same trailing-average logic. The join between a DK salary row
(already matched to a Sleeper player, see "Name matching" above) and
nflverse's per-game stats turned out not to be as simple as Sleeper's
`gsis_id` field: only about 19% of Sleeper's skill-position players actually
have one populated, so `app.nflverse_client.player_key` falls back to the
same normalized-name approach as the DK<->Sleeper join, keyed with position
to avoid cross-position name collisions.

## Week Breakdown page

`/breakdown` gives a per-game "worksheet"-style summary of every game
scheduled that week, structurally inspired by fantasy-football stat-preview
formats (a team-vs-team comparison table with league ranks, plus a short
written takeaway per game) -- but every number is real, and every sentence
of analysis is generated by template logic in `app/breakdown.py` from that
app's own already-integrated data, not reproduced from any outside site's
actual written commentary.

For each game it shows, per team, the trailing (last up-to-8 games)
points/gm, points allowed/gm, yards/play (offense and allowed), neutral
tempo, plays/gm, neutral pass rate, and the neutral pass/rush rate each
defense faces. Each is ranked 1-32 across the league
(`app.nflverse_client.rank_teams`) among whichever teams have a value at
that point in the season. From those numbers,
`app.breakdown.generate_takeaways` produces short bullets covering:

- the real closing spread/total and how they rank league-wide this week,
- a tempo mismatch,
- a "funnel" defense (top-10 in neutral pass or rush rate faced),
- a yards/play efficiency mismatch (a top-10 offense against a bottom-10
  defense in the same stat).

Each bullet is only included when the numbers support it.

**Targets** (`app/targets.py`): each team gets two "core" DFS targets plus
one "value" target (best ceiling per $1k at $5,500 or less). Candidates are
players who are Healthy or Questionable, have played this season, and are
projected for at least 3 DK points. They're
ranked by their matchup-adjusted Ceiling, which covers:

- DK points the defense allows to the position,
- the team's implied total,
- funnel, tempo and efficiency flags,
- usage trend.

That's tilted toward what the offense does most: a top-10 neutral pass rate
favors its QB/WR/TE, a bottom-10 one its RBs. At most two picks per position.
Each target lists up to three plain-English reasons, e.g. "NYJ allow +42% DK
pts to RBs · DET implied for 27 · 41% of DET targets+carries (up from
37%)".

**DST targets**: each team's DST is listed with its projection, its Ceiling,
where that Ceiling ranks among the week's DSTs, and why. Reasons cover:

- the opponent's implied total (low is good),
- how often the opponent takes sacks and gives the ball away vs league
  average (last 8 games),
- the opponent's offensive efficiency,
- a caution line for tough spots, e.g. "Tough spot: BUF implied for
  28.8".

**Advanced matchup view**: "Advanced matchup ->" on any card opens a detail
view (`app/game_detail.py`, `GET /api/breakdown/game/{game_id}`). The URL
gets `#game=<id>`, so a matchup can be linked directly. Each section pairs a
simple chart with a short "What it means" note on how it's likely to affect
the game and DFS lineups:

| Section | What it shows |
|---|---|
| Vegas outlook | Spread, total and implied totals with their weekly rank; game-script read |
| When X has the ball | Offense yards/play and points vs the opponent defense's allowed, as % above/below league average |
| Tempo and volume | Where each team sits between the league's slowest and fastest (tempo) and fewest-most plays |
| Pass/run tendencies | Neutral pass rate for each offense and the pass rate each defense faces (funnels) |
| Where to attack | DK points each defense allows to QB/RB/WR/TE vs league average, with rank |
| Who gets the ball | Top players' share of team targets + carries: last 3 games vs last 8 |
| DFS targets | The tailored targets with all their reasons |

The charts follow a data-viz method:
- The two team colors are validated for colorblind separation on the app's
  dark surface.
- Marks are thin, and every value is labeled directly.
- A tooltip appears on hover and keyboard focus.
- Each chart has a "View as table" version.
- The dialog goes full-screen on phones.

## Running it

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Then open http://127.0.0.1:8000/. The season/week fields default to
whatever `app/config.py` sets (2026 Week 1) but can be changed in the UI --
any past or future week works the same way, live.

## Deploying behind Cloudflare

DFSRiches is a normal long-running ASGI app (FastAPI on Uvicorn) with a
small on-disk cache -- it runs on any regular host or container, with
Cloudflare sitting in front as a proxy/CDN (orange-clouded DNS) or via a
Cloudflare Tunnel. **It does not run inside a Cloudflare Worker, and it
cannot be deployed as a Cloudflare Pages project**: Workers (and the
Functions that back a Pages project) execute in a V8-isolate/Pyodide
sandbox with no local filesystem and no arbitrary outbound sockets, so
Uvicorn, httpx's socket-based transport, and this app's `data/cache/*.json`
files can't run there as-is -- that would be a from-scratch rewrite onto a
different runtime, not a deployment step. Pointing a `*.pages.dev` project
at this repo will 404 on every route: Pages serves a static build output
directory (or small edge functions), and this repo has neither -- it needs
an actual running process, which is what the steps below give it.

```bash
docker build -t dfsriches .
docker run -p 8000:8000 dfsriches
```

### Deploying on Render

A `render.yaml` [Blueprint](https://render.com/docs/blueprint-spec) is
included so Render can build and run the existing `Dockerfile` with no
manual dashboard configuration:

1. Push this repo to GitHub (already done if you're reading this from a
   clone of it).
2. In the Render dashboard: **New +** -> **Blueprint** -> pick this repo.
   Render reads `render.yaml`, builds the `Dockerfile`, and starts the
   service listening on the `$PORT` it injects.
3. Once it's live at `https://<service-name>.onrender.com`, either use that
   URL directly, or put a custom domain on it and proxy that domain through
   Cloudflare (DNS record set to "Proxied"/orange-clouded) for the CDN/edge
   benefits described below -- **not** a Pages project.

Fly.io and Railway work the same way from the same `Dockerfile` (a
`fly launch` or a GitHub-connected Railway service), just without a
committed blueprint file for them.

What's already wired up for sitting behind Cloudflare:

- **`GET /healthz`** -- a dependency-free liveness check (no outbound calls)
  for the platform's health monitoring or a Cloudflare Tunnel's origin check.
- **Trusted proxy headers** -- the container's entrypoint (`python -m
  app.main`, also the Dockerfile's `CMD`) runs Uvicorn with
  `proxy_headers=True, forwarded_allow_ips="*"`, so `X-Forwarded-Proto` /
  `X-Forwarded-For` from Cloudflare's edge are honored and
  `request.url.scheme` reflects the real client's HTTPS connection rather
  than the plain-HTTP hop from Cloudflare to the origin.
- **Edge-cacheable static assets** -- `/static/*` (the CSS/JS) is served
  with `Cache-Control: public, max-age=300`, so Cloudflare can serve it from
  cache instead of round-tripping to the origin on every request. Kept
  short (5 minutes) since there's no cache-busting filename hash yet, so a
  deploy is never more than 5 minutes from being visible everywhere.
- **`$PORT`** -- both the Dockerfile and the `python -m app.main`
  entrypoint bind `0.0.0.0` on `$PORT` (default 8000), the convention most
  container platforms (Fly.io, Render, Railway, etc.) use to tell a
  container which port to listen on.

`data/cache/` is a warm-start convenience, not a database -- if it's empty
(a fresh container, no volume mounted) the app just re-fetches from
Sleeper/DraftKings/nflverse on first request and re-populates it, exactly
as it does locally. Mounting a persistent volume at `/app/data/cache`
speeds up cold starts across restarts but is optional.

## Tests

```bash
pytest
```

Covers the day-part classification and isolated-game detection
(`tests/test_schedule.py`), the name-normalization/matching logic
(`tests/test_matching.py`), the implied-total/pace-delta math
(`tests/test_game_context.py`), and the trailing-average/DK-scoring math
(`tests/test_nflverse_client.py`) -- all pure functions, so no network
access is needed to run them.

## Project layout

```
app/
  config.py        constants: TTLs, ET timezone, isolated day-part set, paths
  cache.py          on-disk TTL cache for the (large, slow-changing) API responses
  sleeper_client.py Sleeper API: players, projections, schedule/scores
  schedule.py       builds the real Week N schedule + day-part/isolation logic
  nflverse_client.py  real lines/box-scores (games.csv, stats_*_week.csv) + trailing averages
                       + team-vs-team ranking (rank_teams) for the breakdown page
  game_context.py     attaches spread/total/implied-total/pace + trends + vs-line results
  dk_scoring.py       real DraftKings Classic scoring rules, offense + DST
  dk_client.py      DraftKings API: draft-group discovery + salary parsing
  matching.py       DK <-> Sleeper name normalization and matching
  slates.py         orchestrates schedule + DK + Sleeper into the final tables
  ceiling.py        per-player 85th-percentile Ceiling (history x matchup x game env x breakdown x usage)
  optimizer.py      exact DK Classic/Showdown lineup optimizer (integer program)
  optimal.py        per-slate optimal lineups, saved pre-kickoff to data/optimal_lineups.json
  breakdown.py      builds the per-game Week Breakdown page (stats, ranks, original takeaways)
  targets.py        per-team DFS targets tailored to the matchup, with reasons
  game_detail.py    the advanced matchup view: chart data + "What it means" notes
  models.py         shared pydantic response models
  main.py           FastAPI routes
data/
  dk_overrides.json draftGroupId fallback for already-started slates, one entry per week
  optimal_lineups.json  each slate's optimal lineups as they stood before kickoff
scripts/record_draft_groups.py   records the current week's live ids into dk_overrides.json
scripts/save_optimal_lineups.py  records the current week's open slates' optimal lineups
  name_aliases.json manual DK-name -> Sleeper-name bridge, empty by default
  cache/            runtime API response cache (gitignored)
templates/index.html, templates/breakdown.html
static/style.css, static/app.js, static/breakdown.js         frontend
static/lineups.js   DK Classic/Showdown roster rules for the lineup builder
tests/                                                    pytest suite
```
