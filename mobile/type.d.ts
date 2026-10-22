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
  name: 'index' | 'dfs-model' | 'cash' | 'gpp' | 'big-picture' | 'lineups';
  /** Label under the icon and the screen title. */
  title: string;
  /** Icon from constants/icons.ts, tinted with the active/inactive color. */
  icon: import('react-native').ImageSourcePropType;
  /** Shown only to master accounts (hidden from the tab bar for everyone else). */
  masterOnly?: boolean;
}

/** The signed-in user shown in the Home header. */
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
  /** What the forecast does to projections, e.g. "Rain: passing TDs -10%, team scoring -6%, DSTs +6%". */
  weatherImpact: string | null;
  /** Away team logo. */
  icon: import('react-native').ImageSourcePropType;
  /** Home team logo. */
  opponentIcon: import('react-native').ImageSourcePropType;
  /** Island-game window label (e.g. "Sun Morning"); null for Sunday main-slate games. */
  islandLabel: string | null;
}

/** One Home section: what it's called and how it's laid out. */
interface HomeSection {
  id: 'profit' | 'upcoming' | 'slates' | 'free' | 'contests' | 'lines';
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
  /** Projection multipliers (pass_yd, pass_td, rush_td, points, dst). */
  multipliers?: Partial<Record<'pass_yd' | 'pass_td' | 'rush_td' | 'points' | 'dst', number>>;
  /** Weather that was actually played in (finished games). */
  observed?: boolean;
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
  /** DK points per game this season: the baseline trailing trends are colored against. */
  trend_season?: number | null;
  /** 85th-percentile DK score estimate; x1.5 for CPT. */
  ceiling: number | null;
  ceiling_notes: string[];
  value_per_1k: number;
  game_info: string;
  injury: InjuryStatus | null;
  sleeper_player_id: string | null;
  dk_draftable_id: number | null;
  /** Role on his team this week, from projections and recent snap share. */
  role?: PlayerRole | null;
  /** Average offensive snap % over his last 3 games. */
  snap_pct?: number | null;
  usage_trend?: UsageTrend | null;
  team_share?: TeamShare | null;
}

/** RB/WR/TE: share of the team's skill-position touches (carries + receptions) and DK points over its
 *  last 3 games, and where each ranks among the team's RBs, WRs and TEs (1 = most). */
interface TeamShare {
  touch_pct: number;
  touch_rank: number;
  fp_pct: number;
  fp_rank: number;
  /** Skill players compared. */
  of: number;
  games: number;
}

/** A role that just shifted: the latest game's snaps/usage against the games before it. */
interface UsageTrend {
  direction: 'up' | 'down';
  /** e.g. "Role growing: 64% of snaps in Week 3 vs 42% in Weeks 1-2; ..., taking work from Tyler Allgeier." */
  text: string;
  snap_delta?: number;
  /** This season's last (up to 4) games, oldest first. */
  series?: { week: number; snap_pct: number | null; opps: number }[];
  /** "carries + targets" (RB) or "targets". */
  unit?: string;
  /** Teammates at the position who moved the other way. */
  partners?: string[];
  sustained?: boolean;
  /** Passed the genuine-shift bar (see app.roles). */
  genuine?: boolean;
}

/** starter: top of the depth chart; rotation: real share of the work (committee backs, WR4s on the field). */
type PlayerRole = 'starter' | 'rotation' | 'backup' | 'out';

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
  /** His game has kicked off: kept in the lineup as saved before kickoff. */
  locked?: boolean;
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

/** live: recalculated until the last kickoff (players lock as their games start); saved: frozen; final: scored. */
/** What a Best contests score weighs: low rake, share of the field paid, first prize for the fee, small field. */
type ContestFactor = 'rake' | 'paid' | 'payout' | 'field';

/** Tournament, Booster (multiplier), League or Qualifier. */
type ContestKind = 'Tournament' | 'Booster' | 'League' | 'Qualifier';

