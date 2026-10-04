import { Pressable, Text } from 'react-native';

/** Green ▲ / red ▼ beside a player's name when his role just grew or shrank; tap to show or hide why. */
export function UsageTrendArrow({ trend, open, onToggle }: { trend?: UsageTrend | null; open: boolean; onToggle: () => void }) {
  if (!trend) return null;
  const up = trend.direction === 'up';
  return (
    <Pressable
      onPress={onToggle}
      hitSlop={10}
      className="trend-arrow"
      accessibilityRole="button"
      aria-expanded={open}
      accessibilityLabel={up ? 'Role growing: show why' : 'Role shrinking: show why'}>
      <Text className={up ? 'trend-arrow-text text-success' : 'trend-arrow-text text-danger'}>{up ? '▲' : '▼'}</Text>
    </Pressable>
  );
}

/** The explanation under the row, shown while the arrow is toggled open. */
export function UsageTrendNote({ trend, open }: { trend?: UsageTrend | null; open: boolean }) {
  if (!trend || !open) return null;
  return (
    <Text className={trend.direction === 'up' ? 'trend-note text-success' : 'trend-note text-danger'}>
      {trend.text} Snap shifts can be one game&apos;s script; watch for it to hold.
    </Text>
  );
}
