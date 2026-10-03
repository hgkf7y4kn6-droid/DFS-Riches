import { useState } from 'react';
import { Text, View } from 'react-native';

import { UsageTrendArrow, UsageTrendNote } from '@/components/UsageTrend';
import MatchupBadge from '@/components/MatchupBadge';
import { roleText } from '@/lib/matchup-sort';
import { formatCurrency, formatPoints } from '@/lib/utils';

export interface RowPlayer {
  name: string;
  position: string;
  team: string;
  opponent?: string;
  salary: number;
  proj_points?: number | null;
  ceiling?: number | null;
  injury?: string | null;
  actual?: number;
  role?: PlayerRole | null;
  snap_pct?: number | null;
  usage_trend?: UsageTrend | null;
}

function pointsLine(p: RowPlayer): string {
  const parts: string[] = [];
  if (p.proj_points != null) parts.push(`${formatPoints(p.proj_points)} proj`);
  if (p.ceiling != null && p.actual == null) parts.push(`${formatPoints(p.ceiling)} ceil`);
  if (p.actual != null) parts.push(`${formatPoints(p.actual)} actual`);
  return parts.join(' · ');
}

/**
 * One lineup as a stacked vertical list: slot, player name with position,
 * team and opponent underneath, then salary and projection on the right --
 * readable on a phone without a wide table.
 */
export function LineupRow({ slot, player, right, note }: { slot: string; player: RowPlayer | null; right?: React.ReactNode; note?: string | null }) {
  const [trendOpen, setTrendOpen] = useState(false);
  return (
    <View className="lineup-row">
      <Text className="lineup-slot">{slot}</Text>
      {player ? (
        <>
          <View className="lineup-player">
            <View className="flex-row items-center">
              <Text className="lineup-player-name flex-shrink" numberOfLines={1}>
                {player.name}
                {player.injury && player.injury !== 'Healthy' ? <Text className="injury-tag"> {player.injury}</Text> : null}
              </Text>
              <UsageTrendArrow trend={player.usage_trend} open={trendOpen} onToggle={() => setTrendOpen((o) => !o)} />
            </View>
            <Text className="lineup-player-meta">
              {player.position} · {player.team}
              {player.opponent ? ` vs ${player.opponent}` : ''}
              {roleText(player) ? ` · ${roleText(player)}` : ''}
            </Text>
            {player.opponent ? <MatchupBadge opponent={player.opponent} position={player.position} /> : null}
            <UsageTrendNote trend={player.usage_trend} open={trendOpen} />
            {note ? <Text className="lineup-player-note">{note}</Text> : null}
          </View>
          <View className="lineup-numbers">
            <Text className="lineup-salary">{formatCurrency(player.salary)}</Text>
            <Text className="lineup-proj">{pointsLine(player)}</Text>
          </View>
        </>
      ) : (
        <Text className="lineup-open">Open</Text>
      )}
      {right}
    </View>
  );
}

export function Totals({ items }: { items: { label: string; value: string; tone?: 'negative' }[] }) {
  return (
    <View className="lineup-totals">
      {items.map((it) => (
        <View key={it.label} className="lineup-total">
          <Text className="lineup-total-label">{it.label}</Text>
          <Text className={`lineup-total-value ${it.tone === 'negative' ? 'text-negative' : ''}`}>{it.value}</Text>
        </View>
      ))}
    </View>
  );
}
