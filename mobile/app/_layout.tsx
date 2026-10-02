import '../global.css';

import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { WeekProvider } from '@/lib/week-context';

export default function RootLayout() {
  return (
    <SafeAreaProvider>
      <WeekProvider>
        <StatusBar style="dark" />
        <Stack screenOptions={{ headerShown: false }}>
          <Stack.Screen name="(tabs)" />
        </Stack>
      </WeekProvider>
    </SafeAreaProvider>
  );
}
