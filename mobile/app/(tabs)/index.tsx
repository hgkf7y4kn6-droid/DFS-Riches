import { useUser } from '@clerk/expo';
import { router } from 'expo-router';
import { useMemo, useState } from 'react';
import { FlatList, Pressable, RefreshControl, ScrollView, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import BestContests from '@/components/BestContests';
import BrandHeader from '@/components/BrandHeader';
import BalanceStats from '@/components/BalanceStats';
import ExpandableCard from '@/components/ExpandableCard';
import FreeContests from '@/components/FreeContests';
import LinesList from '@/components/LinesList';
import ListHeading from '@/components/ListHeading';
import OptimalLineups from '@/components/OptimalLineups';
import ProfitLossTracker from '@/components/ProfitLossTracker';
import SafeAreaView from '@/components/SafeAreaView';
import SlateList from '@/components/SlateList';
import HomeTopPlays from '@/components/HomeTopPlays';
import StartHereCard from '@/components/StartHereCard';
import StatusView from '@/components/StatusView';
import SubmissionForm from '@/components/SubmissionForm';
import UpcomingGamesCard from '@/components/UpcomingGamesCard';
import { HOME_BALANCE, HOME_GREETING, HOME_SECTIONS } from '@/constants/data';
import { FLOATING_TAB_BAR, useThemeColors } from '@/constants/theme';
import dayjs from '@/lib/dayjs';
import { toUpcomingGame } from '@/lib/games';
import { useOnboarding } from '@/lib/onboarding-context';
import { useChooseSlate } from '@/lib/slate-choice';
import { stats } from '@/lib/submissions';
import { useSubmissions } from '@/lib/submissions-context';
import { formatCurrency } from '@/lib/utils';
import { useWeek } from '@/lib/week-context';

export default function Home() {
  const insets = useSafeAreaInsets();
  const colors = useThemeColors();
  const { week, weekData, refresh, selectedSlate } = useWeek();
  const choose = useChooseSlate();
  const { startHereHidden } = useOnboarding();
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

  // Everyone in the app is signed in (app/(tabs)/_layout.tsx): greet them by username.
  const { user } = useUser();
  const displayName = user?.username || user?.firstName || user?.primaryEmailAddress?.emailAddress?.split('@')[0] || 'there';

  return (
    <SafeAreaView className="flex-1 bg-background" edges={['top', 'left', 'right']}>
      <ScrollView
        showsVerticalScrollIndicator={false}
        contentContainerClassName="screen-content"
        contentContainerStyle={{ paddingBottom: insets.bottom + FLOATING_TAB_BAR.space }}
        refreshControl={<RefreshControl refreshing={weekData.loading && !!data} onRefresh={refresh} tintColor={colors.accent} />}>
        <BrandHeader title="Home" slate="week" />

        {/* User info */}
        <View className="home-header">
          <View className="home-user">
            <View className="home-avatar account-avatar" style={{ width: 56, height: 56 }}>
              <Text className="account-avatar-text text-2xl">{displayName[0]?.toUpperCase()}</Text>
            </View>
            <View className="flex-1">
              <Text className="home-user-greeting">
                {HOME_GREETING}
                {week ? ` · Week ${week}` : ''}
              </Text>
              <Text className="home-user-name" numberOfLines={1}>
                {displayName}
              </Text>
            </View>
          </View>
        </View>

        {/* Start here: pick a slate, see its top plays, build a lineup */}
        {!startHereHidden ? <StartHereCard /> : null}

        {/* What they play (Settings or the first-run question): its top play at each position */}
        <HomeTopPlays />

        <StatusView loading={weekData.loading && !data} error={weekData.error} />

        {/* This week's slates first: every DraftKings slate (Sunday Main, Full Week, each Showdown) and its optimal lineups */}
        {data ? (
          <View>
            <ListHeading
              title={HOME_SECTIONS.slates.title}
              subtitle={
                startHereHidden
                  ? `${data.slates.length} slates this week · tap one for its optimal lineups`
                  : 'The projected best lineups for the slate you picked'
              }
              onPress={() => router.push('/lineups')}
            />
            {data.slates.length ? (
              <>
                {startHereHidden ? <SlateList slates={data.slates} selectedId={selectedSlate?.slate_id ?? null} onSelect={choose} /> : null}
                <View className={startHereHidden ? 'mt-3' : ''}>
                  <OptimalLineups collapsible />
                </View>
                <Pressable className="btn-outline mt-2" onPress={() => router.push('/lineups')} accessibilityRole="button">
                  <Text className="btn-outline-text">Build lineups for this slate ›</Text>
                </Pressable>
              </>
            ) : (
              <Text className="home-empty-state">
                {"DraftKings hasn't posted this week's slates yet. They usually go up a few days before the first kickoff."}
              </Text>
            )}
          </View>
        ) : null}

        {/* Balance card: money spent on lineup submissions, once there's an entry to show */}
        {submissions.length ? (
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
        ) : null}

        {/* Free contests that pay cash: opens itself when there are any */}
        <FreeContests />

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
          </>
        ) : null}

        {/* Best contests: lowest-rake GPPs by max entries and entry fee */}
        <ExpandableCard
          title={HOME_SECTIONS.contests.title}
          subtitle={HOME_SECTIONS.contests.subtitle}
          defaultExpanded={HOME_SECTIONS.contests.defaultExpanded}>
          <BestContests slate={selectedSlate} />
        </ExpandableCard>

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
