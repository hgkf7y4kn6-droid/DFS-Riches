import { useMemo, useState } from 'react';
import { Pressable, ScrollView, Text, View } from 'react-native';

import DfsPlayerRow, { type DfsMetric } from '@/components/dfs/DfsPlayerRow';
import { useExpandedWidth } from '@/components/dfs/useCardWidth';
import { PLAYABLE_STATUSES } from '@/constants/data';
import LeverageBadge from '@/components/LeverageBadge';

const POSITIONS = ['QB', 'RB', 'WR', 'TE', 'DST'];

interface Props {
  title: string;
  subtitle: string;
  metric: DfsMetric;
  players: DfsPlayer[];
}

/**
 * A horizontal-list card ranking the slate's players by one metric (final
 * projection, value or ceiling). Collapsed: the top 3 overall. Tap to expand
 * into the top 10 at each position (pick it with the chips); tap the
 * header again to collapse.
 */
export default function RankedPlayersCard({ title, subtitle, metric, players }: Props) {
  const [expanded, setExpanded] = useState(false);
  const [position, setPosition] = useState('QB');
  const style = useExpandedWidth(expanded);

  const ranked = useMemo(
    () =>
      players
        .filter((p) => PLAYABLE_STATUSES.has(p.injury ?? 'Healthy') && p.final > 0)
        .sort((a, b) => (b[metric] ?? 0) - (a[metric] ?? 0)),
    [players, metric],
  );
  const top3 = ranked.slice(0, 3);
  const byPosition = ranked.filter((p) => p.position === position).slice(0, 10);

  return (
    <View className="dfs-card" style={style}>
      <Pressable onPress={() => setExpanded((e) => !e)} accessibilityRole="button" aria-expanded={expanded}>
        <Text className="dfs-card-kicker">Top 10 by position</Text>
        <Text className="dfs-card-title">{title}</Text>
        <Text className="dfs-card-subtitle">{subtitle}</Text>
        {!expanded ? (
          <View className="mt-2">
            {top3.map((p, i) => (
              <Text key={p.id} className="dfs-preview" numberOfLines={1}>
                {i + 1}. {p.name}
                <LeverageBadge inline player={{ id: p.id, name: p.name, team: p.team }} /> <Text className="dfs-meta">{p.position} · {(p[metric] ?? 0).toFixed(metric === 'value' ? 2 : 1)}</Text>
              </Text>
            ))}
          </View>
        ) : null}
        <Text className="upcoming-expand-hint">{expanded ? 'Collapse ▲' : 'Tap for the top 10 at each position ▼'}</Text>
      </Pressable>
      {expanded ? (
        <View className="mt-3">
          <ScrollView horizontal showsHorizontalScrollIndicator={false} className="chip-row" contentContainerClassName="chip-row-content">
            {POSITIONS.map((pos) => {
              const active = pos === position;
              return (
                <Pressable
                  key={pos}
                  className={`filter-chip ${active ? 'filter-chip-active' : ''}`}
                  onPress={() => setPosition(pos)}
                  accessibilityRole="button"
                  aria-pressed={active}>
                  <Text className={`filter-chip-text ${active ? 'filter-chip-text-active' : ''}`}>{pos}</Text>
                </Pressable>
              );
            })}
          </ScrollView>
          {byPosition.length ? (
            byPosition.map((p, i) => <DfsPlayerRow key={p.id} player={p} rank={i + 1} metric={metric} />)
          ) : (
            <Text className="home-empty-state">No {position}s on this slate.</Text>
          )}
        </View>
      ) : null}
    </View>
  );
}
