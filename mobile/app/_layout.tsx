import '../global.css';

import {
  PlusJakartaSans_400Regular,
  PlusJakartaSans_500Medium,
  PlusJakartaSans_600SemiBold,
  PlusJakartaSans_700Bold,
  PlusJakartaSans_800ExtraBold,
  useFonts,
} from '@expo-google-fonts/plus-jakarta-sans';
import { ClerkProvider } from '@clerk/expo';
import { tokenCache } from '@clerk/expo/token-cache';
import { DarkTheme, DefaultTheme, Stack, ThemeProvider } from 'expo-router';
import * as SplashScreen from 'expo-splash-screen';
import { StatusBar } from 'expo-status-bar';
import { useEffect } from 'react';
import { Platform, useColorScheme } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { CLERK_PUBLISHABLE_KEY } from '@/constants/config';
import { darkColors, lightColors } from '@/constants/theme';
import { AccountSyncProvider } from '@/lib/account-sync';
import { AnalyticsProvider } from '@/lib/analytics';
import { DfsModelProvider } from '@/lib/dfs-model-context';
import { LeverageProvider } from '@/lib/leverage-context';
import { MatchupsProvider } from '@/lib/matchups-context';
import { PoolTagsProvider } from '@/lib/pool-tags-context';
import { SubmissionsProvider } from '@/lib/submissions-context';
import { WeekProvider } from '@/lib/week-context';

SplashScreen.preventAutoHideAsync();

// Navigation chrome (screen backgrounds behind content, headers) in the
// app's palette, so nothing flashes white in dark mode.
const navTheme = (dark: boolean) => {
  const base = dark ? DarkTheme : DefaultTheme;
  const c = dark ? darkColors : lightColors;
  return {
    ...base,
    colors: { ...base.colors, background: c.background, card: c.card, text: c.foreground, border: c.border, primary: c.primary },
  };
};

export default function RootLayout() {
  const dark = useColorScheme() === 'dark';
  // The font-sans-* classes (tailwind.config.js) name these families.
  const [fontsLoaded, fontError] = useFonts({
    PlusJakartaSans_400Regular,
    PlusJakartaSans_500Medium,
    PlusJakartaSans_600SemiBold,
    PlusJakartaSans_700Bold,
    PlusJakartaSans_800ExtraBold,
  });

  useEffect(() => {
    if (fontsLoaded || fontError) SplashScreen.hideAsync();
  }, [fontsLoaded, fontError]);

  if (!fontsLoaded && !fontError) return null;

  return (
    <ClerkProvider publishableKey={CLERK_PUBLISHABLE_KEY} tokenCache={Platform.OS === 'web' ? undefined : tokenCache}>
      <AnalyticsProvider>
        <SafeAreaProvider>
          <ThemeProvider value={navTheme(dark)}>
            <AccountSyncProvider>
              <SubmissionsProvider>
                <WeekProvider>
                  <DfsModelProvider>
                    <LeverageProvider>
                      <PoolTagsProvider>
                        <MatchupsProvider>
                          <StatusBar style={dark ? 'light' : 'dark'} />
                          <Stack screenOptions={{ headerShown: false }}>
                            <Stack.Screen name="(tabs)" />
                            <Stack.Screen name="sign-in" options={{ presentation: 'modal' }} />
                            <Stack.Screen name="sign-up" options={{ presentation: 'modal' }} />
                          </Stack>
                        </MatchupsProvider>
                      </PoolTagsProvider>
                    </LeverageProvider>
                  </DfsModelProvider>
                </WeekProvider>
              </SubmissionsProvider>
            </AccountSyncProvider>
          </ThemeProvider>
        </SafeAreaProvider>
      </AnalyticsProvider>
    </ClerkProvider>
  );
}
