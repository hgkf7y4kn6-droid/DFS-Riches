import { FlatList, RefreshControl, ScrollView, Text } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import BrandHeader from '@/components/BrandHeader';
import DfsSlatePicker from '@/components/dfs/DfsSlatePicker';
import ListHeading from '@/components/ListHeading';
import OwnershipList from '@/components/plays/OwnershipList';
import OwnershipModelNote from '@/components/plays/OwnershipModelNote';
import PlayRankingCard from '@/components/plays/PlayRankingCard';
import SafeAreaView from '@/components/SafeAreaView';
import StatusView from '@/components/StatusView';
import { FLOATING_TAB_BAR, useThemeColors } from '@/constants/theme';
import { usePlays } from '@/lib/plays';
import { poolKey, usePool } from '@/lib/pool-tags-context';
import { useWeek } from '@/lib/week-context';

const COPY: Record<PlayContest, { title: string; subtitle: string; balance: string; ownTitle: string; ownSubtitle: string }> = {
  cash: {
    title: 'Cash',
    subtitle: '50/50s, double-ups and head-to-heads',
    balance: 'Ranked on floor safety, salary, game environment and the odds of a median-to-high (2.5x) game',
    ownTitle: 'Expected cash ownership',
    ownSubtitle: 'Every playable player, most owned first · tap a row for the models and game log, a tag to set your own call',
  },
  gpp: {
    title: 'GPP',
    subtitle: 'Tournaments, small field and large field',
    balance: 'Ranked on ownership leverage, salary, game environment and the odds of a ceiling game',
    ownTitle: 'Expected GPP ownership',
    ownSubtitle: 'Small-field and large-field, most owned first · tap a row for the models and game log, a tag to set your own call',
  },
};

const POSITION_CARDS: { pos: 'QB' | 'RB' | 'WR' | 'TE'; label: string }[] = [
  { pos: 'QB', label: 'Quarterbacks' },
  { pos: 'RB', label: 'Running backs' },
  { pos: 'WR', label: 'Wide receivers' },
  { pos: 'TE', label: 'Tight ends' },
];

interface Card {
  key: string;
  kicker?: string;
  title: string;
  subtitle: string;
  players: PlayPlayer[];
  preview?: (p: PlayPlayer) => string;
  note?: string;
}

/** The horizontal list: a card per position, then (GPP) the chalk and leverage cards. */
function cards(data: PlaysResponse, contest: PlayContest): Card[] {
  const list: Card[] = POSITION_CARDS.map(({ pos, label }) => ({
    key: pos,
    title: `Top ${data.rankings[pos]?.length ?? 0} ${label}`,
    subtitle: `${pos} ranked by strength of play`,
    players: data.rankings[pos] ?? [],
  }));
  if (contest === 'gpp' && data.chalk?.length) {
    list.push({
      key: 'chalk',
      kicker: 'Chalk',
      title: `The ${data.chalk.length} most-owned`,
      subtitle: 'Highest large-field ownership, every position',
      players: data.chalk,
      preview: (p) => `${p.position} · ${p.ownership.large_gpp?.toFixed(1)}% own`,
      note: 'Chalk with a strong ceiling (Prioritize) is worth eating; chalk tagged Fade is owned beyond its ceiling odds -- the field\'s best place to get off.',
    });
  }
  if (contest === 'gpp' && data.leverage?.length) {
    list.push({
      key: 'leverage',
      kicker: 'Leverage',
      title: `Top ${data.leverage.length} leverage plays`,
      subtitle: 'Ceiling odds per point of ownership, every position',
      players: data.leverage,
      preview: (p) => `${p.position} · ${p.leverage_ratio?.toFixed(1)}x · ${p.ownership.large_gpp?.toFixed(1)}% own`,
      note: 'Leverage = P(ceiling game) / large-field ownership; 1.0x is owned in line with the ceiling odds. Each has at least a 12% shot at a tournament-winning score.',
    });
  }
  return list;
}

/** The Cash and GPP tabs: top plays by position (horizontal), then field ownership with tags (vertical). */
export default function PlaysScreen({ contest }: { contest: PlayContest }) {
  const insets = useSafeAreaInsets();
  const colors = useThemeColors();
  const { data, loading, refreshing, error, refresh } = usePlays(contest);
  const { season, week } = useWeek();
  const copy = COPY[contest];
  const ready = data?.available ? data : null;
  const pool = usePool(ready && season && week ? poolKey(season, week, ready.slate.slate_id, contest) : null);
  const columns: OwnershipContest[] = contest === 'cash' ? ['cash'] : ['small_gpp', 'large_gpp'];

  return (
    <SafeAreaView className="flex-1 bg-background" edges={['top', 'left', 'right']}>
      <ScrollView
        showsVerticalScrollIndicator={false}
        contentContainerClassName="screen-content"
        contentContainerStyle={{ paddingBottom: insets.bottom + FLOATING_TAB_BAR.space }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={refresh} tintColor={colors.accent} />}>
        <BrandHeader title={copy.title} />
        <Text className="screen-subtitle">{ready ? `${ready.slate.label} · ${copy.subtitle}` : copy.subtitle}</Text>
        <DfsSlatePicker slates={ready?.slates} current={ready?.slate.slate_id} />
        <StatusView loading={loading} error={error} />
        {loading ? <Text className="empty-text">Simulating the field -- this can take a few seconds.</Text> : null}
        {data && !data.available ? <Text className="home-empty-state">{data.reason}</Text> : null}

        {ready ? (
          <>
            <ListHeading title={`Top ${contest === 'cash' ? 'cash' : 'GPP'} plays`} subtitle={copy.balance} />
            <FlatList
              data={cards(ready, contest)}
              keyExtractor={(item) => item.key}
              renderItem={({ item }) => (
                <PlayRankingCard
                  kicker={item.kicker}
                  title={item.title}
                  subtitle={item.subtitle}
                  players={item.players}
                  contest={contest}
                  pool={pool}
                  preview={item.preview}
                  note={item.note}
                />
              )}
              horizontal
              showsHorizontalScrollIndicator={false}
            />
            <ListHeading title={copy.ownTitle} subtitle={copy.ownSubtitle} />
            <OwnershipModelNote models={ready.ownership_models} />
            <OwnershipList players={ready.players} columns={columns} pool={pool} />
          </>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}
