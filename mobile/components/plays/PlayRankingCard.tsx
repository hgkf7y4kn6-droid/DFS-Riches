import { useState } from 'react';
import { Pressable, Text, View } from 'react-native';

import { useExpandedWidth } from '@/components/dfs/useCardWidth';
import PlayRow from '@/components/plays/PlayRow';

interface Props {
  title: string;
  subtitle: string;
  players: PlayPlayer[];
  contest: PlayContest;
}

/**
 * Horizontal-list card for one position's top plays. Collapsed: the top 3.
 * Tap to expand into the full ranked list with each play's components and
 * tag; tap the header again to collapse.
 */
export default function PlayRankingCard({ title, subtitle, players, contest }: Props) {
  const [expanded, setExpanded] = useState(false);
  const style = useExpandedWidth(expanded);
  return (
    <View className="dfs-card" style={style}>
      <Pressable onPress={() => setExpanded((e) => !e)} accessibilityRole="button" accessibilityState={{ expanded }}>
        <Text className="dfs-card-kicker">{contest === 'cash' ? 'Cash plays' : 'GPP plays'}</Text>
        <Text className="dfs-card-title">{title}</Text>
        <Text className="dfs-card-subtitle">{subtitle}</Text>
        {!expanded ? (
          <View className="mt-2">
            {players.slice(0, 3).map((p) => (
              <Text key={p.id} className="dfs-preview" numberOfLines={1}>
                {p.rank}. {p.name}{' '}
                <Text className="dfs-meta">
                  {p.team} · {Object.values(p.ownership).at(-1)?.toFixed(1)}% own
                </Text>
              </Text>
            ))}
          </View>
        ) : null}
        <Text className="upcoming-expand-hint">{expanded ? 'Collapse ▲' : `Tap for all ${players.length} ranked ▼`}</Text>
      </Pressable>
      {expanded ? (
        <View className="mt-2">
          {players.map((p) => (
            <PlayRow key={p.id} player={p} contest={contest} />
          ))}
        </View>
      ) : null}
    </View>
  );
}
