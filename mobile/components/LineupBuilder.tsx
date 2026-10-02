import { useMemo, useState } from 'react';
import { Image, Pressable, ScrollView, Text, TextInput, View } from 'react-native';

import { LineupRow, Totals } from '@/components/LineupRows';
import StatusView from '@/components/StatusView';
import SubmissionForm from '@/components/SubmissionForm';
import { MAX_LINEUPS } from '@/constants/config';
import { PLAYABLE_STATUSES, POSITION_FILTERS } from '@/constants/data';
import icons from '@/constants/icons';
import { useThemeColors } from '@/constants/theme';
import { addPlayer, fitChecker, indexOfPlayer, removeAt, summarize, template } from '@/lib/lineups';
import { formatCurrency, formatPoints } from '@/lib/utils';
import { useWeek } from '@/lib/week-context';

const PAGE = 40;

/**
 * Build up to MAX_LINEUPS lineups for the selected slate: the active lineup
 * as a stacked vertical list of slots (tap x to remove), its totals, then the
 * player pool -- filter by position, search, tap + to add. Players that
 * can't fit (no open slot, or too little salary left to fill the rest) are
 * dimmed with the reason.
 */
export default function LineupBuilder() {
  const { selectedSlate, players, lineups, activeLineup, setActiveLineup, setLineup, addLineup, deleteLineup } = useWeek();
  const colors = useThemeColors();
  const [position, setPosition] = useState('All');
  const [query, setQuery] = useState('');
  const [showAll, setShowAll] = useState(false);
  const [limit, setLimit] = useState(PAGE);
  const [message, setMessage] = useState<{ text: string; error?: boolean } | null>(null);
  const [logging, setLogging] = useState(false);

  const slateType: SlateType = selectedSlate?.slate_type ?? 'classic';
  const pool = useMemo(() => players.data?.players ?? [], [players.data]);
  const lineup = useMemo(() => lineups[activeLineup] ?? [], [lineups, activeLineup]);
  const defs = template(slateType);
  const summary = summarize(lineup, slateType);
  const fits = useMemo(() => fitChecker(lineup, slateType, pool), [lineup, slateType, pool]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return pool
      .filter((p) => showAll || PLAYABLE_STATUSES.has(p.injury ?? 'Healthy'))
      .filter((p) => {
        if (position === 'All') return true;
        return slateType === 'showdown' ? p.roster_slot === position : p.position === position;
      })
      .filter((p) => !q || p.name.toLowerCase().includes(q) || p.team.toLowerCase() === q)
      .sort((a, b) => b.proj_points - a.proj_points);
  }, [pool, position, query, showAll, slateType]);

  if (!selectedSlate) return null;
  if (!selectedSlate.available) {
    return <Text className="empty-text">DraftKings has not posted salaries for this slate yet.</Text>;
  }

  const toggle = (player: Player) => {
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
      {/* Lineup switcher */}
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
              accessibilityState={{ selected: active }}>
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

      {/* Active lineup: stacked vertical slots */}
      <View className="lineup-card">
        <View className="lineup-card-header">
          <Text className="lineup-title">Lineup {activeLineup + 1}</Text>
          <View className="flex-row gap-4">
            <Pressable onPress={() => setLineup(activeLineup, defs.map(() => null))} accessibilityRole="button">
              <Text className="caption">Clear</Text>
            </Pressable>
            <Pressable onPress={() => deleteLineup(activeLineup)} accessibilityRole="button">
              <Text className="danger-link">Delete</Text>
            </Pressable>
          </View>
        </View>
        {defs.map((def, i) => {
          const p = lineup[i] ?? null;
          return (
            <LineupRow
              key={i}
              slot={def.label}
              player={p}
              right={
                p ? (
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
        {summary.valid && !logging ? (
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
              accessibilityState={{ selected: active }}>
              <Text className={`filter-chip-text ${active ? 'filter-chip-text-active' : ''}`}>{pos}</Text>
            </Pressable>
          );
        })}
        <Pressable
          className={`filter-chip ${showAll ? 'filter-chip-active' : ''}`}
          onPress={() => setShowAll((v) => !v)}
          accessibilityRole="button"
          accessibilityState={{ selected: showAll }}>
          <Text className={`filter-chip-text ${showAll ? 'filter-chip-text-active' : ''}`}>Incl. Out/Doubtful</Text>
        </Pressable>
      </ScrollView>
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
        {filtered.slice(0, limit).map((p) => {
          const fit = fits(p);
          const inLineup = indexOfPlayer(lineup, p) !== -1;
          return (
            <View key={p.dk_draftable_id ?? `${p.name}-${p.roster_slot}`} className={fit.ok ? '' : 'player-unfit'}>
              <LineupRow
                slot={p.roster_slot || p.position}
                player={p}
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
