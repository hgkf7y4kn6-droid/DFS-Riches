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

DEFAULT_SEASON = 2026
DEFAULT_WEEK = 1

# Cache time-to-live, in seconds.
TTL_PLAYERS = 60 * 60 * 12       # Sleeper's full player dict rarely changes intra-day
TTL_PROJECTIONS = 60 * 15        # weekly projections can move
TTL_SCHEDULE = 60 * 30           # kickoff times/broadcasters
TTL_DK_DISCOVERY = 60 * 10       # DK draft-group listing
TTL_DK_DRAFTABLES = 60 * 5       # DK salaries move as slates get edited

# Day-part windows used to bucket a game's ET kickoff into a broadcast window.
# "Isolated" windows are the ones DraftKings builds single-game Showdown
# contests around: Wednesday Night, Thursday Night, Sunday Night, Monday Night.
ISOLATED_DAY_PARTS = {"WED_NIGHT", "THU_NIGHT", "SUN_NIGHT", "MON_NIGHT"}

# DraftKings contestTypeId for the standard "Showdown Captain Mode" slate
# (single game, CPT slot at 1.5x salary/points + 5 FLEX slots). Verified
# against DraftKings' own live draft-group listing for the 2026 slate.
DK_SHOWDOWN_GAME_TYPE_ID = 96
DK_SHOWDOWN_CPT_SLOT_IDS = {511}

NFL_TEAMS = {
    "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE", "DAL", "DEN",
    "DET", "GB", "HOU", "IND", "JAX", "KC", "LAC", "LAR", "LV", "MIA",
    "MIN", "NE", "NO", "NYG", "NYJ", "PHI", "PIT", "SEA", "SF", "TB",
    "TEN", "WAS",
}
