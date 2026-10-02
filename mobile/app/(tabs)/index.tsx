import { router } from 'expo-router';
import { useMemo, useState } from 'react';
import { FlatList, Image, Pressable, RefreshControl, ScrollView, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import BalanceStats from '@/components/BalanceStats';
import ExpandableCard from '@/components/ExpandableCard';
import LinesList from '@/components/LinesList';
import ListHeading from '@/components/ListHeading';
import ProfitLossTracker from '@/components/ProfitLossTracker';
import SafeAreaView from '@/components/SafeAreaView';
import SlateCard from '@/components/SlateCard';
import StatusView from '@/components/StatusView';
import SubmissionForm from '@/components/SubmissionForm';
import UpcomingGamesCard from '@/components/UpcomingGamesCard';
import { HOME_BALANCE, HOME_SECTIONS, HOME_USER } from '@/constants/data';
import icons from '@/constants/icons';
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
  const [expandedSlate, setExpandedSlate] = useState<string | null>(null);
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

  const openLogEntry = () => {
    setProfitOpen(true);
    setLogging(true);
  };

  return (
    <SafeAreaView className="flex-1 bg-background" edges={['top', 'left', 'right']}>
      <ScrollView
        showsVerticalScrollIndicator={false}
        contentContainerClassName="screen-content"
        contentContainerStyle={{ paddingBottom: insets.bottom + FLOATING_TAB_BAR.space }}
        refreshControl={<RefreshControl refreshing={weekData.loading && !!data} onRefresh={refresh} tintColor={colors.accent} />}>
        {/* Header: user info */}
        <View className="home-header">
          <View className="home-user">
            <Image source={HOME_USER.avatar} className="home-avatar" style={{ width: 64, height: 64 }} />
            <View>
              <Text className="home-user-greeting">
                {HOME_USER.greeting}
                {week ? ` · Week ${week}` : ''}
              </Text>
              <Text className="home-user-name">{HOME_USER.name}</Text>
            </View>
          </View>
          <Pressable onPress={openLogEntry} accessibilityRole="button" accessibilityLabel="Log a contest entry">
            <Image source={icons.add} className="home-add-icon" style={{ width: 48, height: 48, tintColor: colors.primary }} />
          </Pressable>
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

            {/* Slates: every DraftKings slate this week; tap one to open its lineups */}
            <View>
              <ListHeading
                title={HOME_SECTIONS.slates.title}
                subtitle={`${data.slates.length} slates this week · tap one for lineups`}
                onPress={() => router.push('/lineups')}
              />
              {data.slates.length ? (
                data.slates.map((slate) => (
                  <SlateCard
                    key={slate.slate_id}
                    slate={slate}
                    now={now}
                    expanded={expandedSlate === slate.slate_id}
                    onToggle={() => {
                      if (expandedSlate === slate.slate_id) {
                        setExpandedSlate(null);
                      } else {
                        selectSlate(slate.slate_id);
                        setExpandedSlate(slate.slate_id);
                      }
                    }}
                  />
                ))
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
