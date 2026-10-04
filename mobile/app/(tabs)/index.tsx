import { useAuth, useUser } from '@clerk/expo';
import { Link, router } from 'expo-router';
import { useMemo, useState } from 'react';
import { FlatList, Image, Pressable, RefreshControl, ScrollView, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import BrandHeader from '@/components/BrandHeader';
import BalanceStats from '@/components/BalanceStats';
import ExpandableCard from '@/components/ExpandableCard';
import LinesList from '@/components/LinesList';
import ListHeading from '@/components/ListHeading';
import OptimalLineups from '@/components/OptimalLineups';
import ProfitLossTracker from '@/components/ProfitLossTracker';
import SafeAreaView from '@/components/SafeAreaView';
import SlateList from '@/components/SlateList';
import StatusView from '@/components/StatusView';
import SubmissionForm from '@/components/SubmissionForm';
import UpcomingGamesCard from '@/components/UpcomingGamesCard';
import { HOME_BALANCE, HOME_SECTIONS, HOME_USER } from '@/constants/data';
import { FLOATING_TAB_BAR, useThemeColors } from '@/constants/theme';
import dayjs from '@/lib/dayjs';
import { toUpcomingGame } from '@/lib/games';
import { stats } from '@/lib/submissions';
import { useSubmissions } from '@/lib/submissions-context';
import { formatCurrency } from '@/lib/utils';
import { useWeek } from '@/lib/week-context';

export default function Home() {
  const insets = useSafeAreaInsets();
  const colors = useThemeColors();
  const { week, weekData, refresh, selectedSlate, selectSlate } = useWeek();
  const { submissions } = useSubmissions();
  const data = weekData.data;
  const [profitOpen, setProfitOpen] = useState(HOME_SECTIONS.profit.defaultExpanded);
  const [logging, setLogging] = useState(false);
  const [now] = useState(() => Date.now());

  // Games that haven't kicked off, soonest first.
  const upcoming = useMemo(
    () => (data?.schedule.games ?? []).filter((g) => new Date(g.kickoff_utc).getTime() > now),
    [data, now],
  );

  // Cards for the Upcoming list, and this week's finished games for when nothing is left.
  const upcomingGames = useMemo(() => upcoming.map((g) => toUpcomingGame(g, now)), [upcoming, now]);
  const playedGames = useMemo(
    () => (data?.schedule.games ?? []).filter((g) => g.context?.is_final).map((g) => toUpcomingGame(g, now)),
    [data, now],
  );

  // Balance card: HOME_BALANCE's hard-coded values until live numbers exist --
  // money spent on logged entries, and the next lineup lock (the selected
  // slate's next kickoff, else the week's next game).
  const nextLock =
    selectedSlate?.games.map((g) => g.kickoff_utc).find((k) => new Date(k).getTime() > now) ?? upcoming[0]?.kickoff_utc;
  const homeBalance: HomeBalance = {
    amount: submissions.length ? stats(submissions).spent : HOME_BALANCE.amount,
    lineupContestDate: nextLock ?? HOME_BALANCE.lineupContestDate,
  };

  const { isSignedIn } = useAuth();
  const { user } = useUser();
  const displayName = isSignedIn
    ? user?.firstName || user?.username || user?.primaryEmailAddress?.emailAddress?.split('@')[0] || HOME_USER.name
    : HOME_USER.name;

  return (
    <SafeAreaView className="flex-1 bg-background" edges={['top', 'left', 'right']}>
      <ScrollView
        showsVerticalScrollIndicator={false}
        contentContainerClassName="screen-content"
        contentContainerStyle={{ paddingBottom: insets.bottom + FLOATING_TAB_BAR.space }}
        refreshControl={<RefreshControl refreshing={weekData.loading && !!data} onRefresh={refresh} tintColor={colors.accent} />}>
        <BrandHeader title="Home" />

        {/* User info */}
        <View className="home-header">
          <View className="home-user">
            {isSignedIn ? (
              <View className="home-avatar account-avatar" style={{ width: 64, height: 64 }}>
                <Text className="account-avatar-text text-2xl">{displayName[0]?.toUpperCase()}</Text>
              </View>
            ) : (
              <Image source={HOME_USER.avatar} className="home-avatar" style={{ width: 64, height: 64 }} />
            )}
            <View className="flex-1">
              <Text className="home-user-greeting">
                {HOME_USER.greeting}
                {week ? ` · Week ${week}` : ''}
              </Text>
              <Text className="home-user-name" numberOfLines={1}>
                {displayName}
              </Text>
              {!isSignedIn ? (
                // A real link, so it works on the pre-rendered page before the app has loaded.
                <Link href="/sign-in" asChild>
                  <Pressable accessibilityRole="link" className="ml-4 mt-0.5 self-start">
                    <Text className="link-text text-xs">Sign in to sync across devices ›</Text>
                  </Pressable>
                </Link>
              ) : null}
            </View>
          </View>
        </View>

        {/* Balance card: money spent on lineup submissions */}
        <View className="home-balance-card">
          <Text className="home-balance-label">Spent on lineup submissions</Text>
          <View className="home-balance-row">
            <Text className="home-balance-amount">{formatCurrency(homeBalance.amount)}</Text>
            <View className="home-balance-date-block">
              <Text className="home-balance-date-label">Next lineup lock</Text>
              <Text className="home-balance-date">{dayjs(homeBalance.lineupContestDate).format('MM/DD')}</Text>
            </View>
          </View>
          <BalanceStats />
        </View>

        <StatusView loading={weekData.loading && !data} error={weekData.error} />

        {data ? (
          <>
            {/* Upcoming: games that haven't kicked off, as a horizontal list */}
            <View>
              <ListHeading
                title={HOME_SECTIONS.upcoming.title}
                subtitle={
                  upcomingGames.length
                    ? `${upcomingGames.length} of ${data.schedule.games.length} games this week`
                    : `All games played · this week's results`
                }
                onPress={() => router.push('/lines')}
              />
              <FlatList
                data={upcomingGames}
                renderItem={({ item }) => <UpcomingGamesCard {...item} />}
                keyExtractor={(item) => item.id}
                horizontal
                showsHorizontalScrollIndicator={false}
                // Nothing left to play: show this week's results instead.
                ListEmptyComponent={
                  playedGames.length ? (
                    <View className="flex-row">
                      {playedGames.map((game) => (
                        <UpcomingGamesCard key={game.id} {...game} />
                      ))}
                    </View>
                  ) : (
                    <Text className="home-empty-state">No games scheduled this week.</Text>
                  )
                }
              />
            </View>

            {/* Slates: every DraftKings slate this week (Sunday Main, Full Week, each Showdown) and its optimal lineups */}
            <View>
              <ListHeading
                title={HOME_SECTIONS.slates.title}
                subtitle={`${data.slates.length} slates this week · tap one for its optimal lineups`}
                onPress={() => router.push('/lineups')}
              />
              {data.slates.length ? (
                <>
                  <SlateList slates={data.slates} selectedId={selectedSlate?.slate_id ?? null} onSelect={selectSlate} />
                  <View className="mt-3">
                    <OptimalLineups />
                  </View>
                  <Pressable className="btn-outline mt-2" onPress={() => router.push('/lineups')} accessibilityRole="button">
                    <Text className="btn-outline-text">Build lineups for this slate ›</Text>
                  </Pressable>
                </>
              ) : (
                <Text className="home-empty-state">{"DraftKings hasn't posted this week's slates yet."}</Text>
              )}
            </View>
          </>
        ) : null}

        {/* Profit / loss by contest type */}
        <ExpandableCard
          title={HOME_SECTIONS.profit.title}
          subtitle={HOME_SECTIONS.profit.subtitle}
          expanded={profitOpen}
          onExpandedChange={setProfitOpen}>
          {logging ? (
            <View className="mb-4">
              <View className="section-header">
                <Text className="card-title">Log a contest entry</Text>
                <Pressable onPress={() => setLogging(false)} accessibilityRole="button">
                  <Text className="caption">Cancel</Text>
                </Pressable>
              </View>
              {data ? <SubmissionForm onDone={() => setLogging(false)} /> : <StatusView loading={weekData.loading} error={weekData.error} />}
            </View>
          ) : (
            <Pressable className="btn-outline mb-2" onPress={() => setLogging(true)} accessibilityRole="button">
              <Text className="btn-outline-text">+ Log a contest entry</Text>
            </Pressable>
          )}
          <ProfitLossTracker />
        </ExpandableCard>

        {data ? (
          <>
            {/* Lines & Performance */}
            <ExpandableCard
              title={HOME_SECTIONS.lines.title}
              subtitle={HOME_SECTIONS.lines.subtitle}
              defaultExpanded={HOME_SECTIONS.lines.defaultExpanded}>
              <LinesList games={data.schedule.games} />
            </ExpandableCard>
          </>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}
