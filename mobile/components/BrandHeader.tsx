import { router } from 'expo-router';
import type { ReactNode } from 'react';
import { Image, Pressable, Text, View } from 'react-native';

import SlatePill from '@/components/SlatePill';
import WeekPicker from '@/components/WeekPicker';
import icons from '@/constants/icons';
import { useThemeColors } from '@/constants/theme';
import { formatEt } from '@/lib/utils';
import { useWeek } from '@/lib/week-context';

interface Props {
  title: string;
  /** The contest term under a plain-language title (e.g. "Cash games" under "Safe Plays"). */
  term?: string;
  /** Which slate list the header's slate button picks from; false hides it. */
  slate?: 'week' | 'model' | false;
  /** The model's slates, when the screen has them (Safe Plays / Tournaments). */
  modelSlates?: { slate_id: string; label: string }[];
  /** The Settings gear (hidden on Settings itself). */
  settings?: boolean;
  /** Replaces the week / slate / gear controls. */
  right?: ReactNode;
}

/**
 * The top-left "$DFSRiches" heading every tab shares, with the tab's name as a
 * subheading below it. On the right: the season / week picker and the
 * Settings gear, with the selected slate underneath (a screen can pass its
 * own `right` instead).
 */
export default function BrandHeader({ title, term, slate = false, modelSlates, settings = true, right }: Props) {
  const colors = useThemeColors();
  const { offlineSince, refresh } = useWeek();
  return (
    <>
      <View className="brand-header">
        <View className="flex-1">
          <Text className="brand-title" accessibilityRole="header">
            <Text className="brand-accent">$</Text>DFS<Text className="brand-accent">Riches</Text>
          </Text>
          <Text className="brand-subheading">{title}</Text>
          {term ? <Text className="brand-term">{term}</Text> : null}
        </View>
        {right ?? (
          <View className="brand-controls">
            <View className="flex-row items-center gap-2">
              <WeekPicker />
              {settings ? (
                <Pressable
                  className="gear-btn"
                  onPress={() => router.push('/settings')}
                  accessibilityRole="button"
                  accessibilityLabel="Settings"
                  hitSlop={6}>
                  <Image source={icons.settings} style={{ width: 20, height: 20, tintColor: colors.foreground }} resizeMode="contain" />
                </Pressable>
              ) : null}
            </View>
            {slate ? <SlatePill scope={slate} slates={modelSlates} /> : null}
          </View>
        )}
      </View>
      {/* Offline: the week's data is the copy saved on this device. */}
      {offlineSince ? (
        <Pressable className="offline-banner" onPress={refresh} accessibilityRole="button" accessibilityLabel="Offline. Try again">
          <Text className="offline-banner-text">Offline · showing data from {formatEt(offlineSince)} · Tap to retry</Text>
        </Pressable>
      ) : null}
    </>
  );
}
