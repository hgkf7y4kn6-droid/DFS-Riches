import { FlatList, ScrollView } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import BrandHeader from '@/components/BrandHeader';
import BackLink from '@/components/BackLink';
import LineupBuilder from '@/components/LineupBuilder';
import ListHeading from '@/components/ListHeading';
import OptimalLineups from '@/components/OptimalLineups';
import SafeAreaView from '@/components/SafeAreaView';
import SlateList from '@/components/SlateList';
import StatusView from '@/components/StatusView';
import UpcomingGamesCard from '@/components/UpcomingGamesCard';
import { toUpcomingGame } from '@/lib/games';
import { FLOATING_TAB_BAR } from '@/constants/theme';
import { useWeek } from '@/lib/week-context';

export default function Lineups() {
  const insets = useSafeAreaInsets();
  const { weekData, selectedSlate, selectSlate } = useWeek();
  const data = weekData.data;

  return (
    <SafeAreaView className="flex-1 bg-background" edges={['top', 'left', 'right']}>
      <ScrollView
        showsVerticalScrollIndicator={false}
        contentContainerClassName="screen-content"
        contentContainerStyle={{ paddingBottom: insets.bottom + FLOATING_TAB_BAR.space }}
        keyboardShouldPersistTaps="handled">
        <BrandHeader title="Lineups" />
        <BackLink />
        <StatusView loading={weekData.loading && !data} error={weekData.error} />
        {data ? (
          <>
            <SlateList slates={data.slates} selectedId={selectedSlate?.slate_id ?? null} onSelect={selectSlate} />
            {selectedSlate ? (
              <>
                <ListHeading
                  title="Games on this slate"
                  subtitle={selectedSlate.label}
                />
                <FlatList
                  horizontal
                  data={selectedSlate.games}
                  keyExtractor={(g) => g.game_id}
                  renderItem={({ item }) => <UpcomingGamesCard {...toUpcomingGame(item)} />}
                  showsHorizontalScrollIndicator={false}
                />
              </>
            ) : null}
            <ListHeading title="Projected optimal" />
            <OptimalLineups />
            <ListHeading title="Build lineups" />
            <LineupBuilder />
          </>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}
