import { useAuth } from '@clerk/expo';
import { Redirect, Tabs, usePathname } from 'expo-router';
import { ActivityIndicator, Image, Platform, Text, useWindowDimensions, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import IntroTour from '@/components/IntroTour';
import ProfileQuestion from '@/components/ProfileQuestion';
import RememberPlace from '@/components/RememberPlace';
import SessionGuard from '@/components/SessionGuard';
import WhatsNew from '@/components/WhatsNew';
import { HIDDEN_TAB_ROUTES, tabs } from '@/constants/data';
import { FLOATING_TAB_BAR, fonts, useThemeColors } from '@/constants/theme';
import { useAccountSync } from '@/lib/account-sync';

export default function TabLayout() {
  // The tab bar floats above the device's bottom inset (home indicator /
  // gesture bar) on every phone.
  const insets = useSafeAreaInsets();
  const theme = useThemeColors();
  const { master } = useAccountSync();
  const { isLoaded, isSignedIn } = useAuth();
  const pathname = usePathname();
  // Labels as large as their slot allows (up to 11px) so the longest,
  // "Tournaments", fits on narrow phones and when the master-only tab makes six.
  const { width } = useWindowDimensions();
  const visible = tabs.filter((t) => !t.masterOnly || master).length;
  const perTab = (Math.min(width, FLOATING_TAB_BAR.maxWidth + 2 * FLOATING_TAB_BAR.margin) - 2 * FLOATING_TAB_BAR.margin - 2) / visible;
  const labelSize = Math.max(8.5, Math.min(11, Math.floor(((perTab - 2) / 6.3) * 2) / 2));
  // On web, the stylesheet's theme variables (they follow the device's light/dark
  // setting instantly, even on the pre-rendered page); native uses the palette.
  const colors =
    Platform.OS === 'web'
      ? {
          ...theme,
          background: 'var(--color-background)',
          card: 'var(--color-card)',
          border: 'var(--color-border)',
          accentInk: 'var(--color-accent-ink)',
          mutedForeground: 'var(--color-muted-foreground)',
        }
      : theme;

  // The app needs an account: until Clerk knows who this is, a loading
  // screen (also what the pre-rendered web page shows); signed out, the
  // sign-in page (it links to creating an account).
  if (!isLoaded) {
    return (
      <View className="auth-gate">
        <Text className="brand-title">
          <Text className="brand-accent">Riches</Text> Analytics
        </Text>
        <ActivityIndicator className="mt-4" color={theme.accent} />
      </View>
    );
  }
  // Back to this page once they're in.
  if (!isSignedIn) return <Redirect href={{ pathname: '/sign-in', params: pathname && pathname !== '/' ? { next: pathname } : {} }} />;

  return (
    <>
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
          tabBarLabelStyle: { fontSize: labelSize, lineHeight: 14, fontFamily: fonts.semibold, marginTop: 3, marginHorizontal: 0 },
          tabBarIconStyle: { height: 28 },
          tabBarItemStyle: { justifyContent: 'center', paddingVertical: 0, paddingHorizontal: 0 },
        }}>
        {tabs.map((tab) => (
          <Tabs.Screen
            key={tab.id}
            name={tab.name}
            options={{
              title: tab.title,
              ...(tab.masterOnly && !master ? { href: null } : null),
              tabBarIcon: ({ focused }) => (
                <View className={`tabs-pill ${focused ? 'tabs-active' : ''}`}>
                  <Image
                    source={tab.icon}
                    className="tabs-icon"
                    // size-6 is 24px; set here too because react-native-web ignores className sizes on Image
                    style={{ width: 22, height: 22, tintColor: focused ? theme.accentForeground : theme.mutedForeground }}
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
      <IntroTour />
      <ProfileQuestion />
      <RememberPlace />
      <SessionGuard />
      <WhatsNew />
    </>
  );
}
