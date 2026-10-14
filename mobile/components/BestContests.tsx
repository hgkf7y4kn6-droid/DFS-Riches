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
  { id: '1-5', label: '$1–$5' },
  { id: '6-10', label: '$6–$10' },
  { id: '11-25', label: '$11–$25' },
  { id: 'over25', label: 'Over $25' },
];
const KINDS: Option<ContestKind>[] = [
  { id: 'Tournament', label: 'Tournaments' },
  { id: 'Booster', label: 'Boosters' },
  { id: 'League', label: 'Leagues' },
  { id: 'Qualifier', label: 'Qualifiers' },
];

/** Score factors, with the server's default points (app.contests.WEIGHTS). */
const FACTORS: { id: ContestFactor; label: string; hint: string }[] = [
  { id: 'rake', label: 'Low rake', hint: 'Less of the entry fees kept by DraftKings' },
  { id: 'paid', label: 'Payout %', hint: 'More of the field gets paid' },
  { id: 'payout', label: 'First prize', hint: '1st place prize for the entry fee' },
  { id: 'field', label: 'Small field', hint: 'Fewer entries to beat' },
];
const DEFAULT_WEIGHTS: Record<ContestFactor, number> = { rake: 4, paid: 3, payout: 3, field: 0 };
const MAX_WEIGHT = 10;

const STORAGE_KEY = 'dfsriches:best-contests-filters';
const OLD_HIDDEN_KEY = 'dfsriches:best-contests-hidden';

interface Filters {
  /** Entry and fee group ids; empty = all. */
  entries: string[];
  fees: string[];
  hidden: ContestKind[];
  /** Points (0-MAX_WEIGHT) per score factor. */
  weights: Record<ContestFactor, number>;
}

const savedWeights = (w: unknown): Record<ContestFactor, number> => {
  if (!w || typeof w !== 'object') return DEFAULT_WEIGHTS;
  const out = { ...DEFAULT_WEIGHTS };
  for (const f of FACTORS) {
    const v = (w as Record<string, unknown>)[f.id];
    if (typeof v === 'number' && Number.isInteger(v) && v >= 0 && v <= MAX_WEIGHT) out[f.id] = v;
  }
  return Object.values(out).some(Boolean) ? out : DEFAULT_WEIGHTS;
};

const only = <T extends string>(ids: unknown, options: Option<T>[]): T[] =>
  Array.isArray(ids) ? options.map((o) => o.id).filter((id) => ids.includes(id)) : [];

