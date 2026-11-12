import { useState } from 'react';
import { Modal, Pressable, Text, View } from 'react-native';

import { track } from '@/lib/analytics';
import { useOnboarding } from '@/lib/onboarding-context';
import { FOCUS_OPTIONS, SPEND_OPTIONS, type ContestFocus, type WeeklySpend, usePrefs } from '@/lib/prefs-context';

function Chip({ label, hint, active, onPress }: { label: string; hint?: string; active: boolean; onPress: () => void }) {
  return (
    <Pressable className={`choice ${active ? 'choice-active' : ''}`} onPress={onPress} accessibilityRole="radio" aria-checked={active}>
      <Text className={`choice-label ${active ? 'choice-label-active' : ''}`}>{label}</Text>
      {hint ? <Text className={`choice-hint ${active ? 'choice-hint-active' : ''}`}>{hint}</Text> : null}
    </Pressable>
  );
}

/**
 * "What do you play?" -- asked once after sign-up (after the intro), saved
 * to the account (lib/prefs-context.tsx). Home, the lineup builder and Best
 * contests follow the answer; Settings changes it.
 */
export default function ProfileQuestion() {
  const { prefs, settled, asked, update } = usePrefs();
  const { introOpen, whatsNewOpen } = useOnboarding();
  const [focus, setFocus] = useState<ContestFocus | undefined>(prefs.focus);
  const [spend, setSpend] = useState<WeeklySpend | undefined>(prefs.spend);
  const visible = settled && !asked && !introOpen && !whatsNewOpen;

  const finish = (skipped: boolean) => {
    track(skipped ? 'profile_question_skipped' : 'profile_question_answered', { focus: focus ?? 'none', spend: spend ?? 'none' });
    update({ ...(skipped ? {} : { focus, spend }), askedAt: new Date().toISOString() });
  };

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={() => finish(true)}>
      <View className="week-backdrop">
        <View className="week-sheet intro-sheet">
          <Text className="intro-kicker">One quick question</Text>
          <Text className="intro-title">What do you play?</Text>
          <Text className="intro-text">We&apos;ll lead with the plays and contests that fit. Change it any time in Settings.</Text>
          <View className="choice-row">
            {FOCUS_OPTIONS.map((o) => (
              <Chip key={o.id} label={o.label} hint={o.hint} active={focus === o.id} onPress={() => setFocus(o.id)} />
            ))}
          </View>
          <Text className="input-label mt-3">Roughly how much do you enter per week?</Text>
          <View className="flex-row flex-wrap">
            {SPEND_OPTIONS.map((o) => {
              const active = spend === o.id;
              return (
                <Pressable
                  key={o.id}
                  className={`filter-chip mb-2 ${active ? 'filter-chip-active' : ''}`}
                  onPress={() => setSpend(o.id)}
                  accessibilityRole="radio"
                  aria-checked={active}>
                  <Text className={`filter-chip-text ${active ? 'filter-chip-text-active' : ''}`}>{o.label}</Text>
                </Pressable>
              );
            })}
          </View>
          <View className="mt-4 flex-row gap-2">
            <Pressable className="btn-outline flex-1 justify-center" onPress={() => finish(true)} accessibilityRole="button">
              <Text className="btn-outline-text">Skip</Text>
            </Pressable>
            <Pressable className={`btn flex-1 ${focus ? '' : 'opacity-60'}`} onPress={() => focus && finish(false)} disabled={!focus} accessibilityRole="button">
              <Text className="btn-text">Save</Text>
            </Pressable>
          </View>
        </View>
      </View>
    </Modal>
  );
}
