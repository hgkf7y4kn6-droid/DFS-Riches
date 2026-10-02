import { Text, View } from 'react-native';

import TagPill from '@/components/plays/TagPill';
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
 * chips (z-scores within the position); and the tag.
 */
export default function PlayRow({ player, contest }: { player: PlayPlayer; contest: PlayContest }) {
  const p = player;
  const hitLabel = contest === 'cash' ? 'P(2.5x)' : 'P(ceiling)';
  return (
    <View className="dfs-row">
      <View className="dfs-row-main">
        {p.rank != null ? <Text className="dfs-rank">{p.rank}</Text> : null}
        <View className="flex-1 pr-2">
          <Text className="dfs-name" numberOfLines={1}>
            {p.name}
            {p.injury && p.injury !== 'Healthy' ? <Text className="injury-tag"> {p.injury}</Text> : null}
          </Text>
          <Text className="dfs-meta">
            {p.position} · {p.team} vs {p.opponent} · implied {p.implied}
          </Text>
        </View>
        <View className="items-end">
          <Text className="dfs-salary">{formatCurrency(p.salary)}</Text>
          <TagPill tag={p.tag} />
        </View>
      </View>
      <Text className="dfs-stats">
        {p.final.toFixed(1)} proj · {p.floor.toFixed(1)}-{p.ceiling.toFixed(1)} · {hitLabel} {formatPercent(p.p_hit, 0)} ·{' '}
        {(Object.entries(p.ownership) as [OwnershipContest, number][])
          .map(([c, v]) => `${v.toFixed(1)}% ${OWN_LABEL[c]}`)
          .join(' · ')}
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
    </View>
  );
}
