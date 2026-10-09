import { useState } from 'react';
import { Pressable, ScrollView, Text, View } from 'react-native';

import { useExpandedWidth } from '@/components/dfs/useCardWidth';
import LeverageBadge from '@/components/LeverageBadge';
import PlayRow from '@/components/plays/PlayRow';
import type { Pool } from '@/lib/pool-tags-context';

const POSITIONS = ['QB', 'RB', 'WR', 'TE', 'DST'] as const;

const NOTE =
  "Leverage = fair ownership minus projected large-field ownership (points). Fair ownership spreads each position's ownership by efficiency-adjusted ceiling odds -- his offense's EPA, the opposing defense's EPA allowed and its record vs his position -- so a barely-owned dart with no real upside lands near zero, and chalk in a bad matchup goes negative.";

/**
 * GPP leverage plays by position: collapsed, the strongest play at each
 * position; expanded, the top 10 at the chosen position ranked by leverage,
 * each row with its game log, tag and how its leverage was built.
 */
export default function LeverageCard({ byPosition, pool }: { byPosition: Partial<Record<string, PlayPlayer[]>>; pool: Pool }) {
  const [expanded, setExpanded] = useState(false);
  const positions = POSITIONS.filter((p) => byPosition[p]?.length);
  const [pos, setPos] = useState<string>(positions[0] ?? 'QB');
  const style = useExpandedWidth(expanded);
  const players = byPosition[pos] ?? [];
  return (
    <View className="dfs-card" style={style}>
      <Pressable onPress={() => setExpanded((e) => !e)} accessibilityRole="button" aria-expanded={expanded}>
        <Text className="dfs-card-kicker">Leverage</Text>
        <Text className="dfs-card-title">Top leverage plays by position</Text>
        <Text className="dfs-card-subtitle">Top 10 at each position, most under-owned for their efficiency-adjusted ceiling odds</Text>
        {!expanded ? (
          <View className="mt-2">
            {positions.map((p) => {
              const best = byPosition[p]![0];
              return (
                <Text key={p} className="dfs-preview" numberOfLines={1}>
                  {p} {best.name}
                  <LeverageBadge inline value={best.leverage ?? null} detail={best.leverage_detail} name={best.name} />{' '}
                  <Text className="dfs-meta">{best.ownership.large_gpp?.toFixed(1)}% own</Text>
                </Text>
              );
            })}
          </View>
        ) : null}
        <Text className="upcoming-expand-hint">{expanded ? 'Collapse ▲' : 'Tap for the top 10 at each position ▼'}</Text>
      </Pressable>
      {expanded ? (
        <View className="mt-2">
          <ScrollView horizontal showsHorizontalScrollIndicator={false} className="chip-row mb-1" contentContainerClassName="chip-row-content">
            {positions.map((p) => {
              const active = p === pos;
              return (
                <Pressable
                  key={p}
                  className={`filter-chip ${active ? 'filter-chip-active' : ''}`}
                  onPress={() => setPos(p)}
                  accessibilityRole="button"
                  aria-pressed={active}>
                  <Text className={`filter-chip-text ${active ? 'filter-chip-text-active' : ''}`}>
                    {p} ({byPosition[p]!.length})
                  </Text>
                </Pressable>
              );
            })}
          </ScrollView>
          <Text className="dfs-reason mb-1">{NOTE}</Text>
          {players.map((p) => (
            <PlayRow key={p.id} player={p} contest="gpp" pool={pool} />
          ))}
        </View>
      ) : null}
    </View>
  );
}
