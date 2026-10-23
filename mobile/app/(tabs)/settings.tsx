import { useAuth, useUser } from '@clerk/expo';
import AsyncStorage from '@react-native-async-storage/async-storage';
import Constants from 'expo-constants';
import * as Updates from 'expo-updates';
import { router } from 'expo-router';
import { useState } from 'react';
import { Alert, Linking, Platform, Pressable, ScrollView, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import AccountCard from '@/components/AccountCard';
import MatchupModeToggle from '@/components/MatchupModeToggle';
import NewsOverrideCard from '@/components/NewsOverrideCard';
import PrefsEditor from '@/components/PrefsEditor';
import BackLink from '@/components/BackLink';
import BrandHeader from '@/components/BrandHeader';
import FeedbackSheet from '@/components/FeedbackSheet';
import { ProSheet } from '@/components/ProLock';
import SafeAreaView from '@/components/SafeAreaView';
import { API_BASE_URL } from '@/constants/config';
import { FLOATING_TAB_BAR } from '@/constants/theme';
import { useAccountSync } from '@/lib/account-sync';
import { track } from '@/lib/analytics';
import { deleteAccount } from '@/lib/api';
import { useDfsModel } from '@/lib/dfs-model-context';
import { useOnboarding } from '@/lib/onboarding-context';
import { useSubmissions } from '@/lib/submissions-context';
import { usePoolTags } from '@/lib/pool-tags-context';
import { useWeek } from '@/lib/week-context';
import { useColorScheme } from '@/lib/color-scheme';

const PLAN_LABEL: Record<Plan, string> = { free: 'Free', pro: 'Pro', admin: 'Admin' };

/** The National Council on Problem Gambling's help line and site (1-800-GAMBLER). */
const HELP_URL = 'https://www.ncpgambling.org/help-treatment/';

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
  const { showIntro, startHereHidden, setStartHereHidden } = useOnboarding();
  const { plan } = useAccountSync();
  const { getToken, signOut } = useAuth();
  const { user } = useUser();
  const [feedbackOpen, setFeedbackOpen] = useState(false);
  const [proOpen, setProOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);

  // Deletes the account and everything stored for it, then this device's copies, then signs out.
  const removeAccount = async () => {
    setDeleting(true);
    try {
      const token = await getToken();
      if (!token) throw new Error('Not signed in');
      const res = await deleteAccount(token);
      if (!res.deleted_account) await user?.delete();
      track('account_deleted');
      const keys = (await AsyncStorage.getAllKeys()).filter((k) => k.startsWith('dfsriches:'));
      await AsyncStorage.multiRemove(keys);
      await signOut().catch(() => {});
      router.replace('/sign-up');
    } catch (e) {
      const msg = `Couldn't delete your account: ${e instanceof Error ? e.message : String(e)}. Try again, or send feedback and we'll do it for you.`;
      if (Platform.OS === 'web') window.alert(msg);
      else Alert.alert('Delete account', msg);
    } finally {
      setDeleting(false);
    }
  };
  const poolChanges = Object.values(pools).reduce((n, tags) => n + Object.keys(tags).length, 0);

  return (
    <SafeAreaView className="flex-1 bg-background" edges={['top', 'left', 'right']}>
      <ScrollView
        showsVerticalScrollIndicator={false}
        contentContainerClassName="screen-content"
        contentContainerStyle={{ paddingBottom: insets.bottom + FLOATING_TAB_BAR.space }}>
        <BrandHeader title="Settings" settings={false} />
        <BackLink />

        <Text className="settings-group-title">Account</Text>
        <AccountCard />
        <NewsOverrideCard />
        <View className="settings-group mt-2">
          <Row
            label="Plan"
            value={`${PLAN_LABEL[plan]}${plan === 'free' ? ' · see what Pro adds ›' : ''}`}
            onPress={plan === 'free' ? () => setProOpen(true) : undefined}
          />
          <Row label="Appearance" value={`${scheme === 'dark' ? 'Dark' : 'Light'} (follows your device)`} last />
        </View>

        <Text className="settings-group-title">Your game</Text>
        <PrefsEditor />

        <Text className="settings-group-title">Help</Text>
        <View className="settings-group mt-0">
          <Row label="Glossary" value="What every term means ›" onPress={() => router.push('/glossary')} />
          <Row label="Show the intro again" value="3 quick screens ›" onPress={showIntro} />
          <Row
            label="Start here card on Home"
            value={startHereHidden ? 'Hidden · tap to show' : 'Showing · tap to hide'}
            onPress={() => setStartHereHidden(!startHereHidden)}
          />
          <Row label="Send feedback" value="Bugs, ideas ›" onPress={() => setFeedbackOpen(true)} />
          <Row label="Play responsibly" value="Help: 1-800-GAMBLER ›" onPress={() => Linking.openURL(HELP_URL)} last />
        </View>

        <Text className="settings-group-title">Matchups</Text>
        <View className="settings-group mt-0 p-4">
          <MatchupModeToggle explained />
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
          <Row label="How we did" value="Our lineups vs results ›" onPress={() => router.push('/results')} />
          <Row label="Classic website" value="Original pages ›" onPress={openClassic} last />
        </View>

        <Text className="settings-group-title">Saved data (synced to your account when signed in)</Text>
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
          />
          <Row
            label={deleting ? 'Deleting your account…' : 'Delete account'}
            value="Account and all its data"
            danger
            onPress={
              deleting
                ? undefined
                : () =>
                    confirm(
                      'Delete your account?',
                      'Your account, saved lineups, contest entries, pool tags and settings are deleted for good. This cannot be undone.',
                      removeAccount,
                    )
            }
            last
          />
        </View>

        <Text className="settings-group-title">About</Text>
        <View className="settings-group mt-0">
          <Row
            label="DFSRiches"
            value={`Version ${Constants.expoConfig?.version ?? '1.0.0'}${
              // An over-the-air update (EAS Update) rather than the JS the build shipped with.
              Updates.isEnabled && !Updates.isEmbeddedLaunch && Updates.createdAt
                ? ` · updated ${Updates.createdAt.toLocaleDateString('en-US', { month: 'numeric', day: 'numeric' })}`
                : ''
            }`}
          />
          <Row label="Data" value="DraftKings, Sleeper, nflverse" />
          <Row label="Weather" value="Open-Meteo.com (CC BY 4.0), National Weather Service" last />
        </View>
      </ScrollView>
      <FeedbackSheet visible={feedbackOpen} onClose={() => setFeedbackOpen(false)} />
      <ProSheet feature="ownership" visible={proOpen} onClose={() => setProOpen(false)} />
    </SafeAreaView>
  );
}
