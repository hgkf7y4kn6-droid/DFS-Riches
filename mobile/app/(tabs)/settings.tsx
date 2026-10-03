import Constants from 'expo-constants';
import { router } from 'expo-router';
import { Alert, Linking, Platform, Pressable, ScrollView, Text, useColorScheme, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import BrandHeader from '@/components/BrandHeader';
import SafeAreaView from '@/components/SafeAreaView';
import { API_BASE_URL } from '@/constants/config';
import { HOME_USER } from '@/constants/data';
import { FLOATING_TAB_BAR } from '@/constants/theme';
import { useDfsModel } from '@/lib/dfs-model-context';
import { useSubmissions } from '@/lib/submissions-context';
import { usePoolTags } from '@/lib/pool-tags-context';
import { useWeek } from '@/lib/week-context';

/** Asks before destructive actions (Alert on phones; confirm() on web, where Alert is a no-op). */
function confirm(title: string, message: string, onConfirm: () => void) {
  if (Platform.OS === 'web') {
    if (window.confirm(`${title}\n\n${message}`)) onConfirm();
    return;
  }
  Alert.alert(title, message, [
    { text: 'Cancel', style: 'cancel' },
    { text: 'Delete', style: 'destructive', onPress: onConfirm },
  ]);
}

function Row({ label, value, onPress, danger, last }: { label: string; value?: string; onPress?: () => void; danger?: boolean; last?: boolean }) {
  const body = (
    <>
      <Text className={danger ? 'settings-danger' : 'settings-label'}>{label}</Text>
      {value ? (
        <Text className="settings-value" numberOfLines={1}>
          {value}
        </Text>
      ) : null}
    </>
  );
  const cls = `settings-row ${last ? 'settings-row-last' : ''}`;
  return onPress ? (
    <Pressable className={cls} onPress={onPress} accessibilityRole="button">
      {body}
    </Pressable>
  ) : (
    <View className={cls}>{body}</View>
  );
}

/** The original website pages, now under /classic on the same server. */
function openClassic() {
  if (Platform.OS === 'web') window.location.assign('/classic');
  else Linking.openURL(`${API_BASE_URL}/classic`);
}

export default function SettingsScreen() {
  const insets = useSafeAreaInsets();
  const scheme = useColorScheme();
  const { season, week, refresh, clearSavedLineups } = useWeek();
  const { refresh: refreshModel } = useDfsModel();
  const { submissions, clear } = useSubmissions();
  const { pools, clearAll: clearPoolTags } = usePoolTags();
  const poolChanges = Object.values(pools).reduce((n, tags) => n + Object.keys(tags).length, 0);

  return (
    <SafeAreaView className="flex-1 bg-background" edges={['top', 'left', 'right']}>
      <ScrollView
        showsVerticalScrollIndicator={false}
        contentContainerClassName="screen-content"
        contentContainerStyle={{ paddingBottom: insets.bottom + FLOATING_TAB_BAR.space }}>
        <BrandHeader title="Settings" />

        <Text className="settings-group-title">Account</Text>
        <View className="settings-group mt-0">
          <Row label="Name" value={HOME_USER.name} />
          <Row label="Appearance" value={`${scheme === 'dark' ? 'Dark' : 'Light'} (follows your device)`} last />
        </View>

        <Text className="settings-group-title">Data</Text>
        <View className="settings-group mt-0">
          <Row label="Season / week" value={season && week ? `${season} · Week ${week}` : 'Loading'} />
          <Row label="Server" value={API_BASE_URL ? API_BASE_URL.replace(/^https?:\/\//, '') : 'This website'} />
          <Row
            label="Refresh everything"
            value="Schedule, slates, model"
            onPress={() => {
              refresh();
              refreshModel();
            }}
            last
          />
        </View>

        <Text className="settings-group-title">More</Text>
        <View className="settings-group mt-0">
          <Row label="Lineup builder" value="All slates ›" onPress={() => router.push('/lineups')} />
          <Row label="Lines & Performance" value="Every game ›" onPress={() => router.push('/lines')} />
          <Row label="Classic website" value="Original pages ›" onPress={openClassic} last />
        </View>

        <Text className="settings-group-title">Saved on this device</Text>
        <View className="settings-group mt-0">
          <Row
            label="Clear saved lineups"
            danger
            onPress={() => confirm('Clear saved lineups?', 'Every lineup you saved in the builder will be deleted.', clearSavedLineups)}
          />
          <Row
            label="Reset my pool tags"
            value={`${poolChanges} set`}
            danger
            onPress={() => confirm('Reset pool tags?', 'Your Prioritize / Neutral / Fade calls go back to the model\'s tags.', clearPoolTags)}
          />
          <Row
            label="Clear contest entries"
            value={`${submissions.length} logged`}
            danger
            onPress={() => confirm('Clear contest entries?', 'Your balance card and profit/loss history will reset.', clear)}
            last
          />
        </View>

        <Text className="settings-group-title">About</Text>
        <View className="settings-group mt-0">
          <Row label="DFSRiches" value={`Version ${Constants.expoConfig?.version ?? '1.0.0'}`} />
          <Row label="Data" value="DraftKings, Sleeper, nflverse" last />
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}
