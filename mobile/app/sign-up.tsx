import { useSignUp } from '@clerk/expo/legacy';
import { Link, router } from 'expo-router';
import { useState } from 'react';
import { Platform, Text, View } from 'react-native';

import { AuthShell, clerkMessage, Field, FormError, SubmitButton } from '@/components/auth/AuthShell';

type Step = 'details' | 'email_code' | 'phone_code';

/**
 * Clerk sign-up: name, username, email, phone and password (what this Clerk
 * app requires), then the codes Clerk sends to verify the email and phone.
 */
export default function SignUpScreen() {
  const { isLoaded, signUp, setActive } = useSignUp();
  const [form, setForm] = useState({ firstName: '', lastName: '', username: '', email: '', phone: '', password: '' });
  const [code, setCode] = useState('');
  const [step, setStep] = useState<Step>('details');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const set = (k: keyof typeof form) => (v: string) => setForm((f) => ({ ...f, [k]: v }));

  const done = async (sessionId: string | null) => {
    await setActive!({ session: sessionId });
    if (router.canGoBack()) router.back();
    else router.replace('/settings');
  };

  // After a step: finish, or move on to whichever verification Clerk still needs.
  const next = async (res: { status: string | null; createdSessionId: string | null; unverifiedFields: string[] }) => {
    if (res.status === 'complete') return done(res.createdSessionId);
    if (res.unverifiedFields.includes('email_address')) {
      await signUp!.prepareEmailAddressVerification({ strategy: 'email_code' });
      setStep('email_code');
    } else if (res.unverifiedFields.includes('phone_number')) {
      await signUp!.preparePhoneNumberVerification({ strategy: 'phone_code' });
      setStep('phone_code');
    } else {
      setError('Clerk needs more details for this account. Check the fields above and try again.');
      setStep('details');
    }
    setCode('');
  };

  const submit = async () => {
    if (!isLoaded || busy) return;
    setBusy(true);
    setError(null);
    try {
      if (step === 'details') {
        const phone = form.phone.trim();
        const res = await signUp.create({
          firstName: form.firstName.trim(),
          lastName: form.lastName.trim(),
          username: form.username.trim(),
          emailAddress: form.email.trim(),
          phoneNumber: phone ? (phone.startsWith('+') ? phone : `+1${phone.replace(/\D/g, '')}`) : undefined,
          password: form.password,
        });
        await next(res);
      } else if (step === 'email_code') {
        await next(await signUp.attemptEmailAddressVerification({ code: code.trim() }));
      } else {
        await next(await signUp.attemptPhoneNumberVerification({ code: code.trim() }));
      }
    } catch (e) {
      setError(clerkMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const verifying = step !== 'details';
  return (
    <AuthShell
      title={step === 'email_code' ? 'Check your email' : step === 'phone_code' ? 'Check your phone' : 'Create your account'}
      subtitle={
        step === 'email_code'
          ? `Enter the code sent to ${form.email.trim()}.`
          : step === 'phone_code'
            ? `Enter the code texted to ${form.phone.trim()}.`
            : 'Your saved lineups, contest entries, pool tags and settings will follow you to every device.'
      }
      footer={
        <Text className="text-sm font-sans-medium text-muted-foreground">
          Already have an account?{' '}
          <Link href="/sign-in" replace>
            <Text className="link-text text-sm">Sign in</Text>
          </Link>
        </Text>
      }>
      <FormError message={error} />
      {verifying ? (
        <Field label="Verification code" value={code} onChangeText={setCode} keyboardType="number-pad" autoComplete="one-time-code" />
      ) : (
        <>
          <View className="input-row">
            <View className="flex-1">
              <Field label="First name" value={form.firstName} onChangeText={set('firstName')} />
            </View>
            <View className="flex-1">
              <Field label="Last name" value={form.lastName} onChangeText={set('lastName')} />
            </View>
          </View>
          <Field label="Username" value={form.username} onChangeText={set('username')} />
          <Field label="Email" value={form.email} onChangeText={set('email')} keyboardType="email-address" autoComplete="email" placeholder="you@example.com" />
          <Field label="Mobile number" value={form.phone} onChangeText={set('phone')} keyboardType="phone-pad" placeholder="(555) 555-0100" />
          <Field label="Password" value={form.password} onChangeText={set('password')} secure autoComplete="new-password" />
        </>
      )}
      {/* Clerk's bot protection (CAPTCHA) renders here on the web. */}
      {Platform.OS === 'web' && !verifying ? <View nativeID="clerk-captcha" className="mb-2" /> : null}
      <SubmitButton label={verifying ? 'Verify and continue' : 'Create account'} onPress={submit} busy={busy} />
    </AuthShell>
  );
}
