// Global types for DFSRiches. This file has no imports or exports, so every
// interface here is available app-wide without importing it. Shapes mirror
// the FastAPI responses in app/models.py (backend) one-for-one; keep them in
// sync when a backend model changes.

// ---------------------------------------------------------------- navigation

/** One bottom tab. constants/data.ts maps over these to build the tab bar. */
interface AppTab {
  /** Stable id, used as the React key. */
  id: string;
  /** Route file name inside app/(tabs) (e.g. "index" for app/(tabs)/index.tsx). */
  name: 'index' | 'lineups' | 'lines';
  /** Label under the icon and the screen title. */
  title: string;
  /** Icon from constants/icons.ts, tinted with the active/inactive color. */
  icon: import('react-native').ImageSourcePropType;
}

/** The signed-in user shown in the Home header. */
interface HomeUser {
  name: string;
  greeting: string;
  avatar: import('react-native').ImageSourcePropType;
}

/** The Home balance card: money spent on lineup submissions and the next contest lock. */
interface HomeBalance {
  /** Dollars spent on contest entries. */
  amount: number;
  /** ISO timestamp of the next lineup lock (first kickoff of the upcoming slate). */
  lineupContestDate: string;
}

/** One Home section: what it's called and how it's laid out. */
interface HomeSection {
  id: 'profit' | 'upcoming' | 'slates' | 'lineups' | 'lines';
  title: string;
  subtitle: string;
  /** Whether the section starts expanded. */
  defaultExpanded: boolean;
}

// ------------------------------------------------------------------ schedule

/** Every broadcast window a game can fall in (app/schedule.classify_day_part). */
type DayPart =
  | 'SUN_MORNING' | 'SUN_EARLY' | 'SUN_LATE' | 'SUN_NIGHT'
  | `${'MON' | 'TUE' | 'WED' | 'THU' | 'FRI' | 'SAT'}_${'EARLY' | 'LATE' | 'NIGHT'}`;

/** A team's own trailing average over its last 3/6/9 games. */
interface TeamTrend {
  l3: number | null;
  l6: number | null;
  l9: number | null;
}

interface PaceStat {
  actual_plays: number | null;
  baseline_plays: number | null;
  /** actual - baseline; positive = faster than expected. */
  delta: number | null;
  trend: TeamTrend | null;
}

/** Closing betting lines, and how the game performed against them once final. */
interface GameContext {
  away_spread: number | null;
  home_spread: number | null;
  total_line: number | null;
  away_implied_total: number | null;
  home_implied_total: number | null;
  away_spread_trend: TeamTrend | null;
  home_spread_trend: TeamTrend | null;
  away_total_trend: TeamTrend | null;
  home_total_trend: TeamTrend | null;
  away_implied_total_trend: TeamTrend | null;
  home_implied_total_trend: TeamTrend | null;
  is_final: boolean;
  away_score: number | null;
  home_score: number | null;
  /** Home margin vs home spread; + = home covered, - = away covered. */
  spread_result: number | null;
  /** Combined score - total; + = over. */
  total_result: number | null;
  away_pace: PaceStat | null;
  home_pace: PaceStat | null;
}

type WeatherSeverity = 'good' | 'fair' | 'poor' | 'bad' | string;

/** Kickoff-window forecast for a game (app/weather.py). */
interface GameWeather {
  venue: string | null;
  roof: 'outdoors' | 'dome' | 'retractable' | string;
  temp_f: number | null;
  wind_mph: number | null;
  precip_chance: number | null;
  condition: string | null;
  available: boolean;
  indoor: boolean;
  severity: WeatherSeverity | null;
  summary: string | null;
  /** Plain-English projection impact, e.g. "passing yards -4%". */
  impact: string | null;
  source: string | null;
  long_range: boolean;
}

interface Game {
  game_id: string;
  season: number;
  week: number;
  away: string;
  home: string;
  kickoff_utc: string;
  /** Pre-formatted, e.g. "Sun 10/4 1:00 PM ET". */
  kickoff_et: string;
  network: string | null;
  day_part: DayPart;
  /** An island game: the lone game in a window outside the Sunday main slate. */
  isolated: boolean;
  context: GameContext | null;
  weather: GameWeather | null;
}

interface WeekSchedule {
  season: number;
  week: number;
  games: Game[];
  isolated_games: Game[];
}

// -------------------------------------------------------------------- slates

type SlateType = 'classic' | 'showdown';
type SlateSource = 'live' | 'override' | 'unavailable';

interface Slate {
  /** e.g. "classic", "classic_sunday", "showdown_thu_night", "showdown_sun_morning". */
  slate_id: string;
  label: string;
  slate_type: SlateType;
  day_part: DayPart | null;
  draft_group_id: number | null;
  games: Game[];
  available: boolean;
  source: SlateSource;
}

interface WeekData {
  schedule: WeekSchedule;
  slates: Slate[];
}

/** DraftKings injury/game status: "Healthy", "Q", "D", "O"/"OUT", "IR", ... */
type InjuryStatus = 'Healthy' | 'Q' | 'D' | 'O' | 'OUT' | 'IR' | string;

