import { useEffect, useMemo, useRef, useState } from 'react';
import { Image, Pressable, ScrollView, Text, TextInput, View } from 'react-native';

import MatchupModeToggle from '@/components/MatchupModeToggle';
import { LineupRow, type RowPlayer, Totals } from '@/components/LineupRows';
import StatusView from '@/components/StatusView';
import SubmissionForm from '@/components/SubmissionForm';
import { MAX_LINEUPS } from '@/constants/config';
import { PLAYABLE_STATUSES, POSITION_FILTERS } from '@/constants/data';
import icons from '@/constants/icons';
import { useThemeColors } from '@/constants/theme';
import { addPlayer, fitChecker, indexOfPlayer, removeAt, summarize, template } from '@/lib/lineups';
import { sortByMatchup } from '@/lib/matchup-sort';
import { useSlateOwnership } from '@/lib/slate-ownership';
import { useLeverage } from '@/lib/leverage-context';
import { useSubmissions } from '@/lib/submissions-context';
import { matchupScore, useMatchups } from '@/lib/matchups-context';
import { formatCurrency, formatEt, formatPoints } from '@/lib/utils';
import { evenWeights, type Factor, setWeight, totalWeight, type Weights, weightedRank } from '@/lib/weighted-sort';
import { type LineupScope, useLineups, useWeek } from '@/lib/week-context';

const PAGE = 40;

type SortKey = 'proj' | 'floor' | 'ceiling' | 'value' | 'salary' | 'own' | 'lev' | 'env' | 'touch' | 'l3' | 'l6' | 'l9' | 'matchup';
const SORTS: { key: SortKey; label: string }[] = [
  { key: 'proj', label: 'Projection' },
  { key: 'floor', label: 'Floor' },
  { key: 'ceiling', label: 'Ceiling' },
  { key: 'value', label: 'Value' },
  { key: 'salary', label: 'Salary' },
  { key: 'own', label: 'Ownership' },
  { key: 'lev', label: 'Leverage' },
  { key: 'env', label: 'Game environment' },
  { key: 'touch', label: 'Touch %' },
  { key: 'l3', label: 'Last 3' },
  { key: 'l6', label: 'Last 6' },
  { key: 'l9', label: 'Last 9' },
  { key: 'matchup', label: 'Matchup' },
];
const SORT_LABEL = Object.fromEntries(SORTS.map((o) => [o.key, o.label])) as Record<SortKey, string>;
// The FLEX filter: every player who can fill the FLEX slot.
const FLEX_POSITIONS = new Set(['RB', 'WR', 'TE']);
const STEP = 5;
const SORT_NOTE: Record<SortKey, string> = {
  proj: 'Projected DK points',
  floor: "Floor: the DFS model's low-end (15th-percentile) DK score -- what a cash lineup leans on",
  ceiling: 'Ceiling: the 85th-percentile DK score (one game in seven)',
  value: 'Projected points per $1k of salary',
  salary: 'DraftKings salary',
  own: 'Expected large-field ownership from the DFS model',
  lev: "Leverage: fair minus projected ownership (points) -- fair ownership spreads the position's ownership by efficiency-adjusted odds (ceiling for GPP, 2.5x salary for cash)",
  env: "Game environment: the model's score for his team's scoring setup -- implied total, game total, pace and weather",
  touch: "Touch %: his share of the team's RB / WR / TE touches (carries + receptions) over the last 3 games",
  l3: 'DK points per game over his last 3 games this season (shown once he has played 3)',
  l6: 'DK points per game over his last 6 games this season (shown once he has played 6)',
  l9: 'DK points per game over his last 9 games this season (shown once he has played 9)',
  matchup:
    'Softest matchups first (#32 = allows the most), starters and rotation players (committee backs, every-down WRs) ahead of backups.',
};

/** Expected ownership (and model floor) for the field a lineup is being built for, by DK draftable id. */
export interface BuildField {
  /** e.g. "Cash", "Large-field GPP" */
  label: string;
  ownership: Map<number, number>;
  floor?: Map<number, number>;
  /** The model's game-environment score (z within the position: implied total, game total, pace, weather). */
  env?: Map<number, number>;
  /** Fair minus projected ownership in points (app/leverage.py) for this field. */
  leverage?: Map<number, number>;
}

