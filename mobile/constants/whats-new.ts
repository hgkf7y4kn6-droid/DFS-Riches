// "What's new" after an update (components/WhatsNew.tsx): the newest entry
// shows once to people who used an earlier version. Add an entry for a
// release worth telling users about; patch updates without one show nothing.
export interface WhatsNewEntry {
  /** The app version (mobile/app.json) this note is for. */
  version: string;
  title: string;
  items: string[];
}

export const WHATS_NEW: WhatsNewEntry[] = [
  {
    version: '1.1.34',
    title: "What's new",
    items: [
      'Player props are now part of DFSRiches Pro: median yards and catches for every player in DFS Model, and his chances at each ladder rung.',
    ],
  },
  {
    version: '1.1.33',
    title: "What's new",
    items: [
      'Props: tap Props on any player in DFS Model for his median yards and catches, and his chances at each ladder rung (50+, 75+, 100+ yards).',
    ],
  },
  {
    version: '1.1.31',
    title: "What's new",
    items: [
      'Build for me: the model builds up to 5 different lineups at once, keeping the players you picked.',
      'Export for DraftKings: download your lineups as DraftKings\u2019 upload file.',
      'Alerts when a player in your lineups is ruled out, when salaries come out, and before lineups lock.',
      'How we did: our projected lineups against what they actually scored, every week.',
      'Tell us what you play (Settings → Your game) and Home leads with your top plays.',
      'One lineup builder in Lineups, a faster model, offline reading and bigger text.',
    ],
  },
];
