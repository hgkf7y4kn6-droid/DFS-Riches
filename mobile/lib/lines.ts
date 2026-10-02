// "Lines & Performance" formatting, ported from the website's static/app.js
// odds table: each function returns display text for one game's cell.
import { formatLine, formatSigned } from '@/lib/utils';

export type Tone = 'positive' | 'negative' | 'neutral' | 'pending';
export interface Cell {
  text: string;
  sub?: string;
  tone?: Tone;
}

function trendLine(away: TeamTrend | null, home: TeamTrend | null, opts: { signed?: boolean; decimals?: number } = {}) {
  if (!away && !home) return undefined;
  const decimals = opts.decimals ?? 1;
  const fmt = (v: number | null) => (v == null ? '-' : opts.signed ? formatSigned(v, decimals) : v.toFixed(decimals));
  const a = away ?? { l3: null, l6: null, l9: null };
  const h = home ?? { l3: null, l6: null, l9: null };
  return `L3 ${fmt(a.l3)}/${fmt(h.l3)} · L6 ${fmt(a.l6)}/${fmt(h.l6)} · L9 ${fmt(a.l9)}/${fmt(h.l9)}`;
}

export function spreadCell(g: Game): Cell {
  const c = g.context;
  if (!c || c.away_spread == null || c.home_spread == null) return { text: '-' };
  return {
    text: `${g.away} ${formatSigned(c.away_spread)} / ${g.home} ${formatSigned(c.home_spread)}`,
    sub: trendLine(c.away_spread_trend, c.home_spread_trend, { signed: true }),
  };
}

export function totalCell(g: Game): Cell {
  const c = g.context;
  if (!c || c.total_line == null) return { text: '-' };
  return { text: c.total_line.toFixed(1), sub: trendLine(c.away_total_trend, c.home_total_trend) };
}

export function impliedCell(g: Game): Cell {
  const c = g.context;
  if (!c || c.away_implied_total == null || c.home_implied_total == null) return { text: '-' };
  return {
    text: `${g.away} ${c.away_implied_total.toFixed(1)} / ${g.home} ${c.home_implied_total.toFixed(1)}`,
    sub: trendLine(c.away_implied_total_trend, c.home_implied_total_trend),
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
    sub: trendLine(c.away_pace?.trend ?? null, c.home_pace?.trend ?? null, { decimals: 0 }),
  };
}

export function weatherText(w: GameWeather | null): string {
  if (!w) return '';
  if (w.roof === 'dome') return 'Dome';
  if (w.roof === 'retractable') return 'Retractable roof';
  return w.summary || 'Weather unavailable';
}
