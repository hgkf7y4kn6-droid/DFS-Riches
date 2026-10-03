import { Text, View } from 'react-native';

import MatchupBadge from '@/components/MatchupBadge';
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
  return (
    <View className="lineup-row">
      <Text className="lineup-slot">{slot}</Text>
      {player ? (
        <>
          <View className="lineup-player">
            <Text className="lineup-player-name" numberOfLines={1}>
              {player.name}
              {player.injury && player.injury !== 'Healthy' ? <Text className="injury-tag"> {player.injury}</Text> : null}
            </Text>
            <Text className="lineup-player-meta">
              {player.position} · {player.team}
              {player.opponent ? ` vs ${player.opponent}` : ''}
            </Text>
            {player.opponent ? <MatchupBadge opponent={player.opponent} position={player.position} /> : null}
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
