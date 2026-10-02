import { Text, View } from 'react-native';

import dayjs from '@/lib/dayjs';
import { weatherText } from '@/lib/lines';
import { formatDayPart, formatSigned } from '@/lib/utils';

/**
 * One game as a card: countdown to kickoff, matchup, kickoff day/time,
 * network and weather, and the betting lines (favorite, total, implied
 * totals). Island games (their own Showdown slate) get a badge.
 */
export default function UpcomingGameCard({ game }: { game: Game }) {
  const kickoff = dayjs(game.kickoff_utc);
  const c = game.context;
  const favorite =
    c?.away_spread != null && c.home_spread != null
      ? c.away_spread < c.home_spread
        ? `${game.away} ${formatSigned(c.away_spread)}`
        : c.home_spread < c.away_spread
          ? `${game.home} ${formatSigned(c.home_spread)}`
          : 'PK'
      : '-';

  return (
    <View className="upcoming-card">
      <View className="upcoming-header">
        <Text className="upcoming-countdown">{kickoff.fromNow()}</Text>
        {game.isolated ? (
          <View className="badge">
            <Text className="badge-text">{formatDayPart(game.day_part)}</Text>
          </View>
        ) : null}
      </View>
      <Text className="upcoming-matchup">
        {game.away} @ {game.home}
      </Text>
      <Text className="upcoming-time">{game.kickoff_et}</Text>
      <Text className="upcoming-meta" numberOfLines={1}>
        {[game.network, weatherText(game.weather)].filter(Boolean).join(' · ')}
      </Text>
      <View className="upcoming-lines">
        <View>
          <Text className="upcoming-line-value">{favorite}</Text>
          <Text className="upcoming-line-label">Spread</Text>
        </View>
        <View>
          <Text className="upcoming-line-value">{c?.total_line != null ? c.total_line.toFixed(1) : '-'}</Text>
          <Text className="upcoming-line-label">Total</Text>
        </View>
        <View>
          <Text className="upcoming-line-value">
            {c?.away_implied_total != null && c.home_implied_total != null
              ? `${c.away_implied_total.toFixed(1)}/${c.home_implied_total.toFixed(1)}`
              : '-'}
          </Text>
          <Text className="upcoming-line-label">Implied</Text>
        </View>
      </View>
    </View>
  );
}
