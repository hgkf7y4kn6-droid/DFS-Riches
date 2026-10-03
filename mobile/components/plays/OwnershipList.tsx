import { useState } from 'react';
import { Pressable, ScrollView, Text, View } from 'react-native';

import { UsageTrendArrow, UsageTrendNote } from '@/components/UsageTrend';
import MatchupBadge from '@/components/MatchupBadge';
import GameLog from '@/components/plays/GameLog';
import TagChoices from '@/components/plays/TagChoices';
import TagPill, { TAG_STYLE } from '@/components/plays/TagPill';
import { roleText, sortByMatchup } from '@/lib/matchup-sort';
import { useMatchups } from '@/lib/matchups-context';
import type { Pool } from '@/lib/pool-tags-context';
import { formatCurrency, formatSigned } from '@/lib/utils';

const POSITIONS = ['All', 'QB', 'RB', 'WR', 'TE', 'DST'];
type TagFilter = 'all' | 'mine' | PlayTag;
const TAGS: TagFilter[] = ['all', 'prioritize', 'neutral', 'fade', 'mine'];
const TAG_LABEL: Record<TagFilter, string> = { all: 'All tags', prioritize: 'Prioritize', neutral: 'Neutral', fade: 'Fade', mine: 'My changes' };
const MODEL_LABEL: Record<string, string> = {
  sim: 'Field sim',
  bt: 'Bradley-Terry',
  frac_logit: 'Fractional logit',
  gbm: 'LightGBM',
};
const COLUMN: Record<OwnershipContest, string> = { cash: 'Cash', small_gpp: 'Small GPP', large_gpp: 'Large GPP' };
const PAGE = 30;
type SortKey = 'own' | 'matchup';
const SORTS: SortKey[] = ['own', 'matchup'];
const SORT_LABEL: Record<SortKey, string> = { own: 'Most owned', matchup: 'Best matchup' };

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

interface RowProps {
  player: PlayPlayer;
  columns: OwnershipContest[];
  expanded: boolean;
  onToggle: () => void;
  pool: Pool;
}

function OwnershipRow({ player, columns, expanded, onToggle, pool }: RowProps) {
  const p = player;
  const f = p.features;
  const [picking, setPicking] = useState(false);
  const [trendOpen, setTrendOpen] = useState(false);
  return (
    <Pressable className="own-row" onPress={onToggle} accessibilityRole="button" accessibilityState={{ expanded }}>
      <View className="dfs-row-main">
        <View className="flex-1 pr-2">
          <View className="flex-row items-center">
            <Text className="dfs-name flex-shrink" numberOfLines={1}>
              {p.name}
              {p.injury && p.injury !== 'Healthy' ? <Text className="injury-tag"> {p.injury}</Text> : null}
            </Text>
            <UsageTrendArrow trend={p.usage_trend} open={trendOpen} onToggle={() => setTrendOpen((o) => !o)} />
          </View>
          <Text className="dfs-meta">
            {p.position} · {p.team} vs {p.opponent} · {formatCurrency(p.salary)} · {p.final.toFixed(1)} proj
            {roleText(p) ? ` · ${roleText(p)}` : ''}
          </Text>
          <MatchupBadge opponent={p.opponent} position={p.position} />
          <UsageTrendNote trend={p.usage_trend} open={trendOpen} />
        </View>
        {columns.map((c) => (
          <View key={c} className="own-col">
            <Text className="own-value">{(p.ownership[c] ?? 0).toFixed(1)}%</Text>
            {columns.length > 1 ? <Text className="own-label">{COLUMN[c]}</Text> : null}
          </View>
        ))}
      </View>
      <View className="mt-1.5 flex-row items-center gap-2">
        <TagPill tag={pool.tagOf(p)} mine={pool.isMine(p)} onPress={() => setPicking((v) => !v)} />
        <Text className="dfs-reason flex-1" numberOfLines={expanded ? undefined : 1}>
          {pool.isMine(p) ? `Your call (model: ${TAG_STYLE[p.tag].label}) · ` : ''}
          {p.tag_reason}
        </Text>
      </View>
      {picking ? <TagChoices player={p} pool={pool} onDone={() => setPicking(false)} /> : null}
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
          <GameLog player={p} />
        </View>
      ) : null}
    </Pressable>
  );
}

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`;

/** How the user's pool differs from the model's tags, with a reset. */
function PoolSummary({ players, pool }: { players: PlayPlayer[]; pool: Pool }) {
  const mine = players.filter((p) => pool.isMine(p));
  const count = (t: PlayTag) => players.filter((p) => pool.tagOf(p) === t).length;
  return (
    <View className="pool-summary">
      <Text className="pool-summary-text">
        Your pool: {count('prioritize')} prioritized · {count('fade')} faded
        {mine.length ? ` · ${plural(mine.length, 'change')} from the model` : ' · tap any tag to change it'}
      </Text>
      {mine.length ? (
        <Pressable onPress={pool.reset} hitSlop={8} accessibilityRole="button">
          <Text className="tag-choice-reset mt-0">Reset</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

/**
 * Every playable player with expected field ownership for the contest
 * type(s), most owned first, with Prioritize / Neutral / Fade tags. Tap a
 * tag to set your own call for your pool (saved on the device). Filter by
 * position and tag; tap a row for each model's estimate, the engineered
 * features behind it, and the player's recent game log.
 */
export default function OwnershipList({ players, columns, pool }: { players: PlayPlayer[]; columns: OwnershipContest[]; pool: Pool }) {
  const [position, setPosition] = useState('All');
  const [tag, setTag] = useState<TagFilter>('all');
  const [limit, setLimit] = useState(PAGE);
  const [open, setOpen] = useState<number | null>(null);
  const [sortBy, setSortBy] = useState<SortKey>('own');
  const { lookup } = useMatchups();
  const matching = players.filter(
    (p) =>
      (position === 'All' || p.position === position) &&
      (tag === 'all' || (tag === 'mine' ? pool.isMine(p) : pool.tagOf(p) === tag)),
  );
  const filtered = sortBy === 'matchup' ? sortByMatchup(matching, lookup, (p) => p.final) : matching;
  return (
    <View>
      <PoolSummary players={players} pool={pool} />
      <Chips items={POSITIONS} value={position} label={(t) => t} onChange={(t) => (setPosition(t), setLimit(PAGE))} />
      <Chips items={TAGS} value={tag} label={(t) => TAG_LABEL[t]} onChange={(t) => (setTag(t), setLimit(PAGE))} />
      <Chips items={SORTS} value={sortBy} label={(t) => SORT_LABEL[t]} onChange={(t) => (setSortBy(t), setLimit(PAGE))} />
      <View className="player-pool">
        {filtered.slice(0, limit).map((p) => (
          <OwnershipRow
            key={p.id}
            player={p}
            columns={columns}
            pool={pool}
            expanded={open === p.id}
            onToggle={() => setOpen((o) => (o === p.id ? null : p.id))}
          />
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
