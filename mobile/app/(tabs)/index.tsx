import { Image, RefreshControl, ScrollView, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import ExpandableCard from '@/components/ExpandableCard';
import LineupBuilder from '@/components/LineupBuilder';
import LinesList from '@/components/LinesList';
import OptimalLineups from '@/components/OptimalLineups';
import SafeAreaView from '@/components/SafeAreaView';
import ScheduleCard from '@/components/ScheduleCard';
import SlateList from '@/components/SlateList';
import StatusView from '@/components/StatusView';
import { SALARY_CAP } from '@/constants/config';
import { HOME_SECTIONS, HOME_USER } from '@/constants/data';
import { colors } from '@/constants/theme';
import { formatCurrency, formatPoints } from '@/lib/utils';
import { useWeek } from '@/lib/week-context';

export default function Home() {
  const insets = useSafeAreaInsets();
  const { week, weekData, refresh, selectedSlate, selectSlate, optimal } = useWeek();
  const data = weekData.data;
  const topProj = optimal.data?.lineups.find((l) => l.metric === 'proj_points')?.proj_points;

  return (
    <SafeAreaView className="flex-1 bg-background" edges={['top', 'left', 'right']}>
      <ScrollView
        showsVerticalScrollIndicator={false}
        contentContainerClassName="px-5 pt-5"
        contentContainerStyle={{ paddingBottom: insets.bottom + 24 }}
        refreshControl={<RefreshControl refreshing={weekData.loading && !!data} onRefresh={refresh} tintColor={colors.accent} />}>
        {/* Header: user info */}
        <View className="home-header">
          <View className="home-user">
            <Image source={HOME_USER.avatar} className="home-avatar" style={{ width: 48, height: 48 }} />
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

        {/* Balance card */}
        <View className="home-balance-card">
          <Text className="home-balance-label">DraftKings salary cap</Text>
          <Text className="home-balance-amount">{formatCurrency(SALARY_CAP)}</Text>
          <View className="home-balance-row">
            <View className="home-balance-stat">
              <Text className="home-balance-stat-value">{data ? data.schedule.games.length : '-'}</Text>
              <Text className="home-balance-stat-label">Games</Text>
            </View>
            <View className="home-balance-stat">
              <Text className="home-balance-stat-value">{data ? data.slates.length : '-'}</Text>
              <Text className="home-balance-stat-label">Slates</Text>
            </View>
            <View className="home-balance-stat">
              <Text className="home-balance-stat-value">{formatPoints(topProj)}</Text>
              <Text className="home-balance-stat-label">Top optimal proj</Text>
            </View>
          </View>
        </View>

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
