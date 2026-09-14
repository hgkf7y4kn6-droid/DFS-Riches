"""Static configuration for DFSRiches."""
from pathlib import Path
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
CACHE_DIR = DATA_DIR / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

DK_OVERRIDES_PATH = DATA_DIR / "dk_overrides.json"
NAME_ALIASES_PATH = DATA_DIR / "name_aliases.json"

ET = ZoneInfo("America/New_York")

SLEEPER_BASE = "https://api.sleeper.app"
DK_BASE = "https://api.draftkings.com"

# nflverse (https://github.com/nflverse) publishes real, free, public NFL
# data with no API key: schedules + closing sportsbook lines (games.csv) and
# team-level per-game box-score stats (stats_team_week_{season}.csv), updated
# within hours of each game.
NFLVERSE_GAMES_CSV_URL = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
NFLVERSE_TEAM_STATS_URL_TMPL = (
    "https://github.com/nflverse/nflverse-data/releases/download/stats_team/stats_team_week_{season}.csv"
)
NFLVERSE_PLAYER_STATS_URL_TMPL = (
    "https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_{season}.csv"
)
# nflverse spells the Rams "LA"; every other team code matches ours exactly.
NFLVERSE_TO_APP_TEAM = {"LA": "LAR"}

DEFAULT_SEASON = 2026
DEFAULT_WEEK = 1

# Cache time-to-live, in seconds.
TTL_PLAYERS = 60 * 60 * 12       # Sleeper's full player dict rarely changes intra-day
TTL_PROJECTIONS = 60 * 15        # weekly projections can move
TTL_SCHEDULE = 60 * 30           # kickoff times/broadcasters
TTL_DK_DISCOVERY = 60 * 10       # DK draft-group listing
TTL_DK_DRAFTABLES = 60 * 5       # DK salaries move as slates get edited
TTL_NFLVERSE_GAMES = 60 * 20     # closing lines + scores, updates through/after games
TTL_NFLVERSE_TEAM_STATS = 60 * 30  # per-game team box-score stats, used for pace baselines

# Day-part windows used to bucket a game's ET kickoff into a broadcast window.
# "Isolated" windows are the ones DraftKings builds single-game Showdown
# contests around: Wednesday Night, Thursday Night, Sunday Night, Monday Night.
ISOLATED_DAY_PARTS = {"WED_NIGHT", "THU_NIGHT", "SUN_NIGHT", "MON_NIGHT"}

# DraftKings contestTypeId for the standard "Showdown Captain Mode" slate
# (single game, CPT slot at 1.5x salary/points + 5 FLEX slots). Verified
# against DraftKings' own live draft-group listing for the 2026 slate.
DK_SHOWDOWN_GAME_TYPE_ID = 96
DK_SHOWDOWN_CPT_SLOT_IDS = {511}
