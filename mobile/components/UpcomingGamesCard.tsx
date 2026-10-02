import { Image, Text, View } from 'react-native';

function countdown(status: UpcomingGameStatus, daysLeft: number): string {
  if (status === 'final') return 'Final';
  if (status === 'live') return 'Live';
  if (daysLeft <= 0) return 'Today';
  return daysLeft === 1 ? 'Tomorrow' : `In ${daysLeft} days`;
}

interface Props {
  data: UpcomingGame;
  /** Stretch to the screen width (vertical lists) instead of a fixed-width card (horizontal lists). */
  fullWidth?: boolean;
}

/**
 * One game: both teams' logos, the matchup and countdown, then game time,
 * venue, weather, and the spread / over-under (or the score once it starts).
 */
export default function UpcomingGamesCard({ data, fullWidth = false }: Props) {
  const { name, location, kickoff, network, daysLeft, status, score, lines, weather, icon, opponentIcon, islandLabel } = data;
  return (
    <View className={`upcoming-card ${fullWidth ? 'upcoming-card-full' : ''}`}>
      <View className="upcoming-row">
        <View className="upcoming-logos">
          <Image source={icon} className="upcoming-icon" style={{ width: 40, height: 40 }} resizeMode="contain" />
          <Image source={opponentIcon} className="upcoming-icon upcoming-icon-overlap" style={{ width: 40, height: 40, marginLeft: -10 }} resizeMode="contain" />
        </View>
        <View className="flex-1">
          <Text className="upcoming-name">{name}</Text>
          <Text className={`upcoming-countdown ${status === 'live' ? 'text-negative' : status === 'final' ? 'text-pending' : ''}`}>
            {countdown(status, daysLeft)}
            {islandLabel ? ` · ${islandLabel}` : ''}
          </Text>
        </View>
      </View>
      <View className="upcoming-info">
        <Text className="upcoming-game-info">
          {kickoff}
          {network ? ` · ${network}` : ''}
        </Text>
        <Text className="upcoming-game-info" numberOfLines={1}>
          {location}
        </Text>
        <Text className="upcoming-game-info" numberOfLines={1}>
          {weather}
        </Text>
        <Text className="upcoming-game-lines">{status === 'upcoming' || !score ? lines : score}</Text>
      </View>
    </View>
  );
}
