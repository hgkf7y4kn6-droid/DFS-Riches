import { ScrollView, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import LineupBuilder from '@/components/LineupBuilder';
import OptimalLineups from '@/components/OptimalLineups';
import SafeAreaView from '@/components/SafeAreaView';
import SlateList from '@/components/SlateList';
import StatusView from '@/components/StatusView';
import { useWeek } from '@/lib/week-context';

export default function Lineups() {
  const insets = useSafeAreaInsets();
  const { weekData, selectedSlate, selectSlate } = useWeek();
  const data = weekData.data;

  return (
    <SafeAreaView className="flex-1 bg-background" edges={['top', 'left', 'right']}>
      <ScrollView showsVerticalScrollIndicator={false} contentContainerClassName="px-5 pt-5"
        contentContainerStyle={{ paddingBottom: insets.bottom + 24 }} keyboardShouldPersistTaps="handled">
        <Text className="mb-3 text-2xl font-bold text-primary">Lineups</Text>
        <StatusView loading={weekData.loading && !data} error={weekData.error} />
        {data ? (
          <>
            <SlateList slates={data.slates} selectedId={selectedSlate?.slate_id ?? null} onSelect={selectSlate} />
            <View className="section">
              <Text className="section-title mb-3">Projected optimal</Text>
              <OptimalLineups />
            </View>
            <View className="section">
              <Text className="section-title mb-3">Build lineups</Text>
              <LineupBuilder />
            </View>
          </>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}
