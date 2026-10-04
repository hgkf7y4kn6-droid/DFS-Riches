import { useAuth } from '@clerk/expo';
import { useSignIn } from '@clerk/expo/legacy';
import { Link, router } from 'expo-router';
import { useEffect, useState } from 'react';
import { Pressable, Text } from 'react-native';

import { AuthShell, clerkMessage, Field, FormError, SubmitButton } from '@/components/auth/AuthShell';

type Step = 'password' | 'first_code' | 'second_code';
type Factor = { strategy: string; emailAddressId?: string; phoneNumberId?: string };

const leave = () => {
  if (router.canGoBack()) router.back();
  else router.replace('/settings');
};

/**
 * Clerk sign-in: email or username + password, or a one-time code by email
 * (also the way in after a forgotten password). Handles Clerk's new-device
 * check and second factors with a code too.
 */
export default function SignInScreen() {
  const { isLoaded, signIn, setActive } = useSignIn();
  const { isSignedIn } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [code, setCode] = useState('');
  const [step, setStep] = useState<Step>('password');
  const [codeStrategy, setCodeStrategy] = useState<'email_code' | 'phone_code'>('email_code');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Already signed in (this app allows one session at a time): nothing to do here.
  useEffect(() => {
    if (isSignedIn) leave();
  }, [isSignedIn]);

  const finish = async (sessionId: string | null) => {
    await setActive!({ session: sessionId });
    leave();
  };

  const pick = (factors: Factor[] | null | undefined) => {
    const list = factors ?? [];
    return list.find((f) => f.strategy === 'email_code') ?? list.find((f) => f.strategy === 'phone_code');
  };

  // Send a one-time code as the first factor (no password).
  const sendFirstCode = async (factors: Factor[] | null | undefined) => {
    const f = pick(factors);
    if (!f) throw new Error('This account cannot sign in with a code. Use your password.');
    await signIn!.prepareFirstFactor(
      f.strategy === 'email_code'
        ? { strategy: 'email_code', emailAddressId: f.emailAddressId! }
        : { strategy: 'phone_code', phoneNumberId: f.phoneNumberId! },
    );
    setCodeStrategy(f.strategy as 'email_code' | 'phone_code');
    setCode('');
    setStep('first_code');
  };

  const run = async (fn: () => Promise<unknown>) => {
    if (!isLoaded || busy) return;
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      const code = (e as { errors?: { code?: string }[] })?.errors?.[0]?.code;
      if (code === 'session_exists') leave();
      else setError(clerkMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const submit = () =>
    run(async () => {
      if (step === 'first_code') {
        const res = await signIn!.attemptFirstFactor({ strategy: codeStrategy, code: code.trim() });
        if (res.status === 'complete') return finish(res.createdSessionId);
        return afterFirst(res);
      }
      if (step === 'second_code') {
        const res = await signIn!.attemptSecondFactor({ strategy: codeStrategy, code: code.trim() });
        if (res.status === 'complete') return finish(res.createdSessionId);
        setError('That code did not work. Check it and try again.');
        return;
      }
      if (!email.trim()) return setError('Enter your email or username.');
      if (!password) return setError('Enter your password, or tap "Email me a sign-in code".');
      const res = await signIn!.create({ identifier: email.trim(), password });
      if (res.status === 'complete') return finish(res.createdSessionId);
      return afterFirst(res);
    });

  // After the first factor: a second factor, or Clerk's "new device" check
  // (client trust) -- a one-time code by email, else by text.
  const afterFirst = async (res: { status: string | null; supportedFirstFactors?: Factor[] | null; supportedSecondFactors?: Factor[] | null }) => {
    if (res.status === 'needs_first_factor') return sendFirstCode(res.supportedFirstFactors);
    if (res.status === 'needs_second_factor' || res.status === 'needs_client_trust') {
      const f = pick(res.supportedSecondFactors) ?? { strategy: 'email_code' };
      await signIn!.prepareSecondFactor(
        f.strategy === 'phone_code'
          ? { strategy: 'phone_code', phoneNumberId: f.phoneNumberId }
          : { strategy: 'email_code', emailAddressId: f.emailAddressId },
      );
      setCodeStrategy(f.strategy === 'phone_code' ? 'phone_code' : 'email_code');
      setCode('');
      setStep('second_code');
      return;
    }
    setError(`Sign-in needs another step this app does not support yet (${res.status}).`);
  };

  const emailCode = () =>
    run(async () => {
      if (!email.trim()) return setError('Enter your email or username first.');
      const res = await signIn!.create({ identifier: email.trim() });
      await sendFirstCode(res.supportedFirstFactors as Factor[] | null);
    });

  const back = () => {
    setStep('password');
    setCode('');
    setError(null);
  };

  const coding = step !== 'password';
  const where = codeStrategy === 'email_code' ? 'email' : 'phone';
  return (
    <AuthShell
      title={coding ? `Check your ${where}` : 'Welcome back'}
      subtitle={coding ? `Enter the code we sent to your ${where}.` : 'Sign in to bring your saved lineups, contest entries and pool tags to this device.'}
      footer={
        <Text className="text-sm font-sans-medium text-muted-foreground">
          New here?{' '}
          <Link href="/sign-up" replace>
            <Text className="link-text text-sm">Create an account</Text>
          </Link>
        </Text>
      }>
      <FormError message={error} />
      {coding ? (
        <Field label="Verification code" value={code} onChangeText={setCode} keyboardType="number-pad" autoComplete="one-time-code" />
      ) : (
        <>
          <Field label="Email or username" value={email} onChangeText={setEmail} keyboardType="email-address" autoComplete="email" placeholder="you@example.com" />
          <Field label="Password" value={password} onChangeText={setPassword} secure autoComplete="password" />
        </>
      )}
      <SubmitButton label={coding ? 'Verify' : 'Sign in'} onPress={submit} busy={busy} />
      <Pressable className="mt-3 items-center" onPress={coding ? back : emailCode} accessibilityRole="button" disabled={busy}>
        <Text className="link-text text-sm">{coding ? 'Use a different email or password' : 'Forgot password? Email me a sign-in code'}</Text>
      </Pressable>
    </AuthShell>
  );
}
