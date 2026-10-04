import { useState } from 'react';
import { Text, View } from 'react-native';

import { UsageTrendArrow, UsageTrendNote } from '@/components/UsageTrend';
import MatchupBadge from '@/components/MatchupBadge';
import TeamShareText from '@/components/TeamShare';
import TrendChips from '@/components/TrendChips';
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
  /** Shown when the builder sorts by them: expected ownership (%), DK pts/game over the last 3. */
  ownership?: number | null;
  trend?: number | null;
  /** Builder "Recent form" sort: DK points per game over the last 3 / 6 / 9 games vs the season average. */
  form?: { l3: number | null; l6: number | null; l9: number | null; season: number | null } | null;
  /** Builder blended sort: the player's weighted score (0-100) in the current pool. */
  blend?: number | null;
  /** Cash builder: the model's floor. */
  floor?: number | null;
  team_share?: TeamShare | null;
}

function pointsLine(p: RowPlayer): string {
  const parts: string[] = [];
  if (p.blend != null) parts.push(`Blend ${Math.round(p.blend)}`);
  if (p.proj_points != null) parts.push(`${formatPoints(p.proj_points)} proj`);
  if (p.floor != null) parts.push(`${formatPoints(p.floor)} floor`);
  if (p.ceiling != null && p.actual == null) parts.push(`${formatPoints(p.ceiling)} ceil`);
  if (p.actual != null) parts.push(`${formatPoints(p.actual)} actual`);
  if (p.ownership !== undefined) parts.push(p.ownership != null ? `${p.ownership.toFixed(1)}% own` : 'own n/a');
  if (p.trend !== undefined) parts.push(p.trend != null ? `${formatPoints(p.trend)} L3` : 'no games');
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
              <TeamShareText share={player.team_share} />
            </Text>
            {player.opponent ? <MatchupBadge opponent={player.opponent} position={player.position} /> : null}
            <UsageTrendNote trend={player.usage_trend} open={trendOpen} />
            {player.form ? <TrendChips windows={player.form} baseline={player.form.season} /> : null}
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
