import { useState } from 'react';
import { Linking, Pressable, ScrollView, Text, View } from 'react-native';

import StatusView from '@/components/StatusView';
import { getBestContests } from '@/lib/api';
import { createFetchCache, useCachedFetch } from '@/lib/cached-fetch';
import { formatEt, formatPercent } from '@/lib/utils';

const cache = createFetchCache<BestContestsResponse>();

/** Whole dollars when the amount is, cents otherwise: 1500 -> "$1,500", 0.25 -> "$0.25". */
const money = (n: number) =>
  `$${n.toLocaleString('en-US', { minimumFractionDigits: Number.isInteger(n) ? 0 : 2, maximumFractionDigits: 2 })}`;

function ChipRow({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: { id: string; label: string }[];
  value: string;
  onChange: (id: string) => void;
}) {
  return (
    <ScrollView horizontal showsHorizontalScrollIndicator={false} className="chip-row mb-2" contentContainerClassName="chip-row-content">
      <Text className="matchup-toggle-label mr-1 self-center">{label}</Text>
      {options.map((o) => {
        const active = o.id === value;
        return (
          <Pressable
            key={o.id}
            className={`filter-chip ${active ? 'filter-chip-active' : ''}`}
            onPress={() => onChange(o.id)}
            accessibilityRole="button"
            aria-pressed={active}>
            <Text className={`filter-chip-text ${active ? 'filter-chip-text-active' : ''}`}>{o.label}</Text>
          </Pressable>
        );
      })}
    </ScrollView>
  );
}

function ContestRow({ contest: c, rank }: { contest: BestContest; rank: number }) {
  return (
    <Pressable
      className="pl-row"
      onPress={() => Linking.openURL(`https://www.draftkings.com/draft/contest/${c.id}`)}
      accessibilityRole="link"
      accessibilityLabel={`${c.name}, open on DraftKings`}>
      <View className="pl-row-header">
        <Text className="pl-type flex-1 pr-2" numberOfLines={2}>
          {rank}. {c.name}
        </Text>
        <Text className="pl-net text-foreground">{money(c.entry_fee)}</Text>
      </View>
      <View className="pl-stats">
        {[
          ['Rake', formatPercent(c.rake)],
          ['Paid', c.paid_pct == null ? '-' : formatPercent(c.paid_pct, 0)],
          ['Prizes', money(c.prize_pool)],
          ['Field', `${c.entries.toLocaleString('en-US')}/${c.field_size.toLocaleString('en-US')}`],
          ['Max', String(c.max_entries)],
        ].map(([label, value]) => (
          <View key={label}>
            <Text className="pl-stat-value">{value}</Text>
            <Text className="pl-stat-label">{label}</Text>
          </View>
        ))}
      </View>
      <Text className="caption mt-1">
        {[c.game_type === 'Classic' ? 'Classic' : 'Showdown', c.slate, c.kind === 'Tournament' ? '' : c.kind, formatEt(c.start_utc)]
          .filter(Boolean)
          .join(' · ')}
        {c.guaranteed ? '' : ' · not guaranteed'}
      </Text>
    </Pressable>
  );
}

/**
 * DraftKings' lowest-rake NFL GPPs for a max-entries group and entry-fee range,
 * ties broken by the share of the field paid. Tapping one opens it on DraftKings.
 */
export default function BestContests() {
  const { data, error, loading } = useCachedFetch(cache, 'best', getBestContests);
  const [entryGroup, setEntryGroup] = useState('se');
  const [feeGroup, setFeeGroup] = useState('1-4');

  if (!data) return <StatusView loading={loading} error={error} />;
  const rows = data.contests[entryGroup]?.[feeGroup] ?? [];
  const range = data.entry_groups.find((g) => g.id === entryGroup);
  return (
    <View>
      <ChipRow label="Entries" options={data.entry_groups} value={entryGroup} onChange={setEntryGroup} />
      <ChipRow label="Fee" options={data.fee_groups} value={feeGroup} onChange={setFeeGroup} />
      <Text className="caption mb-1">
        Rake = share of entry fees DraftKings keeps · Paid = share of the field that cashes
        {range && range.min !== range.max ? ` · ${range.min}–${range.max} entries per user` : ''}
      </Text>
      {rows.length ? (
        rows.map((c, i) => <ContestRow key={c.id} contest={c} rank={i + 1} />)
      ) : (
        <Text className="home-empty-state">No upcoming GPPs in this range.</Text>
      )}
    </View>
  );
}
