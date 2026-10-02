import { useState } from 'react';
import { Pressable, Text, View } from 'react-native';

import DfsPlayerRow, { type DfsMetric } from '@/components/dfs/DfsPlayerRow';
import { useExpandedWidth } from '@/components/dfs/useCardWidth';

interface Props {
  kicker: string;
  title: string;
  subtitle?: string;
  players: DfsPlayer[];
  metric?: DfsMetric;
}

/**
 * A horizontal-list card for one player pool (e.g. Cash RBs, GPP leverage).
 * Collapsed: the first few names. Tap to expand into every player with the
 * model's reasons; tap again to collapse.
 */
export default function PlayerPoolCard({ kicker, title, subtitle, players, metric = 'final' }: Props) {
  const [expanded, setExpanded] = useState(false);
  const style = useExpandedWidth(expanded);
  return (
    <View className="dfs-card" style={style}>
      <Pressable onPress={() => setExpanded((e) => !e)} accessibilityRole="button" accessibilityState={{ expanded }}>
        <Text className="dfs-card-kicker">{kicker}</Text>
        <Text className="dfs-card-title">{title}</Text>
        {subtitle ? <Text className="dfs-card-subtitle">{subtitle}</Text> : null}
        {!expanded ? (
          <View className="mt-2">
            {players.slice(0, 3).map((p) => (
              <Text key={p.id} className="dfs-preview" numberOfLines={1}>
                {p.name} <Text className="dfs-meta">{p.position} · {p.team}</Text>
              </Text>
            ))}
            {!players.length ? <Text className="dfs-meta">No players in this pool.</Text> : null}
          </View>
        ) : null}
        <Text className="upcoming-expand-hint">
          {expanded ? 'Collapse ▲' : `Tap for all ${players.length} with reasons ▼`}
        </Text>
      </Pressable>
      {expanded ? (
        <View className="mt-2">
          {players.map((p, i) => (
            <DfsPlayerRow key={`${p.id}-${i}`} player={p} rank={i + 1} metric={metric} showReasons={3} />
          ))}
        </View>
      ) : null}
    </View>
  );
}