/** The card's filters, remembered on this device. */
function useFilters() {
  const [filters, setFilters] = useState<Filters>({ entries: [], fees: [], hidden: [], weights: DEFAULT_WEIGHTS });
  const [loaded, setLoaded] = useState(false);
  useEffect(() => {
    Promise.all([AsyncStorage.getItem(STORAGE_KEY), AsyncStorage.getItem(OLD_HIDDEN_KEY)])
      .then(([raw, oldHidden]) => {
        const saved = raw ? JSON.parse(raw) : { hidden: oldHidden ? JSON.parse(oldHidden) : [] };
        setFilters({
          entries: only(saved.entries, ENTRY_GROUPS),
          fees: only(saved.fees, FEE_GROUPS),
          hidden: only(saved.hidden, KINDS),
          weights: savedWeights(saved.weights),
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

/** The latest value once it has stopped changing for ms, so quick taps make one request. */
function useSettled<T>(value: T, ms: number): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setSettled(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return settled;
}

/** A collapsible panel of 0-10 steppers, one per score factor, with each one's share of the score. */
function WeightsPanel({ weights, onChange }: { weights: Record<ContestFactor, number>; onChange: (w: Record<ContestFactor, number>) => void }) {
  const [open, setOpen] = useState(false);
  const total = Object.values(weights).reduce((a, b) => a + b, 0);
  const isDefault = FACTORS.every((f) => weights[f.id] === DEFAULT_WEIGHTS[f.id]);
  const set = (id: ContestFactor, v: number) => {
    const next = { ...weights, [id]: Math.max(0, Math.min(MAX_WEIGHT, v)) };
    if (Object.values(next).some(Boolean)) onChange(next); // at least one factor counts
  };
  const summary = FACTORS.filter((f) => weights[f.id])
    .map((f) => `${f.label} ${Math.round((weights[f.id] / total) * 100)}%`)
    .join(' · ');
  return (
    <View className="mb-2">
      <View className="flex-row items-center gap-2">
        <Text className="matchup-toggle-label w-14">Sort</Text>
        <Pressable
          className="filter-chip flex-row items-center shrink"
          onPress={() => setOpen((o) => !o)}
          accessibilityRole="button"
          aria-expanded={open}
          accessibilityLabel={`Sort weights: ${summary}. Change`}>
          <Text className="filter-chip-text" numberOfLines={1}>
            {isDefault ? 'Default weights' : 'Custom weights'} {open ? '▴' : '▾'}
          </Text>
        </Pressable>
      </View>
      {open ? (
        <View className="matchup-menu self-stretch">
          {FACTORS.map((f) => {
            const v = weights[f.id];
            return (
              <View key={f.id} className="matchup-menu-item flex-row items-center">
                <View className="flex-1 pr-2">
                  <Text className="matchup-menu-label">
                    {f.label} <Text className="caption">{total ? `${Math.round((v / total) * 100)}%` : ''}</Text>
                  </Text>
                  <Text className="matchup-menu-hint">{f.hint}</Text>
                </View>
                <Pressable
                  className="filter-chip"
                  onPress={() => set(f.id, v - 1)}
                  disabled={v === 0}
                  accessibilityRole="button"
                  accessibilityLabel={`Less weight on ${f.label}`}>
                  <Text className="filter-chip-text">−</Text>
                </Pressable>
                <Text className="pl-stat-value w-6 text-center" accessibilityLabel={`${f.label} weight ${v} of ${MAX_WEIGHT}`}>
                  {v}
                </Text>
                <Pressable
                  className="filter-chip"
                  onPress={() => set(f.id, v + 1)}
                  disabled={v === MAX_WEIGHT}
                  accessibilityRole="button"
                  accessibilityLabel={`More weight on ${f.label}`}>
                  <Text className="filter-chip-text">+</Text>
                </Pressable>
              </View>
            );
          })}
          <View className="matchup-menu-item flex-row justify-between">
            <Pressable onPress={() => onChange(DEFAULT_WEIGHTS)} disabled={isDefault} accessibilityRole="button">
              <Text className={`text-xs ${isDefault ? 'caption' : 'link-text'}`}>Reset to default</Text>
            </Pressable>
            <Pressable onPress={() => setOpen(false)} accessibilityRole="button">
              <Text className="link-text text-xs">Done</Text>
            </Pressable>
          </View>
        </View>
      ) : null}
    </View>
  );
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

const OTHER_SLATES_SHOWN = 3;

/** "25 copies on 9 slates · also SEA @ DEN, CHI @ ATL, HOU vs JAX +5"; the row is the fullest copy. */
function copiesNote(c: BestContest) {
  const others = c.slates.filter((s) => s !== c.slate);
  const where = c.slates.length > 1 ? ` on ${c.slates.length} slates` : '';
  const also = others.length
    ? ` · also ${others.slice(0, OTHER_SLATES_SHOWN).join(', ')}${others.length > OTHER_SLATES_SHOWN ? ` +${others.length - OTHER_SLATES_SHOWN}` : ''}`
    : '';
  return `⧉ ${c.copies} copies${where}${also} · opens the fullest`;
}

function ContestRow({ contest: c, rank }: { contest: BestContest; rank: number }) {
  return (
    <Pressable
      className="pl-row"
      onPress={() => Linking.openURL(`https://www.draftkings.com/draft/contest/${c.id}`)}
      accessibilityRole="link"
      accessibilityLabel={`${c.name}, score ${c.score}${c.copies > 1 ? `, ${c.copies} copies` : ''}, open on DraftKings`}>
      <View className="pl-row-header">
        <Text className="pl-type flex-1 pr-2" numberOfLines={2}>
          {rank}. {c.title}
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
          c.guaranteed ? '' : 'not guaranteed',
        ]
          .filter(Boolean)
          .join(' · ')}
      </Text>
      {c.copies > 1 ? <Text className="caption mt-0.5">{copiesNote(c)}</Text> : null}
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
  // Nothing until the saved filters load; then the filters once they stop changing.
  const settled = useSettled(loaded ? filters : null, 400);
  const { entries, fees, hidden, weights } = settled ?? filters;
  const exclude = [...hidden].sort();
  const key = settled ? JSON.stringify([entries, fees, exclude, weights]) : '';
  const { data, error, loading } = useCachedFetch(cache, key, () => getBestContests({ entries, fees, exclude, weights }));
  const w = data?.weights;
  const weighs = w
    ? FACTORS.filter((f) => w[f.id])
        .map((f) => `${f.label.toLowerCase()} ${Math.round(w[f.id] * 100)}%`)
        .join(', ')
    : '';
  return (
    <View>
      <MultiSelect label="Entries" allLabel="All entry limits" options={ENTRY_GROUPS} value={filters.entries} onChange={(v) => update({ entries: v })} />
      <MultiSelect label="Fee" allLabel="All entry fees" options={FEE_GROUPS} value={filters.fees} onChange={(v) => update({ fees: v })} />
      <WeightsPanel weights={filters.weights} onChange={(v) => update({ weights: v })} />
      <KindChips hidden={filters.hidden} onChange={(v) => update({ hidden: v })} />
      {!data ? (
        <StatusView loading={loading || !settled} error={error} />
      ) : (
        <>
          <Text className="caption mb-1">
            Best {data.contests.length} of {data.matching.toLocaleString('en-US')} matching. Score ranks each against the
            other matches on {weighs}.
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
