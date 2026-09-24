# DFSRiches

A DraftKings DFS explorer for the NFL, built with Python (FastAPI). It merges
**real DraftKings salaries** with **real Sleeper schedule/projection data**
for every Week 1 game, and automatically builds a **DraftKings Showdown
Captain Mode** slate for each isolated single-game broadcast window --
Wednesday Night, Thursday Night, Sunday Night, and Monday Night -- alongside
one Classic slate covering the full week. A "Lines & Performance" table shows
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
        - one Classic slate (every game in the week)
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
empty. The five ids currently in that file for 2026 Week 1 (one Classic +
four Showdown) were fetched live from DraftKings and verified by inspecting
each draft group's roster-slot structure (CPT/FLEX at a 1.5x salary ratio
for Showdown; 16 distinct matchups for Classic). For any future week, live
discovery alone is enough -- you only need to add an override entry if you
want the app to keep working for a week whose slates have already started
before you first loaded it.

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

DraftKings' own per-player **FPPG** (season fantasy points per game) is the
primary projection the Value column is computed from -- it's reliably
populated on every draft group. Sleeper's week-specific PPR projection is
merged in as a bonus "Sleeper Proj" column when Sleeper's endpoint has one
available for that week (see the docstring on
`app.sleeper_client.get_projections` for the current caveat there). Showdown
Captain (CPT) rows show both salary and points at DraftKings' 1.5x multiplier.

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
  the away team did (0 is a push).
- **O/U result**: `(home_score + away_score) - total_line` -- positive
  means the game went over, negative means it went under.
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
points/gm, points allowed/gm, yards/play (offense and allowed), pace
(plays/gm), pass/rush rate, and opponent pass/rush rate allowed -- each
ranked 1-32 across the league (`app.nflverse_client.rank_teams`) among
whichever teams have a trailing value at that point in the season. From
those numbers, `app.breakdown.generate_takeaways` produces short bullets
covering: the real closing spread/total and how they rank league-wide this
week, a pace mismatch, a "funnel" defense (a top-10 opponent pass- or
rush-rate-allowed, meaning that side leans on the run or pass more than
usual against this defense), and a yards/play efficiency mismatch (a top-10
offense against a bottom-10 defense in the same stat) -- each is only
included when the underlying numbers actually support it. A "players to
watch" callout per team lists the top-3 real DraftKings salaries with their
trailing L3 DK-style FPPG, when DraftKings has posted pricing for that slate
yet.

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
  breakdown.py      builds the per-game Week Breakdown page (stats, ranks, original takeaways)
  models.py         shared pydantic response models
  main.py           FastAPI routes
data/
  dk_overrides.json manual draftGroupId fallback for already-started slates
  name_aliases.json manual DK-name -> Sleeper-name bridge, empty by default
  cache/            runtime API response cache (gitignored)
templates/index.html, templates/breakdown.html
static/style.css, static/app.js, static/breakdown.js         frontend
tests/                                                    pytest suite
```
