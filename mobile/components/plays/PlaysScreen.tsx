import { FlatList, RefreshControl, ScrollView, Text } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import DfsSlatePicker from '@/components/dfs/DfsSlatePicker';
import ListHeading from '@/components/ListHeading';
import OwnershipList from '@/components/plays/OwnershipList';
import OwnershipModelNote from '@/components/plays/OwnershipModelNote';
import PlayRankingCard from '@/components/plays/PlayRankingCard';
import SafeAreaView from '@/components/SafeAreaView';
import StatusView from '@/components/StatusView';
import { FLOATING_TAB_BAR, useThemeColors } from '@/constants/theme';
import { usePlays } from '@/lib/plays';

const COPY: Record<PlayContest, { title: string; subtitle: string; balance: string; ownTitle: string; ownSubtitle: string }> = {
  cash: {
    title: 'Cash',
    subtitle: '50/50s, double-ups and head-to-heads',
    balance: 'Ranked on floor safety, salary, game environment and the odds of a median-to-high (2.5x) game',
    ownTitle: 'Expected cash ownership',
    ownSubtitle: 'Every playable player, most owned first · tap a row for the models behind it',
  },
  gpp: {
    title: 'GPP',
    subtitle: 'Tournaments, small field and large field',
    balance: 'Ranked on ownership leverage, salary, game environment and the odds of a ceiling game',
    ownTitle: 'Expected GPP ownership',
    ownSubtitle: 'Small-field and large-field, most owned first · tap a row for the models behind it',
  },
};

const CARDS: { pos: 'QB' | 'RB' | 'WR' | 'TE'; label: string }[] = [
  { pos: 'QB', label: 'Quarterbacks' },
  { pos: 'RB', label: 'Running backs' },
  { pos: 'WR', label: 'Wide receivers' },
  { pos: 'TE', label: 'Tight ends' },
];

/** The Cash and GPP tabs: top plays by position (horizontal), then field ownership with tags (vertical). */
export default function PlaysScreen({ contest }: { contest: PlayContest }) {
  const insets = useSafeAreaInsets();
  const colors = useThemeColors();
  const { data, loading, refreshing, error, refresh } = usePlays(contest);
  const copy = COPY[contest];
  const ready = data?.available ? data : null;
  const columns: OwnershipContest[] = contest === 'cash' ? ['cash'] : ['small_gpp', 'large_gpp'];

  return (
    <SafeAreaView className="flex-1 bg-background" edges={['top', 'left', 'right']}>
      <ScrollView
        showsVerticalScrollIndicator={false}
        contentContainerClassName="screen-content"
        contentContainerStyle={{ paddingBottom: insets.bottom + FLOATING_TAB_BAR.space }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={colors.accent} />}>
        <Text className="screen-title">{copy.title}</Text>
        <Text className="screen-subtitle">{ready ? `${ready.slate.label} · ${copy.subtitle}` : copy.subtitle}</Text>
        <DfsSlatePicker slates={ready?.slates} current={ready?.slate.slate_id} />
        <StatusView loading={loading} error={error} />
        {loading ? <Text className="empty-text">Simulating the field -- this can take a few seconds.</Text> : null}
        {data && !data.available ? <Text className="home-empty-state">{data.reason}</Text> : null}

        {ready ? (
          <>
            <ListHeading title={`Top ${contest === 'cash' ? 'cash' : 'GPP'} plays`} subtitle={copy.balance} />
            <FlatList
              data={CARDS}
              keyExtractor={(item) => item.pos}
              renderItem={({ item }) => (
                <PlayRankingCard
                  title={`Top ${ready.rankings[item.pos]?.length ?? 0} ${item.label}`}
                  subtitle={`${item.pos} ranked by strength of play`}
                  players={ready.rankings[item.pos] ?? []}
                  contest={contest}
                />
              )}
              horizontal
              showsHorizontalScrollIndicator={false}
            />
            <ListHeading title={copy.ownTitle} subtitle={copy.ownSubtitle} />
            <OwnershipModelNote models={ready.ownership_models} />
            <OwnershipList players={ready.players} columns={columns} />
          </>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}
