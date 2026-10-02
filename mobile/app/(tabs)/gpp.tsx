import { useState } from 'react';
import { FlatList, RefreshControl, ScrollView, Text } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import DfsLineupCard from '@/components/dfs/DfsLineupCard';
import DfsSlatePicker from '@/components/dfs/DfsSlatePicker';
import ModelStatus from '@/components/dfs/ModelStatus';
import PlayerPoolCard from '@/components/dfs/PlayerPoolCard';
import ListHeading from '@/components/ListHeading';
import SafeAreaView from '@/components/SafeAreaView';
import { FLOATING_TAB_BAR, useThemeColors } from '@/constants/theme';
import { useDfsModel } from '@/lib/dfs-model-context';

export default function GppScreen() {
  const insets = useSafeAreaInsets();
  const colors = useThemeColors();
  const { model, loading, refresh } = useDfsModel();
  const [open, setOpen] = useState<string | null>(null);
  const ready = model?.available ? model : null;

  const pools = ready
    ? (() => {
        const G = ready.strategy.gpp_pool;
        const P = ready.strategy.pools;
        const F = ready.strategy.fades;
        return [
          { id: 'core', kicker: 'GPP pool', title: 'Core plays', players: G.core, metric: 'ceiling' as const },
          { id: 'leverage', kicker: 'GPP pool', title: 'Leverage', subtitle: 'Ceiling the field is underweight on', players: G.leverage, metric: 'ceiling' as const },
          { id: 'low', kicker: 'GPP pool', title: 'Low-owned ceiling', players: G.low_owned_ceiling, metric: 'ceiling' as const },
          { id: 'chalk', kicker: 'GPP pool', title: 'Chalk', subtitle: 'Most popular plays', players: G.chalk, metric: 'final' as const },
          { id: 'qb', kicker: 'By position', title: 'GPP quarterbacks', players: P.QB.gpp, metric: 'ceiling' as const },
          { id: 'rb', kicker: 'By position', title: 'GPP running backs', players: P.RB.gpp, metric: 'ceiling' as const },
          { id: 'wr', kicker: 'By position', title: 'GPP wide receivers', players: P.WR.gpp, metric: 'ceiling' as const },
          { id: 'te', kicker: 'By position', title: 'Tight ends', subtitle: P.TE.recommendation?.why, players: [...P.TE.pay_up, ...P.TE.punt], metric: 'ceiling' as const },
          { id: 'savers', kicker: 'Salary savers', title: 'Cheap with upside', players: G.salary_savers, metric: 'value' as const },
          { id: 'fades', kicker: 'Avoid', title: 'GPP fades', subtitle: 'Fragile chalk and poor fits', players: [...F.gpp, ...F.fragile_chalk, ...F.poor_fit], metric: 'final' as const },
        ];
      })()
    : [];
  const lineups = ready ? [...ready.lineups.gpp, ...ready.lineups.contrarian] : [];

  return (
    <SafeAreaView className="flex-1 bg-background" edges={['top', 'left', 'right']}>
      <ScrollView
        showsVerticalScrollIndicator={false}
        contentContainerClassName="screen-content"
        contentContainerStyle={{ paddingBottom: insets.bottom + FLOATING_TAB_BAR.space }}
        refreshControl={<RefreshControl refreshing={loading && !!model} onRefresh={refresh} tintColor={colors.accent} />}>
        <Text className="screen-title">GPP</Text>
        <Text className="screen-subtitle">Tournaments: ceiling, correlation and leverage against the field</Text>
        <DfsSlatePicker />
        <ModelStatus />
        {ready ? (
          <>
            <ListHeading title="GPP pools" subtitle="Tap a card for every player and why" />
            <FlatList
              data={pools}
              keyExtractor={(item) => item.id}
              renderItem={({ item }) => (
                <PlayerPoolCard kicker={item.kicker} title={item.title} subtitle={item.subtitle} players={item.players} metric={item.metric} />
              )}
              horizontal
              showsHorizontalScrollIndicator={false}
            />
            <ListHeading title="GPP lineups" subtitle="Stacked builds plus contrarian options · tap for details" />
            {lineups.map((lu, i) => (
              <DfsLineupCard
                key={`${lu.label}-${i}`}
                lineup={lu}
                expanded={open === `${i}`}
                onToggle={() => setOpen((cur) => (cur === `${i}` ? null : `${i}`))}
              />
            ))}
            {!lineups.length ? <Text className="home-empty-state">No GPP lineups for this slate.</Text> : null}
          </>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}
