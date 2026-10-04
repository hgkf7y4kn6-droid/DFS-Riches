import { useFocusEffect } from 'expo-router';
import { useCallback, useMemo, useState } from 'react';
import { FlatList, Pressable, RefreshControl, ScrollView, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import MatchupModeToggle from '@/components/MatchupModeToggle';
import BrandHeader from '@/components/BrandHeader';
import DfsSlatePicker from '@/components/dfs/DfsSlatePicker';
import ExpandableCard from '@/components/ExpandableCard';
import LineupBuilder, { type BuildField } from '@/components/LineupBuilder';
import ListHeading from '@/components/ListHeading';
import OwnershipList from '@/components/plays/OwnershipList';
import OptimalLineups from '@/components/OptimalLineups';
import OwnershipModelNote from '@/components/plays/OwnershipModelNote';
import ActualOwnershipCard from '@/components/plays/ActualOwnershipCard';
import LeverageCard from '@/components/plays/LeverageCard';
import PlayRankingCard from '@/components/plays/PlayRankingCard';
import RoleShiftsCard from '@/components/plays/RoleShiftsCard';
import SafeAreaView from '@/components/SafeAreaView';
import StatusView from '@/components/StatusView';
import { FLOATING_TAB_BAR, useThemeColors } from '@/constants/theme';
import { usePlays } from '@/lib/plays';
import { poolKey, usePool } from '@/lib/pool-tags-context';
import { useWeek } from '@/lib/week-context';

const COPY: Record<PlayContest, { title: string; subtitle: string; balance: string; ownTitle: string; ownSubtitle: string }> = {
  cash: {
    title: 'Cash',
    subtitle: '50/50s, double-ups and head-to-heads',
    balance: 'Ranked on floor safety, salary, game environment and the odds of a median-to-high (2.5x) game',
    ownTitle: 'Expected cash ownership',
    ownSubtitle: 'By position, most owned first · tap a card for every player, a row for the models and game log',
  },
  gpp: {
    title: 'GPP',
    subtitle: 'Tournaments, small field and large field',
    balance: 'Ranked on ownership leverage, salary, game environment and the odds of a ceiling game',
    ownTitle: 'Expected GPP ownership',
    ownSubtitle: 'Small- and large-field by position, most owned first · tap a card for every player, a row for the models and game log',
  },
};

const POSITION_CARDS: { pos: 'QB' | 'RB' | 'WR' | 'TE'; label: string }[] = [
  { pos: 'QB', label: 'Quarterbacks' },
  { pos: 'RB', label: 'Running backs' },
  { pos: 'WR', label: 'Wide receivers' },
  { pos: 'TE', label: 'Tight ends' },
];

interface Card {
  key: string;
  /** Rendered as the role-shifts card instead of a ranked-plays card. */
  kind?: 'shifts' | 'leverage';
  kicker?: string;
  title: string;
  subtitle: string;
  players: PlayPlayer[];
  preview?: (p: PlayPlayer) => string;
  note?: string;
}

/** The horizontal list: a card per position, then (GPP) the chalk and leverage cards. */
function cards(data: PlaysResponse, contest: PlayContest): Card[] {
  const list: Card[] = POSITION_CARDS.map(({ pos, label }) => ({
    key: pos,
    title: `Top ${data.rankings[pos]?.length ?? 0} ${label}`,
    subtitle: `${pos} ranked by strength of play`,
    players: data.rankings[pos] ?? [],
  }));
  if (data.role_shifts?.length) {
    list.push({ key: 'shifts', kind: 'shifts', title: '', subtitle: '', players: data.role_shifts });
  }
  if (contest === 'gpp' && data.chalk?.length) {
    list.push({
      key: 'chalk',
      kicker: 'Chalk',
      title: `The ${data.chalk.length} most-owned`,
      subtitle: 'Highest large-field ownership, every position',
      players: data.chalk,
      preview: (p) => `${p.position} · ${p.ownership.large_gpp?.toFixed(1)}% own`,
      note: 'Chalk with a strong ceiling (Prioritize) is worth eating; chalk tagged Fade is owned beyond its ceiling odds -- the field\'s best place to get off.',
    });
  }
  if (contest === 'gpp' && data.leverage_by_position && Object.keys(data.leverage_by_position).length) {
    list.push({ key: 'leverage', kind: 'leverage', title: '', subtitle: '', players: [] });
  }
  return list;
}

type GppField = 'large_gpp' | 'small_gpp';
const FIELD_LABEL: Record<OwnershipContest, string> = { cash: 'Cash', small_gpp: 'Small-field GPP', large_gpp: 'Large-field GPP' };
const BUILD_NOTE: Record<PlayContest, string> = {
  cash: 'Cash lineups lean on floor and utilization -- every player shows expected cash ownership and the model floor',
  gpp: 'Every player shows expected ownership for the field you pick',
};

/** The field's ownership (and, for cash, the model floor) by DK draftable id, for the lineup builder. */
function buildField(players: PlayPlayer[], field: OwnershipContest): BuildField {
  const ownership = new Map<number, number>();
  const floor = new Map<number, number>();
  const env = new Map<number, number>();
  const leverage = new Map<number, number>();
  for (const p of players) {
    const own = p.ownership[field];
    if (own != null) ownership.set(p.id, own);
    floor.set(p.id, p.floor);
    if (p.parts.env != null) env.set(p.id, p.parts.env);
    // Fair minus projected ownership for this tab's contest (app/leverage.py; cash: odds of 2.5x salary).
    if (p.leverage != null) leverage.set(p.id, p.leverage);
  }
  return { label: FIELD_LABEL[field], ownership, floor: field === 'cash' ? floor : undefined, env, leverage };
}

/**
 * The Cash and GPP tabs: top plays by position (horizontal), field ownership
 * by position (horizontal), then this contest's own lineup builder.
 */
export default function PlaysScreen({ contest }: { contest: PlayContest }) {
  const insets = useSafeAreaInsets();
  const colors = useThemeColors();
  const { data, loading, refreshing, error, refresh } = usePlays(contest);
  const { season, week, selectedSlate, selectSlate } = useWeek();
  const copy = COPY[contest];
  const ready = data?.available ? data : null;
  const pool = usePool(ready && season && week ? poolKey(season, week, ready.slate.slate_id, contest) : null);
  const columns: OwnershipContest[] = contest === 'cash' ? ['cash'] : ['small_gpp', 'large_gpp'];
  const [gppField, setGppField] = useState<GppField>('large_gpp');
  const fieldKey: OwnershipContest = contest === 'cash' ? 'cash' : gppField;
  const field = useMemo(() => (ready ? buildField(ready.players, fieldKey) : undefined), [ready, fieldKey]);

  // The builder works on Home's selected slate; keep it on this tab's slate while the tab is open.
  const slateId = ready?.slate.slate_id;
  useFocusEffect(
    useCallback(() => {
      if (slateId && selectedSlate?.slate_id !== slateId) selectSlate(slateId);
    }, [slateId, selectedSlate?.slate_id, selectSlate]),
  );

  return (
    <SafeAreaView className="flex-1 bg-background" edges={['top', 'left', 'right']}>
      <ScrollView
        showsVerticalScrollIndicator={false}
        contentContainerClassName="screen-content"
        contentContainerStyle={{ paddingBottom: insets.bottom + FLOATING_TAB_BAR.space }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={colors.accent} />}>
        <BrandHeader title={copy.title} />
        <Text className="screen-subtitle">{ready ? `${ready.slate.label} · ${copy.subtitle}` : copy.subtitle}</Text>
        <DfsSlatePicker slates={ready?.slates} current={ready?.slate.slate_id} />
        <MatchupModeToggle />
        <StatusView loading={loading} error={error} />
        {loading ? <Text className="empty-text">Simulating the field -- this can take a few seconds.</Text> : null}
        {data && !data.available ? <Text className="home-empty-state">{data.reason}</Text> : null}

        {ready ? (
          <>
            <ListHeading title={`Top ${contest === 'cash' ? 'cash' : 'GPP'} plays`} subtitle={copy.balance} />
            <FlatList
              data={cards(ready, contest)}
              keyExtractor={(item) => item.key}
              renderItem={({ item }) =>
                item.kind === 'shifts' ? (
                  <RoleShiftsCard players={item.players} pool={pool} />
                ) : item.kind === 'leverage' ? (
                  <LeverageCard byPosition={ready.leverage_by_position ?? {}} pool={pool} />
                ) : (
                  <PlayRankingCard
                    kicker={item.kicker}
                    title={item.title}
                    subtitle={item.subtitle}
                    players={item.players}
                    contest={contest}
                    pool={pool}
                    preview={item.preview}
                    note={item.note}
                  />
                )
              }
              horizontal
              showsHorizontalScrollIndicator={false}
            />
            <ListHeading title={copy.ownTitle} subtitle={copy.ownSubtitle} />
            <OwnershipModelNote models={ready.ownership_models} />
            <ActualOwnershipCard contest={contest} plays={ready} onUploaded={refresh} />
            <OwnershipList players={ready.players} columns={columns} pool={pool} />

            <ListHeading title={`Build ${contest === 'cash' ? 'cash' : 'GPP'} lineups`} subtitle={BUILD_NOTE[contest]} />
            {contest === 'gpp' ? (
              <View className="chip-row-content mb-2 flex-row">
                {(['large_gpp', 'small_gpp'] as GppField[]).map((f) => {
                  const active = f === gppField;
                  return (
                    <Pressable
                      key={f}
                      className={`filter-chip ${active ? 'filter-chip-active' : ''}`}
                      onPress={() => setGppField(f)}
                      accessibilityRole="button"
                      accessibilityState={{ selected: active }}>
                      <Text className={`filter-chip-text ${active ? 'filter-chip-text-active' : ''}`}>
                        {f === 'large_gpp' ? 'Large field' : 'Small field'}
                      </Text>
                    </Pressable>
                  );
                })}
              </View>
            ) : null}
            {selectedSlate?.slate_id === ready.slate.slate_id ? (
              <>
                <ExpandableCard title="Projected optimal" subtitle="Highest-projected lineups · copy one into the builder" defaultExpanded={false}>
                  <OptimalLineups scope={contest} />
                </ExpandableCard>
                <LineupBuilder scope={contest} field={field} />
              </>
            ) : null}
          </>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}
