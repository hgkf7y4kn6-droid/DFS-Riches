// Profit/loss math for logged contest entries. Pure functions, so the
// numbers on the balance card and the tracker always agree.

export function cost(s: LineupSubmission): number {
  return s.entryFee * s.entries;
}

export function profit(s: LineupSubmission): number | null {
  return s.winnings == null ? null : s.winnings - cost(s);
}

export function stats(list: LineupSubmission[]): ProfitLossStats {
  const settled = list.filter((s) => s.winnings != null);
  const settledFees = settled.reduce((sum, s) => sum + cost(s), 0);
  const won = settled.reduce((sum, s) => sum + (s.winnings ?? 0), 0);
  const wins = settled.filter((s) => (profit(s) ?? 0) > 0).length;
  return {
    submissions: list.length,
    entries: list.reduce((sum, s) => sum + s.entries, 0),
    settled: settled.length,
    pending: list.length - settled.length,
    spent: round2(list.reduce((sum, s) => sum + cost(s), 0)),
    won: round2(won),
    net: round2(won - settledFees),
    wins,
    winPct: settled.length ? wins / settled.length : null,
    roi: settledFees > 0 ? (won - settledFees) / settledFees : null,
  };
}

export function statsByType(list: LineupSubmission[]): { type: ContestType; stats: ProfitLossStats }[] {
  const types = [...new Set(list.map((s) => s.contestType))];
  return types.map((type) => ({ type, stats: stats(list.filter((s) => s.contestType === type)) }));
}

function round2(n: number): number {
  return Math.round(n * 100) / 100;
}

/** Parses a dollar amount typed by the user ("$1,250.50" -> 1250.5); null if invalid. */
export function parseMoney(text: string): number | null {
  const cleaned = text.replace(/[$,\s]/g, '');
  if (!cleaned) return null;
  const n = Number(cleaned);
  return Number.isFinite(n) && n >= 0 ? round2(n) : null;
}

/** How often a player (or team) was played, and what lineups with him returned. */
export interface ExposureStat {
  key: string;
  label: string;
  sub: string;
  /** Entries (contest entries) whose lineup included him. */
  entries: number;
  /** Logged lineups that included him. */
  lineups: number;
  /** Entry fees on those lineups, settled and pending. */
  spent: number;
  /** Net on settled lineups with him (winnings - fees); null until one settles. */
  net: number | null;
  /** Fees of the settled lineups with him, for ROI. */
  settledFees: number;
}

/**
 * Exposure and results by player and by team across logged lineups: each
 * submission's entries, fees and (once settled) profit count toward every
 * player in its lineup, and once toward each team in it. Submissions logged
 * without a lineup don't count.
 */
export function exposure(list: LineupSubmission[]): { players: ExposureStat[]; teams: ExposureStat[] } {
  const players = new Map<string, ExposureStat>();
  const teams = new Map<string, ExposureStat>();
  const bump = (map: Map<string, ExposureStat>, key: string, label: string, sub: string, s: LineupSubmission) => {
    const cur = map.get(key) ?? { key, label, sub, entries: 0, lineups: 0, spent: 0, net: null, settledFees: 0 };
    cur.entries += s.entries;
    cur.lineups += 1;
    cur.spent = round2(cur.spent + cost(s));
    const p = profit(s);
    if (p != null) {
      cur.net = round2((cur.net ?? 0) + p);
      cur.settledFees = round2(cur.settledFees + cost(s));
    }
    map.set(key, cur);
  };
  for (const s of list) {
    if (!s.lineup?.length) continue;
    for (const pl of s.lineup) bump(players, `${pl.name}|${pl.team}`, pl.name, `${pl.position} · ${pl.team}`, s);
    for (const team of new Set(s.lineup.map((pl) => pl.team))) bump(teams, team, team, '', s);
  }
  return { players: [...players.values()], teams: [...teams.values()] };
}

/** Most played first (entries, then lineups). */
export const mostPlayed = (stats: ExposureStat[], n = 5) =>
  [...stats].sort((a, b) => b.entries - a.entries || b.lineups - a.lineups).slice(0, n);

/** Most profitable first, among those with a settled lineup. */
export const mostProfitable = (stats: ExposureStat[], n = 5) =>
  stats.filter((s) => s.net != null).sort((a, b) => (b.net ?? 0) - (a.net ?? 0)).slice(0, n);
