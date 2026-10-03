import '../global.css';

import {
  PlusJakartaSans_400Regular,
  PlusJakartaSans_500Medium,
  PlusJakartaSans_600SemiBold,
  PlusJakartaSans_700Bold,
  PlusJakartaSans_800ExtraBold,
  useFonts,
} from '@expo-google-fonts/plus-jakarta-sans';
import { DarkTheme, DefaultTheme, Stack, ThemeProvider } from 'expo-router';
import * as SplashScreen from 'expo-splash-screen';
import { StatusBar } from 'expo-status-bar';
import { useEffect } from 'react';
import { useColorScheme } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { darkColors, lightColors } from '@/constants/theme';
import { DfsModelProvider } from '@/lib/dfs-model-context';
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
    <SafeAreaProvider>
      <ThemeProvider value={navTheme(dark)}>
        <SubmissionsProvider>
          <WeekProvider>
            <DfsModelProvider>
              <PoolTagsProvider>
                <MatchupsProvider>
                  <StatusBar style={dark ? 'light' : 'dark'} />
                  <Stack screenOptions={{ headerShown: false }}>
                    <Stack.Screen name="(tabs)" />
                  </Stack>
                </MatchupsProvider>
              </PoolTagsProvider>
            </DfsModelProvider>
          </WeekProvider>
        </SubmissionsProvider>
      </ThemeProvider>
    </SafeAreaProvider>
  );
}
