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
    version: '1.1.49',
    title: "What's new",
    items: [
      'Best contests now include cash games: 50/50s, Double Ups and Triple Ups. Turn each on or off under Show. Cash games are scored against other cash games, so they rank on rake and payouts without crowding out tournaments.',
    ],
  },
  {
    version: '1.1.48',
    title: "What's new",
    items: [
      "Weekly Pro Picks: if a player you ranked is ruled out, you'll get a heads-up to swap him before the Sunday Main locks. If you can't, he just scores 0 -- he doesn't count against your accuracy, and the players you ranked below him move up a spot.",
    ],
  },
  {
    version: '1.1.47',
    title: "What's new",
    items: [
      "Weekly Pro Picks results now show each position side by side: who you ranked at every spot next to who actually finished there, with their DraftKings points.",
    ],
  },
  {
    version: '1.1.46',
    title: "What's new",
    items: [
      "Weekly Pro Picks: once the Sunday Main is scored you'll see where you finished out of every Pro entry and your accuracy -- the share of players you ranked who finished as top performers. Other users' rankings stay private.",
    ],
  },
  {
    version: '1.1.45',
    title: "What's new",
    items: [
      "Weekly Pro Picks: Pro users rank the Sunday Main's top scorers at each position (on Home) and compete for the closest to perfect.",
      'Model lineup cards on the Lineups tab open and close with a tap again.',
      'Build for me now builds around your picks: put at least two players in the lineup first.',
      'The separate player pool under the builder is gone: tap a slot to pick from that position.',
    ],
  },
  {
    version: '1.1.43',
    title: "What's new",
    items: [
      'When a player is ruled out before the projections catch up, his teammates now pick up their share of his targets and carries right away -- mostly the next man up at his position, as in past games.',
    ],
  },
  {
    version: '1.1.42',
    title: 'DFSRiches is now Riches Analytics',
    items: [
      'Same app, same account and saved lineups -- just a new name.',
      'Questionable players keep their chance-of-playing discount until an hour before kickoff, so a late inactive has time to show up before the app counts him as active.',
    ],
  },
  {
    version: '1.1.40',
    title: "What's new",
    items: [
      'Questionable players now project at their chance of playing, read from this week\u2019s practice report (a full practice Friday plays about 90% of the time; no practice about half). Their cards show the chance and the practice log. Once inactives are out, active players get their full chance back.',
    ],
  },
  {
    version: '1.1.39',
    title: "What's new",
    items: [
      'Tap any slot in your lineup (QB, RB, FLEX, CPT...) to see just the players for it, in your current sort or blend. Players who fit your remaining salary come first, the rest fold away, and your salary left stays in view at the bottom.',
    ],
  },
  {
    version: '1.1.38',
    title: "What's new",
    items: [
      'Model lineups: a Safe lineup (the most projected points, built to cash) and a stacked Tournament lineup (QB, two of his pass catchers and an opposing receiver) replace the Ceiling lineup.',
      'Corners out: when a defense is missing starting cornerbacks, receivers\u2019 projections and workhorse pass-catching backs\u2019 ceilings go up, and the player cards say so.',
    ],
  },
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
