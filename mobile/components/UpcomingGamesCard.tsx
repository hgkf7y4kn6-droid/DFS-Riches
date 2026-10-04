import { useState } from 'react';
import { Image, Pressable, Text, useWindowDimensions, View } from 'react-native';

import GameDetailPanel from '@/components/GameDetailPanel';
import { formatGameDetails, formatStatusLabel } from '@/lib/utils';

interface Props extends UpcomingGame {
  /** Stretch to the screen width (vertical lists) instead of a fixed-width card (horizontal lists). */
  fullWidth?: boolean;
}

/**
 * One game: both teams' logos, the matchup and status, then game time,
 * venue, weather, and the spread / over-under (or the score once it starts).
 * Tap to expand the game's Weekly Breakdown inside the card; tap again to
 * collapse it.
 */
export default function UpcomingGamesCard({
  id,
  name,
  location,
  kickoff,
  network,
  daysLeft,
  status,
  score,
  lines,
  weather,
  icon,
  opponentIcon,
  islandLabel,
  fullWidth = false,
}: Props) {
  const [expanded, setExpanded] = useState(false);
  const { width } = useWindowDimensions();
  // Expanded cards in a horizontal list widen to the screen (minus its 20px gutters).
  const style = expanded && !fullWidth ? { width: width - 40 } : undefined;

  return (
    <Pressable
      className={`upcoming-card ${fullWidth ? 'upcoming-card-full' : ''}`}
      style={style}
      onPress={() => setExpanded((e) => !e)}
      accessibilityRole="button"
      aria-expanded={expanded}
      accessibilityLabel={`${name}, ${expanded ? 'hide' : 'show'} game breakdown`}>
      <View className="upcoming-row">
        <View className="upcoming-logos">
          <Image source={icon} className="upcoming-icon" style={{ width: 40, height: 40 }} resizeMode="contain" />
          <Image source={opponentIcon} className="upcoming-icon upcoming-icon-overlap" style={{ width: 40, height: 40, marginLeft: -10 }} resizeMode="contain" />
        </View>
        <View className="flex-1">
          <Text className="upcoming-name">{name}</Text>
          <Text className={`upcoming-countdown ${status === 'live' ? 'text-negative' : status === 'final' ? 'text-pending' : ''}`}>
            {formatStatusLabel(status, daysLeft)}
            {islandLabel ? ` · ${islandLabel}` : ''}
          </Text>
        </View>
      </View>
      <View className="upcoming-info">
        <Text className="upcoming-game-info">{formatGameDetails({ time: kickoff, network })}</Text>
        <Text className="upcoming-game-info" numberOfLines={1}>
          {location}
        </Text>
        <Text className="upcoming-game-info" numberOfLines={expanded ? undefined : 1}>
          {weather}
        </Text>
        <Text className="upcoming-game-lines">{status === 'upcoming' || !score ? lines : score}</Text>
        <Text className="upcoming-expand-hint">{expanded ? 'Hide breakdown ▲' : 'Tap for game breakdown ▼'}</Text>
      </View>
      {expanded ? <GameDetailPanel gameId={id} /> : null}
    </Pressable>
  );
}