/** One DraftKings GPP from /api/contests/best. rake and paid_pct are 0-1 ratios; score is 0-100. */
interface BestContest {
  id: number;
  name: string;
  game_type: string;
  entry_fee: number;
  max_entries: number;
  field_size: number;
  entries: number;
  prize_pool: number;
  rake: number;
  guaranteed: boolean;
  kind: ContestKind;
  /** The slate: "Main", "Thu-Mon", "Early Only", "SEA @ DEN"... */
  slate: string;
  start_utc: string | null;
  start_label: string;
  draft_group_id: number;
  template_id: number;
  paid_places: number | null;
  paid_pct: number | null;
  /** First-place prize (cash plus tickets/seats at face value), and as a multiple of the entry fee. */
  top_prize: number | null;
  top_multiple: number | null;
  score: number;
  /** The name without its slate when the contest runs on several slates, else the name. */
  title: string;
  /** Copies DraftKings lists of this contest, on this and other slates (this row is the fullest copy). */
  copies: number;
  /** Every slate a copy is on, soonest first. */
  slates: string[];
  /** A copy runs on the slate selected in the app (this row is that slate's fullest copy). */
  on_selected_slate: boolean;
}

/** A free DraftKings NFL contest that pays cash, from /api/contests/free. */
interface FreeContest {
  id: number;
  name: string;
  game_type: string;
  prize_pool: number;
  /** DraftKings' cash prize text, e.g. "$2,000". */
  cash: string | null;
  field_size: number;
  entries: number;
  max_entries: number;
  slate: string;
  start_utc: string | null;
}

interface FreeContestsResponse {
  contests: FreeContest[];
  updated_at: string;
}

interface BestContestsResponse {
  entry_groups: { id: string; label: string; min: number; max: number }[];
  fee_groups: { id: string; label: string }[];
  kinds: ContestKind[];
  /** Each factor's share (0-1) of the score: low rake, share of field paid, first prize for the fee, small field. */
  weights: Record<ContestFactor, number>;
  /** Points per factor when the user sets none, and the most a factor can have. */
  default_weights: Record<ContestFactor, number>;
  max_weight: number;
  selected: { entries: string[]; fees: string[]; excluded: ContestKind[] };
  /** Contests matching the selection (copies collapsed), of which up to 15 are listed. */
  matching: number;
  /** The slate selected in the app and how many matching contests run on it (listed first); null when none is. */
  selected_slate: { draft_group_id: number; matching: number } | null;
  /** The selected slate's contests first, then the rest; best first within each. Started slates are left out. */
  contests: BestContest[];
  updated_at: string;
}

type OptimalStatus = 'live' | 'saved' | 'final' | 'none';

interface OptimalResponse {
  status: OptimalStatus;
  saved_at: string | null;
  results_at: string | null;
  lineups: OptimalLineup[];
  hindsight: OptimalLineup | null;
  /** Live, with games underway: players locked across the lineups, and how many games have started. */
  locked_players?: number;
  games_started?: number;
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
  /** Share of team targets + carries this season. */
  share_season: number;
  /** Last 3 / 6 / 9 games; null until he has played that many this season. */
  share_l3: number | null;
  share_l6: number | null;
  share_l9: number | null;
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
  trenches?: TrenchDetail | null;
  units?: GameUnits | null;
}

/** One unit metric: season-to-date per game, league rank (1 = best) and trailing windows (null until played). */
interface UnitMetric {
  value: number;
  rank: number;
  l3: number | null;
  l6: number | null;
  l9: number | null;
}
interface TeamUnits {
  games: number;
  offense: Record<string, UnitMetric>;
  defense: Record<string, UnitMetric>;
}
interface UnitLeague {
  avg: number | null;
  label: string;
  unit: string;
  better: 'high' | 'low';
}
interface GameUnits {
  away: TeamUnits;
  home: TeamUnits;
  league: { offense: Record<string, UnitLeague>; defense: Record<string, UnitLeague> };
  teams_ranked: number;
}

/** Offense unit vs the defense unit it faces: positive = offense advantage (league z-score difference). */
interface TrenchEdge {
  edge: number;
  strength: 'strong' | 'lean' | 'neutral';
  offense_rank: number;
  defense_rank: number;
}
interface TrenchMatchup {
  offense: string;
  defense: string;
  edges: Partial<Record<'protection' | 'run' | 'pass', TrenchEdge>>;
  notes: string[];
}
interface TrenchTeam {
  team: string;
  games: number;
  units: Record<string, { label: string; rank: number; z: number }>;
  off: Record<string, number | null>;
  def: Record<string, number | null>;
  cov: Record<string, number | string | null>;
  /** Late-down success beyond the early-down pace (offense, defense, net); a monitor, not a model input. */
  late_downs?: { offense: number; defense: number; net: number; z?: number; flag?: 'hot' | 'cold' | null } | null;
}
interface TrenchDetail {
  away: TrenchTeam;
  home: TrenchTeam;
  away_offense: TrenchMatchup;
  home_offense: TrenchMatchup;
  league: { off?: Record<string, number | null>; def?: Record<string, number | null>; cov?: Record<string, number | string | null> };
  coverage_season?: number | null;
  window?: string | null;
  insight: string;
  late_down_notes?: string[];
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
  role?: PlayerRole | null;
  snap_pct?: number | null;
  usage_trend?: UsageTrend | null;
  team_share?: TeamShare | null;
  /** Prop medians and ladder chances by stat (pass_yd, rush_yd, rec_yd, rec), from app.prop_pricer. */
  props?: Record<string, PropPrice> | null;
}

