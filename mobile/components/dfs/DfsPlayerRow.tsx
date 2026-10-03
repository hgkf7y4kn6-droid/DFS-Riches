import { useState } from 'react';
import { Text, View } from 'react-native';

import { UsageTrendArrow, UsageTrendNote } from '@/components/UsageTrend';
import MatchupBadge from '@/components/MatchupBadge';
import { formatCurrency, formatPercent } from '@/lib/utils';

export type DfsMetric = 'final' | 'value' | 'ceiling';

const METRIC_LABEL: Record<DfsMetric, string> = { final: 'proj', value: 'pts/$1k', ceiling: 'ceil' };

/**
 * One player, stacked for a phone: rank and name (with injury status), position
 * and matchup, salary; then projection, ceiling, value and expected roster %.
 * `metric` is shown first and bold.
 */
export default function DfsPlayerRow({
  player,
  rank,
  metric = 'final',
  showReasons = 0,
}: {
  player: DfsPlayer;
  rank?: number;
  metric?: DfsMetric;
  /** How many of the model's reasons to list under the row. */
  showReasons?: number;
}) {
  const p = player;
  const [trendOpen, setTrendOpen] = useState(false);
  const stats: [DfsMetric | 'own', string][] = [
    ['final', `${p.final.toFixed(1)} proj`],
    ['ceiling', p.ceiling != null ? `${p.ceiling.toFixed(1)} ceil` : ''],
    ['value', p.value != null ? `${p.value.toFixed(2)} pts/$1k` : ''],
    ['own', p.ownership != null ? `${formatPercent(p.ownership / 100, 1)} own` : ''],
  ];
  const lead = stats.find(([k]) => k === metric);
  const rest = stats.filter(([k, v]) => k !== metric && v);
  const reasons = (p.reasons ?? (p.reason ? [p.reason] : [])).slice(0, showReasons);

  return (
    <View className="dfs-row">
      <View className="dfs-row-main">
        {rank != null ? <Text className="dfs-rank">{rank}</Text> : null}
        <View className="flex-1 pr-2">
          <View className="flex-row items-center">
            <Text className="dfs-name flex-shrink" numberOfLines={1}>
              {p.name}
              {p.injury && p.injury !== 'Healthy' ? <Text className="injury-tag"> {p.injury}</Text> : null}
            </Text>
            <UsageTrendArrow trend={p.usage_trend} open={trendOpen} onToggle={() => setTrendOpen((o) => !o)} />
          </View>
          <Text className="dfs-meta">
            {p.slot && p.slot !== p.position ? `${p.slot} · ` : ''}
            {p.position} · {p.team} vs {p.opponent}
          </Text>
          <MatchupBadge opponent={p.opponent} position={p.position} />
          <UsageTrendNote trend={p.usage_trend} open={trendOpen} />
        </View>
        <View className="items-end">
          <Text className="dfs-salary">{formatCurrency(p.salary)}</Text>
          <Text className="dfs-lead">{lead?.[1] || `- ${METRIC_LABEL[metric]}`}</Text>
        </View>
      </View>
      <Text className="dfs-stats">{rest.map(([, v]) => v).join(' · ')}</Text>
      {reasons.map((r, i) => (
        <Text key={i} className="dfs-reason">
          • {r}
        </Text>
      ))}
    </View>
  );
}
