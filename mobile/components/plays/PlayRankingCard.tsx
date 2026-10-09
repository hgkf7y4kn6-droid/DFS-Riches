import { useState } from 'react';
import { Pressable, Text, View } from 'react-native';

import { useExpandedWidth } from '@/components/dfs/useCardWidth';
import PlayRow from '@/components/plays/PlayRow';
import type { Pool } from '@/lib/pool-tags-context';
import LeverageBadge from '@/components/LeverageBadge';

interface Props {
  kicker?: string;
  title: string;
  subtitle: string;
  players: PlayPlayer[];
  contest: PlayContest;
  pool: Pool;
  /** The collapsed preview's detail after each name; defaults to team and ownership. */
  preview?: (p: PlayPlayer) => string;
  /** Shown above the list when expanded. */
  note?: string;
}

const defaultPreview = (p: PlayPlayer) => `${p.team} · ${Object.values(p.ownership).at(-1)?.toFixed(1)}% own`;

/**
 * Horizontal-list card for a ranked list of plays (one position's top plays,
 * or GPP chalk / leverage). Collapsed: the top 3. Tap to expand into the full
 * list, where each play opens its game log and its tag can be changed; tap
 * the header again to collapse.
 */
export default function PlayRankingCard({ kicker, title, subtitle, players, contest, pool, preview = defaultPreview, note }: Props) {
  const [expanded, setExpanded] = useState(false);
  const style = useExpandedWidth(expanded);
  return (
    <View className="dfs-card" style={style}>
      <Pressable onPress={() => setExpanded((e) => !e)} accessibilityRole="button" aria-expanded={expanded}>
        <Text className="dfs-card-kicker">{kicker ?? (contest === 'cash' ? 'Cash plays' : 'GPP plays')}</Text>
        <Text className="dfs-card-title">{title}</Text>
        <Text className="dfs-card-subtitle">{subtitle}</Text>
        {!expanded ? (
          <View className="mt-2">
            {players.slice(0, 3).map((p) => (
              <Text key={p.id} className="dfs-preview" numberOfLines={1}>
                {p.rank}. {p.name}
                <LeverageBadge inline value={p.leverage ?? null} detail={p.leverage_detail} name={p.name} /> <Text className="dfs-meta">{preview(p)}</Text>
              </Text>
            ))}
          </View>
        ) : null}
        <Text className="upcoming-expand-hint">{expanded ? 'Collapse ▲' : `Tap for all ${players.length} ▼`}</Text>
      </Pressable>
      {expanded ? (
        <View className="mt-2">
          {note ? <Text className="dfs-reason mb-1">{note}</Text> : null}
          {players.map((p) => (
            <PlayRow key={p.id} player={p} contest={contest} pool={pool} />
          ))}
        </View>
      ) : null}
    </View>
  );
}
