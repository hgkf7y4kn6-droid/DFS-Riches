import { useState, type ReactNode } from 'react';
import { Modal, Pressable, Text, View } from 'react-native';

import { useAccountSync } from '@/lib/account-sync';
import { track } from '@/lib/analytics';

const FEATURE_LABEL: Record<ProFeature, string> = {
  optimal: 'Model lineups',
  ownership: 'Expected ownership',
  leverage: 'Leverage',
  multiple_lineups: 'Multiple lineups',
  big_picture: 'The Big Picture',
  alerts: 'Lineup alerts',
  props: 'Player props',
  competition: 'Weekly Pro Picks',
};

/** The sheet behind "Unlock with Pro": what Pro adds. Checkout comes with billing; until then it counts interest. */
export function ProSheet({ feature, visible, onClose }: { feature: ProFeature; visible: boolean; onClose: () => void }) {
  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <Pressable className="week-backdrop" onPress={onClose} accessibilityRole="button" accessibilityLabel="Close">
        <Pressable className="week-sheet intro-sheet" onPress={() => {}}>
          <Text className="intro-kicker">Riches Analytics Pro</Text>
          <Text className="intro-title">{FEATURE_LABEL[feature]} is part of Pro</Text>
          <Text className="intro-text">Pro adds what the field doesn&apos;t see:</Text>
          <Text className="intro-text">• Model lineups (Safe and stacked Tournament), and Build for me</Text>
          <Text className="intro-text">• Expected ownership for cash and tournament fields</Text>
          <Text className="intro-text">• Leverage: who the crowd is under- and over-playing</Text>
          <Text className="intro-text">• Up to 5 lineups per slate, and alerts when a player in one is ruled out</Text>
          <Text className="intro-text">• Player props: median yards and catches, and the chance he reaches each ladder rung</Text>
          <Text className="intro-text">• Weekly Pro Picks: rank the Sunday Main&apos;s top scorers against other Pro users</Text>
          <Text className="intro-text">• The Big Picture research desk</Text>
          <Text className="caption mt-2">Pro sign-ups open soon. We&apos;ll let you know in the app.</Text>
          <Pressable className="btn mt-4" onPress={onClose} accessibilityRole="button">
            <Text className="btn-text">Got it</Text>
          </Pressable>
        </Pressable>
      </Pressable>
    </Modal>
  );
}

/**
 * A locked Pro feature for a free account: a faded preview with "Unlock
 * with Pro" on top, instead of hiding it. Shows the feature as-is for Pro
 * and admin accounts, and while the feature isn't locked (accounts.gated_features).
 */
export default function ProLock({
  feature,
  children,
  minHeight = 160,
  preview,
}: {
  feature: ProFeature;
  children: ReactNode;
  minHeight?: number;
  /** Shown faded instead of the children when locked (when rendering them would load the locked data). */
  preview?: ReactNode;
}) {
  const { locked } = useAccountSync();
  const [open, setOpen] = useState(false);
  if (!locked(feature)) return <>{children}</>;
  return (
    <View className="pro-lock" style={{ minHeight }}>
      <View pointerEvents="none" style={{ opacity: 0.18, maxHeight: 360, overflow: 'hidden' }} aria-hidden>
        {preview ?? children}
      </View>
      <View className="pro-lock-overlay">
        <Text className="pro-lock-title">{FEATURE_LABEL[feature]}</Text>
        <Pressable
          className="btn-accent mt-2 px-6"
          onPress={() => {
            track('pro_unlock_tapped', { feature });
            setOpen(true);
          }}
          accessibilityRole="button">
          <Text className="btn-text">Unlock with Pro</Text>
        </Pressable>
      </View>
      <ProSheet feature={feature} visible={open} onClose={() => setOpen(false)} />
    </View>
  );
}
