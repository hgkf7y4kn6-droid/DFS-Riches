import { useLocalSearchParams } from 'expo-router';
import { useEffect, useMemo, useState } from 'react';
import { FlatList, Pressable, ScrollView, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import AlertsCard from '@/components/AlertsCard';
import BrandHeader from '@/components/BrandHeader';
import LineupBuilder from '@/components/LineupBuilder';
import ListHeading from '@/components/ListHeading';
import OptimalLineups from '@/components/OptimalLineups';
import SafeAreaView from '@/components/SafeAreaView';
import SlateList from '@/components/SlateList';
import StatusView from '@/components/StatusView';
import { Glossed, Term } from '@/components/Term';
import UpcomingGamesCard from '@/components/UpcomingGamesCard';
import { FLOATING_TAB_BAR } from '@/constants/theme';
import { buildField } from '@/lib/build-field';
import { toUpcomingGame } from '@/lib/games';
import { usePlays } from '@/lib/plays';
import { usePrefs } from '@/lib/prefs-context';
import { useChooseSlate } from '@/lib/slate-choice';
import { useSubmissions } from '@/lib/submissions-context';
import { useWeek } from '@/lib/week-context';

/** Which contest the lineups are for: any, cash, or a tournament field. */
type Mode = 'any' | 'cash' | 'large_gpp' | 'small_gpp';
const MODES: { id: Mode; label: string }[] = [
  { id: 'any', label: 'Any' },
  { id: 'cash', label: 'Cash' },
  { id: 'large_gpp', label: 'Tournament' },
  { id: 'small_gpp', label: 'Small tournament' },
];
const NOTE: Record<Mode, string> = {
  any: 'Projections, values and matchups for every player.',
  cash: 'Every player shows expected cash ownership and the model floor. Cash lineups lean on safe, popular plays.',
  large_gpp: 'Every player shows expected large-field ownership and leverage. Get different from the crowd where it counts.',
  small_gpp: 'Every player shows expected small-field ownership and leverage.',
};

/**
 * The one lineup builder: pick a slate and a contest (any, cash, or a
 * tournament field), see the model lineups (Safe and Tournament), then build. Cash and
 * tournament modes add that field's ownership, floor and leverage on the
 * model's Classic slate; each mode keeps its own saved lineups.
 */
export default function Lineups() {
  const insets = useSafeAreaInsets();
  const { weekData, selectedSlate, refresh } = useWeek();
  const choose = useChooseSlate();
  const { editing } = useSubmissions();
  const { prefs } = usePrefs();
  const data = weekData.data;
  const { contest: contestParam } = useLocalSearchParams<{ contest?: string }>();
  const fromFocus: Mode = prefs.focus === 'cash' ? 'cash' : prefs.focus === 'gpp' ? 'large_gpp' : 'any';
  const [picked, setPicked] = useState<Mode | null>(null);
  // Safe Plays / Tournaments link here with ?contest=; otherwise what the user plays (prefs.focus).
  const mode: Mode = picked ?? (contestParam === 'cash' ? 'cash' : contestParam === 'gpp' ? 'large_gpp' : fromFocus);
  const playContest: PlayContest | null = mode === 'cash' ? 'cash' : mode === 'any' ? null : 'gpp';
  const plays = usePlays(playContest ?? 'cash', playContest != null);
  const ready = plays.data?.available ? plays.data : null;
  const onPlaysSlate = !!ready && ready.slate.slate_id === selectedSlate?.slate_id;
  const field = useMemo(() => (ready && onPlaysSlate && mode !== 'any' ? buildField(ready.players, mode) : undefined), [ready, onPlaysSlate, mode]);

  // Editing a logged entry: show its slate.
  const editSlate = editing?.slateId;
  useEffect(() => {
    if (editSlate && data?.slates.some((s) => s.slate_id === editSlate) && selectedSlate?.slate_id !== editSlate) choose(editSlate, false);
  }, [editSlate, data, selectedSlate?.slate_id, choose]);

  const scope = playContest ?? '';
  return (
    <SafeAreaView className="flex-1 bg-background" edges={['top', 'left', 'right']}>
      <ScrollView
        showsVerticalScrollIndicator={false}
        contentContainerClassName="screen-content"
        contentContainerStyle={{ paddingBottom: insets.bottom + FLOATING_TAB_BAR.space }}
        keyboardShouldPersistTaps="handled">
        <BrandHeader title="Lineups" slate="week" />
        <Text className="screen-subtitle">
          <Glossed text="Pick a slate and a contest, then tap players to fill each slot under the $50,000 salary cap. Start from a model lineup (Safe or Tournament) if you like." />
        </Text>
        <StatusView loading={weekData.loading && !data} error={weekData.error} onRetry={refresh} />
        <AlertsCard />
        {data && editing ? (
          <>
            <ListHeading title="Edit your entry" subtitle="Late swap: change players whose games haven't started" />
            <LineupBuilder scope="edit" />
          </>
        ) : data ? (
          <>
            <SlateList slates={data.slates} selectedId={selectedSlate?.slate_id ?? null} onSelect={(id) => choose(id)} />

            <Text className="input-label mt-4">Building for</Text>
            <ScrollView horizontal showsHorizontalScrollIndicator={false} className="chip-row" contentContainerClassName="chip-row-content">
              {MODES.map((m) => {
                const active = m.id === mode;
                return (
                  <Pressable
                    key={m.id}
                    className={`filter-chip ${active ? 'filter-chip-active' : ''}`}
                    onPress={() => setPicked(m.id)}
                    accessibilityRole="radio"
                    aria-checked={active}>
                    <Text className={`filter-chip-text ${active ? 'filter-chip-text-active' : ''}`}>{m.label}</Text>
                  </Pressable>
                );
              })}
            </ScrollView>
            <Text className="caption">
              {mode !== 'any' && selectedSlate?.slate_type === 'showdown' ? (
                <>
                  Field <Term id="ownership">ownership</Term> is modeled for <Term id="classic">Classic</Term> slates; this <Term id="showdown">Showdown</Term> builds with projections only.
                </>
              ) : mode !== 'any' && ready && !onPlaysSlate ? (
                `Field ownership is modeled for ${ready.slate.label}; pick it above to see it here.`
              ) : (
                <Glossed text={NOTE[mode]} />
              )}
            </Text>
            {playContest && plays.loading && !ready ? <Text className="caption mt-1">Loading the field&apos;s ownership…</Text> : null}

            {selectedSlate ? (
              <>
                <ListHeading title="Games on this slate" subtitle={selectedSlate.label} />
                <FlatList
                  horizontal
                  data={selectedSlate.games}
                  keyExtractor={(g) => g.game_id}
                  renderItem={({ item }) => <UpcomingGamesCard {...toUpcomingGame(item)} />}
                  showsHorizontalScrollIndicator={false}
                />
              </>
            ) : null}
            <ListHeading title="Model lineups" subtitle="Safe lineup to cash · Tournament lineup to win" />
            <OptimalLineups scope={scope} collapsible />
            <ListHeading title={mode === 'cash' ? 'Build cash lineups' : mode === 'any' ? 'Build lineups' : 'Build tournament lineups'} />
            <View>
              <LineupBuilder key={scope} scope={scope} field={field} />
            </View>
          </>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}
