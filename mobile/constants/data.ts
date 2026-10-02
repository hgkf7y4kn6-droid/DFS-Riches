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

// Home sections, top to bottom after the header and balance card. Each one
// maps to a live data piece from the DFSRiches API (lib/week-context.tsx).
export const HOME_SECTIONS: Record<HomeSection['id'], HomeSection> = {
  schedule: {
    id: 'schedule',
    title: 'This week',
    subtitle: 'Every game, kickoff, network and weather',
    defaultExpanded: false,
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
