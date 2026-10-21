import { ScrollView, Text } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import BrandHeader from '@/components/BrandHeader';
import BackLink from '@/components/BackLink';
import LinesList from '@/components/LinesList';
import SafeAreaView from '@/components/SafeAreaView';
import StatusView from '@/components/StatusView';
import { Glossed } from '@/components/Term';
import { HOME_SECTIONS } from '@/constants/data';
import { FLOATING_TAB_BAR } from '@/constants/theme';
import { useWeek } from '@/lib/week-context';

export default function Lines() {
  const insets = useSafeAreaInsets();
  const { week, weekData, refresh } = useWeek();
  const data = weekData.data;

  return (
    <SafeAreaView className="flex-1 bg-background" edges={['top', 'left', 'right']}>
      <ScrollView showsVerticalScrollIndicator={false} contentContainerClassName="screen-content"
        contentContainerStyle={{ paddingBottom: insets.bottom + FLOATING_TAB_BAR.space }}>
        <BrandHeader title={HOME_SECTIONS.lines.title} />
        <BackLink />
        <Text className="screen-subtitle">
          <Glossed
            text={`${week ? `Week ${week}: ` : ''}what Vegas expects in each game (spread, total, implied totals) and how it played out. Tap a game for recent form and pace.`}
          />
        </Text>
        <StatusView loading={weekData.loading && !data} error={weekData.error} onRetry={refresh} />
        {data ? <LinesList games={data.schedule.games} /> : null}
      </ScrollView>
    </SafeAreaView>
  );
}
