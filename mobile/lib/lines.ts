// "Lines & Performance" formatting, ported from the website's static/app.js
// odds table: each function returns display text for one game's cell.
import type { Better } from '@/lib/trend';
import { formatLine, formatSigned } from '@/lib/utils';

export type Tone = 'positive' | 'negative' | 'neutral' | 'pending';

/** One team's L3 / L6 / L9 trailing averages, colored against a baseline (components/TrendChips). */
export interface CellTrend {
  label: string;
  windows: TeamTrend | null;
  baseline: number | null | undefined;
  better: Better;
  steps: [number, number, number];
  format: (v: number) => string;
}

export interface Cell {
  text: string;
  sub?: string;
  tone?: Tone;
  trends?: CellTrend[];
}

/**
 * Both teams' trailing windows for a line. Lines are colored by where this
 * week's number sits against each window -- `nowBetter` says which way is
 * good for the team (a bigger implied total, being favored by more), so a
 * window *below* a higher number now means trending up (green).
 */
function lineTrends(
  g: Game,
  away: TeamTrend | null,
  home: TeamTrend | null,
  now: [number | null | undefined, number | null | undefined],
  nowBetter: Better,
  steps: [number, number, number],
  format: (v: number) => string,
): CellTrend[] {
  const better: Better = nowBetter === 'high' ? 'low' : 'high';     // the window vs now, flipped
  return [
    { label: `${g.away} line`, windows: away, baseline: now[0], better, steps, format },
    { label: `${g.home} line`, windows: home, baseline: now[1], better, steps, format },
  ];
}

/** Explains the chips under the Lines card (they are easy to misread as team form). */
export const LINES_LEGEND =
  "line = the team's average closing market line over its last 3 / 6 / 9 games. Green means this week's line is more favorable to the team than that average, red less, gold about the same. " +
  "actual = what the team really scored (or won by) over the same games, green when that is above what this week's line expects, red when below. A window appears once the team has played that many games this season.";

/** Combine two trailing windows window by window (null until both have that many games). */
function combine(a: TeamTrend | null | undefined, b: TeamTrend | null | undefined, op: (x: number, y: number) => number): TeamTrend | null {
  if (!a || !b) return null;
  const w = (x: number | null, y: number | null) => (x == null || y == null ? null : op(x, y));
  return { l3: w(a.l3, b.l3), l6: w(a.l6, b.l6), l9: w(a.l9, b.l9) };
}

/**
 * What actually happened over the same windows (results, not market lines), colored against THIS week's
 * number: green = the team has recently produced more than this week's line implies, red = less.
 */
function actualTrends(
  g: Game,
  away: TeamTrend | null | undefined,
  home: TeamTrend | null | undefined,
  now: [number | null | undefined, number | null | undefined],
  steps: [number, number, number],
  format: (v: number) => string,
): CellTrend[] {
  return [
    { label: `${g.away} actual`, windows: away ?? null, baseline: now[0], better: 'high', steps, format },
    { label: `${g.home} actual`, windows: home ?? null, baseline: now[1], better: 'high', steps, format },
  ];
}

export function spreadCell(g: Game): Cell {
  const c = g.context;
  if (!c || c.away_spread == null || c.home_spread == null) return { text: '-' };
  const margin = (pf?: TeamTrend | null, pa?: TeamTrend | null) => combine(pf, pa, (x, y) => x - y);
  return {
    text: `${g.away} ${formatSigned(c.away_spread)} / ${g.home} ${formatSigned(c.home_spread)}`,
    trends: [
      // A spread is better when lower (favored by more).
      ...lineTrends(g, c.away_spread_trend, c.home_spread_trend, [c.away_spread, c.home_spread], 'low', [0.5, 1.5, 3], (v) => formatSigned(v, 1)),
      // Actual margin (+ = won by) against the margin this week's spread expects (-spread).
      ...actualTrends(
        g,
        margin(c.away_points_for_trend, c.away_points_against_trend),
        margin(c.home_points_for_trend, c.home_points_against_trend),
        [-c.away_spread, -c.home_spread],
        [1, 3, 6],
        (v) => formatSigned(v, 1),
      ),
    ],
  };
}

export function totalCell(g: Game): Cell {
  const c = g.context;
  if (!c || c.total_line == null) return { text: '-' };
  const points = (pf?: TeamTrend | null, pa?: TeamTrend | null) => combine(pf, pa, (x, y) => x + y);
  return {
    text: c.total_line.toFixed(1),
    trends: [
      ...lineTrends(g, c.away_total_trend, c.home_total_trend, [c.total_line, c.total_line], 'high', [1, 2.5, 4], (v) => v.toFixed(1)),
      // Actual combined points in each team's recent games against this week's total.
      ...actualTrends(
        g,
        points(c.away_points_for_trend, c.away_points_against_trend),
        points(c.home_points_for_trend, c.home_points_against_trend),
        [c.total_line, c.total_line],
        [1, 2.5, 4],
        (v) => v.toFixed(1),
      ),
    ],
  };
}

