import { Text, useColorScheme, View } from 'react-native';

// Away / home identity for two-team charts, validated for color-vision
// deficiency in each mode; every bar also carries its team label.
const TEAM_FILL = {
  light: { away: '#1D4ED8', home: '#EA7A53' },
  dark: { away: '#3B82F6', home: '#D06F45' },
};
export type Side = 'away' | 'home';

export function useTeamFill(side: Side): string {
  return TEAM_FILL[useColorScheme() === 'dark' ? 'dark' : 'light'][side];
}

/**
 * League rank as a meter: the fuller the bar, the better the rank
 * (#1 = full). Label on the left, "value · #rank" on the right.
 */
export function RankBar({ label, side, rank, of, value }: { label: string; side: Side; rank: number; of: number; value: string }) {
  const fill = useTeamFill(side);
  const pct = of > 1 ? ((of - rank) / (of - 1)) * 100 : 100;
  return (
    <View className="chart-row" accessibilityLabel={`${label}: ${value}, ranked ${rank} of ${of}`}>
      <Text className="chart-label" numberOfLines={1}>
        {label}
      </Text>
      <View className="chart-track">
        <View className="chart-bar" style={{ width: `${Math.max(pct, 3)}%`, backgroundColor: fill }} />
      </View>
      <Text className="chart-value">
        {value} <Text className="chart-rank">#{rank}</Text>
      </Text>
    </View>
  );
}

/**
 * A bar diverging from a center line (0 = even): right of center favors the
 * offense, left favors the defense. `muted` draws it gray (no real edge).
 */
export function DivergingBar({ label, side, value, max, muted, valueText }: {
  label: string;
  side: Side;
  value: number;
  max: number;
  muted?: boolean;
  valueText: string;
}) {
  const fill = useTeamFill(side);
  const half = Math.min(Math.abs(value) / max, 1) * 50;
  return (
    <View className="chart-diverging-row" accessibilityLabel={`${label}: ${valueText}${muted ? ', no real edge' : ''}`}>
      <Text className="chart-diverging-label">{label}</Text>
      <View className="chart-diverging-line">
        <View className="chart-track flex-1">
          <View className="chart-center" />
          <View
            className={`chart-bar absolute ${muted ? 'chart-bar-muted' : ''}`}
            style={{
              left: value >= 0 ? '50%' : `${50 - half}%`,
              width: `${Math.max(half, 1.5)}%`,
              ...(muted ? {} : { backgroundColor: fill }),
            }}
          />
        </View>
        <Text className="chart-value">{valueText}</Text>
      </View>
    </View>
  );
}

export function ChartAxis({ left, center, right }: { left: string; center: string; right: string }) {
  return (
    <View className="chart-axis">
      <Text className="chart-axis-text">{left}</Text>
      <Text className="chart-axis-text">{center}</Text>
      <Text className="chart-axis-text">{right}</Text>
    </View>
  );
}
