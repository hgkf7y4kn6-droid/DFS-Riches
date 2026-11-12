// Multi-factor player ranking for the lineup builder: each selected sort
// (projection, ceiling, ownership, ...) gets a weight, the weights always
// total 100%, and players are ranked on the weighted blend of their
// percentile within the current pool for each factor.

/** Weights for the selected keys, in whole percents summing to exactly 100. */
export type Weights<K extends string> = Partial<Record<K, number>>;

/** Spreads `total` across `n` slots as whole numbers (the first slots take the remainder). */
function spread(total: number, n: number): number[] {
  const base = Math.floor(total / n);
  return Array.from({ length: n }, (_, i) => base + (i < total - base * n ? 1 : 0));
}

/** An even split across the selected keys: 2 -> 50/50, 3 -> 34/33/33. */
export function evenWeights<K extends string>(keys: K[]): Weights<K> {
  const parts = spread(100, keys.length);
  return Object.fromEntries(keys.map((k, i) => [k, parts[i]])) as Weights<K>;
}

/**
 * Sets one key's weight (clamped to 0-100) and rescales the others in
 * proportion to fill the rest, so the total stays 100. If the others were
 * all 0 they share the rest evenly. Whole numbers throughout.
 */
export function setWeight<K extends string>(weights: Weights<K>, keys: K[], key: K, value: number): Weights<K> {
  if (keys.length <= 1) return { [key]: 100 } as Weights<K>;
  const v = Math.max(0, Math.min(100, Math.round(Number.isFinite(value) ? value : 0)));
  const others = keys.filter((k) => k !== key);
  const rest = 100 - v;
  const current = others.map((k) => weights[k] ?? 0);
  const sum = current.reduce((a, b) => a + b, 0);
  let parts: number[];
  if (sum <= 0) {
    parts = spread(rest, others.length);
  } else {
    // Largest-remainder rounding keeps the proportions and an exact total.
    const raw = current.map((c) => (c / sum) * rest);
    parts = raw.map(Math.floor);
    let left = rest - parts.reduce((a, b) => a + b, 0);
    const order = raw.map((r, i) => [r - Math.floor(r), i] as const).sort((a, b) => b[0] - a[0]);
    for (const [, i] of order) {
      if (left <= 0) break;
      parts[i] += 1;
      left -= 1;
    }
  }
  return { ...Object.fromEntries(others.map((k, i) => [k, parts[i]])), [key]: v } as Weights<K>;
}

export const totalWeight = <K extends string>(weights: Weights<K>, keys: K[]) => keys.reduce((a, k) => a + (weights[k] ?? 0), 0);

export interface Factor<T> {
  weight: number;
  /** The player's raw value for this factor; null = unknown. */
  value: (t: T) => number | null | undefined;
  /** True when lower raw values are better (e.g. cheaper salary, lower ownership). */
  ascending?: boolean;
}

/**
 * Percentile (0 = worst, 1 = best) of every item for one factor, ties
 * sharing the average rank. Unknown values sit at the middle (0.5) so a
 * missing stat neither helps nor buries a player.
 */
function percentiles<T>(items: T[], f: Factor<T>): number[] {
  const known = items.map((t, i) => ({ i, v: f.value(t) })).filter((x): x is { i: number; v: number } => x.v != null && Number.isFinite(x.v));
  const out = items.map(() => 0.5);
  if (known.length < 2) return out;
  known.sort((a, b) => (f.ascending ? b.v - a.v : a.v - b.v));        // worst first
  let r = 0;
  while (r < known.length) {
    let end = r;
    while (end + 1 < known.length && known[end + 1].v === known[r].v) end += 1;
    const pct = (r + end) / 2 / (known.length - 1);
    for (let j = r; j <= end; j += 1) out[known[j].i] = pct;
    r = end + 1;
  }
  return out;
}

/**
 * Ranks items by the weighted blend of their per-factor percentiles
 * (weights in percent, summing to 100). Returns the items best first with
 * their blend score (0-100). Ties break on the first factor's raw order.
 */
export function weightedRank<T>(items: T[], factors: Factor<T>[]): { item: T; score: number }[] {
  const total = factors.reduce((a, f) => a + f.weight, 0) || 1;
  const cols = factors.map((f) => percentiles(items, f));
  const scored = items.map((item, i) => ({
    item,
    i,
    score: (factors.reduce((a, f, k) => a + f.weight * cols[k][i], 0) / total) * 100,
  }));
  scored.sort((a, b) => b.score - a.score || (cols[0]?.[b.i] ?? 0) - (cols[0]?.[a.i] ?? 0));
  return scored.map(({ item, score }) => ({ item, score }));
}
