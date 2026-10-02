import { ScrollView, Text } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import BackLink from '@/components/BackLink';
import LinesList from '@/components/LinesList';
import SafeAreaView from '@/components/SafeAreaView';
import StatusView from '@/components/StatusView';
import { HOME_SECTIONS } from '@/constants/data';
import { FLOATING_TAB_BAR } from '@/constants/theme';
import { useWeek } from '@/lib/week-context';

export default function Lines() {
  const insets = useSafeAreaInsets();
  const { week, weekData } = useWeek();
  const data = weekData.data;

  return (
    <SafeAreaView className="flex-1 bg-background" edges={['top', 'left', 'right']}>
      <ScrollView showsVerticalScrollIndicator={false} contentContainerClassName="screen-content"
        contentContainerStyle={{ paddingBottom: insets.bottom + FLOATING_TAB_BAR.space }}>
        <BackLink />
        <Text className="screen-title">{HOME_SECTIONS.lines.title}</Text>
        <Text className="screen-subtitle">
          {week ? `Week ${week} · ` : ''}
          {HOME_SECTIONS.lines.subtitle}
        </Text>
        <StatusView loading={weekData.loading && !data} error={weekData.error} />
        {data ? <LinesList games={data.schedule.games} /> : null}
      </ScrollView>
    </SafeAreaView>
  );
}
