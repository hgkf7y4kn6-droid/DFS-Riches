import { ScrollView, Text } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import LinesList from '@/components/LinesList';
import SafeAreaView from '@/components/SafeAreaView';
import StatusView from '@/components/StatusView';
import { HOME_SECTIONS } from '@/constants/data';
import { useWeek } from '@/lib/week-context';

export default function Lines() {
  const insets = useSafeAreaInsets();
  const { week, weekData } = useWeek();
  const data = weekData.data;

  return (
    <SafeAreaView className="flex-1 bg-background" edges={['top', 'left', 'right']}>
      <ScrollView showsVerticalScrollIndicator={false} contentContainerClassName="px-5 pt-5"
        contentContainerStyle={{ paddingBottom: insets.bottom + 24 }}>
        <Text className="text-2xl font-bold text-primary">{HOME_SECTIONS.lines.title}</Text>
        <Text className="mb-4 text-xs text-muted">
          {week ? `Week ${week} · ` : ''}
          {HOME_SECTIONS.lines.subtitle}
        </Text>
        <StatusView loading={weekData.loading && !data} error={weekData.error} />
        {data ? <LinesList games={data.schedule.games} /> : null}
      </ScrollView>
    </SafeAreaView>
  );
}
