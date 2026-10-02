import icons from '@/constants/icons';
import images from '@/constants/images';

// Bottom tabs: app/(tabs)/_layout.tsx maps over these, one Tabs.Screen each.
export const tabs: AppTab[] = [
  { id: 'home', name: 'index', title: 'Home', icon: icons.home },
  { id: 'lineups', name: 'lineups', title: 'Lineups', icon: icons.lineups },
  { id: 'lines', name: 'lines', title: 'Lines', icon: icons.lines },
];

// Home header.
export const HOME_USER: HomeUser = {
  name: 'Rags2Riches26',
  greeting: 'Welcome back',
  avatar: images.avatar,
};

// Home balance card. Hard-coded starting values: app/(tabs)/index.tsx
// replaces them with live numbers (logged entry fees, next slate lock) once
// those load, and with real API responses when accounts exist.
export const HOME_BALANCE: HomeBalance = {
  amount: 0,
  lineupContestDate: '2026-10-04T17:00:00Z',
};

// Home sections, top to bottom after the header and balance card. Each one
// maps to a live data piece from the DFSRiches API (lib/week-context.tsx).
export const HOME_SECTIONS: Record<HomeSection['id'], HomeSection> = {
  profit: {
    id: 'profit',
    title: 'Profit / Loss',
    subtitle: 'Results by contest type: win rate, ROI and net dollars',
    defaultExpanded: false,
  },
  upcoming: {
    id: 'upcoming',
    title: 'Upcoming games',
    subtitle: "This week's games that haven't kicked off",
    defaultExpanded: true,
  },
  slates: {
    id: 'slates',
    title: 'Slates',
    subtitle: 'Main, Full Week and every island Showdown',
    defaultExpanded: true,
  },
  lineups: {
    id: 'lineups',
    title: 'Lineups',
    subtitle: 'Projected optimal lineups for the selected slate',
    defaultExpanded: true,
  },
  lines: {
    id: 'lines',
    title: 'Lines & Performance',
    subtitle: 'Spread, total, implied totals and results vs the line',
    defaultExpanded: false,
  },
};

// Lineup builder position filters.
export const POSITION_FILTERS: Record<SlateType, string[]> = {
  classic: ['All', 'QB', 'RB', 'WR', 'TE', 'DST'],
  showdown: ['All', 'CPT', 'FLEX'],
};

// DraftKings statuses the builder's pool shows by default (same as the DFS
// model's playable set); Doubtful, Out and IR players are hidden.
export const PLAYABLE_STATUSES = new Set(['Healthy', 'Q']);

export const OPTIMAL_STATUS_TEXT: Record<OptimalStatus, string> = {
  live: 'Live: recalculated until kickoff',
  saved: 'Saved at kickoff; actual scores are added once every game is final',
  final: 'Final: scored with actual points',
  none: 'No lineups were saved for this slate',
};

// Contest formats for logging entries and the profit/loss tracker.
export const CONTEST_TYPES: ContestTypeInfo[] = [
  { id: 'gpp', title: 'Tournament (GPP)', short: 'GPP', description: 'Large-field, top-heavy payouts' },
  { id: 'cash', title: 'Cash (50/50, Double Up)', short: 'Cash', description: 'About half the field gets paid' },
  { id: 'h2h', title: 'Head-to-Head', short: 'H2H', description: 'One opponent, winner takes it' },
  { id: 'single_entry', title: 'Single Entry', short: 'Single', description: 'One lineup per user' },
  { id: 'satellite', title: 'Satellite / Qualifier', short: 'Satellite', description: 'Wins tickets to bigger contests' },
];

export const CONTEST_TYPE_BY_ID = Object.fromEntries(CONTEST_TYPES.map((c) => [c.id, c])) as Record<ContestType, ContestTypeInfo>;