/**
 * Build up to MAX_LINEUPS lineups for the selected slate: the active lineup
 * as a stacked vertical list of slots (tap x to remove), its totals, then the
 * player pool -- filter by position, search, tap + to add. Players that
 * can't fit (no open slot, or too little salary left to fill the rest) are
 * dimmed with the reason.
 */
export default function LineupBuilder({ scope = '', field }: { scope?: LineupScope; field?: BuildField } = {}) {
  const { selectedSlate, players, weekData } = useWeek();
  const { lineups, activeLineup, setActiveLineup, setLineup, addLineup, deleteLineup, saveLineups, savedAt, unsaved } = useLineups(scope);
  // Late swap: a logged entry's lineup open for editing (scope "edit").
  const { editing, updateLineup, stopEditing } = useSubmissions();
  const editMode = scope === 'edit' && editing != null;
  const colors = useThemeColors();
  const [position, setPosition] = useState('All');
  const [query, setQuery] = useState('');
  const [showAll, setShowAll] = useState(false);
  // One or more sorts; with several, each gets a weight (always totalling 100%) and players rank on the blend.
  const [selected, setSelected] = useState<SortKey[]>(['proj']);
  const [weights, setWeights] = useState<Weights<SortKey>>({ proj: 100 });
  // Per sort: lower values rank higher (e.g. cheaper salary, lower ownership). Tap the only sort again to flip it.
  const [lowFirst, setLowFirst] = useState<Partial<Record<SortKey, boolean>>>({});
  const sortBy = selected[0];
  const blended = selected.length > 1;
  const ascending = Boolean(lowFirst[sortBy]);
  const { lookup } = useMatchups();
  const { lookup: leverageOf, request: requestLeverage } = useLeverage();
  const [limit, setLimit] = useState(PAGE);
  const [message, setMessage] = useState<{ text: string; error?: boolean } | null>(null);
  const [logging, setLogging] = useState(false);

  const slateType: SlateType = selectedSlate?.slate_type ?? 'classic';
  const pool = useMemo(() => players.data?.players ?? [], [players.data]);
  // With a field (Cash / GPP tabs) ownership comes from that contest's plays; otherwise the DFS model, on demand.
  const modelOwn = useSlateOwnership(selectedSlate, !field && selected.includes('own'));
  const own = field ? { ownership: field.ownership, available: true, loading: false, error: null } : modelOwn;
  const hasWindow = (k: 'trend_l6' | 'trend_l9') => pool.some((p) => p[k] != null);
  const sorts = SORTS.filter(
    (o) =>
      (o.key !== 'floor' || field?.floor) &&
      (o.key !== 'l6' || hasWindow('trend_l6')) &&
      (o.key !== 'l9' || hasWindow('trend_l9')),
  );
  // Game environment without the model (the Lineups tab): each team's Vegas implied total.
  const implied = useMemo(() => {
    const m = new Map<string, number>();
    for (const g of weekData.data?.schedule.games ?? []) {
      if (g.context?.away_implied_total != null) m.set(g.away, g.context.away_implied_total);
      if (g.context?.home_implied_total != null) m.set(g.home, g.context.home_implied_total);
    }
    return m;
  }, [weekData.data]);
  const lineup = useMemo(() => lineups[activeLineup] ?? [], [lineups, activeLineup]);
  const defs = template(slateType);
  const summary = summarize(lineup, slateType);
  const baseFits = useMemo(() => fitChecker(lineup, slateType, pool), [lineup, slateType, pool]);
  // While editing an entry, players whose games have kicked off are locked in (or out), like DraftKings late swap.
  const [now] = useState(() => Date.now());
  const lockedTeams = useMemo(() => {
    if (!editMode || !selectedSlate) return new Set<string>();
    return new Set(selectedSlate.games.filter((g) => new Date(g.kickoff_utc).getTime() <= now).flatMap((g) => [g.away, g.home]));
  }, [editMode, selectedSlate, now]);
  const fits = (p: Player) => (lockedTeams.has(p.team) && indexOfPlayer(lineup, p) === -1 ? { ok: false, reason: 'Game started: locked' } : baseFits(p));

  // Load the entry's lineup into the edit builder once its slate's players are in.
  const loadedFor = useRef<string | null>(null);
  useEffect(() => {
    const pool = players.data?.players;
    if (!editMode || !editing || !pool || players.data?.slate.slate_id !== editing.slateId) return;
    const stamp = `${editing.id}:${editing.editedAt ?? ''}`;
    if (loadedFor.current === stamp) return;
    loadedFor.current = stamp;
    const byId = new Map(pool.map((p) => [p.dk_draftable_id, p]));
    let slots: BuilderLineup = defs.map(() => null);
    for (const sp of editing.lineup ?? []) {
      const p = byId.get(sp.dk_draftable_id);
      if (!p) continue;
      const res = addPlayer(slots, slateType, p);
      if (res.ok) slots = res.slots;
    }
    setActiveLineup(0);
    setLineup(0, slots);
    // defs / setters follow slateType and scope
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editMode, editing, players.data, slateType]);

  /** The active lineup as stored on a logged entry. */
  const asSubmitted = (): SubmittedPlayer[] =>
    lineup.flatMap((p, i) =>
      p ? [{ slot: defs[i].label, dk_draftable_id: p.dk_draftable_id, name: p.name, team: p.team, position: p.position, salary: p.salary }] : [],
    );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = pool
      .filter((p) => showAll || PLAYABLE_STATUSES.has(p.injury ?? 'Healthy'))
      .filter((p) => {
        if (position === 'All') return true;
        if (slateType === 'showdown') return p.roster_slot === position;
        return position === 'FLEX' ? FLEX_POSITIONS.has(p.position) : p.position === position;
      })
      .filter((p) => !q || p.name.toLowerCase().includes(q) || p.team.toLowerCase() === q);
    const ownership = own.ownership;
    const value: Record<SortKey, (p: Player) => number | null | undefined> = {
      proj: (p) => p.proj_points,
      floor: (p) => (p.dk_draftable_id != null ? field?.floor?.get(p.dk_draftable_id) ?? null : null),
      ceiling: (p) => p.ceiling,
      value: (p) => p.value_per_1k,
      salary: (p) => p.salary,
      own: (p) => (p.dk_draftable_id != null ? ownership?.get(p.dk_draftable_id) ?? null : null),
      // This tab's contest leverage, else large-field GPP leverage for the DFS model's slate.
      lev: (p) =>
        field?.leverage
          ? p.dk_draftable_id != null
            ? field.leverage.get(p.dk_draftable_id) ?? null
            : null
          : leverageOf({ id: p.dk_draftable_id, name: p.name, team: p.team })?.value ?? null,
      env: (p) => (field?.env ? (p.dk_draftable_id != null ? field.env.get(p.dk_draftable_id) ?? null : null) : implied.get(p.team) ?? null),
      touch: (p) => p.team_share?.touch_pct ?? null,
      l3: (p) => p.trend_l3,
      l6: (p) => p.trend_l6,
      l9: (p) => p.trend_l9,
      // Higher = softer defense vs his position.
      matchup: (p) => {
        const m = lookup(p.opponent, p.position);
        return m ? matchupScore(m) : null;
      },
    };
    if (blended) {
      const factors: Factor<Player>[] = selected.map((k) => ({ weight: weights[k] ?? 0, value: value[k], ascending: Boolean(lowFirst[k]) }));
      return weightedRank(list, factors).map(({ item, score }) => ({ player: item, blend: score }));
    }
    if (sortBy === 'matchup') return sortByMatchup(list, lookup, (p) => p.proj_points).map((p) => ({ player: p, blend: null }));
    const get = value[sortBy];
    const dir = ascending ? 1 : -1;
    // Players with no value for the sort (no ceiling, no ownership, no games) go last either way.
    return list
      .sort((a, b) => {
        const va = get(a);
        const vb = get(b);
        if (va == null || vb == null) return va == null && vb == null ? b.proj_points - a.proj_points : va == null ? 1 : -1;
        return dir * (va - vb) || b.proj_points - a.proj_points;
      })
      .map((p) => ({ player: p, blend: null as number | null }));
  }, [pool, position, query, showAll, slateType, selected, weights, lowFirst, blended, sortBy, ascending, lookup, own.ownership, field, implied, leverageOf]);

  /** Tap a sort: add it (weights reset to an even split), or remove it; tapping the only sort flips its direction. */
  const pressSort = (key: SortKey) => {
    setLimit(PAGE);
    if (key === 'lev') requestLeverage();
    if (!selected.includes(key)) {
      const next = [...selected, key];
      setSelected(next);
      setWeights(evenWeights(next));
      return;
    }
    if (selected.length === 1) {
      if (key !== 'matchup') setLowFirst((d) => ({ ...d, [key]: !d[key] }));
      return;
    }
    const next = selected.filter((k) => k !== key);
    setSelected(next);
    setWeights(evenWeights(next));
  };
  const changeWeight = (key: SortKey, v: number) => setWeights((w) => setWeight(w, selected, key, v));

  // What each pool row shows beyond projection: the field's ownership (always, on the Cash / GPP tabs), floor for cash.
  const rowPlayer = (p: Player) => {
    const id = p.dk_draftable_id;
    const extra: Pick<RowPlayer, 'ownership' | 'floor' | 'form' | 'leverage' | 'env'> = {};
    if (field || selected.includes('own')) extra.ownership = id != null ? own.ownership?.get(id) ?? null : null;
    if (field?.floor) extra.floor = id != null ? field.floor.get(id) ?? null : null;
    if (field?.leverage) extra.leverage = id != null ? field.leverage.get(id) ?? null : null;
    if (selected.includes('env')) {
      extra.env = field?.env
        ? { value: id != null ? field.env.get(id) ?? null : null, kind: 'score' }
        : { value: implied.get(p.team) ?? null, kind: 'implied' };
    }
    if (selected.some((k) => k === 'l3' || k === 'l6' || k === 'l9')) {
      extra.form = { l3: p.trend_l3, l6: p.trend_l6, l9: p.trend_l9, season: p.trend_season ?? null };
    }
    return { ...p, ...extra };
  };

  if (!selectedSlate) return null;
  if (!selectedSlate.available) {
    return <Text className="empty-text">DraftKings has not posted salaries for this slate yet.</Text>;
  }

  const toggle = (player: Player) => {
    if (lockedTeams.has(player.team)) {
      setMessage({ text: `${player.name}'s game has started: he's locked.`, error: true });
      return;
    }
    const idx = indexOfPlayer(lineup, player);
    if (idx !== -1) {
      setLineup(activeLineup, removeAt(lineup, idx));
      setMessage({ text: `Removed ${player.name}.` });
      return;
    }
    const res = addPlayer(lineup, slateType, player);
    if (!res.ok) {
      setMessage({ text: res.reason, error: true });
      return;
    }
    setLineup(activeLineup, res.slots);
    setMessage({ text: `Added ${player.name} at ${defs[res.index].label}.` });
  };

  return (
    <View>
      {editMode ? (
        <View className="edit-banner">
          <Text className="edit-banner-title">Editing your logged entry</Text>
          <Text className="edit-banner-text">
            {editing!.contestName || 'Contest entry'} · {editing!.entries} × {formatCurrency(editing!.entryFee)} · {editing!.slateLabel}. Swap players for late news;
            players whose games have started are locked.
          </Text>
          <View className="mt-2 flex-row gap-2">
            <Pressable
              className={`btn-accent flex-1 ${summary.valid ? '' : 'opacity-50'}`}
              disabled={!summary.valid}
              onPress={() => {
                updateLineup(editing!.id, asSubmitted());
                setMessage({ text: 'Entry updated with your new lineup.' });
                stopEditing();
              }}
              accessibilityRole="button">
              <Text className="btn-text">
                {summary.valid
                  ? 'Save changes to entry'
                  : summary.filled < summary.total
                    ? `Fill every slot (${summary.filled}/${summary.total})`
                    : summary.errors[0] ?? 'Lineup not valid yet'}
              </Text>
            </Pressable>
            <Pressable className="btn-outline px-4" onPress={stopEditing} accessibilityRole="button">
              <Text className="btn-outline-text">Cancel</Text>
            </Pressable>
          </View>
        </View>
      ) : null}
      {/* Save: keeps this slate's lineups on the device */}
      {!editMode ? (
      <View className="save-row">
        <Text className="save-status">
          {savedAt ? (unsaved ? `Unsaved changes · last saved ${formatEt(savedAt)}` : `Saved ${formatEt(savedAt)}`) : 'Not saved yet'}
        </Text>
        <Pressable
          className={`save-btn ${unsaved ? '' : 'save-btn-idle'}`}
          onPress={() => {
            saveLineups();
            setMessage({ text: `Saved ${lineups.length} lineup${lineups.length === 1 ? '' : 's'} for ${selectedSlate.label}.` });
          }}
          accessibilityRole="button"
          accessibilityLabel="Save lineups">
          <Text className={`save-btn-text ${unsaved ? '' : 'save-btn-text-idle'}`}>{unsaved ? 'Save lineups' : 'Saved'}</Text>
        </Pressable>
      </View>
      ) : null}

      {/* Lineup switcher */}
      {!editMode ? (
      <ScrollView horizontal showsHorizontalScrollIndicator={false} className="chip-row" contentContainerClassName="chip-row-content">
        {lineups.map((lu, i) => {
          const s = summarize(lu, slateType);
          const active = i === activeLineup;
          return (
            <Pressable
              key={i}
              className={`filter-chip ${active ? 'filter-chip-active' : ''}`}
              onPress={() => setActiveLineup(i)}
              accessibilityRole="button"
              aria-pressed={active}>
              <Text className={`filter-chip-text ${active ? 'filter-chip-text-active' : ''}`}>
                Lineup {i + 1} · {s.valid ? 'Valid' : `${s.filled}/${s.total}`}
              </Text>
            </Pressable>
          );
        })}
        {lineups.length < MAX_LINEUPS ? (
          <Pressable className="filter-chip flex-row items-center" onPress={addLineup} accessibilityRole="button" accessibilityLabel="Add a lineup">
            <Image source={icons.plus} className="mr-1" style={{ width: 12, height: 12, tintColor: colors.foreground }} />
            <Text className="filter-chip-text">New</Text>
          </Pressable>
        ) : null}
      </ScrollView>
      ) : null}

      {/* Active lineup: stacked vertical slots */}
      <View className="lineup-card">
        <View className="lineup-card-header">
          <Text className="lineup-title">{editMode ? 'Your entry' : `Lineup ${activeLineup + 1}`}</Text>
          {!editMode ? (
          <View className="flex-row gap-4">
            <Pressable onPress={() => setLineup(activeLineup, defs.map(() => null))} accessibilityRole="button">
              <Text className="caption">Clear</Text>
            </Pressable>
            <Pressable onPress={() => deleteLineup(activeLineup)} accessibilityRole="button">
              <Text className="danger-link">Delete</Text>
            </Pressable>
          </View>
          ) : null}
        </View>
        {defs.map((def, i) => {
          const p = lineup[i] ?? null;
          return (
            <LineupRow
              key={i}
              slot={def.label}
              player={p}
              note={p && lockedTeams.has(p.team) ? 'Locked: game started' : null}
              right={
                p && lockedTeams.has(p.team) ? (
                  <Text className="caption">🔒</Text>
                ) : p ? (
                  <Pressable
                    className="player-remove"
                    onPress={() => setLineup(activeLineup, removeAt(lineup, i))}
                    accessibilityRole="button"
                    accessibilityLabel={`Remove ${p.name}`}>
                    <Image source={icons.close} style={{ width: 12, height: 12, tintColor: colors.mutedForeground }} />
                  </Pressable>
                ) : null
              }
            />
          );
        })}
        <Totals
          items={[
            { label: 'Salary', value: formatCurrency(summary.salary) },
            { label: 'Remaining', value: formatCurrency(summary.remaining), tone: summary.remaining < 0 ? 'negative' : undefined },
            { label: 'Avg / open slot', value: summary.avgRemaining != null ? formatCurrency(Math.max(0, summary.avgRemaining)) : '-' },
            { label: 'Proj', value: formatPoints(summary.proj) },
            { label: 'Ceiling', value: formatPoints(summary.ceiling) },
            { label: 'Status', value: summary.valid ? 'Valid' : `${summary.filled}/${summary.total}` },
          ]}
        />
        {summary.errors.length > 0 && summary.filled > 0 ? (
          <Text className="lineup-errors">{summary.errors.join(' · ')}</Text>
        ) : null}
        {summary.valid && !logging && !editMode ? (
          <Pressable className="btn-accent mt-3" onPress={() => setLogging(true)} accessibilityRole="button">
            <Text className="btn-text">Log a contest entry for this lineup</Text>
          </Pressable>
        ) : null}
        {logging ? (
          <View className="mt-4">
            <View className="section-header">
              <Text className="card-title">Log a contest entry</Text>
              <Pressable onPress={() => setLogging(false)} accessibilityRole="button">
                <Text className="caption">Cancel</Text>
              </Pressable>
            </View>
            <SubmissionForm
              slateId={selectedSlate.slate_id}
              lineup={asSubmitted()}
              onDone={() => {
                setLogging(false);
                setMessage({ text: 'Entry logged -- see Profit / Loss on Home.' });
              }}
            />
          </View>
        ) : null}
      </View>

      {message ? <Text className={`lineup-message ${message.error ? 'text-negative' : ''}`}>{message.text}</Text> : null}

      {/* Player pool */}
      <Text className="section-title mb-2">Player pool</Text>
      <MatchupModeToggle />
      <ScrollView horizontal showsHorizontalScrollIndicator={false} className="chip-row mb-2" contentContainerClassName="chip-row-content">
        {POSITION_FILTERS[slateType].map((pos) => {
          const active = pos === position;
          return (
            <Pressable
              key={pos}
              className={`filter-chip ${active ? 'filter-chip-active' : ''}`}
              onPress={() => {
                setPosition(pos);
                setLimit(PAGE);
              }}
              accessibilityRole="button"
              aria-pressed={active}>
              <Text className={`filter-chip-text ${active ? 'filter-chip-text-active' : ''}`}>{pos}</Text>
            </Pressable>
          );
        })}
        <Pressable
          className={`filter-chip ${showAll ? 'filter-chip-active' : ''}`}
          onPress={() => setShowAll((v) => !v)}
          accessibilityRole="button"
          aria-pressed={showAll}>
          <Text className={`filter-chip-text ${showAll ? 'filter-chip-text-active' : ''}`}>Incl. Out/Doubtful</Text>
        </Pressable>
      </ScrollView>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} className="chip-row mb-2" contentContainerClassName="chip-row-content">
        <Text className="matchup-toggle-label mr-1 self-center">Sort</Text>
        {sorts.map((o) => {
          const active = selected.includes(o.key);
          const showDir = active && !blended && o.key !== 'matchup';
          return (
            <Pressable
              key={o.key}
              className={`filter-chip ${active ? 'filter-chip-active' : ''}`}
              onPress={() => pressSort(o.key)}
              accessibilityRole="button"
              aria-pressed={active}
              accessibilityHint={active ? (blended ? 'Removes this sort from the blend' : 'Flips the order') : 'Adds this sort'}>
              <Text className={`filter-chip-text ${active ? 'filter-chip-text-active' : ''}`}>
                {o.label}
                {showDir ? (ascending ? ' ▲' : ' ▼') : ''}
                {active && blended ? ` ${weights[o.key] ?? 0}%` : ''}
              </Text>
            </Pressable>
          );
        })}
      </ScrollView>
      {blended ? (
        <View className="weight-panel">
          <View className="flex-row items-center justify-between">
            <Text className="weight-title">Sort weights · total {totalWeight(weights, selected)}%</Text>
            <Pressable onPress={() => setWeights(evenWeights(selected))} hitSlop={8} accessibilityRole="button">
              <Text className="link-text text-xs">Even split</Text>
            </Pressable>
          </View>
          <Text className="weight-help">
            Players rank on a blend of their percentile in this pool for each sort. Change one weight and the others rescale so the total stays 100%. Tap a
            sort chip again to drop it.
          </Text>
          {selected.map((k) => (
            <View key={k} className="weight-row">
              <Text className="weight-label" numberOfLines={1}>
                {SORT_LABEL[k]}
              </Text>
              {k !== 'matchup' ? (
                <Pressable
                  className="weight-dir"
                  onPress={() => setLowFirst((d) => ({ ...d, [k]: !d[k] }))}
                  accessibilityRole="button"
                  accessibilityLabel={`${SORT_LABEL[k]}: ${lowFirst[k] ? 'lower is better' : 'higher is better'}; tap to flip`}>
                  <Text className="weight-dir-text">{lowFirst[k] ? 'Low ▲' : 'High ▼'}</Text>
                </Pressable>
              ) : (
                <Text className="weight-dir-text px-2">Softest</Text>
              )}
              <Pressable className="weight-step" onPress={() => changeWeight(k, (weights[k] ?? 0) - STEP)} accessibilityRole="button" accessibilityLabel={`Lower ${SORT_LABEL[k]} weight`}>
                <Text className="weight-step-text">−</Text>
              </Pressable>
              <TextInput
                className="weight-input"
                keyboardType="number-pad"
                defaultValue={String(weights[k] ?? 0)}
                key={`${k}-${weights[k]}`}
                onEndEditing={(e) => changeWeight(k, Number(e.nativeEvent.text))}
                onSubmitEditing={(e) => changeWeight(k, Number(e.nativeEvent.text))}
                maxLength={3}
                selectTextOnFocus
                accessibilityLabel={`${SORT_LABEL[k]} weight percent`}
              />
              <Text className="weight-pct">%</Text>
              <Pressable className="weight-step" onPress={() => changeWeight(k, (weights[k] ?? 0) + STEP)} accessibilityRole="button" accessibilityLabel={`Raise ${SORT_LABEL[k]} weight`}>
                <Text className="weight-step-text">+</Text>
              </Pressable>
            </View>
          ))}
        </View>
      ) : null}
      <Text className="dfs-reason mb-2">
        {blended
          ? 'Blend score (0-100) shown on each player: 100 = best in this pool on every selected sort.'
          : sortBy === 'own' && field
            ? `Expected ${field.label.toLowerCase()} ownership`
            : SORT_NOTE[sortBy]}
        {!blended && sortBy !== 'matchup' ? (ascending ? ' · lowest first (tap again to flip)' : ' · highest first (tap again to flip)') : ''}
        {!blended ? ' · tap more sorts to blend them' : ''}
        {selected.includes('own') && !own.available ? ' · ownership not available for Showdown slates (no DFS model)' : ''}
        {selected.includes('own') && own.loading ? ' · loading the DFS model…' : ''}
        {selected.includes('own') && own.error ? ` · couldn't load ownership: ${own.error}` : ''}
        {position === 'FLEX' ? ' · FLEX: RBs, WRs and TEs -- adding one fills an open RB / WR / TE slot first, then FLEX' : ''}
      </Text>
      <TextInput
        className="input mb-2"
        placeholder="Search player or team (e.g. BUF)"
        placeholderTextColor={colors.mutedForeground}
        value={query}
        onChangeText={(t) => {
          setQuery(t);
          setLimit(PAGE);
        }}
        autoCorrect={false}
        autoCapitalize="none"
      />

      <StatusView loading={players.loading} error={players.error} empty={!players.loading && filtered.length === 0 ? 'No players match' : null} />
      <View className="player-pool">
        {filtered.slice(0, limit).map(({ player: p, blend }) => {
          const fit = fits(p);
          const inLineup = indexOfPlayer(lineup, p) !== -1;
          return (
            <View key={p.dk_draftable_id ?? `${p.name}-${p.roster_slot}`} className={fit.ok ? '' : 'player-unfit'}>
              <LineupRow
                slot={p.roster_slot || p.position}
                player={{ ...rowPlayer(p), blend }}
                note={fit.ok ? null : fit.reason}
                right={
                  <Pressable
                    className={`player-action ${inLineup ? 'player-action-remove' : ''}`}
                    onPress={() => toggle(p)}
                    accessibilityRole="button"
                    accessibilityLabel={`${inLineup ? 'Remove' : 'Add'} ${p.name}`}>
                    <Image source={inLineup ? icons.close : icons.plus} style={{ width: 12, height: 12, tintColor: inLineup ? colors.accentForeground : colors.primaryForeground }} />
                  </Pressable>
                }
              />
            </View>
          );
        })}
      </View>
      {filtered.length > limit ? (
        <Pressable className="btn-outline mt-3" onPress={() => setLimit((n) => n + PAGE)} accessibilityRole="button">
          <Text className="btn-outline-text">Show more ({filtered.length - limit} left)</Text>
        </Pressable>
      ) : null}
    </View>
  );
}
