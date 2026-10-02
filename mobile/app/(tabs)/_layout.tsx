import { Tabs } from 'expo-router';
import { Image, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { tabs } from '@/constants/data';
import { fonts, useThemeColors } from '@/constants/theme';

export default function TabLayout() {
  // Pads the tab bar by the device's bottom inset (home indicator / gesture
  // bar) so it sits above it on every phone.
  const insets = useSafeAreaInsets();
  const colors = useThemeColors();

  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        sceneStyle: { backgroundColor: colors.background },
        tabBarActiveTintColor: colors.accent,
        tabBarInactiveTintColor: colors.mutedForeground,
        tabBarStyle: {
          backgroundColor: colors.card,
          borderTopColor: colors.border,
          height: 78 + insets.bottom,
          paddingBottom: insets.bottom + 10,
          paddingTop: 8,
        },
        tabBarLabelStyle: { fontSize: 11, fontFamily: fonts.semibold, marginTop: 4 },
        tabBarIconStyle: { height: 32 },
      }}>
      {tabs.map((tab) => (
        <Tabs.Screen
          key={tab.id}
          name={tab.name}
          options={{
            title: tab.title,
            tabBarIcon: ({ focused }) => (
              <View className={`tabs-pill ${focused ? 'tabs-active' : ''}`}>
                <Image
                  source={tab.icon}
                  className="tabs-icon"
                  // size-6 is 24px; set here too because react-native-web ignores className sizes on Image
                  style={{ width: 24, height: 24, tintColor: focused ? colors.accentForeground : colors.mutedForeground }}
                  resizeMode="contain"
                />
              </View>
            ),
          }}
        />
      ))}
    </Tabs>
  );
}
