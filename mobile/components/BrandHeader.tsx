import type { ReactNode } from 'react';
import { Text, View } from 'react-native';

/**
 * The top-left "$DFSRiches" heading every tab shares, with the tab's name as a
 * subheading below it. `right` holds a screen's header action (e.g. Home's +).
 */
export default function BrandHeader({ title, right }: { title: string; right?: ReactNode }) {
  return (
    <View className="brand-header">
      <View className="flex-1">
        <Text className="brand-title" accessibilityRole="header">
          <Text className="brand-accent">$</Text>DFS<Text className="brand-accent">Riches</Text>
        </Text>
        <Text className="brand-subheading">{title}</Text>
      </View>
      {right}
    </View>
  );
}