/** One stat's prop pricing: the median and P(stat >= rung) for each ladder rung ("50": 0.57). */
interface PropPrice {
  median: number;
  ladder: Record<string, number>;
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
  /** Drive velocity, run funnels, four-man pressure, playcaller pace and separation (app.advanced_env). */
  advanced_env?: AdvancedEnv | null;
  /** Pass-funnel, pressure-fragility and lean flags from advanced_env. */
  advanced_notes?: string[];
  /** Shootout leverage (app.shootout_leverage): expected share of the slate's top scorers vs the field's share. */
  shootout_leverage?: {
    expected_share: number;
    own_share: number;
    leverage: number;
    rank: number;
    flag: boolean;
    over_by_10: number | null;
    points_50: number | null;
  } | null;
  shootout_note?: string;
  /** The weekly audit checklist (app.game_model): which items fire and each item's 2023-2025 record. */
  checklist?: ChecklistItem[] | null;
  /** Game model v2: the market line plus a correction fit on 2023-2025. */
  model_v2?: {
    fair_total: number;
    total_adj: number;
    fair_home_margin: number;
    margin_adj: number;
    qbs: Record<string, { name: string | null; dropback_epa: number; dropbacks: number }>;
    ol_out: Record<string, number>;
  } | null;
}

interface ChecklistItem {
  id: string;
  label: string;
  /** true = fires, false = doesn't, null = no data. */
  flag: boolean | null;
  /** The direction the item points when it fires. */
  call: 'Over' | 'Under' | null;
  record: { hit: number; n: number; pct: number | null } | null;
}

