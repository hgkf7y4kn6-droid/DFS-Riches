import { useState } from 'react';
import { Pressable, ScrollView, Text, View } from 'react-native';

import { useExpandedWidth } from '@/components/dfs/useCardWidth';
import MatchupBadge from '@/components/MatchupBadge';
import TagPill from '@/components/plays/TagPill';
import TagChoices from '@/components/plays/TagChoices';
import type { Pool } from '@/lib/pool-tags-context';
import { formatCurrency } from '@/lib/utils';
import LeverageBadge from '@/components/LeverageBadge';

const POSITIONS = ['All', 'RB', 'WR', 'TE'];
const BAR_MAX = 40;

const arrow = (t: UsageTrend) => (t.direction === 'up' ? '▲' : '▼');
const arrowClass = (t: UsageTrend) => (t.direction === 'up' ? 'text-success' : 'text-danger');

/** Snap share per game as small bars, the latest highlighted green (up) or red (down). */
function SnapBars({ trend }: { trend: UsageTrend }) {
  const series = trend.series ?? [];
  return (
    <View className="shift-bars">
      {series.map((g, i) => {
        const last = i === series.length - 1;
        const pct = g.snap_pct ?? 0;
        return (
          <View key={g.week} className="shift-bar-col">
            <Text className="shift-bar-value">{g.snap_pct != null ? `${Math.round(pct)}%` : '-'}</Text>
            <View
              className={last ? (trend.direction === 'up' ? 'shift-bar bg-success' : 'shift-bar bg-danger') : 'shift-bar bg-muted-foreground/40'}
              style={{ height: Math.max(2, (pct / 100) * BAR_MAX) }}
            />
            <Text className="shift-bar-week">Wk {g.week}</Text>
            <Text className="shift-bar-opps">{g.opps}</Text>
          </View>
        );
      })}
    </View>
  );
}

function ShiftRow({ player, pool }: { player: PlayPlayer; pool: Pool }) {
  const p = player;
  const t = p.usage_trend!;
  const [picking, setPicking] = useState(false);
  return (
    <View className="dfs-row">
      <View className="dfs-row-main">
        <Text className={`shift-arrow ${arrowClass(t)}`}>{arrow(t)}</Text>
        <View className="flex-1 pr-2">
          <View className="flex-row items-center">
            <Text className="dfs-name flex-shrink" numberOfLines={1}>
              {p.name}
            </Text>
            <LeverageBadge value={p.leverage ?? null} detail={p.leverage_detail} />
          </View>
          <Text className="dfs-meta">
            {p.position} · {p.team} vs {p.opponent} · {formatCurrency(p.salary)} · {p.final.toFixed(1)} proj
          </Text>
          <MatchupBadge opponent={p.opponent} position={p.position} />
        </View>
        <View className="items-end">
          <Text className={`dfs-lead ${arrowClass(t)}`}>
            {t.snap_delta != null ? `${t.snap_delta > 0 ? '+' : ''}${Math.round(t.snap_delta)}% snaps` : ''}
          </Text>
          <TagPill tag={pool.tagOf(p)} mine={pool.isMine(p)} onPress={() => setPicking((v) => !v)} />
        </View>
      </View>
      {picking ? <TagChoices player={p} pool={pool} onDone={() => setPicking(false)} /> : null}
      <SnapBars trend={t} />
      <Text className="shift-legend">Snap share per game · bottom number: {t.unit ?? 'carries + targets'}</Text>
      <Text className="dfs-reason">{t.text}</Text>
      {t.sustained ? <Text className="dfs-reason">Two straight games past his earlier usage.</Text> : null}
    </View>
  );
}

/**
 * Horizontal-list card for players whose roles are genuinely shifting: a new
 * season high or low in snap share, backed by a teammate moving the other
 * way, two straight games, or a big swing with the touches to match.
 * Collapsed: the three biggest moves. Expanded: every shift with snap-share
 * bars and usage per game, filterable by position.
 */
export default function RoleShiftsCard({ players, pool }: { players: PlayPlayer[]; pool: Pool }) {
  const [expanded, setExpanded] = useState(false);
  const [position, setPosition] = useState('All');
  const style = useExpandedWidth(expanded);
  const shown = players.filter((p) => position === 'All' || p.position === position);
  const up = players.filter((p) => p.usage_trend?.direction === 'up').length;
  return (
    <View className="dfs-card" style={style}>
      <Pressable onPress={() => setExpanded((e) => !e)} accessibilityRole="button" aria-expanded={expanded}>
        <Text className="dfs-card-kicker">Role shifts</Text>
        <Text className="dfs-card-title">{players.length} roles shifting</Text>
        <Text className="dfs-card-subtitle">
          {up} growing · {players.length - up} shrinking · snap share and usage
        </Text>
        {!expanded ? (
          <View className="mt-2">
            {players.slice(0, 3).map((p) => (
              <Text key={p.id} className="dfs-preview" numberOfLines={1}>
                <Text className={arrowClass(p.usage_trend!)}>{arrow(p.usage_trend!)}</Text> {p.name}
                <LeverageBadge inline value={p.leverage ?? null} />{' '}
                <Text className="dfs-meta">
                  {p.team} {p.position} ·{' '}
                  {(p.usage_trend!.series ?? [])
                    .map((g) => (g.snap_pct != null ? Math.round(g.snap_pct) : '-'))
                    .join('→')}
                  % snaps
                </Text>
              </Text>
            ))}
          </View>
        ) : null}
        <Text className="upcoming-expand-hint">{expanded ? 'Collapse ▲' : `Tap for all ${players.length} ▼`}</Text>
      </Pressable>
      {expanded ? (
        <View className="mt-2">
          <Text className="dfs-reason mb-2">
            A new season high or low in snap share, backed by a teammate moving the other way, two straight games, or a big swing
            with the touches to match -- not one odd game.
          </Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} className="chip-row mb-1" contentContainerClassName="chip-row-content">
            {POSITIONS.map((pos) => {
              const active = pos === position;
              return (
                <Pressable
                  key={pos}
                  className={`filter-chip ${active ? 'filter-chip-active' : ''}`}
                  onPress={() => setPosition(pos)}
                  accessibilityRole="button"
                  aria-pressed={active}>
                  <Text className={`filter-chip-text ${active ? 'filter-chip-text-active' : ''}`}>{pos}</Text>
                </Pressable>
              );
            })}
          </ScrollView>
          {shown.map((p) => (
            <ShiftRow key={p.id} player={p} pool={pool} />
          ))}
          {!shown.length ? <Text className="home-empty-state">No {position} role shifts this week.</Text> : null}
        </View>
      ) : null}
    </View>
  );
}
