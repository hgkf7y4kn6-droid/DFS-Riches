import { useEffect } from 'react';
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
import { useSubmissions } from '@/lib/submissions-context';
import { useWeek } from '@/lib/week-context';

export default function Lineups() {
  const insets = useSafeAreaInsets();
  const { weekData, selectedSlate, selectSlate } = useWeek();
  const { editing } = useSubmissions();
  const data = weekData.data;
  // Editing a logged entry: show its slate.
  const editSlate = editing?.slateId;
  useEffect(() => {
    if (editSlate && data?.slates.some((s) => s.slate_id === editSlate) && selectedSlate?.slate_id !== editSlate) selectSlate(editSlate);
  }, [editSlate, data, selectedSlate?.slate_id, selectSlate]);

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
        {data && editing ? (
          <>
            <ListHeading title="Edit your entry" subtitle="Late swap: change players whose games haven't started" />
            <LineupBuilder scope="edit" />
          </>
        ) : data ? (
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
