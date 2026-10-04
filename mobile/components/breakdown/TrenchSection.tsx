import { Text, View } from 'react-native';

import { ChartAxis, DivergingBar, type Side } from '@/components/breakdown/charts';
import { ordinal } from '@/lib/utils';

const EDGE_LABELS: Record<string, [string, string]> = {
  protection: ['protection', 'pass rush'],
  run: ['run blocking', 'run defense'],
  pass: ['dropback offense', 'pass defense'],
};
const EDGE_MAX = 2.5;

type Kind = 'pct' | 'epa' | 'sec' | 'dec';
// The key line and efficiency rates (app/trenches.py), team vs team vs league.
const METRICS: { group: string; rows: [string, (t: { off: any; def: any; cov: any }) => unknown, Kind][] }[] = [
  {
    group: 'Offense',
    rows: [
      ['Success rate', (t) => t.off?.success, 'pct'],
      ['EPA / play', (t) => t.off?.epa_play, 'epa'],
      ['Sack rate', (t) => t.off?.sack_rate, 'pct'],
      ['Sack + QB-hit rate', (t) => t.off?.pressure_rate, 'pct'],
      ['Explosive pass rate (20+)', (t) => t.off?.explosive_pass, 'pct'],
      ['Rush success rate', (t) => t.off?.rush_success, 'pct'],
      ['Run stuff rate (0 or less)', (t) => t.off?.stuff_rate, 'pct'],
      ['Explosive run rate (10+)', (t) => t.off?.explosive_run, 'pct'],
    ],
  },
  {
    group: 'Defense',
    rows: [
      ['Success rate allowed', (t) => t.def?.success, 'pct'],
      ['EPA / play allowed', (t) => t.def?.epa_play, 'epa'],
      ['Sack rate', (t) => t.def?.sack_rate, 'pct'],
      ['Sack + QB-hit rate', (t) => t.def?.pressure_rate, 'pct'],
      ['Blitz rate', (t) => t.def?.blitz, 'pct'],
      ['Rush success allowed', (t) => t.def?.rush_success, 'pct'],
      ['Run stuff rate', (t) => t.def?.stuff_rate, 'pct'],
    ],
  },
  {
    group: 'Coverage',
    rows: [
      ['Man coverage rate', (t) => t.cov?.man, 'pct'],
      ['Two-high shell', (t) => t.cov?.two_high, 'pct'],
      ['Pressure rate (NGS)', (t) => t.cov?.true_pressure, 'pct'],
      ['Time to throw (offense)', (t) => t.cov?.time_to_throw, 'sec'],
    ],
  },
];

function fmt(v: unknown, kind: Kind): string {
  if (v == null || v === '') return '-';
  if (typeof v !== 'number') return String(v);
  if (kind === 'pct') return `${(v * 100).toFixed(1)}%`;
  if (kind === 'epa') return `${v > 0 ? '+' : ''}${v.toFixed(3)}`;
  if (kind === 'sec') return `${v.toFixed(2)}s`;
  return v.toFixed(2);
}

function Row({ cells, head }: { cells: string[]; head?: boolean }) {
  const compact = cells.length > 3;
  return (
    <View className="detail-row">
      <Text className={`detail-row-label ${head ? 'detail-row-head' : ''}`}>{cells[0]}</Text>
      {cells.slice(1).map((c, i) => (
        <Text key={i} className={`${compact ? 'detail-row-value-compact' : 'detail-row-value'} ${head ? 'detail-row-head' : ''}`}>
          {c}
        </Text>
      ))}
    </View>
  );
}

/**
 * Trenches, efficiency and schemes: each offense unit against the defense
 * unit it faces as diverging bars (right = offense edge, gray = no real
 * edge), both teams' unit grades, and the line / efficiency rates behind them.
 */
export default function TrenchSection({ t, away, home }: { t: TrenchDetail; away: string; home: string }) {
  const edges: { key: string; label: string; side: Side; e: TrenchEdge }[] = [];
  for (const [m, side] of [
    [t.away_offense, 'away'],
    [t.home_offense, 'home'],
  ] as [TrenchMatchup, Side][]) {
    for (const [key, e] of Object.entries(m.edges)) {
      if (!e) continue;
      const [ou, du] = EDGE_LABELS[key];
      edges.push({
        key: `${m.offense}-${key}`,
        label: `${m.offense} ${ou} (${ordinal(e.offense_rank)}) vs ${m.defense} ${du} (${ordinal(e.defense_rank)})`,
        side,
        e,
      });
    }
  }
  const notes = [...t.away_offense.notes, ...t.home_offense.notes].filter((n) => !t.insight.includes(n));
  const lg = { off: t.league.off ?? {}, def: t.league.def ?? {}, cov: t.league.cov ?? {} };
  return (
    <View>
      <Text className="detail-note">
        Each offense unit vs the defense unit it faces. Bars right of center favor the offense, left favor the defense; gray = no real edge.
        Competitive plays only (win probability 10-90%).
      </Text>
      {edges.length ? (
        <View className="mt-2">
          {edges.map((r) => (
            <DivergingBar
              key={r.key}
              label={r.label}
              side={r.side}
              value={r.e.edge}
              max={EDGE_MAX}
              muted={r.e.strength === 'neutral'}
              valueText={`${r.e.edge > 0 ? '+' : ''}${r.e.edge.toFixed(1)}`}
            />
          ))}
          <ChartAxis left="Defense edge" center="Even" right="Offense edge" />
        </View>
      ) : null}
      <Text className="detail-insight">{t.insight}</Text>
      {notes.map((n, i) => (
        <Text key={i} className="detail-bullet">
          • {n}
        </Text>
      ))}

      <Text className="detail-subhead mt-3">Unit grades (league rank, 1 = best)</Text>
      <Row head cells={['Unit', away, home]} />
      {Object.entries(t.away.units).map(([k, u]) => (
        <Row key={k} cells={[u.label, `#${u.rank}`, t.home.units[k] ? `#${t.home.units[k].rank}` : '-']} />
      ))}

      {METRICS.map((g) => (
        <View key={g.group} className="mt-3">
          <Text className="detail-subhead">
            {g.group}
            {g.group === 'Coverage' && t.coverage_season ? ` (${t.coverage_season} season)` : ''}
          </Text>
          <Row head cells={['', away, home, 'League']} />
          {g.rows.map(([label, get, kind]) => (
            <Row key={label} cells={[label, fmt(get(t.away), kind), fmt(get(t.home), kind), fmt(get(lg), kind)]} />
          ))}
        </View>
      ))}
      {t.window ? <Text className="detail-note mt-2">{t.window}</Text> : null}
    </View>
  );
}
