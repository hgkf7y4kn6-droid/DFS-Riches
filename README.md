# DFSRiches

A DraftKings DFS explorer for the NFL, built with Python (FastAPI). It merges
**real DraftKings salaries** with **real Sleeper schedule/projection data**
for every Week 1 game, and automatically builds a **DraftKings Showdown
Captain Mode** slate for each isolated single-game broadcast window --
Wednesday Night, Thursday Night, Sunday Night, and Monday Night -- alongside
one Classic slate covering the full week.

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

## Running it

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Then open http://127.0.0.1:8000/. The season/week fields default to
whatever `app/config.py` sets (2026 Week 1) but can be changed in the UI --
any past or future week works the same way, live.

## Tests

```bash
pytest
```

Covers the day-part classification and isolated-game detection
(`tests/test_schedule.py`) and the name-normalization/matching logic
(`tests/test_matching.py`) -- both pure functions, so no network access is
needed to run them.

## Project layout

```
app/
  config.py        constants: TTLs, ET timezone, isolated day-part set, paths
  cache.py          on-disk TTL cache for the (large, slow-changing) API responses
  sleeper_client.py Sleeper API: players, projections, schedule/scores
  schedule.py       builds the real Week N schedule + day-part/isolation logic
  dk_client.py      DraftKings API: draft-group discovery + salary parsing
  matching.py       DK <-> Sleeper name normalization and matching
  slates.py         orchestrates schedule + DK + Sleeper into the final tables
  models.py         shared pydantic response models
  main.py           FastAPI routes
data/
  dk_overrides.json manual draftGroupId fallback for already-started slates
  name_aliases.json manual DK-name -> Sleeper-name bridge, empty by default
  cache/            runtime API response cache (gitignored)
templates/index.html, static/style.css, static/app.js   frontend
tests/                                                    pytest suite
```
