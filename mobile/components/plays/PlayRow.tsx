import { useState } from 'react';
import { Pressable, Text, View } from 'react-native';

import { UsageTrendArrow, UsageTrendNote } from '@/components/UsageTrend';
import MatchupBadge from '@/components/MatchupBadge';
import GameLog from '@/components/plays/GameLog';
import TagChoices from '@/components/plays/TagChoices';
import TagPill from '@/components/plays/TagPill';
import { roleText } from '@/lib/matchup-sort';
import type { Pool } from '@/lib/pool-tags-context';
import { formatCurrency, formatPercent, formatSigned } from '@/lib/utils';

const OWN_LABEL: Record<OwnershipContest, string> = { cash: 'cash own', small_gpp: 'small-field', large_gpp: 'large-field' };
const PART_LABEL: Record<string, string> = {
  p_hit: 'Hit odds',
  floor: 'Floor',
  salary: 'Salary',
  env: 'Game env',
  leverage: 'Leverage',
};

/**
 * A ranked play: rank, name and matchup, salary; projection, floor/ceiling,
 * hit odds and expected ownership; the strength-of-play components as
 * chips (z-scores within the position); and the tag. Tap the row for the
 * player's recent game log; tap the tag to set your own call for your pool.
 */
export default function PlayRow({ player, contest, pool }: { player: PlayPlayer; contest: PlayContest; pool: Pool }) {
  const p = player;
  const [expanded, setExpanded] = useState(false);
  const [picking, setPicking] = useState(false);
  const [trendOpen, setTrendOpen] = useState(false);
  const hitLabel = contest === 'cash' ? 'P(2.5x)' : 'P(ceiling)';
  return (
    <Pressable className="dfs-row" onPress={() => setExpanded((e) => !e)} accessibilityRole="button" accessibilityState={{ expanded }}>
      <View className="dfs-row-main">
        {p.rank != null ? <Text className="dfs-rank">{p.rank}</Text> : null}
        <View className="flex-1 pr-2">
          <View className="flex-row items-center">
            <Text className="dfs-name flex-shrink" numberOfLines={1}>
              {p.name}
              {p.injury && p.injury !== 'Healthy' ? <Text className="injury-tag"> {p.injury}</Text> : null}
            </Text>
            <UsageTrendArrow trend={p.usage_trend} open={trendOpen} onToggle={() => setTrendOpen((o) => !o)} />
          </View>
          <Text className="dfs-meta">
            {p.position} · {p.team} vs {p.opponent} · implied {p.implied}
            {roleText(p) ? ` · ${roleText(p)}` : ''}
          </Text>
          <MatchupBadge opponent={p.opponent} position={p.position} />
          <UsageTrendNote trend={p.usage_trend} open={trendOpen} />
        </View>
        <View className="items-end">
          <Text className="dfs-salary">{formatCurrency(p.salary)}</Text>
          <TagPill tag={pool.tagOf(p)} mine={pool.isMine(p)} onPress={() => setPicking((v) => !v)} />
        </View>
      </View>
      {picking ? <TagChoices player={p} pool={pool} onDone={() => setPicking(false)} /> : null}
      <Text className="dfs-stats">
        {p.final.toFixed(1)} proj · {p.floor.toFixed(1)}-{p.ceiling.toFixed(1)} · {hitLabel} {formatPercent(p.p_hit, 0)} ·{' '}
        {(Object.entries(p.ownership) as [OwnershipContest, number][])
          .map(([c, v]) => `${v.toFixed(1)}% ${OWN_LABEL[c]}`)
          .join(' · ')}
        {p.leverage_ratio != null ? ` · ${p.leverage_ratio.toFixed(1)}x leverage` : ''}
      </Text>
      <View className="part-row">
        {Object.entries(p.parts).map(([k, z]) => (
          <View key={k} className={`part-chip ${z >= 0.5 ? 'part-chip-good' : z <= -0.5 ? 'part-chip-bad' : ''}`}>
            <Text className="part-chip-text">
              {PART_LABEL[k] ?? k} {formatSigned(z, 1)}
            </Text>
          </View>
        ))}
      </View>
      {expanded ? <GameLog player={p} /> : <Text className="upcoming-expand-hint mt-1">Game log ▼</Text>}
    </Pressable>
  );
}