interface AdvancedEnv {
  /** 0.7 x total + adj. */
  score: number | null;
  /** The index's adjustment: positive = faster, more explosive, less pressure-prone than the total implies. */
  adj: number;
  parts: { drive_velocity: number; funnel: number; playcaller_pace: number; separation: number; trench_penalty: number };
  lean?: 'Over' | 'Under' | 'Neutral';
  vs_slate?: number;
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

// --------------------------------------------- cash / GPP plays (/api/plays)

type PlayContest = 'cash' | 'gpp';
/** Ownership contest types: cash, small-field GPP, large-field GPP. */
type OwnershipContest = 'cash' | 'small_gpp' | 'large_gpp';
type PlayTag = 'prioritize' | 'neutral' | 'fade';

/** One player's play strength and expected field ownership for a contest type. */
interface ActualOwnershipSummary {
  uploaded_at: string | null;
  players: number;
  /** Mean absolute miss of the projection, in ownership points. */
  mae: number | null;
  misses: { name: string; position: string; team: string; actual: number | null; projected: number | null }[];
}

/** How a player's leverage was built (app/leverage.py). */
interface LeverageDetail {
  /** Fair ownership: the position's ownership redistributed by efficiency-adjusted odds (percent). */
  fair_own: number | null;
  own: number | null;
  /** True when `own` is uploaded actual ownership rather than the projection. */
  own_is_actual?: boolean;
  /** True Efficiency-Adjusted Projection. */
  teap: number | null;
  /** Efficiency-adjusted hit odds (GPP: ceiling score; cash: 2.5x salary), 0-1. */
  p: number | null;
  /** Matchup-Efficiency Multiplier and its parts (league z-scores). */
  mem: number;
  off_z: number;
  def_z: number;
  pos_z: number;
  verdict: 'Efficient secret' | 'Public trap' | 'Mirage' | null;
}

interface PlayPlayer {
  /** The projection's weather adjustment (outdoor games where weather moved it). */
  weather?: { factor: number; text: string | null } | null;
  /** 1-based strength-of-play rank in a ranking list; null in the full player list. */
  rank: number | null;
  id: number;
  name: string;
  position: string;
  team: string;
  opponent: string;
  salary: number;
  injury: InjuryStatus | null;
  final: number;
  floor: number;
  ceiling: number;
  value: number;
  implied: number;
  /** Cash: P(2.5x salary). GPP: P(the position's tournament-winning score). 0-1. */
  p_hit: number;
  /** Strength of play (weighted z-scores within the position). */
  score: number;
  /** Each component's z-score: p_hit, floor or leverage, salary, env. */
  parts: Record<string, number>;
  /** GPP: P(ceiling) / large-field ownership (1.0 = owned in line with the ceiling odds); null for cash. */
  leverage_ratio: number | null;
  /** Uploaded actual contest ownership (percent) where known, per field. */
  actual_ownership?: Partial<Record<OwnershipContest, number>>;
  /** Fair minus projected ownership for this contest's field, in percentage points (app/leverage.py). */
  leverage?: number | null;
  leverage_detail?: LeverageDetail | null;
  /** Blended expected ownership, percent, per contest type. */
  ownership: Partial<Record<OwnershipContest, number>>;
  /** Each model's estimate (percent) before the blend: sim, bt, frac_logit, gbm. */
  ownership_models: Partial<Record<OwnershipContest, Record<string, number>>>;
  tag: PlayTag;
  tag_reason: string;
  role?: PlayerRole | null;
  snap_pct?: number | null;
  usage_trend?: UsageTrend | null;
  team_share?: TeamShare | null;
  features: {
    value_ratio: number;
    position_value_rank: number;
    salary_delta_vs_average: number;
    team_implied_total: number;
    position_scarcity_index: number;
    is_backup_injury_start: boolean;
  };
}

interface OwnershipModelInfo {
  label: string;
  /** Blend weights of the models in use (untrained ones drop out). */
  weights: Record<string, number>;
  /** The simulated field's price of $1k of salary, in points. */
  price_per_k: number;
  training: { slates: number; rows: number; frac_logit: boolean; gbm: boolean };
  simulated_lineups: number;
}

interface PlaysResponse {
  available: boolean;
  reason?: string;
  contest: PlayContest;
  slate: { slate_id: string; label: string; games: number };
  slates: { slate_id: string; label: string }[];
  /** Top 5 QB, 10 RB, 10 WR, 5 TE by strength of play. */
  rankings: Record<'QB' | 'RB' | 'WR' | 'TE', PlayPlayer[]>;
  /** Every playable player, most owned first. */
  players: PlayPlayer[];
  ownership_models: Partial<Record<OwnershipContest, OwnershipModelInfo>>;
  /** Players whose roles are genuinely shifting, biggest snap moves first. */
  role_shifts?: PlayPlayer[];
  /** GPP only: the 10 highest large-field ownerships across positions. */
  chalk?: PlayPlayer[];
  /** GPP only: the 10 best ceiling-odds-per-ownership pivots across positions. */
  leverage?: PlayPlayer[];
  /** Uploaded actual ownership per field: when, how many players, model error and the biggest misses. */
  actual_ownership?: Partial<Record<OwnershipContest, ActualOwnershipSummary>>;
  /** GPP: the top 10 leverage plays at each position, strongest first. */
  leverage_by_position?: Partial<Record<string, PlayPlayer[]>>;
}

/** The user's own Prioritize / Neutral / Fade calls for one pool, by player id. */
type PoolTags = Record<number, PlayTag>;

interface PlayerGameStats {
  passing?: { cmp: number; att: number; yds: number; td: number; int: number; sacks: number };
  rushing?: { att: number; yds: number; td: number };
  receiving?: { tgt: number; rec: number; yds: number; td: number; target_share?: number };
  defense?: { sacks: number; int: number; fum_rec: number; td: number; pts_allowed: number | null };
}

/** One past game: snap share, DK points and the position's relevant box-score lines. */
interface PlayerGame {
  season: number;
  week: number;
  team: string;
  opponent: string;
  dk_points: number;
  /** Percent of the offense's snaps; null for DSTs or a missing snap row. */
  snap_pct: number | null;
  offense_snaps: number | null;
  stats: PlayerGameStats;
}

interface PlayerGamesResponse {
  name: string;
  position: string;
  team: string;
  /** Newest first. */
  games: PlayerGame[];
  summary: { games: number; avg_dk_points: number | null; avg_snap_pct: number | null };
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
  /** The lineup entered (logged from the builder); edited for late swaps until each player's game starts. */
  lineup?: SubmittedPlayer[];
  /** ISO timestamp of the last lineup edit. */
  editedAt?: string;
}

/** One slot of a logged lineup. */
interface SubmittedPlayer {
  slot: string;
  dk_draftable_id: number | null;
  name: string;
  team: string;
  position: string;
  salary: number;
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

// ------------------------------------------------------ defense vs position

/** Raw ranks, or strength-of-schedule adjusted (vs what each opponent usually produces). */
type MatchupMode = 'raw' | 'adj';

interface MatchupMetrics {
  /** Raw: DK points allowed per game. Adjusted: points allowed above the opponents' usual output. */
  fp: number;
  /** 1 = allows the least (toughest); 32 = allows the most (softest matchup). */
  fp_rank: number;
  /** Raw: the position's efficiency metric allowed. Adjusted: above the opponents' usual. */
  eff: number;
  eff_rank: number;
}

interface PositionMatchupRank {
  games: number;
  raw: MatchupMetrics;
  adj: MatchupMetrics;
}

interface DefenseVsPosition {
  season: number;
  week: number;
  /** Games per team in the window. */
  window: number;
  /** Efficiency metric label per position, e.g. RB "yds/touch". */
  efficiency: Record<string, string>;
  league: Record<string, { fp: number; eff: number; teams: number }>;
  /** team -> position -> ranks. For DST the team is the opposing offense. */
  teams: Record<string, Record<string, PositionMatchupRank>>;
}

// ---------------------------------------------------------- account sync

/** The saved data that follows a signed-in user between devices. */
type SyncKey = 'saved_lineups' | 'submissions' | 'pool_tags' | 'settings' | 'prefs';

interface SyncedDoc {
  value: unknown;
  /** ISO time of the write the server kept. */
  updated_at: string;
}

interface AccountData {
  user_id: string;
  /** Master accounts keep every week's data forever. */
  master: boolean;
  /** Where the data lives: Neon Postgres, Clerk metadata, or not configured on the server. */
  storage: 'neon' | 'clerk' | 'none';
  data: Partial<Record<SyncKey, SyncedDoc>>;
  /** free / pro / admin (masters); app.accounts.plan. */
  plan?: Plan;
  /** Pro features are locked for free accounts (billing is on). */
  pro_gating?: boolean;
  pro_features?: ProFeature[];
}

type Plan = 'free' | 'pro' | 'admin';
type ProFeature = 'optimal' | 'ownership' | 'leverage' | 'multiple_lineups' | 'big_picture' | 'alerts';

// ------------------------------------------------------------- Big Picture (master-only pilot)
interface BigPictureRow {
  game: string;
  market: string;
  side: string;
  opening: string;
  current: string;
  fair: string;
  edge: string;
  status: string;
  class: 'strongest' | 'price_sensitive' | 'watchlist' | 'none';
  moved: string | null;
}

interface BigPictureChange {
  item: string;
  previous: string;
  current: string;
  reason: string;
  action: string;
}

interface BigPictureSection {
  n: number;
  title: string;
  markdown: string;
  author: string;
  unverified: string[];
}

interface BigPictureRecord {
  w: number;
  l: number;
  p: number;
  n: number;
  win_pct: number | null;
}

interface BigPictureReport {
  title: string;
  header: {
    generated_et: string;
    status: 'Preliminary' | 'Updated';
    week: number;
    season: number;
    games: string[];
    markets: string[];
    freshness: { source: string; status?: string | null; captured_at?: string | null }[];
    gaps: string[];
  };
  writer: 'agents' | 'desk';
  model: string | null;
  sections: BigPictureSection[];
  tables: { dashboard: BigPictureRow[]; changelog: BigPictureChange[] };
  qc: { review: { verdict: string; issues: { section: number; problem: string; fix?: string }[]; revised?: boolean } | null };
  agent_notes: Record<string, string>;
  elapsed_s: number;
}

interface BigPictureVersion {
  id: number;
  created_at: string;
  season: number;
  week: number;
  kind: string;
  summary: { title: string; status: string; writer: string; edges: number; games: number; generated_et: string };
}

interface BigPictureResponse {
  report: {
    id: number;
    created_at: string;
    season: number;
    week: number;
    kind: string;
    report: BigPictureReport;
    dossier?: {
      track_record?: {
        backtest?: Record<string, unknown> & { games: number; note?: string };
        graded?: { record: BigPictureRecord; avg_clv_points: number | null; note: string | null };
      };
      calibration?: { trusted?: { spread?: boolean; total?: boolean } };
    };
  } | null;
  versions: BigPictureVersion[];
  can_run: boolean;
  run: { status: string | null; conclusion?: string | null; started_at?: string | null } | null;
}
