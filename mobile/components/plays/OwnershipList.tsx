import { useMemo, useState } from 'react';
import { Pressable, ScrollView, Text, View } from 'react-native';

import TagPill from '@/components/plays/TagPill';
import { formatCurrency, formatSigned } from '@/lib/utils';

const POSITIONS = ['All', 'QB', 'RB', 'WR', 'TE', 'DST'];
const TAGS: ('all' | PlayTag)[] = ['all', 'prioritize', 'neutral', 'fade'];
const TAG_LABEL = { all: 'All tags', prioritize: 'Prioritize', neutral: 'Neutral', fade: 'Fade' };
const MODEL_LABEL: Record<string, string> = {
  sim: 'Field sim',
  bt: 'Bradley-Terry',
  frac_logit: 'Fractional logit',
  gbm: 'LightGBM',
};
const COLUMN: Record<OwnershipContest, string> = { cash: 'Cash', small_gpp: 'Small GPP', large_gpp: 'Large GPP' };
const PAGE = 30;

function Chips<T extends string>({ items, value, label, onChange }: { items: T[]; value: T; label: (t: T) => string; onChange: (t: T) => void }) {
  return (
    <ScrollView horizontal showsHorizontalScrollIndicator={false} className="chip-row mb-2" contentContainerClassName="chip-row-content">
      {items.map((it) => {
        const active = it === value;
        return (
          <Pressable
            key={it}
            className={`filter-chip ${active ? 'filter-chip-active' : ''}`}
            onPress={() => onChange(it)}
            accessibilityRole="button"
            accessibilityState={{ selected: active }}>
            <Text className={`filter-chip-text ${active ? 'filter-chip-text-active' : ''}`}>{label(it)}</Text>
          </Pressable>
        );
      })}
    </ScrollView>
  );
}

function OwnershipRow({ player, columns, expanded, onToggle }: { player: PlayPlayer; columns: OwnershipContest[]; expanded: boolean; onToggle: () => void }) {
  const p = player;
  const f = p.features;
  return (
    <Pressable className="own-row" onPress={onToggle} accessibilityRole="button" accessibilityState={{ expanded }}>
      <View className="dfs-row-main">
        <View className="flex-1 pr-2">
          <Text className="dfs-name" numberOfLines={1}>
            {p.name}
            {p.injury && p.injury !== 'Healthy' ? <Text className="injury-tag"> {p.injury}</Text> : null}
          </Text>
          <Text className="dfs-meta">
            {p.position} · {p.team} vs {p.opponent} · {formatCurrency(p.salary)} · {p.final.toFixed(1)} proj
          </Text>
        </View>
        {columns.map((c) => (
          <View key={c} className="own-col">
            <Text className="own-value">{(p.ownership[c] ?? 0).toFixed(1)}%</Text>
            {columns.length > 1 ? <Text className="own-label">{COLUMN[c]}</Text> : null}
          </View>
        ))}
      </View>
      <View className="mt-1.5 flex-row items-center gap-2">
        <TagPill tag={p.tag} />
        <Text className="dfs-reason flex-1" numberOfLines={expanded ? undefined : 1}>
          {p.tag_reason}
        </Text>
      </View>
      {expanded ? (
        <View className="own-detail">
          {columns.map((c) => (
            <Text key={c} className="dfs-stats">
              {COLUMN[c]} by model:{' '}
              {Object.entries(p.ownership_models[c] ?? {})
                .map(([m, v]) => `${MODEL_LABEL[m] ?? m} ${v.toFixed(1)}%`)
                .join(' · ')}
            </Text>
          ))}
          <Text className="dfs-stats">
            Value {f.value_ratio.toFixed(2)} pts/$1k (#{f.position_value_rank} at {p.position}) · salary{' '}
            {formatSigned(f.salary_delta_vs_average / 1000, 1)}k vs position avg · team implied {f.team_implied_total} · scarcity{' '}
            {f.position_scarcity_index.toFixed(2)}
            {f.is_backup_injury_start ? ' · backup starting for an injured starter' : ''}
          </Text>
        </View>
      ) : null}
    </Pressable>
  );
}

/**
 * Every playable player with expected field ownership for the contest
 * type(s), most owned first, with Prioritize / Neutral / Fade tags. Filter by
 * position and tag; tap a row for each model's estimate and the engineered
 * features behind it.
 */
export default function OwnershipList({ players, columns }: { players: PlayPlayer[]; columns: OwnershipContest[] }) {
  const [position, setPosition] = useState('All');
  const [tag, setTag] = useState<'all' | PlayTag>('all');
  const [limit, setLimit] = useState(PAGE);
  const [open, setOpen] = useState<number | null>(null);
  const filtered = useMemo(
    () => players.filter((p) => (position === 'All' || p.position === position) && (tag === 'all' || p.tag === tag)),
    [players, position, tag],
  );
  return (
    <View>
      <Chips items={POSITIONS} value={position} label={(t) => t} onChange={(t) => (setPosition(t), setLimit(PAGE))} />
      <Chips items={TAGS} value={tag} label={(t) => TAG_LABEL[t]} onChange={(t) => (setTag(t), setLimit(PAGE))} />
      <View className="player-pool">
        {filtered.slice(0, limit).map((p) => (
          <OwnershipRow key={p.id} player={p} columns={columns} expanded={open === p.id} onToggle={() => setOpen((o) => (o === p.id ? null : p.id))} />
        ))}
        {!filtered.length ? <Text className="home-empty-state">No players match.</Text> : null}
      </View>
      {filtered.length > limit ? (
        <Pressable className="btn-outline mt-3" onPress={() => setLimit((n) => n + PAGE)} accessibilityRole="button">
          <Text className="btn-outline-text">Show more ({filtered.length - limit} left)</Text>
        </Pressable>
      ) : null}
    </View>
  );
}
