// Conditional formatting for trailing L3 / L6 / L9 trends: each window is
// compared with a baseline (the season-to-date average, or this week's line)
// and colored green (improving), red (getting worse) or gold (steady), with
// three shades each way -- the darker, the bigger the move.

export type Better = 'high' | 'low';
/** -3 (much worse) .. 0 (steady) .. 3 (much better). */
type TrendLevel = -3 | -2 | -1 | 0 | 1 | 2 | 3;

/** Relative change (fraction of the baseline) for shades 1, 2 and 3. */
const PCT_STEPS: [number, number, number] = [0.04, 0.1, 0.2];

/**
 * How a window compares with its baseline, from the unit's point of view
 * (`better` = which direction is good). `steps` are the thresholds for each
 * shade: relative to the baseline by default, or absolute when `absolute`
 * (e.g. spreads, in points).
 */
export function trendLevel(
  value: number | null | undefined,
  baseline: number | null | undefined,
  better: Better = 'high',
  { steps = PCT_STEPS, absolute = false }: { steps?: [number, number, number]; absolute?: boolean } = {},
): TrendLevel {
  if (value == null || baseline == null) return 0;
  let diff = value - baseline;
  if (!absolute) {
    if (baseline === 0) return 0;
    diff /= Math.abs(baseline);
  }
  if (better === 'low') diff = -diff;
  const size = Math.abs(diff);
  const shade = size >= steps[2] ? 3 : size >= steps[1] ? 2 : size >= steps[0] ? 1 : 0;
  return (Math.sign(diff) * shade) as TrendLevel;
}

const LIGHT: Record<TrendLevel, string> = {
  [-3]: '#EF4444',
  [-2]: '#FCA5A5',
  [-1]: '#FEE2E2',
  0: '#FDECB4',
  1: '#DCFCE7',
  2: '#86EFAC',
  3: '#22C55E',
};
const DARK: Record<TrendLevel, string> = {
  [-3]: '#B91C1C',
  [-2]: '#7F1D1D',
  [-1]: '#3F1D1D',
  0: '#4A3B0A',
  1: '#173A26',
  2: '#166534',
  3: '#15703A',
};

/** Background fill for a level; text stays in the normal foreground ink. */
export function trendFill(level: TrendLevel, dark: boolean): string {
  return (dark ? DARK : LIGHT)[level];
}

// Text colors for the same scale (the number itself is colored, no fill): stronger
// shade = bigger, kept readable on the card background in each theme.
const INK_LIGHT: Record<TrendLevel, string> = {
  [-3]: '#7F1D1D',
  [-2]: '#B91C1C',
  [-1]: '#D63A3A',
  0: '#8A6500',
  1: '#1A7F41',
  2: '#15803D',
  3: '#14532D',
};
const INK_DARK: Record<TrendLevel, string> = {
  [-3]: '#FF4D4D',
  [-2]: '#F87171',
  [-1]: '#FCA5A5',
  0: '#E5BE4F',
  1: '#A7F3C0',
  2: '#4ADE80',
  3: '#22C55E',
};

/** Text color for a level, for values shown in color rather than on a fill. */
export function trendInk(level: TrendLevel, dark: boolean): string {
  return (dark ? INK_DARK : INK_LIGHT)[level];
}

export const TREND_LEGEND = 'Green = improving, red = getting worse (darker = bigger move), gold = steady';
