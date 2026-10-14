import AsyncStorage from '@react-native-async-storage/async-storage';
import { useEffect, useState } from 'react';
import { Linking, Pressable, ScrollView, Text, View } from 'react-native';

import StatusView from '@/components/StatusView';
import { getBestContests } from '@/lib/api';
import { createFetchCache, useCachedFetch } from '@/lib/cached-fetch';
import { formatEt, formatPercent } from '@/lib/utils';

const cache = createFetchCache<BestContestsResponse>();

type Option<T extends string = string> = { id: T; label: string };

// The server's groups and kinds (app.contests ENTRY_GROUPS, FEE_GROUPS, CONTEST_KINDS),
// here so the filters show before the first response.
const ENTRY_GROUPS: Option[] = [
  { id: 'se', label: 'Single entry' },
  { id: '2-10', label: '2–10 max' },
  { id: '20', label: '20 max (11–20)' },
  { id: '150', label: '150 max (21–150)' },
];
const FEE_GROUPS: Option[] = [
  { id: 'under1', label: 'Under $1' },
  { id: '1-4', label: '$1–$4' },
  { id: '5-9', label: '$5–$9' },
  { id: '10-25', label: '$10–$25' },
  { id: 'over25', label: 'Over $25' },
];
const KINDS: Option<ContestKind>[] = [
  { id: 'Tournament', label: 'Tournaments' },
  { id: 'Booster', label: 'Boosters' },
  { id: 'League', label: 'Leagues' },
  { id: 'Qualifier', label: 'Qualifiers' },
];

const STORAGE_KEY = 'dfsriches:best-contests-filters';
const OLD_HIDDEN_KEY = 'dfsriches:best-contests-hidden';

interface Filters {
  /** Entry and fee group ids; empty = all. */
  entries: string[];
  fees: string[];
  hidden: ContestKind[];
}

const only = <T extends string>(ids: unknown, options: Option<T>[]): T[] =>
  Array.isArray(ids) ? options.map((o) => o.id).filter((id) => ids.includes(id)) : [];

/** The card's filters, remembered on this device. */
function useFilters() {
  const [filters, setFilters] = useState<Filters>({ entries: [], fees: [], hidden: [] });
  const [loaded, setLoaded] = useState(false);
  useEffect(() => {
    Promise.all([AsyncStorage.getItem(STORAGE_KEY), AsyncStorage.getItem(OLD_HIDDEN_KEY)])
      .then(([raw, oldHidden]) => {
        const saved = raw ? JSON.parse(raw) : { hidden: oldHidden ? JSON.parse(oldHidden) : [] };
        setFilters({
          entries: only(saved.entries, ENTRY_GROUPS),
          fees: only(saved.fees, FEE_GROUPS),
          hidden: only(saved.hidden, KINDS),
        });
      })
      .catch(() => {})
      .finally(() => setLoaded(true));
  }, []);
  const update = (patch: Partial<Filters>) =>
    setFilters((f) => {
      const next = { ...f, ...patch };
      AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(next)).catch(() => {});
      return next;
    });
  return { filters, loaded, update };
}

