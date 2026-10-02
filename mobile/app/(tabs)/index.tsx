import { router } from 'expo-router';
import { useMemo, useState } from 'react';
import { FlatList, Image, Pressable, RefreshControl, ScrollView, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import BalanceStats from '@/components/BalanceStats';
import ExpandableCard from '@/components/ExpandableCard';
import LineupBuilder from '@/components/LineupBuilder';
import LinesList from '@/components/LinesList';
import ListHeading from '@/components/ListHeading';
import OptimalLineups from '@/components/OptimalLineups';
import ProfitLossTracker from '@/components/ProfitLossTracker';
import SafeAreaView from '@/components/SafeAreaView';
import SlateList from '@/components/SlateList';
import StatusView from '@/components/StatusView';
import SubmissionForm from '@/components/SubmissionForm';
import UpcomingGameCard from '@/components/UpcomingGameCard';
import { HOME_BALANCE, HOME_SECTIONS, HOME_USER } from '@/constants/data';
import icons from '@/constants/icons';
import { useThemeColors } from '@/constants/theme';
import dayjs from '@/lib/dayjs';
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
        contentContainerStyle={{ paddingBottom: insets.bottom + 24 }}
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

        <StatusView loading={weekData.loading && !data} error={weekData.error} />

        {data ? (
          <>
            {/* Upcoming games: horizontal list */}
            <ListHeading
              title={HOME_SECTIONS.upcoming.title}
              subtitle={`${upcoming.length} of ${data.schedule.games.length} games this week`}
              buttonText="View all"
              onPress={() => router.push('/lines')}
            />
            {upcoming.length ? (
              <FlatList
                horizontal
                data={upcoming}
                keyExtractor={(g) => g.game_id}
                renderItem={({ item }) => <UpcomingGameCard game={item} />}
                showsHorizontalScrollIndicator={false}
              />
            ) : (
              <Text className="home-empty-state">Every game this week has kicked off.</Text>
            )}

            {/* Slates: horizontal list; the selected one drives Lineups below */}
            <ExpandableCard
              title={HOME_SECTIONS.slates.title}
              subtitle={HOME_SECTIONS.slates.subtitle}
              aside={`${data.slates.length} slates`}
              defaultExpanded={HOME_SECTIONS.slates.defaultExpanded}>
              <SlateList slates={data.slates} selectedId={selectedSlate?.slate_id ?? null} onSelect={selectSlate} />
            </ExpandableCard>

            {/* Lineups for the selected slate */}
            <ExpandableCard
              title={HOME_SECTIONS.lineups.title}
              subtitle={selectedSlate ? selectedSlate.label : HOME_SECTIONS.lineups.subtitle}
              defaultExpanded={HOME_SECTIONS.lineups.defaultExpanded}>
              <OptimalLineups />
            </ExpandableCard>

            <ExpandableCard title="Build lineups" subtitle={selectedSlate ? selectedSlate.label : undefined}>
              <LineupBuilder />
            </ExpandableCard>

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