export function impliedCell(g: Game): Cell {
  const c = g.context;
  if (!c || c.away_implied_total == null || c.home_implied_total == null) return { text: '-' };
  return {
    text: `${g.away} ${c.away_implied_total.toFixed(1)} / ${g.home} ${c.home_implied_total.toFixed(1)}`,
    trends: [
      ...lineTrends(
        g,
        c.away_implied_total_trend,
        c.home_implied_total_trend,
        [c.away_implied_total, c.home_implied_total],
        'high',
        [0.75, 2, 3.5],
        (v) => v.toFixed(1),
      ),
      // Points each team actually scored recently against the points the market expects from it this week.
      ...actualTrends(g, c.away_points_for_trend, c.home_points_for_trend, [c.away_implied_total, c.home_implied_total], [0.75, 2, 3.5], (v) => v.toFixed(1)),
    ],
  };
}

export function finalCell(g: Game): Cell {
  const c = g.context;
  if (!c || !c.is_final) return { text: 'Not final', tone: 'pending' };
  return { text: `${g.away} ${c.away_score} - ${g.home} ${c.home_score}` };
}

/** e.g. "ATL +4.5 covered by 25.5" -- the team's line and the margin it beat it by. */
export function atsCell(g: Game): Cell {
  const c = g.context;
  if (!c || !c.is_final || c.spread_result == null || c.away_spread == null || c.home_spread == null) {
    return { text: '-', tone: 'pending' };
  }
  if (c.spread_result === 0) return { text: 'Push', tone: 'neutral' };
  const homeCovered = c.spread_result > 0;
  const team = homeCovered ? g.home : g.away;
  const line = homeCovered ? c.home_spread : c.away_spread;
  return { text: `${team} ${formatLine(line)} covered by ${Math.abs(c.spread_result).toFixed(1)}`, tone: 'positive' };
}

export function totalResultCell(g: Game): Cell {
  const c = g.context;
  if (!c || !c.is_final || c.total_result == null || c.away_score == null || c.home_score == null) {
    return { text: '-', tone: 'pending' };
  }
  const combined = c.away_score + c.home_score;
  if (c.total_result === 0) return { text: `Push (${combined} pts)`, tone: 'neutral' };
  const over = c.total_result > 0;
  return {
    text: `${over ? 'Over' : 'Under'} by ${Math.abs(c.total_result).toFixed(1)} (${combined} pts)`,
    tone: over ? 'positive' : 'negative',
  };
}

/** Plays vs each team's own baseline once final, plus trailing plays/game. */
export function paceCell(g: Game): Cell {
  const c = g.context;
  if (!c) return { text: '-', tone: 'pending' };
  const part = (team: string, pace: PaceStat | null) =>
    !c.is_final || !pace || pace.delta == null ? `${team} -` : `${team} ${formatSigned(pace.delta)}`;
  return {
    text: `${part(g.away, c.away_pace)} / ${part(g.home, c.home_pace)}`,
    // Plays per game: each window against the team's season baseline.
    trends: [
      { label: g.away, windows: c.away_pace?.trend ?? null, baseline: c.away_pace?.baseline_plays, better: 'high', steps: [1.5, 3.5, 6], format: (v) => v.toFixed(0) },
      { label: g.home, windows: c.home_pace?.trend ?? null, baseline: c.home_pace?.baseline_plays, better: 'high', steps: [1.5, 3.5, 6], format: (v) => v.toFixed(0) },
    ],
  };
}

/** What a game's forecast does to projections (null when it doesn't move them or the game is played). */
export function weatherImpactText(w: GameWeather | null): string | null {
  if (!w || w.observed || !w.impact) return null;
  const dst = w.multipliers?.dst;
  const dstText = dst != null && Math.abs(dst - 1) >= 0.01 ? `, DSTs ${dst > 1 ? '+' : '−'}${Math.round(Math.abs(dst - 1) * 100)}%` : '';
  return `Projections: ${w.impact}${dstText}${w.long_range ? ' (long-range, half strength)' : ''}`;
}

export function weatherText(w: GameWeather | null): string {
  if (!w) return '';
  if (w.roof === 'dome') return 'Dome';
  if (w.roof === 'retractable') return 'Retractable roof';
  return w.summary || 'Weather unavailable';
}
