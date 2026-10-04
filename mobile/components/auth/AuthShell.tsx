import { router } from 'expo-router';
import type { ReactNode } from 'react';
import { KeyboardAvoidingView, Platform, Pressable, ScrollView, Text, TextInput, View } from 'react-native';

import SafeAreaView from '@/components/SafeAreaView';
import { useThemeColors } from '@/constants/theme';

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

export function SubmitButton({ label, onPress, busy }: { label: string; onPress: () => void; busy?: boolean }) {
  return (
    <Pressable className={`btn mt-1 ${busy ? 'opacity-60' : ''}`} onPress={onPress} disabled={busy} accessibilityRole="button">
      <Text className="btn-text">{busy ? 'One moment…' : label}</Text>
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
