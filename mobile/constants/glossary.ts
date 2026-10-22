// The app's DFS terms in plain language: the Settings glossary lists them
// all, and <Term> / <Glossed> (components/Term.tsx) turn a word on screen
// into a tap that opens its definition. `match` are the spellings
// <Glossed> links (case-insensitive, whole words; longest first wins).

export interface GlossaryEntry {
  id: string;
  term: string;
  /** Spellings to link in running text; the term itself is always included. */
  match?: string[];
  definition: string;
}

export const GLOSSARY: GlossaryEntry[] = [
  {
    id: 'slate',
    term: 'Slate',
    match: ['slates'],
    definition:
      'A set of games DraftKings runs contests on. Sunday Main is the Sunday afternoon games, Full Week adds the Thursday, Sunday night and Monday games, and a Showdown is a single game.',
  },
  {
    id: 'classic',
    term: 'Classic',
    definition:
      'The standard DraftKings format: 9 players (QB, 2 RB, 3 WR, TE, FLEX, DST) under a $50,000 salary cap.',
  },
  {
    id: 'showdown',
    term: 'Showdown',
    match: ['showdowns'],
    definition:
      'A single-game format: 1 Captain plus 5 FLEX players from either team under a $50,000 salary cap.',
  },
  {
    id: 'captain',
    term: 'Captain (CPT)',
    match: ['captain', 'CPT'],
    definition: "Showdown's featured slot: the Captain costs 1.5x his salary and scores 1.5x his points.",
  },
  {
    id: 'flex',
    term: 'FLEX',
    definition: 'A slot any RB, WR or TE can fill in Classic. In Showdown, the 5 non-Captain slots, open to any player.',
  },
  {
    id: 'dst',
    term: 'DST',
    definition: "A team's defense and special teams, scored on sacks, turnovers, return touchdowns and points allowed.",
  },
  {
    id: 'salary',
    term: 'Salary cap',
    match: ['salary', 'salaries'],
    definition:
      'Every player has a DraftKings salary, and a lineup has to fit under $50,000. DraftKings usually posts a slate\'s salaries a few days before its first kickoff.',
  },
  {
    id: 'cash',
    term: 'Cash games',
    match: ['cash', 'cash game', '50/50', '50/50s', 'double-up', 'double-ups', 'double up', 'head-to-head', 'head-to-heads'],
    definition:
      'Contests that pay about the top half of the field a flat prize: 50/50s, double-ups and head-to-heads. A steady score is enough, so the Safe Plays tab favors players with a high floor.',
  },
  {
    id: 'gpp',
    term: 'Tournaments (GPP)',
    match: ['GPP', 'GPPs', 'tournament', 'tournaments', 'guaranteed prize pool'],
    definition:
      'Guaranteed prize pool contests pay roughly the top 20-25% of entries, with most of the money at the very top. Winning takes upside and a lineup that differs from the field, so the Tournaments tab favors ceilings and leverage.',
  },
  {
    id: 'field-size',
    term: 'Small field / large field',
    match: ['small field', 'large field', 'small-field', 'large-field'],
    definition:
      'How many entries a tournament takes. Large fields (thousands of entries) reward being different from the crowd more than small fields do, so ownership is shown for each.',
  },
  {
    id: 'projection',
    term: 'Projection',
    match: ['projections', 'proj', 'projected'],
    definition:
      "The model's expected DraftKings points for a player: a consensus of every projection source, adjusted for his matchup and the weather.",
  },
  {
    id: 'floor',
    term: 'Floor',
    definition: "A bad-but-realistic game for the player: the 15th percentile of his outcomes. Cash players want a high floor.",
  },
  {
    id: 'ceiling',
    term: 'Ceiling',
    match: ['ceilings', 'ceil'],
    definition: 'A great-but-realistic game for the player: the 85th percentile of his outcomes. Tournament players want a high ceiling.',
  },
  {
    id: 'value',
    term: 'Value (pts/$1k)',
    match: ['value', 'values', 'pts/$1k'],
    definition: 'Projected points per $1,000 of salary. A 15-point projection at $5,000 is 3.0 pts/$1k.',
  },
  {
    id: 'prop-median',
    term: 'Prop median',
    match: ['prop medians'],
    definition:
      "The stat line a player beats half the time. Yards and catches skew high (a few big games pull the average up), so the median sits below the average, and it's what sportsbooks set prop lines near.",
  },
  {
    id: 'prop-ladder',
    term: 'Prop ladder',
    match: ['prop ladders'],
    definition:
      "Rungs of the same stat at rising lines (50+, 75+, 100+ yards), each paying more. The percent beside a rung is the model's chance he gets there; compare it with the chance the book's odds imply.",
  },
  {
    id: '2.5x',
    term: '2.5x',
    match: ['P(2.5x)'],
    definition:
      "Scoring 2.5 times a player's salary in thousands (15 points at $6,000): the usual pace a cash lineup needs. P(2.5x) is the model's odds he gets there.",
  },
  {
    id: 'p-ceiling',
    term: 'P(ceiling)',
    match: ['ceiling game', 'ceiling odds'],
    definition:
      "The odds a player reaches a tournament-winning score for his position: 28 points for a QB, 24 for a RB or WR, 18 for a TE, 14 for a DST.",
  },
  {
    id: 'hit-odds',
    term: 'Hit odds',
    definition: "P(2.5x) on the Safe Plays tab and P(ceiling) on the Tournaments tab, compared with the rest of the player's position.",
  },
  {
    id: 'ownership',
    term: 'Ownership',
    match: ['owned', 'own%', 'roster %'],
    definition:
      'The share of lineups in a contest expected to include the player. 30% means about 3 of every 10 entries play him.',
  },
  {
    id: 'chalk',
    term: 'Chalk',
    definition: "The slate's most popular players. Good chalk is worth playing; chalk that's owned beyond his upside is where to get different.",
  },
  {
    id: 'leverage',
    term: 'Leverage',
    match: ['lev'],
    definition:
      "How much less (green, +) or more (red, −) the field plays someone than his odds of a big game justify, in percentage points of ownership. It's the small 'lev' number after a name: tap it for that player's details.",
  },
  {
    id: 'pool-tags',
    term: 'Prioritize / Neutral / Fade',
    match: ['Prioritize', 'Fade', 'Neutral', 'pool tags', 'pool tag'],
    definition:
      "The model's call on each player for this contest type: Prioritize (build around him), Neutral, or Fade (avoid at his price or ownership). Tap a tag to set your own call.",
  },
  {
    id: 'stack',
    term: 'Stack',
    match: ['stacks', 'stacking'],
    definition: 'Playing a QB with his own pass catchers, so their scores rise together when the offense has a big day.',
  },
  {
    id: 'bring-back',
    term: 'Bring-back',
    definition: 'A player from the opposing team added to a stack, in case the other side keeps pace in a high-scoring game.',
  },
  {
    id: 'game-environment',
    term: 'Game environment',
    match: ['game environments', 'env score', 'game env', 'environment score', 'env'],
    definition:
      'How good a game looks for fantasy points, from its Vegas total, how close the spread is, player ceilings, pace and pass rate. #1 is the best game on the slate; the env score is the raw number behind the rank.',
  },
  {
    id: 'popularity',
    term: 'Popularity',
    definition:
      "How much of the field's lineups are expected to come from that game. Popularity #1 is the most-played game.",
  },
  {
    id: 'shootout',
    term: 'Shootout',
    definition: 'A game with a high total (1.5+ points above the slate\'s median) and a close spread (4.5 or less): both offenses should score.',
  },
  {
    id: 'shootout-leverage',
    term: 'Shootout leverage',
    match: ['top-scorer odds'],
    definition:
      "A game's odds of being the slate's highest-scoring game divided by the share of the field playing it. Above 1.00x, the field is under-exposed to that game.",
  },
  {
    id: 'live-dog',
    term: 'Live dog',
    definition: "An underdog of 3+ points that Vegas still expects to score 21.5 or more: its players can outscore the spread's story.",
  },
  {
    id: 'negative-script',
    term: 'Negative script',
    definition: 'A spread of 6.5 or more: the underdog may fall behind and pass a lot, and the favorite may run the clock out.',
  },
  {
    id: 'implied',
    term: 'Implied total',
    match: ['implied', 'implied totals'],
    definition: 'Points Vegas expects a team to score, worked out from the game total and the spread.',
  },
  {
    id: 'total',
    term: 'O/U (total)',
    match: ['O/U', 'over/under'],
    definition: 'The Vegas over/under on combined points in the game. Higher totals mean more fantasy points to go around.',
  },
  {
    id: 'spread',
    term: 'Spread',
    match: ['vs spread', 'ATS'],
    definition: 'How many points the favorite is expected to win by: DET -3 means Detroit is favored by 3.',
  },
  {
    id: 'matchup-ranks',
    term: 'Matchup ranks',
    match: ['matchup rank', 'schedule-adjusted'],
    definition:
      "How each defense has done against a position this season (its last 8 games once it has played that many): #32 allows the most (green, soft), #1 the least (red, tough). Raw uses points allowed as-is; Schedule-adjusted judges each game against what that offense usually produces, so an easy or brutal schedule doesn't skew the rank.",
  },
  {
    id: 'usage-trend',
    term: 'Usage trend',
    match: ['role growing', 'role shrinking'],
    definition: "The green ▲ / red ▼ after a name: the player's share of snaps or touches just grew or shrank. Tap it for the numbers.",
  },
  {
    id: 'trailing',
    term: 'L3 / L6 / L9',
    match: ['L3', 'L6', 'L9'],
    definition: "A team's average over its last 3, 6 or 9 games, colored against its baseline.",
  },
  {
    id: 'pace',
    term: 'Pace',
    match: ['pace vs baseline'],
    definition: 'How many plays a team ran compared with its usual number. More plays, more chances for fantasy points.',
  },
  {
    id: 'optimal',
    term: 'Model lineups',
    match: ['optimal lineup', 'optimal lineups', 'optimal', 'projected optimal', 'model lineup'],
    definition:
      "The model's two lineups for a slate. The Safe lineup has the most projected points: a high floor that cashes often, built for cash games rather than to win a tournament. The Tournament lineup is stacked for upside (the QB, two of his pass catchers and an opposing receiver), built to win big fields. Copy either into the builder to start from it.",
  },
  {
    id: 'late-swap',
    term: 'Late swap',
    definition: "Changing players in an entered lineup whose games haven't started yet.",
  },
  {
    id: 'inactives',
    term: 'Inactives',
    definition: 'The players each team rules out about 90 minutes before kickoff. The app refreshes projections after inactives come out.',
  },
];

export const GLOSSARY_BY_ID: Record<string, GlossaryEntry> = Object.fromEntries(GLOSSARY.map((g) => [g.id, g]));
