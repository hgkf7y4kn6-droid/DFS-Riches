import { useClerk } from '@clerk/expo';
import { router } from 'expo-router';
import { type ReactNode, useEffect, useState } from 'react';
import { KeyboardAvoidingView, Platform, Pressable, ScrollView, Text, TextInput, View } from 'react-native';

import SafeAreaView from '@/components/SafeAreaView';
import { useThemeColors } from '@/constants/theme';
import { track } from '@/lib/analytics';
import { clerkDiagnostics } from '@/lib/clerk-diagnostics';

/** The sign-in / sign-up page frame: brand mark, title, subtitle, form, footer link. */
export function AuthShell({ title, subtitle, children, footer }: { title: string; subtitle: string; children: ReactNode; footer?: ReactNode }) {
  return (
    <SafeAreaView className="auth-safe-area" edges={['top', 'left', 'right', 'bottom']}>
      <KeyboardAvoidingView className="auth-screen" behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <ScrollView className="auth-scroll" contentContainerClassName="auth-content" keyboardShouldPersistTaps="handled">
          <Pressable onPress={() => (router.canGoBack() ? router.back() : router.replace('/'))} accessibilityRole="button" className="mb-4 self-start py-1">
            <Text className="link-text text-sm">‹ Back</Text>
          </Pressable>
          <View className="auth-brand-block">
            <View className="auth-logo-wrap">
              <View className="auth-logo-mark">
                <Text className="auth-logo-mark-text">$</Text>
              </View>
              <View>
                <Text className="brand-title">
                  <Text className="brand-accent">$</Text>DFS<Text className="brand-accent">Riches</Text>
                </Text>
                <Text className="auth-wordmark-sub">Your lineups, entries and pool on every device</Text>
              </View>
            </View>
            <Text className="auth-title">{title}</Text>
            <Text className="auth-subtitle text-muted-foreground">{subtitle}</Text>
          </View>
          <View className="mt-6 w-full max-w-[420px] self-center">{children}</View>
          {footer ? <View className="mt-5 items-center">{footer}</View> : null}
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

export function Field(props: {
  label: string;
  value: string;
  onChangeText: (t: string) => void;
  secure?: boolean;
  keyboardType?: 'email-address' | 'number-pad' | 'phone-pad' | 'default';
  autoComplete?: 'email' | 'current-password' | 'new-password' | 'one-time-code';
  placeholder?: string;
}) {
  const colors = useThemeColors();
  return (
    <View className="input-field">
      <Text className="input-label">{props.label}</Text>
      <TextInput
        className="input"
        value={props.value}
        onChangeText={props.onChangeText}
        secureTextEntry={props.secure}
        keyboardType={props.keyboardType ?? 'default'}
        autoComplete={props.autoComplete}
        autoCapitalize="none"
        autoCorrect={false}
        placeholder={props.placeholder}
        placeholderTextColor={colors.mutedForeground}
        accessibilityLabel={props.label}
      />
    </View>
  );
}

/** `ready` false (sign-in service still loading): shown as "Connecting…" rather than a button that ignores taps. */
export function SubmitButton({ label, onPress, busy, ready = true }: { label: string; onPress: () => void; busy?: boolean; ready?: boolean }) {
  const waiting = busy || !ready;
  return (
    <Pressable className={`btn mt-1 ${waiting ? 'opacity-60' : ''}`} onPress={onPress} disabled={waiting} accessibilityRole="button" aria-busy={waiting}>
      <Text className="btn-text">{busy ? 'One moment…' : !ready ? 'Connecting…' : label}</Text>
    </Pressable>
  );
}

export function FormError({ message }: { message: string | null }) {
  return message ? <Text className="mb-3 text-sm font-sans-medium text-danger">{message}</Text> : null;
}

/** Clerk's own error text when it has one. */
export function clerkMessage(e: unknown): string {
  const err = e as { errors?: { longMessage?: string; message?: string }[]; message?: string };
  return err?.errors?.[0]?.longMessage ?? err?.errors?.[0]?.message ?? err?.message ?? 'Something went wrong. Try again.';
}

const SLOW_MS = 12000;

/** A note when the sign-in service hasn't loaded after a while (offline, or blocked by a content blocker). */
export function useSlowLoadNotice(loaded: boolean): string | null {
  const clerk = useClerk() as { status?: string };
  const [detail, setDetail] = useState<string | null>(null);
  useEffect(() => {
    if (loaded) return;
    const t = setTimeout(() => {
      // Record why (script blocked, script error, Clerk error) so it can be fixed.
      const d = clerkDiagnostics(clerk.status);
      track('sign_in_service_slow', d);
      setDetail(`status ${d.status} · ${d.clerk_global ?? ''} · scripts: ${d.scripts ?? ''} · errors: ${d.errors ?? ''}`);
    }, SLOW_MS);
    return () => clearTimeout(t);
  }, [loaded, clerk]);
  return detail && !loaded
    ? `Still connecting to the sign-in service. Check your connection, or turn off any content blocker for this site, then reload. (Details: ${detail})`
    : null;
}
