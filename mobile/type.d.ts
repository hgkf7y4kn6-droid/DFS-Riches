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
  name: 'index' | 'dfs-model' | 'cash' | 'gpp' | 'settings';
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

/** Props for components/ListHeading.tsx: a section title with a "View all" button. */
interface ListHeadingProps {
  title: string;
  subtitle?: string;
  /** Button label; defaults to "View all". */
  buttonText?: string;
  /** Where the button goes; the button is hidden without it. */
  onPress?: () => void;
}

type UpcomingGameStatus = 'upcoming' | 'live' | 'final';

/** One game as components/UpcomingGamesCard.tsx shows it (lib/games.ts builds these from a Game); spread straight into the card as props. */
interface UpcomingGame {
  id: string;
  /** Matchup, e.g. "IND @ WAS". */
  name: string;
  /** Venue, e.g. "Tottenham Hotspur Stadium" (falls back to the home team). */
  location: string;
  /** Kickoff, e.g. "Sun 10/4 9:30 AM ET". */
  kickoff: string;
  network: string | null;
  /** Whole days until kickoff (0 = today); negative once it has started. */
  daysLeft: number;
  status: UpcomingGameStatus;
  /** Final or in-progress score, e.g. "PIT 24 - CLE 27". */
  score: string | null;
  /** Spread and over/under, e.g. "IND -4.5 · O/U 47.5". */
  lines: string;
  /** Kickoff-window forecast, "Dome" or "Retractable roof". */
  weather: string;
  /** Away team logo. */
  icon: import('react-native').ImageSourcePropType;
  /** Home team logo. */
  opponentIcon: import('react-native').ImageSourcePropType;
  /** Island-game window label (e.g. "Sun Morning"); null for Sunday main-slate games. */
  islandLabel: string | null;
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

// ------------------------------------------------- weekly breakdown (game)

/** A team's trailing profile entering the game; ranks are 1 = best for that side of the ball. */
interface TeamStatLine {
  team: string;
  points_for: number | null;
  points_for_rank: number | null;
  points_against: number | null;
  points_against_rank: number | null;
  yards_per_play: number | null;
  yards_per_play_rank: number | null;
  yards_allowed_per_play: number | null;
  yards_allowed_per_play_rank: number | null;
  plays_per_game: number | null;
  plays_rank: number | null;
  tempo_secs: number | null;
  tempo_rank: number | null;
  pass_pct: number | null;
  rush_pct: number | null;
  opp_pass_pct_allowed: number | null;
  opp_pass_pct_allowed_rank: number | null;
  opp_rush_pct_allowed: number | null;
  opp_rush_pct_allowed_rank: number | null;
}

/** A DFS target for one team in one game. */
interface TopPlayer {
  name: string;
  position: string;
  salary: number;
  trend_l3: number | null;
  ceiling: number | null;
  proj_points: number | null;
  role: 'Core' | 'Value' | string;
  usage_l3: number | null;
  reasons: string[];
}

interface GamePostgame {
  headline?: string;
  result?: string[];
  flow?: string[];
}

interface GameBreakdown {
  game: Game;
  away_stats: TeamStatLine;
  home_stats: TeamStatLine;
  total_rank_this_week: number | null;
  away_implied_rank_this_week: number | null;
  home_implied_rank_this_week: number | null;
  takeaways: string[];
  away_top_players: TopPlayer[];
  home_top_players: TopPlayer[];
  postgame: GamePostgame | null;
}

/** What a defense allows to one position: DK points/game (last 8) vs league. */
interface PositionMatchup {
  position: string;
  allowed: number | null;
  league_avg: number | null;
  /** +0.42 = allows 42% more than average. */
  vs_avg: number | null;
  /** 1 = allows the most. */
  rank: number | null;
}

interface UsageShare {
  name: string;
  position: string;
  injury: string;
  share_l3: number;
  share_l8: number | null;
}

interface LeagueContext {
  yards_per_play: number | null;
  points: number | null;
  tempo_secs: number | null;
  plays: number | null;
  pass_rate: number | null;
}

/** /api/breakdown/game/{id}: everything the website's Weekly Breakdown shows for one game. */
interface GameDetail {
  breakdown: GameBreakdown;
  league: LeagueContext;
  /** What the AWAY defense allows (the home offense attacks it). */
  away_def_vs_pos: PositionMatchup[];
  home_def_vs_pos: PositionMatchup[];
  away_usage: UsageShare[];
  home_usage: UsageShare[];
  /** Section -> 1-2 sentence takeaway: vegas, weather, away_offense, home_offense, tempo, tendency, positions, usage, trenches. */
  insights: Record<string, string>;
}

// ------------------------------------------------------- DFS model (/api/dfs-model)

/** A player as the DFS model reports him (table rows, pools, stacks and lineups share these fields). */
interface DfsPlayer {
  id: number;
  name: string;
  position: string;
  team: string;
  opponent: string;
  salary: number;
  /** Final projection: source consensus with matchup/weather adjustments. */
  final: number;
  floor: number | null;
  ceiling: number | null;
  /** Points per $1k of salary. */
  value: number | null;
  /** Expected roster %, 0-100. */
  ownership: number | null;
  popularity?: string;
  injury: InjuryStatus | null;
  uncertainty_label?: string;
  reasons?: string[];
  reason?: string;
  why_popular?: string;
  risk?: string;
  classification?: string;
  slot?: string;
}

/** One game's environment for DFS, ranked across the slate (1 = best). */
interface DfsGameEnv {
  /** "JAX@CIN". */
  game: string;
  away: string;
  home: string;
  kickoff: string;
  total: number | null;
  spread_home: number | null;
  away_implied: number | null;
  home_implied: number | null;
  env_score: number;
  env_rank: number;
  pop_rank: number;
  /** Share of the field expected in this game, 0-1. */
  pop_share: number;
  shootout: boolean;
  negative_script: boolean;
  favorite: string | null;
  underdog: string | null;
  live_dog: boolean;
  script: string;
  trench_notes: string[];
  weather: GameWeather | null;
  ownership_vs_quality?: string;
  tempo_ranks: Record<string, number>;
  pass_rate_ranks: Record<string, number>;
}

interface DfsStack {
  game: string;
  team: string;
  /** e.g. "Basic stack + bring-back". */
  type: string;
  qb: string;
  players: DfsPlayer[];
  salary: number;
  final: number;
  ceiling: number;
  env_rank: number;
  pop_rank: number;
  score: number;
  bring_back_note: string | null;
  script: string;
  reason: string;
}

interface DfsLineupEval {
  ownership_total: number;
  quality: number;
  checklist: { item: string; ok: boolean }[];
  audit: Record<string, string>;
  win_scenario?: string;
}

interface DfsLineup {
  label: string;
  type: 'cash' | 'gpp' | 'contrarian' | string;
  construction: string;
  idea: string;
  players: DfsPlayer[];
  salary: number;
  final: number;
  floor: number;
  ceiling: number;
  eval: DfsLineupEval;
  strengths?: string[];
  risks?: string[];
}

interface DfsPositionPool {
  cash: DfsPlayer[];
  gpp: DfsPlayer[];
}

/** The DFS model for one Classic slate. */
interface DfsModel {
  available: boolean;
  reason?: string;
  season: number;
  week: number;
  slate: { slate_id: string; label: string; games: number };
  /** Classic slates the model can run on. */
  slates: { slate_id: string; label: string }[];
  generated_at: string;
  table: DfsPlayer[];
  strategy: {
    games: DfsGameEnv[];
    stacks: DfsStack[];
    pools: {
      QB: DfsPositionPool;
      RB: DfsPositionPool;
      WR: DfsPositionPool;
      TE: { pay_up: DfsPlayer[]; punt: DfsPlayer[]; cash_ids: number[]; recommendation: { strategy: string; why: string } };
      DST: DfsPlayer[];
      salary_savers: DfsPlayer[];
    };
    gpp_pool: Record<'core' | 'chalk' | 'leverage' | 'low_owned_ceiling' | 'salary_savers', DfsPlayer[]>;
    fades: Record<'cash' | 'gpp' | 'over_owned' | 'fragile_chalk' | 'poor_fit', DfsPlayer[]>;
  };
  lineups: { cash: DfsLineup[]; gpp: DfsLineup[]; contrarian: DfsLineup[] };
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
