import { router } from 'expo-router';
import { useMemo } from 'react';
import { FlatList, Pressable, RefreshControl, ScrollView, Text } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import MatchupModeToggle from '@/components/MatchupModeToggle';
import BrandHeader from '@/components/BrandHeader';
import ListHeading from '@/components/ListHeading';
import OwnershipList from '@/components/plays/OwnershipList';
import OwnershipModelNote from '@/components/plays/OwnershipModelNote';
import ActualOwnershipCard from '@/components/plays/ActualOwnershipCard';
import LeverageCard from '@/components/plays/LeverageCard';
import PlayRankingCard from '@/components/plays/PlayRankingCard';
import WeatherCard, { weatherGames } from '@/components/plays/WeatherCard';
import RoleShiftsCard from '@/components/plays/RoleShiftsCard';
import SafeAreaView from '@/components/SafeAreaView';
import StatusView from '@/components/StatusView';
import { Glossed } from '@/components/Term';
import { FLOATING_TAB_BAR, useThemeColors } from '@/constants/theme';
import { usePlays } from '@/lib/plays';
import { poolKey, usePool } from '@/lib/pool-tags-context';
import { useWeek } from '@/lib/week-context';

const COPY: Record<PlayContest, { title: string; term: string; description: string; balance: string; ownTitle: string; ownSubtitle: string }> = {
  cash: {
    title: 'Safe Plays',
    term: 'Cash games',
    description: 'Cash games pay about half the field, so you only need a steady score. Pick players with a high floor.',
    balance: 'Ranked on floor safety, salary, game environment and the odds of a median-to-high (2.5x) game',
    ownTitle: 'Expected cash ownership',
    ownSubtitle: 'By position, most owned first · tap a card for every player, a row for the models and game log',
  },
  gpp: {
    title: 'Tournaments',
    term: 'GPP tournaments',
    description: 'Tournaments pay the top finishers, with the big money at the very top. Pick players with big ceilings the field is overlooking.',
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
  kind?: 'shifts' | 'leverage' | 'weather';
  kicker?: string;
  title: string;
  subtitle: string;
  players: PlayPlayer[];
  preview?: (p: PlayPlayer) => string;
  note?: string;
}

/** The horizontal list: a card per position, then the weather card, then (GPP) the chalk and leverage cards. */
function cards(data: PlaysResponse, contest: PlayContest, weather: boolean): Card[] {
  const list: Card[] = POSITION_CARDS.map(({ pos, label }) => ({
    key: pos,
    title: `Top ${data.rankings[pos]?.length ?? 0} ${label}`,
    subtitle: `${pos} ranked by strength of play`,
    players: data.rankings[pos] ?? [],
  }));
  if (weather) list.push({ key: 'weather', kind: 'weather', title: '', subtitle: '', players: [] });
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

/**
 * The Safe Plays (cash) and Tournaments (GPP) tabs: top plays by position
 * (horizontal), field ownership by position, then a way into the Lineups
 * tab's builder set up for this contest.
 */
export default function PlaysScreen({ contest }: { contest: PlayContest }) {
  const insets = useSafeAreaInsets();
  const colors = useThemeColors();
  const { data, loading, refreshing, error, refresh } = usePlays(contest);
  const { season, week, weekData } = useWeek();
  const copy = COPY[contest];
  const ready = data?.available ? data : null;
  const pool = usePool(ready && season && week ? poolKey(season, week, ready.slate.slate_id, contest) : null);
  const columns: OwnershipContest[] = contest === 'cash' ? ['cash'] : ['small_gpp', 'large_gpp'];
  const schedule = weekData.data?.schedule;
  const weather = useMemo(
    () => (ready && schedule ? weatherGames([...schedule.games, ...schedule.isolated_games], ready.players) : []),
    [ready, schedule],
  );

  return (
    <SafeAreaView className="flex-1 bg-background" edges={['top', 'left', 'right']}>
      <ScrollView
        showsVerticalScrollIndicator={false}
        contentContainerClassName="screen-content"
        contentContainerStyle={{ paddingBottom: insets.bottom + FLOATING_TAB_BAR.space }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={colors.accent} />}>
        <BrandHeader title={copy.title} term={copy.term} slate="model" modelSlates={ready?.slates} />
        <Text className="screen-subtitle">
          <Glossed text={copy.description} />
        </Text>
        <MatchupModeToggle />
        <StatusView loading={loading} error={error} onRetry={refresh} />
        {loading ? <Text className="empty-text">Simulating the field -- this can take a few seconds.</Text> : null}
        {data && !data.available ? <Text className="home-empty-state">{data.reason}</Text> : null}

        {ready ? (
          <>
            <ListHeading title={`Top ${contest === 'cash' ? 'safe' : 'tournament'} plays`} subtitle={copy.balance} />
            <FlatList
              data={cards(ready, contest, weather.length > 0)}
              keyExtractor={(item) => item.key}
              renderItem={({ item }) =>
                item.kind === 'shifts' ? (
                  <RoleShiftsCard players={item.players} pool={pool} />
                ) : item.kind === 'weather' ? (
                  <WeatherCard games={weather} />
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
            <OwnershipModelNote models={ready.ownership_models} players={ready.players} field={contest === 'cash' ? 'cash' : 'large_gpp'} />
            <ActualOwnershipCard contest={contest} plays={ready} onUploaded={refresh} />
            <OwnershipList players={ready.players} columns={columns} pool={pool} />

            {/* One builder for every contest, in the Lineups tab (set to this one). */}
            <Pressable
              className="btn mt-4"
              onPress={() => router.push({ pathname: '/lineups', params: { contest } })}
              accessibilityRole="button">
              <Text className="btn-text">{contest === 'cash' ? 'Build cash lineups ›' : 'Build tournament lineups ›'}</Text>
            </Pressable>
          </>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}
