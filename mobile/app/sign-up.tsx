import { useSignUp } from '@clerk/expo/legacy';
import { Link, router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { Platform, Pressable, Text, View } from 'react-native';

import { AuthShell, clerkMessage, Field, FormError, SubmitButton, useSlowLoadNotice } from '@/components/auth/AuthShell';
import { track } from '@/lib/analytics';
import { safeNext } from '@/lib/session';

type Step = 'details' | 'more' | 'email_code' | 'phone_code';
type Extra = 'first_name' | 'last_name' | 'password' | 'phone_number';
type SignUpResult = { status: string | null; createdSessionId: string | null; unverifiedFields: string[]; missingFields: string[] };

const EXTRA_LABEL: Record<Extra, string> = { first_name: 'First name', last_name: 'Last name', password: 'Password', phone_number: 'Mobile number' };
const EXTRAS = Object.keys(EXTRA_LABEL) as Extra[];

/**
 * Clerk sign-up in as few steps as the Clerk app allows: email and username
 * (and an 18+ confirmation), then the code emailed to verify it. Anything
 * else the Clerk app still requires (a password, a name, a phone number) is
 * asked for afterwards, only if it's required.
 */
export default function SignUpScreen() {
  const { isLoaded, signUp, setActive } = useSignUp();
  const slowNotice = useSlowLoadNotice(isLoaded);
  const { next: nextParam } = useLocalSearchParams<{ next?: string }>();
  const [form, setForm] = useState({ email: '', username: '', first_name: '', last_name: '', password: '', phone_number: '' });
  const [adult, setAdult] = useState(false);
  const [missing, setMissing] = useState<Extra[]>([]);
  const [code, setCode] = useState('');
  const [step, setStep] = useState<Step>('details');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const set = (k: keyof typeof form) => (v: string) => setForm((f) => ({ ...f, [k]: v }));

  const done = async (sessionId: string | null) => {
    await setActive!({ session: sessionId });
    track('signed_up');
    router.replace(safeNext(nextParam));
  };

  const phone = () => {
    const p = form.phone_number.trim();
    return p ? (p.startsWith('+') ? p : `+1${p.replace(/\D/g, '')}`) : undefined;
  };

  // After each step: finish, verify the email, ask for what's still required, or verify the phone.
  const advance = async (res: SignUpResult) => {
    setCode('');
    if (res.status === 'complete') return done(res.createdSessionId);
    if (res.unverifiedFields.includes('email_address')) {
      await signUp!.prepareEmailAddressVerification({ strategy: 'email_code' });
      return setStep('email_code');
    }
    const extras = EXTRAS.filter((f) => res.missingFields.includes(f));
    if (extras.length) {
      setMissing(extras);
      return setStep('more');
    }
    if (res.unverifiedFields.includes('phone_number')) {
      await signUp!.preparePhoneNumberVerification({ strategy: 'phone_code' });
      return setStep('phone_code');
    }
    setError(`Your account needs another step this app doesn't support yet (${res.missingFields.join(', ') || res.status}).`);
  };

  const submit = async () => {
    if (!isLoaded || busy) return;
    setError(null);
    if (step === 'details') {
      if (!form.email.trim() || !form.username.trim()) return setError('Enter your email and pick a username.');
      if (!adult) return setError('Please confirm you are 18 or older (21+ where your state requires it).');
    }
    setBusy(true);
    try {
      if (step === 'details') {
        await advance(
          (await signUp.create({
            emailAddress: form.email.trim(),
            username: form.username.trim(),
            unsafeMetadata: { age_confirmed_at: new Date().toISOString() },
          })) as SignUpResult,
        );
      } else if (step === 'email_code') {
        await advance((await signUp.attemptEmailAddressVerification({ code: code.trim() })) as SignUpResult);
      } else if (step === 'phone_code') {
        await advance((await signUp.attemptPhoneNumberVerification({ code: code.trim() })) as SignUpResult);
      } else {
        await advance(
          (await signUp.update({
            ...(missing.includes('first_name') ? { firstName: form.first_name.trim() } : {}),
            ...(missing.includes('last_name') ? { lastName: form.last_name.trim() } : {}),
            ...(missing.includes('password') ? { password: form.password } : {}),
            ...(missing.includes('phone_number') ? { phoneNumber: phone() } : {}),
          })) as SignUpResult,
        );
      }
    } catch (e) {
      setError(clerkMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const coding = step === 'email_code' || step === 'phone_code';
  return (
    <AuthShell
      title={step === 'email_code' ? 'Check your email' : step === 'phone_code' ? 'Check your phone' : step === 'more' ? 'Almost done' : 'Create your free account'}
      subtitle={
        step === 'email_code'
          ? `Enter the code sent to ${form.email.trim()}.`
          : step === 'phone_code'
            ? `Enter the code texted to ${form.phone_number.trim()}.`
            : step === 'more'
              ? 'One more thing for your account.'
              : 'Just an email and a username. Your lineups, entries and settings follow you to every device.'
      }
      footer={
        <Text className="text-sm font-sans-medium text-muted-foreground">
          Already have an account?{' '}
          <Link href={{ pathname: '/sign-in', params: nextParam ? { next: nextParam } : {} }} replace>
            <Text className="link-text text-sm">Sign in</Text>
          </Link>
        </Text>
      }>
      <FormError message={error ?? slowNotice} />
      {coding ? (
        <Field label="Verification code" value={code} onChangeText={setCode} keyboardType="number-pad" autoComplete="one-time-code" />
      ) : step === 'more' ? (
        missing.map((f) => (
          <Field
            key={f}
            label={EXTRA_LABEL[f]}
            value={form[f]}
            onChangeText={set(f)}
            secure={f === 'password'}
            keyboardType={f === 'phone_number' ? 'phone-pad' : 'default'}
            autoComplete={f === 'password' ? 'new-password' : undefined}
            placeholder={f === 'phone_number' ? '(555) 555-0100' : undefined}
          />
        ))
      ) : (
        <>
          <Field label="Email" value={form.email} onChangeText={set('email')} keyboardType="email-address" autoComplete="email" placeholder="you@example.com" />
          <Field label="Username" value={form.username} onChangeText={set('username')} placeholder="How we'll greet you" />
          <Pressable className="check-row" onPress={() => setAdult((a) => !a)} accessibilityRole="checkbox" aria-checked={adult}>
            <View className={`check-box ${adult ? 'check-box-on' : ''}`}>{adult ? <Text className="check-mark">✓</Text> : null}</View>
            <Text className="check-label">I&apos;m 18 or older (21+ where my state requires it).</Text>
          </Pressable>
        </>
      )}
      {/* Clerk's bot protection (CAPTCHA) renders here on the web. */}
      {Platform.OS === 'web' && step === 'details' ? <View nativeID="clerk-captcha" className="mb-2" /> : null}
      <SubmitButton label={coding ? 'Verify and continue' : step === 'more' ? 'Finish' : 'Create account'} onPress={submit} busy={busy} ready={isLoaded} />
    </AuthShell>
  );
}
