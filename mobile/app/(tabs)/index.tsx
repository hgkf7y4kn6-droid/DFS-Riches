import { useState } from 'react';
import { Image, Pressable, RefreshControl, ScrollView, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import BalanceCard from '@/components/BalanceCard';
import ExpandableCard from '@/components/ExpandableCard';
import LineupBuilder from '@/components/LineupBuilder';
import LinesList from '@/components/LinesList';
import OptimalLineups from '@/components/OptimalLineups';
import ProfitLossTracker from '@/components/ProfitLossTracker';
import SafeAreaView from '@/components/SafeAreaView';
import ScheduleCard from '@/components/ScheduleCard';
import SlateList from '@/components/SlateList';
import StatusView from '@/components/StatusView';
import SubmissionForm from '@/components/SubmissionForm';
import { HOME_SECTIONS, HOME_USER } from '@/constants/data';
import { colors } from '@/constants/theme';
import { useWeek } from '@/lib/week-context';

export default function Home() {
  const insets = useSafeAreaInsets();
  const { week, weekData, refresh, selectedSlate, selectSlate } = useWeek();
  const data = weekData.data;
  const [profitOpen, setProfitOpen] = useState(HOME_SECTIONS.profit.defaultExpanded);
  const [logging, setLogging] = useState(false);

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
              <Text className="home-user-greeting">{HOME_USER.greeting}</Text>
              <Text className="home-user-name">{HOME_USER.name}</Text>
            </View>
          </View>
          {week ? (
            <View className="home-week-pill">
              <Text className="home-week-pill-text">Week {week}</Text>
            </View>
          ) : null}
        </View>

        {/* Balance card: money spent on lineup submissions */}
        <BalanceCard
          onLogEntry={() => {
            setProfitOpen(true);
            setLogging(true);
          }}
        />

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
            {/* Weekly schedule */}
            <ScheduleCard schedule={data.schedule} />

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