/** A dropdown of checkboxes; nothing checked means all. */
function MultiSelect({
  label,
  allLabel,
  options,
  value,
  onChange,
}: {
  label: string;
  allLabel: string;
  options: Option[];
  value: string[];
  onChange: (ids: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const summary = !value.length
    ? allLabel
    : value.length <= 2
      ? options
          .filter((o) => value.includes(o.id))
          .map((o) => o.label.replace(/ \(.*\)$/, ''))
          .join(', ')
      : `${value.length} selected`;
  const toggle = (id: string) => {
    const next = value.includes(id) ? value.filter((v) => v !== id) : [...value, id];
    // Everything checked is the same as all: keep "all" as the empty list.
    onChange(next.length === options.length ? [] : options.map((o) => o.id).filter((o) => next.includes(o)));
  };
  return (
    <View className="mb-2">
      <View className="flex-row items-center gap-2">
        <Text className="matchup-toggle-label w-14">{label}</Text>
        <Pressable
          className="filter-chip flex-row items-center"
          onPress={() => setOpen((o) => !o)}
          accessibilityRole="button"
          aria-expanded={open}
          accessibilityLabel={`${label}: ${summary}. Change`}>
          <Text className="filter-chip-text">
            {summary} {open ? '▴' : '▾'}
          </Text>
        </Pressable>
      </View>
      {open ? (
        <View className="matchup-menu">
          <Pressable
            className={`matchup-menu-item ${!value.length ? 'matchup-menu-item-active' : ''}`}
            onPress={() => onChange([])}
            accessibilityRole="checkbox"
            aria-checked={!value.length}>
            <Text className="matchup-menu-label">
              {!value.length ? '☑ ' : '☐ '}
              {allLabel}
            </Text>
          </Pressable>
          {options.map((o) => {
            const checked = value.includes(o.id);
            return (
              <Pressable
                key={o.id}
                className={`matchup-menu-item ${checked ? 'matchup-menu-item-active' : ''}`}
                onPress={() => toggle(o.id)}
                accessibilityRole="checkbox"
                aria-checked={checked}>
                <Text className="matchup-menu-label">
                  {checked ? '☑ ' : '☐ '}
                  {o.label}
                </Text>
              </Pressable>
            );
          })}
          <Pressable className="matchup-menu-item" onPress={() => setOpen(false)} accessibilityRole="button">
            <Text className="link-text text-xs">Done</Text>
          </Pressable>
        </View>
      ) : null}
    </View>
  );
}

function KindChips({ hidden, onChange }: { hidden: ContestKind[]; onChange: (hidden: ContestKind[]) => void }) {
  return (
    <ScrollView horizontal showsHorizontalScrollIndicator={false} className="chip-row mb-2" contentContainerClassName="chip-row-content">
      <Text className="matchup-toggle-label mr-1 self-center">Show</Text>
      {KINDS.map((k) => {
        const shown = !hidden.includes(k.id);
        return (
          <Pressable
            key={k.id}
            className={`filter-chip ${shown ? 'filter-chip-active' : ''}`}
            onPress={() => {
              const next = shown ? [...hidden, k.id] : hidden.filter((h) => h !== k.id);
              if (next.length < KINDS.length) onChange(next); // keep at least one kind showing
            }}
            accessibilityRole="checkbox"
            aria-checked={shown}
            accessibilityLabel={`${k.label}, ${shown ? 'shown' : 'hidden'}`}>
            <Text className={`filter-chip-text ${shown ? 'filter-chip-text-active' : ''}`}>
              {shown ? '✓ ' : ''}
              {k.label}
            </Text>
          </Pressable>
        );
      })}
    </ScrollView>
  );
}

/** Whole dollars when the amount is, cents otherwise: 1500 -> "$1,500", 0.25 -> "$0.25". */
const money = (n: number) =>
  `$${n.toLocaleString('en-US', { minimumFractionDigits: Number.isInteger(n) ? 0 : 2, maximumFractionDigits: 2 })}`;

/** Big prizes short: 1000000 -> "$1M", 25000 -> "$25K". */
const shortMoney = (n: number) =>
  n >= 1_000_000 ? `$${+(n / 1_000_000).toFixed(2)}M` : n >= 10_000 ? `$${+(n / 1000).toFixed(1)}K` : money(n);

function ContestRow({ contest: c, rank }: { contest: BestContest; rank: number }) {
  return (
    <Pressable
      className="pl-row"
      onPress={() => Linking.openURL(`https://www.draftkings.com/draft/contest/${c.id}`)}
      accessibilityRole="link"
      accessibilityLabel={`${c.name}, score ${c.score}, open on DraftKings`}>
      <View className="pl-row-header">
        <Text className="pl-type flex-1 pr-2" numberOfLines={2}>
          {rank}. {c.name}
        </Text>
        <Text className="pl-net text-foreground">{money(c.entry_fee)}</Text>
      </View>
      <View className="pl-stats">
        {[
          ['Score', String(Math.round(c.score))],
          ['Rake', formatPercent(c.rake)],
          ['Paid', c.paid_pct == null ? '-' : formatPercent(c.paid_pct, 0)],
          ['1st', c.top_prize == null ? '-' : `${shortMoney(c.top_prize)} (${Math.round(c.top_multiple ?? 0).toLocaleString('en-US')}x)`],
          ['Field', `${c.entries.toLocaleString('en-US')}/${c.field_size.toLocaleString('en-US')}`],
        ].map(([label, value]) => (
          <View key={label}>
            <Text className="pl-stat-value">{value}</Text>
            <Text className="pl-stat-label">{label}</Text>
          </View>
        ))}
      </View>
      <Text className="caption mt-1">
        {[
          c.game_type === 'Classic' ? 'Classic' : 'Showdown',
          c.slate,
          c.kind === 'Tournament' ? '' : c.kind,
          c.max_entries === 1 ? 'single entry' : `max ${c.max_entries}`,
          formatEt(c.start_utc),
          c.copies > 1 ? `${c.copies} copies` : '',
          c.guaranteed ? '' : 'not guaranteed',
        ]
          .filter(Boolean)
          .join(' · ')}
      </Text>
    </Pressable>
  );
}

/**
 * The 15 best DraftKings NFL GPPs for any mix of max-entries limits, entry fees and
 * contest kinds: low rake, a big share of the field paid, and a big first prize for
 * the fee. Tapping one opens it on DraftKings.
 */
export default function BestContests() {
  const { filters, loaded, update } = useFilters();
  const { entries, fees, hidden } = filters;
  const exclude = [...hidden].sort();
  const key = loaded ? JSON.stringify([entries, fees, exclude]) : '';
  const { data, error, loading } = useCachedFetch(cache, key, () => getBestContests({ entries, fees, exclude }));
  const w = data?.weights;
  const pct = (n: number | undefined) => (n == null ? '' : ` (${Math.round(n * 100)}%)`);
  return (
    <View>
      <MultiSelect label="Entries" allLabel="All entry limits" options={ENTRY_GROUPS} value={entries} onChange={(v) => update({ entries: v })} />
      <MultiSelect label="Fee" allLabel="All entry fees" options={FEE_GROUPS} value={fees} onChange={(v) => update({ fees: v })} />
      <KindChips hidden={hidden} onChange={(v) => update({ hidden: v })} />
      {!data ? (
        <StatusView loading={loading || !loaded} error={error} />
      ) : (
        <>
          <Text className="caption mb-1">
            Best {data.contests.length} of {data.matching.toLocaleString('en-US')} matching. Score weighs low rake
            {pct(w?.rake)}, share of the field paid{pct(w?.paid)} and first prize for the fee{pct(w?.payout)} against
            the other matches.
          </Text>
          {data.contests.length ? (
            data.contests.map((c, i) => <ContestRow key={c.id} contest={c} rank={i + 1} />)
          ) : (
            <Text className="home-empty-state">No upcoming contests match these filters.</Text>
          )}
        </>
      )}
    </View>
  );
}
