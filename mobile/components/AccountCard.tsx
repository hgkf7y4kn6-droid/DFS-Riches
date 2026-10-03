import { useAuth, useUser } from '@clerk/expo';
import { router } from 'expo-router';
import { Pressable, Text, View } from 'react-native';

import { useAccountSync } from '@/lib/account-sync';
import { formatEt } from '@/lib/utils';

const STATUS: Record<string, string> = {
  loading: 'Syncing…',
  saving: 'Saving…',
  synced: 'Synced',
  offline: 'Sync not set up on the server yet',
  error: 'Sync problem',
};
const STORAGE: Record<string, string> = { neon: 'Neon database', clerk: 'Clerk account storage', none: 'not configured' };

/**
 * Sign in / create account when signed out; when signed in, who you are,
 * whether this is the master account, and the sync status of your saved data.
 */
export default function AccountCard() {
  const { isSignedIn, signOut } = useAuth();
  const { user } = useUser();
  const sync = useAccountSync();

  if (!isSignedIn) {
    return (
      <View className="account-card">
        <Text className="account-title">Sync across your devices</Text>
        <Text className="account-text">
          Sign in to keep your saved lineups, contest entries, pool tags and settings on your account -- they follow you to any
          phone or browser.
        </Text>
        <View className="mt-3 flex-row gap-2">
          <Pressable className="btn flex-1" onPress={() => router.push('/sign-in')} accessibilityRole="button">
            <Text className="btn-text">Sign in</Text>
          </Pressable>
          <Pressable className="btn-outline flex-1 justify-center" onPress={() => router.push('/sign-up')} accessibilityRole="button">
            <Text className="btn-outline-text">Create account</Text>
          </Pressable>
        </View>
      </View>
    );
  }

  const email = user?.primaryEmailAddress?.emailAddress ?? 'Signed in';
  const initials = (user?.firstName?.[0] ?? email[0] ?? '?').toUpperCase();
  return (
    <View className="account-card">
      <View className="flex-row items-center">
        <View className="account-avatar">
          <Text className="account-avatar-text">{initials}</Text>
        </View>
        <View className="ml-3 flex-1">
          <Text className="account-title" numberOfLines={1}>
            {user?.fullName || email}
          </Text>
          <Text className="account-text mt-0" numberOfLines={1}>
            {email}
          </Text>
        </View>
        {sync.master ? (
          <View className="account-master">
            <Text className="account-master-text">Master</Text>
          </View>
        ) : null}
      </View>
      <Text className={`account-sync ${sync.status === 'error' ? 'text-danger' : ''}`}>
        {STATUS[sync.status] ?? ''}
        {sync.status === 'synced' && sync.lastSynced ? ` ${formatEt(sync.lastSynced)}` : ''}
        {sync.storage && sync.status !== 'offline' ? ` · ${STORAGE[sync.storage]}` : ''}
        {sync.error && sync.status === 'error' ? ` · ${sync.error}` : ''}
      </Text>
      {sync.master ? <Text className="account-text">Master account: every week of your data is kept, nothing is trimmed.</Text> : null}
      <View className="mt-3 flex-row gap-2">
        <Pressable className="btn-outline flex-1 justify-center" onPress={sync.refresh} accessibilityRole="button">
          <Text className="btn-outline-text">Sync now</Text>
        </Pressable>
        <Pressable className="btn-outline flex-1 justify-center" onPress={() => signOut()} accessibilityRole="button">
          <Text className="btn-outline-text">Sign out</Text>
        </Pressable>
      </View>
    </View>
  );
}
