import { router } from 'expo-router';
import { useState } from 'react';
import type { ReactNode } from 'react';
import { Image, Pressable, Text, View } from 'react-native';

import SlatePill, { useSlateSummary } from '@/components/SlatePill';
import WeekPicker from '@/components/WeekPicker';
import icons from '@/constants/icons';
import { useThemeColors } from '@/constants/theme';
import { formatEt } from '@/lib/utils';
import { useWeek } from '@/lib/week-context';

interface Props {
  title: string;
  /** The contest term under a plain-language title (e.g. "Cash games" under "Safe Plays"). */
  term?: string;
  /** Which slate list the header's slate picker uses; false hides it. */
  slate?: 'week' | 'model' | false;
  /** The model's slates, when the screen has them (Safe Plays / Tournaments). */
  modelSlates?: { slate_id: string; label: string }[];
  /** The Settings shortcut (hidden on Settings itself). */
  settings?: boolean;
  /** Replaces the week / slate / settings control. */
  right?: ReactNode;
}

/**
 * The "Riches Analytics" heading every tab shares, with the tab's name below it.
 * On the title's line: one condensed control showing the week and slate
 * ("Wk 8 · Sunday Main ▾"). Tapping it opens a card with the week and slate
 * pickers and the Settings shortcut; tapping again folds it away.
 */
export default function BrandHeader({ title, term, slate = false, modelSlates, settings = true, right }: Props) {
  const colors = useThemeColors();
  const { offlineSince, refresh, season, week, current } = useWeek();
  const { current: slateNow } = useSlateSummary(slate || 'week', modelSlates);
  const [open, setOpen] = useState(false);
  const viewingCurrent = !current || (current.season === season && current.week === week);
  const weekText = season && week ? `${current && season !== current.season ? `${season} ` : ''}Wk ${week}` : null;
  const slateText = slate ? slateNow?.title : null;
  return (
    <>
      <View className="brand-top">
        <Text className="brand-title flex-1" numberOfLines={1} accessibilityRole="header">
          <Text className="brand-accent">Riches</Text> Analytics
        </Text>
        {right ??
          (weekText ? (
            <Pressable
              className={`brand-chip ${viewingCurrent ? '' : 'picker-card-past'}`}
              onPress={() => setOpen((o) => !o)}
              accessibilityRole="button"
              aria-expanded={open}
              accessibilityLabel={`${weekText}${slateText ? `, ${slateText}` : ''}. ${open ? 'Hide' : 'Show'} week, slate and settings`}>
              <View>
                <Text className={`brand-chip-week ${viewingCurrent ? '' : 'text-accent-ink'}`} numberOfLines={1}>
                  {weekText}
                </Text>
                {slateText ? (
                  <Text className="brand-chip-slate" numberOfLines={1}>
                    {slateText}
                  </Text>
                ) : null}
              </View>
              <Text className="picker-seg-caret">{open ? '▴' : '▾'}</Text>
            </Pressable>
          ) : null)}
      </View>
      {!right && open ? (
        <View className="brand-panel">
          <View className="brand-panel-row">
            <Text className="brand-panel-label">Week</Text>
            <View className="h-10 flex-row items-center">
              <WeekPicker />
            </View>
          </View>
          {slate ? (
            <View className="brand-panel-row">
              <Text className="brand-panel-label">Slate</Text>
              <View className="h-10 flex-row items-center">
                <SlatePill scope={slate} slates={modelSlates} />
              </View>
            </View>
          ) : null}
          {settings ? (
            <Pressable
              className="brand-panel-row"
              onPress={() => {
                setOpen(false);
                router.push('/settings');
              }}
              accessibilityRole="button"
              accessibilityLabel="Settings">
              <Text className="brand-panel-label">Settings</Text>
              <Image source={icons.settings} style={{ width: 20, height: 20, tintColor: colors.foreground }} resizeMode="contain" />
            </Pressable>
          ) : null}
        </View>
      ) : null}
      <View className="brand-header">
        <View className="flex-1 pr-2">
          <Text className="brand-subheading">{title}</Text>
          {term ? <Text className="brand-term">{term}</Text> : null}
        </View>
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
