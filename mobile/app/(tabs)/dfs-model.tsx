import { useMemo, useState } from 'react';
import { FlatList, RefreshControl, ScrollView, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import DfsSlatePicker from '@/components/dfs/DfsSlatePicker';
import GameEnvironmentCard from '@/components/dfs/GameEnvironmentCard';
import ModelStatus from '@/components/dfs/ModelStatus';
import RankedPlayersCard from '@/components/dfs/RankedPlayersCard';
import type { DfsMetric } from '@/components/dfs/DfsPlayerRow';
import ListHeading from '@/components/ListHeading';
import SafeAreaView from '@/components/SafeAreaView';
import { FLOATING_TAB_BAR, useThemeColors } from '@/constants/theme';
import { useDfsModel } from '@/lib/dfs-model-context';
import { formatEt } from '@/lib/utils';
import { useWeek } from '@/lib/week-context';

const RANKINGS: { id: string; title: string; subtitle: string; metric: DfsMetric }[] = [
  { id: 'final', title: 'Final projections', subtitle: 'Consensus of every source, matchup- and weather-adjusted', metric: 'final' },
  { id: 'value', title: 'Best values', subtitle: 'Projected points per $1,000 of salary', metric: 'value' },
  { id: 'ceiling', title: 'Highest ceilings', subtitle: '85th-percentile outcome', metric: 'ceiling' },
];

export default function DfsModelScreen() {
  const insets = useSafeAreaInsets();
  const colors = useThemeColors();
  const { model, loading, refresh } = useDfsModel();
  const { weekData } = useWeek();
  const [open, setOpen] = useState<string | null>(null);

  const ready = model?.available ? model : null;
  const envs = useMemo(() => [...(ready?.strategy.games ?? [])].sort((a, b) => a.env_rank - b.env_rank), [ready]);
  const gameIdFor = (env: DfsGameEnv) =>
    weekData.data?.schedule.games.find((g) => g.away === env.away && g.home === env.home)?.game_id ?? null;

  return (
    <SafeAreaView className="flex-1 bg-background" edges={['top', 'left', 'right']}>
      <ScrollView
        showsVerticalScrollIndicator={false}
        contentContainerClassName="screen-content"
        contentContainerStyle={{ paddingBottom: insets.bottom + FLOATING_TAB_BAR.space }}
        refreshControl={<RefreshControl refreshing={loading && !!model} onRefresh={refresh} tintColor={colors.accent} />}>
        <Text className="screen-title">DFS Model</Text>
        <Text className="screen-subtitle">
          {ready ? `${ready.slate.label} · updated ${formatEt(ready.generated_at)}` : 'Projections, values, ceilings and game environments'}
        </Text>
        <DfsSlatePicker />
        <ModelStatus />

        {ready ? (
          <>
            <ListHeading title="Player rankings" subtitle="Tap a card for the top 10 at each position" />
            <FlatList
              data={RANKINGS}
              keyExtractor={(item) => item.id}
              renderItem={({ item }) => (
                <RankedPlayersCard title={item.title} subtitle={item.subtitle} metric={item.metric} players={ready.table} />
              )}
              horizontal
              showsHorizontalScrollIndicator={false}
            />

            <ListHeading title="Game environments" subtitle="Best to worst · tap one for stacks, matchups and targets" />
            {envs.map((env) => {
              const teams = [env.away, env.home];
              return (
                <GameEnvironmentCard
                  key={env.game}
                  env={env}
                  stacks={ready.strategy.stacks.filter((s) => s.game === env.game)}
                  players={ready.table.filter((p) => teams.includes(p.team))}
                  gameId={gameIdFor(env)}
                  expanded={open === env.game}
                  onToggle={() => setOpen((cur) => (cur === env.game ? null : env.game))}
                />
              );
            })}
            {!envs.length ? <View><Text className="home-empty-state">No games on this slate.</Text></View> : null}
          </>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}
