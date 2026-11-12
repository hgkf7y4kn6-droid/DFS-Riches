import { useState } from 'react';
import { Pressable, Text, View } from 'react-native';

import Stat from '@/components/Stat';
import { UsageTrendArrow, UsageTrendNote } from '@/components/UsageTrend';
import CornersOutNote from '@/components/CornersOutNote';
import PlayChanceNote from '@/components/PlayChanceNote';
import MatchupBadge from '@/components/MatchupBadge';
import { formatCurrency, formatPercent } from '@/lib/utils';
import LeverageBadge from '@/components/LeverageBadge';
import { ProSheet } from '@/components/ProLock';
import PropLadder from '@/components/dfs/PropLadder';
import { useAccountSync } from '@/lib/account-sync';
import { track } from '@/lib/analytics';

export type DfsMetric = 'final' | 'value' | 'ceiling';

const METRIC_LABEL: Record<DfsMetric, string> = { final: 'proj', value: 'pts/$1k', ceiling: 'ceil' };
// The positions app.prop_pricer prices.
const PROP_POSITIONS = new Set(['QB', 'RB', 'WR', 'TE']);

/**
 * One player, stacked for a phone: rank and name (with injury status), position
 * and matchup, salary; then projection, ceiling, value and expected roster %.
 * `metric` is shown first and bold. "Props" opens his prop medians and ladder
 * (a Pro feature: for free accounts it opens what Pro adds).
 */
export default function DfsPlayerRow({
  player,
  rank,
  metric = 'final',
  showReasons = 0,
}: {
  player: DfsPlayer;
  rank?: number;
  metric?: DfsMetric;
  /** How many of the model's reasons to list under the row. */
  showReasons?: number;
}) {
  const p = player;
  const [trendOpen, setTrendOpen] = useState(false);
  const [propsOpen, setPropsOpen] = useState(false);
  const [proOpen, setProOpen] = useState(false);
  const propsLocked = useAccountSync().locked('props');
  const stats: { key: DfsMetric | 'own'; value: string; label: string; term: string }[] = [
    { key: 'final', value: p.final.toFixed(1), label: 'proj', term: 'projection' },
    { key: 'ceiling', value: p.ceiling != null ? p.ceiling.toFixed(1) : '', label: 'ceiling', term: 'ceiling' },
    { key: 'value', value: p.value != null ? p.value.toFixed(2) : '', label: 'pts/$1k', term: 'value' },
    { key: 'own', value: p.ownership != null ? formatPercent(p.ownership / 100, 1) : '', label: 'own', term: 'ownership' },
  ];
  const lead = stats.find((x) => x.key === metric);
  const rest = stats.filter((x) => x.key !== metric && x.value);
  const reasons = (p.reasons ?? (p.reason ? [p.reason] : [])).slice(0, showReasons);
  const hasProps = !!(p.props && Object.keys(p.props).length);
  const propsAvailable = propsLocked ? PROP_POSITIONS.has(p.position) : hasProps;
  // Everything past the ranked metric, salary and first reason waits behind one tap.
  const hasDrawer = rest.length > 0 || reasons.length > 1 || propsAvailable;
  const [drawerOpen, setDrawerOpen] = useState(false);

  return (
    <View className="dfs-row-clean">
      <View className="dfs-row-main">
        {rank != null ? <Text className="dfs-rank">{rank}</Text> : null}
        <View className="flex-1 pr-2">
          <View className="flex-row items-center">
            <Text className="dfs-name flex-shrink" numberOfLines={1}>
              {p.name}
              {p.injury && p.injury !== 'Healthy' ? <Text className="injury-tag"> {p.injury}</Text> : null}
            </Text>
            <LeverageBadge player={{ id: p.id, name: p.name, team: p.team }} />
            <UsageTrendArrow trend={p.usage_trend} open={trendOpen} onToggle={() => setTrendOpen((o) => !o)} />
          </View>
          <Text className="dfs-meta">
            {p.slot && p.slot !== p.position ? `${p.slot} · ` : ''}
            {p.position} · {p.team} vs {p.opponent}
          </Text>
          <MatchupBadge opponent={p.opponent} position={p.position} />
          <CornersOutNote opponent={p.opponent} count={p.opp_cb_out} position={p.position} />
          <PlayChanceNote injury={p.injury} chance={p.play_chance} practice={p.practice} />
          <UsageTrendNote trend={p.usage_trend} open={trendOpen} />
        </View>
        <View className="items-end">
          <Text className="dfs-salary">{formatCurrency(p.salary)}</Text>
          <Text className="t-value" accessibilityLabel={`${METRIC_LABEL[metric]}: ${lead?.value || 'none'}`}>
            {lead?.value || '-'}
            <Text className="t-label"> {METRIC_LABEL[metric]}</Text>
          </Text>
        </View>
      </View>
      {reasons[0] ? (
        <Text className="dfs-reason-line" numberOfLines={1}>
          {reasons[0]}
        </Text>
      ) : null}
      {hasDrawer ? (
        <Pressable
          onPress={() => setDrawerOpen((o) => !o)}
          accessibilityRole="button"
          aria-expanded={drawerOpen}
          accessibilityLabel={`${p.name} details, ${drawerOpen ? 'collapse' : 'expand'}`}
          hitSlop={8}>
          <Text className="link-text mt-1">{drawerOpen ? 'Hide details' : 'Details ›'}</Text>
        </Pressable>
      ) : null}
      {drawerOpen ? (
        <View className="dfs-drawer">
          {rest.length ? (
            <View className="dfs-drawer-stats">
              {rest.map((x) => (
                <Stat key={x.key} value={x.value} label={x.label} term={x.term} />
              ))}
            </View>
          ) : null}
          {reasons.slice(1).map((r, i) => (
            <Text key={i} className="dfs-reason">
              • {r}
            </Text>
          ))}
          {propsLocked && PROP_POSITIONS.has(p.position) ? (
            <Pressable
              onPress={() => {
                track('pro_unlock_tapped', { feature: 'props' });
                setProOpen(true);
              }}
              accessibilityRole="button"
              accessibilityLabel="Props, a Pro feature"
              hitSlop={8}>
              <Text className="link-text mt-2">Props · Pro</Text>
            </Pressable>
          ) : hasProps ? (
            <Pressable
              onPress={() => {
                if (!propsOpen) track('props_opened', { position: p.position });
                setPropsOpen((o) => !o);
              }}
              accessibilityRole="button"
              aria-expanded={propsOpen}
              hitSlop={8}>
              <Text className="link-text mt-2">{propsOpen ? 'Hide props' : 'Props ›'}</Text>
            </Pressable>
          ) : null}
          {propsOpen && p.props && !propsLocked ? <PropLadder props={p.props} /> : null}
        </View>
      ) : null}
      {propsLocked ? <ProSheet feature="props" visible={proOpen} onClose={() => setProOpen(false)} /> : null}
    </View>
  );
}
