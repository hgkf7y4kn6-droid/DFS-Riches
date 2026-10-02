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

export default function CashScreen() {
  const insets = useSafeAreaInsets();
  const colors = useThemeColors();
  const { model, loading, refresh } = useDfsModel();
  const [open, setOpen] = useState<string | null>(null);
  const ready = model?.available ? model : null;

  const pools = ready
    ? (() => {
        const P = ready.strategy.pools;
        const byId = new Map(ready.table.map((p) => [p.id, p]));
        const te = P.TE.cash_ids.map((id) => byId.get(id)).filter((p): p is DfsPlayer => Boolean(p));
        return [
          { id: 'qb', kicker: 'Cash pool', title: 'Quarterbacks', players: P.QB.cash },
          { id: 'rb', kicker: 'Cash pool', title: 'Running backs', players: P.RB.cash },
          { id: 'wr', kicker: 'Cash pool', title: 'Wide receivers', players: P.WR.cash },
          { id: 'te', kicker: 'Cash pool', title: 'Tight ends', subtitle: P.TE.recommendation?.strategy, players: te },
          { id: 'dst', kicker: 'Cash pool', title: 'Defenses', players: P.DST },
          { id: 'savers', kicker: 'Salary savers', title: 'Cheap with a real role', players: P.salary_savers },
          { id: 'fades', kicker: 'Avoid', title: 'Cash fades', subtitle: 'Fragile floors or uncertain roles', players: ready.strategy.fades.cash },
        ];
      })()
    : [];

  return (
    <SafeAreaView className="flex-1 bg-background" edges={['top', 'left', 'right']}>
      <ScrollView
        showsVerticalScrollIndicator={false}
        contentContainerClassName="screen-content"
        contentContainerStyle={{ paddingBottom: insets.bottom + FLOATING_TAB_BAR.space }}
        refreshControl={<RefreshControl refreshing={loading && !!model} onRefresh={refresh} tintColor={colors.accent} />}>
        <Text className="screen-title">Cash</Text>
        <Text className="screen-subtitle">50/50s, double-ups and head-to-heads: floor, volume and stability first</Text>
        <DfsSlatePicker />
        <ModelStatus />
        {ready ? (
          <>
            <ListHeading title="Cash pools" subtitle="Tap a card for every player and why" />
            <FlatList
              data={pools}
              keyExtractor={(item) => item.id}
              renderItem={({ item }) => <PlayerPoolCard kicker={item.kicker} title={item.title} subtitle={item.subtitle} players={item.players} />}
              horizontal
              showsHorizontalScrollIndicator={false}
            />
            <ListHeading title="Cash lineups" subtitle="Tap a lineup for players, strengths and risks" />
            {ready.lineups.cash.map((lu, i) => (
              <DfsLineupCard
                key={`${lu.label}-${i}`}
                lineup={lu}
                expanded={open === `${i}`}
                onToggle={() => setOpen((cur) => (cur === `${i}` ? null : `${i}`))}
              />
            ))}
            {!ready.lineups.cash.length ? <Text className="home-empty-state">No cash lineups for this slate.</Text> : null}
          </>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}
