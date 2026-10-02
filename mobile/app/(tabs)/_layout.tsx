import { Tabs } from 'expo-router';
import { Image } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { tabs } from '@/constants/data';
import { colors } from '@/constants/theme';

export default function TabLayout() {
  // Pads the tab bar by the device's bottom inset (home indicator / gesture
  // bar) so it sits above it on every phone.
  const insets = useSafeAreaInsets();

  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: colors.accent,
        tabBarInactiveTintColor: colors.muted,
        tabBarStyle: {
          backgroundColor: colors.card,
          borderTopColor: colors.border,
          height: 68 + insets.bottom,
          paddingBottom: insets.bottom + 10,
          paddingTop: 8,
        },
        tabBarLabelStyle: { fontSize: 11, fontWeight: '600' },
      }}>
      {tabs.map((tab) => (
        <Tabs.Screen
          key={tab.id}
          name={tab.name}
          options={{
            title: tab.title,
            tabBarIcon: ({ color, size }) => (
              <Image source={tab.icon} style={{ width: size, height: size, tintColor: color }} resizeMode="contain" />
            ),
          }}
        />
      ))}
    </Tabs>
  );
}
