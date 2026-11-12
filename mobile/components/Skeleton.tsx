import { useEffect } from 'react';
import { View, type ViewStyle } from 'react-native';
import Animated, { useAnimatedStyle, useSharedValue, withRepeat, withTiming } from 'react-native-reanimated';

import { useThemeColors } from '@/constants/theme';

/** A gently pulsing grey block where content is about to appear (instead of a spinner). */
export function Skeleton({ style }: { style?: ViewStyle }) {
  const colors = useThemeColors();
  const opacity = useSharedValue(0.45);
  useEffect(() => {
    opacity.value = withRepeat(withTiming(1, { duration: 800 }), -1, true);
  }, [opacity]);
  const pulse = useAnimatedStyle(() => ({ opacity: opacity.value }));
  return <Animated.View style={[{ backgroundColor: colors.muted, borderRadius: 6 }, style, pulse]} />;
}

/** Placeholder rows shaped like player rows: a name line, a detail line and a price. */
export function SkeletonRows({ rows = 3 }: { rows?: number }) {
  return (
    <View className="mt-2" accessibilityLabel="Loading" accessibilityRole="progressbar">
      {Array.from({ length: rows }, (_, i) => (
        <View key={i} className="flex-row items-center py-2">
          <View className="flex-1">
            <Skeleton style={{ height: 14, width: '60%' }} />
            <Skeleton style={{ height: 10, width: '40%', marginTop: 6 }} />
          </View>
          <Skeleton style={{ height: 14, width: 56 }} />
        </View>
      ))}
    </View>
  );
}

/** Placeholder cards for a horizontal card list (rankings, games). */
export function SkeletonCards({ count = 2, height = 180 }: { count?: number; height?: number }) {
  return (
    <View className="flex-row gap-3" accessibilityLabel="Loading" accessibilityRole="progressbar">
      {Array.from({ length: count }, (_, i) => (
        <Skeleton key={i} style={{ height, width: 280, borderRadius: 20 }} />
      ))}
    </View>
  );
}
