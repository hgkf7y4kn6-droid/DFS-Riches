import { useSignIn } from '@clerk/expo/legacy';
import { Link, router } from 'expo-router';
import { useState } from 'react';
import { Text } from 'react-native';

import { AuthShell, clerkMessage, Field, FormError, SubmitButton } from '@/components/auth/AuthShell';

/** Email + password sign-in (Clerk). */
export default function SignInScreen() {
  const { isLoaded, signIn, setActive } = useSignIn();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [code, setCode] = useState('');
  const [needsCode, setNeedsCode] = useState(false);
  const [codeStrategy, setCodeStrategy] = useState<'email_code' | 'phone_code'>('email_code');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const finish = async (sessionId: string | null) => {
    await setActive!({ session: sessionId });
    if (router.canGoBack()) router.back();
    else router.replace('/settings');
  };

  const submit = async () => {
    if (!isLoaded || busy) return;
    setBusy(true);
    setError(null);
    try {
      if (needsCode) {
        const res = await signIn.attemptSecondFactor({ strategy: codeStrategy, code: code.trim() });
        if (res.status === 'complete') return finish(res.createdSessionId);
        setError('That code did not work. Check your email and try again.');
        return;
      }
      const res = await signIn.create({ identifier: email.trim(), password });
      if (res.status === 'complete') return finish(res.createdSessionId);
      // A second factor, or Clerk's "new device" check (client trust): a one-time
      // code by email, else by text.
      if (res.status === 'needs_second_factor' || res.status === 'needs_client_trust') {
        const factors = (res.supportedSecondFactors ?? []).map((f) => f.strategy);
        const strategy = factors.includes('email_code') || !factors.includes('phone_code') ? 'email_code' : 'phone_code';
        const factor = res.supportedSecondFactors?.find((f) => f.strategy === strategy) as { emailAddressId?: string; phoneNumberId?: string } | undefined;
        await signIn.prepareSecondFactor(
          strategy === 'email_code'
            ? { strategy, emailAddressId: factor?.emailAddressId }
            : { strategy, phoneNumberId: factor?.phoneNumberId },
        );
        setCodeStrategy(strategy);
        setNeedsCode(true);
        return;
      }
      setError(`Sign-in needs another step this app does not support yet (${res.status}).`);
    } catch (e) {
      setError(clerkMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthShell
      title="Welcome back"
      subtitle="Sign in to bring your saved lineups, contest entries and pool tags to this device."
      footer={
        <Text className="text-sm font-sans-medium text-muted-foreground">
          New here?{' '}
          <Link href="/sign-up" replace>
            <Text className="link-text text-sm">Create an account</Text>
          </Link>
        </Text>
      }>
      <FormError message={error} />
      {needsCode ? (
        <Field label={`Verification code (sent to your ${codeStrategy === 'email_code' ? 'email' : 'phone'})`} value={code} onChangeText={setCode} keyboardType="number-pad" autoComplete="one-time-code" />
      ) : (
        <>
          <Field label="Email or username" value={email} onChangeText={setEmail} keyboardType="email-address" autoComplete="email" placeholder="you@example.com" />
          <Field label="Password" value={password} onChangeText={setPassword} secure autoComplete="password" />
        </>
      )}
      <SubmitButton label={needsCode ? 'Verify' : 'Sign in'} onPress={submit} busy={busy} />
    </AuthShell>
  );
}
