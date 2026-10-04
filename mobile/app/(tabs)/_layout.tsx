import { Tabs } from 'expo-router';
import { Image, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { HIDDEN_TAB_ROUTES, tabs } from '@/constants/data';
import { FLOATING_TAB_BAR, fonts, useThemeColors } from '@/constants/theme';

export default function TabLayout() {
  // The tab bar floats above the device's bottom inset (home indicator /
  // gesture bar) on every phone.
  const insets = useSafeAreaInsets();
  const colors = useThemeColors();

  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        sceneStyle: { backgroundColor: colors.background },
        tabBarActiveTintColor: colors.accentInk,
        tabBarInactiveTintColor: colors.mutedForeground,
        tabBarStyle: {
          // Floating: inset from the edges and the bottom, rounded, with a shadow.
          position: 'absolute',
          // Full width less the margins on phones; centered at maxWidth on wider screens
          // (pure layout, so the pre-rendered page already has it right).
          left: FLOATING_TAB_BAR.margin,
          right: FLOATING_TAB_BAR.margin,
          maxWidth: FLOATING_TAB_BAR.maxWidth,
          marginHorizontal: 'auto',
          bottom: insets.bottom + FLOATING_TAB_BAR.gap,
          height: FLOATING_TAB_BAR.height,
          paddingTop: 10,
          paddingBottom: 16,
          borderRadius: FLOATING_TAB_BAR.height / 2,
          borderTopWidth: 1,
          borderWidth: 1,
          borderColor: colors.border,
          borderTopColor: colors.border,
          backgroundColor: colors.card,
          shadowColor: '#000',
          shadowOpacity: 0.18,
          shadowRadius: 16,
          shadowOffset: { width: 0, height: 6 },
          elevation: 10,
        },
        tabBarLabelPosition: 'below-icon',
        tabBarLabelStyle: { fontSize: 10, lineHeight: 13, fontFamily: fonts.semibold, marginTop: 3 },
        tabBarIconStyle: { height: 28 },
        tabBarItemStyle: { justifyContent: 'center', paddingVertical: 0 },
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
                  style={{ width: 22, height: 22, tintColor: focused ? colors.accentForeground : colors.mutedForeground }}
                  resizeMode="contain"
                />
              </View>
            ),
          }}
        />
      ))}
      {HIDDEN_TAB_ROUTES.map((name) => (
        <Tabs.Screen key={name} name={name} options={{ href: null }} />
      ))}
    </Tabs>
  );
}
