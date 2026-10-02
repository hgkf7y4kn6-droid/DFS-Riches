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