/** "" for Classic, "CPT" or "FLEX" for Showdown. */
type RosterSlot = '' | 'CPT' | 'FLEX';

interface Player {
  name: string;
  team: string;
  opponent: string;
  position: 'QB' | 'RB' | 'WR' | 'TE' | 'DST' | 'K' | string;
  roster_slot: RosterSlot;
  salary: number;
  /** DK points: Sleeper's projected line, matchup/weather adjusted; x1.5 for CPT. */
  proj_points: number;
  proj_notes: string[];
  dk_fppg: number | null;
  sleeper_proj: number | null;
  trend_l3: number | null;
  trend_l6: number | null;
  trend_l9: number | null;
  /** 85th-percentile DK score estimate; x1.5 for CPT. */
  ceiling: number | null;
  ceiling_notes: string[];
  value_per_1k: number;
  game_info: string;
  injury: InjuryStatus | null;
  sleeper_player_id: string | null;
  dk_draftable_id: number | null;
}

interface SlatePlayers {
  slate: Slate;
  players: Player[];
  unmatched_dk_names: string[];
  match_count: number;
  total_count: number;
}

// ------------------------------------------------------------------- lineups

/** A player inside a saved optimal lineup. */
interface LineupPlayer {
  slot: string;
  name: string;
  position: string;
  team: string;
  opponent: string;
  roster_slot: RosterSlot;
  salary: number;
  proj_points: number;
  ceiling: number | null;
  sleeper_proj: number | null;
  game_info: string;
  injury: InjuryStatus | null;
  dk_draftable_id: number | null;
  dk_fppg: number | null;
  /** Added once the slate is final. */
  actual?: number;
}

interface OptimalLineup {
  metric: 'proj_points' | 'ceiling' | string;
  label: string;
  players: LineupPlayer[];
  salary: number;
  /** Absent on the hindsight (best possible) lineup. */
  proj_points?: number;
  ceiling?: number;
  actual?: number;
}

/** live: recalculated until kickoff; saved: frozen at kickoff; final: scored. */
type OptimalStatus = 'live' | 'saved' | 'final' | 'none';

interface OptimalResponse {
  status: OptimalStatus;
  saved_at: string | null;
  results_at: string | null;
  lineups: OptimalLineup[];
  hindsight: OptimalLineup | null;
}

/** One position in the lineup builder's roster template. */
interface SlotDef {
  label: string;
  /** Classic: positions allowed in this slot. */
  allow?: string[];
  /** Showdown: the roster slot this position takes. */
  rosterSlot?: RosterSlot;
}

/** A lineup being built: one entry per SlotDef, null while open. */
type BuilderLineup = (Player | null)[];

interface LineupSummary {
  salary: number;
  remaining: number;
  avgRemaining: number | null;
  proj: number;
  ceiling: number;
  filled: number;
  total: number;
  valid: boolean;
  errors: string[];
}

// --------------------------------------------------------- contest entries

/** DraftKings contest formats tracked separately in the profit/loss tracker. */
type ContestType = 'gpp' | 'cash' | 'h2h' | 'single_entry' | 'satellite';

interface ContestTypeInfo {
  id: ContestType;
  /** e.g. "Tournament (GPP)". */
  title: string;
  /** Chip label, e.g. "GPP". */
  short: string;
  description: string;
}

/**
 * One contest entry the user logged: what they paid and, once the contest
 * settles, what they won. Stored on the device (lib/submissions-context.tsx).
 */
interface LineupSubmission {
  id: string;
  /** ISO timestamp the entry was logged. */
  createdAt: string;
  season: number;
  week: number;
  slateId: string;
  slateLabel: string;
  contestType: ContestType;
  /** Optional contest name, e.g. "NFL $5 Millionaire Maker". */
  contestName: string;
  /** Fee per entry, in dollars. */
  entryFee: number;
  /** How many entries at that fee. */
  entries: number;
  /** Total winnings across those entries; null while the contest is pending. */
  winnings: number | null;
}

/** Money and results for a set of submissions (all, or one contest type). */
interface ProfitLossStats {
  submissions: number;
  entries: number;
  settled: number;
  pending: number;
  /** Entry fees paid, pending entries included. */
  spent: number;
  /** Winnings from settled entries. */
  won: number;
  /** won - fees of settled entries (pending entries aren't a loss yet). */
  net: number;
  /** Settled submissions that won more than they cost. */
  wins: number;
  /** wins / settled, 0-1; null with nothing settled. */
  winPct: number | null;
  /** net / settled fees, e.g. 0.25 = +25%; null with nothing settled. */
  roi: number | null;
}

// ------------------------------------------------------------------- assets

/** Lets constants/icons.ts and constants/images.ts import PNGs directly. */
declare module '*.png' {
  const source: import('react-native').ImageSourcePropType;
  export default source;
}

/** Side-effect import of global.css in app/_layout.tsx (compiled by NativeWind). */
declare module '*.css';
