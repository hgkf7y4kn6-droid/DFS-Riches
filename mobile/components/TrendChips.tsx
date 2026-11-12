import { Text, View } from 'react-native';

import { type Better, trendFill, trendLevel } from '@/lib/trend';
import { useColorScheme } from '@/lib/color-scheme';

interface Windows {
  l3?: number | null;
  l6?: number | null;
  l9?: number | null;
}

interface Props {
  windows: Windows | null | undefined;
  /** What each window is compared with: the season average, or this week's number. */
  baseline: number | null | undefined;
  better?: Better;
  format?: (v: number) => string;
  /** Absolute thresholds for the three shades (e.g. spreads in points); default is relative change. */
  steps?: [number, number, number];
  absolute?: boolean;
  /** Shown before the chips, e.g. the team. */
  label?: string;
}

/**
 * L3 / L6 / L9 trailing averages as small conditionally-formatted chips:
 * green when the window is better than the baseline, red when worse, gold
 * when steady (darker = bigger move). A window shows only once that many
 * games have been played this season; nothing renders until one has.
 */
export default function TrendChips({ windows, baseline, better = 'high', format = (v) => v.toFixed(1), steps, absolute, label }: Props) {
  const dark = useColorScheme() === 'dark';
  const shown = (['l3', 'l6', 'l9'] as const).filter((k) => windows?.[k] != null);
  if (!shown.length) return null;
  return (
    <View className="trend-chips">
      {label ? <Text className="trend-chips-label">{label}</Text> : null}
      {shown.map((k) => {
        const v = windows![k]!;
        const level = trendLevel(v, baseline, better, { steps, absolute });
        return (
          <View
            key={k}
            className="trend-chip"
            style={{ backgroundColor: trendFill(level, dark) }}
            accessibilityLabel={`Last ${k.slice(1)} games ${format(v)}, ${level > 0 ? 'improving' : level < 0 ? 'getting worse' : 'steady'}`}>
            <Text className="trend-chip-text">
              <Text className="trend-chip-key">{k.toUpperCase()}</Text> {format(v)}
            </Text>
          </View>
        );
      })}
    </View>
  );
}
