import { useAuth } from '@clerk/expo';
import * as DocumentPicker from 'expo-document-picker';
import { useState } from 'react';
import { ActivityIndicator, Pressable, Text, View } from 'react-native';

import { useAccountSync } from '@/lib/account-sync';
import { postActualOwnership } from '@/lib/api';
import { formatEt } from '@/lib/utils';
import { useWeek } from '@/lib/week-context';

const HELP =
  "On DraftKings, open a contest after lock and export its standings (CSV), then upload it here. Mid-slate, DraftKings hides players whose games haven't started (shown as LOCKED) -- upload again after later kickoffs to fill them in. Players with actual ownership use it for leverage.";

type UploadContest = 'gpp' | 'se' | 'cash';
const CONTESTS: { id: UploadContest; label: string; field: OwnershipContest }[] = [
  { id: 'gpp', label: 'Large-field GPP', field: 'large_gpp' },
  { id: 'se', label: 'Small-field GPP', field: 'small_gpp' },
  { id: 'cash', label: 'Cash', field: 'cash' },
];

/**
 * Master accounts: upload a DraftKings contest-standings CSV (contest page
 * after lock -> export) as actual ownership for this slate. Actual
 * ownership then shows on each player next to the projection, leverage uses
 * it, and the ownership models learn from it. Re-upload after later
 * kickoffs: DraftKings hides players whose games haven't started.
 */
export default function ActualOwnershipCard({ contest, plays, onUploaded }: { contest: PlayContest; plays: PlaysResponse; onUploaded: () => void }) {
  const { master, userId } = useAccountSync();
  const { getToken } = useAuth();
  const { season, week } = useWeek();
  const [type, setType] = useState<UploadContest>(contest === 'cash' ? 'cash' : 'gpp');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ text: string; error?: boolean } | null>(null);
  const summaries = plays.actual_ownership ?? {};
  const shown = CONTESTS.filter((c) => summaries[c.field]);
  if (!master && !shown.length) return null;

  const upload = async () => {
    setMessage(null);
    const picked = await DocumentPicker.getDocumentAsync({ type: ['text/csv', 'text/comma-separated-values', 'text/plain', '*/*'], copyToCacheDirectory: true });
    if (picked.canceled || !picked.assets?.[0]) return;
    setBusy(true);
    try {
      const text = await (await fetch(picked.assets[0].uri)).text();
      if (!text.includes('%Drafted')) throw new Error("That file doesn't look like a DraftKings contest standings export (no %Drafted column).");
      const token = await getToken();
      if (!token || !season || !week) throw new Error('Sign in first.');
      const res = await postActualOwnership(token, { season, week, slate_id: plays.slate.slate_id, contest: type, text });
      setMessage({
        text:
          `Uploaded: ${res.added} players with actual ownership` +
          (res.entries ? ` from ${res.entries.toLocaleString()} entries` : '') +
          (res.unmatched.length ? ` · ${res.unmatched.length} names not on this slate` : '') +
          (res.persisted === false ? ' · not saved to the database (kept until the next deploy)' : ''),
      });
      onUploaded();
    } catch (e) {
      setMessage({ text: e instanceof Error ? e.message : String(e), error: true });
    } finally {
      setBusy(false);
    }
  };

  return (
    <View className="actual-card">
      <Text className="actual-title">Actual contest ownership</Text>
      {shown.map((c) => {
        const s = summaries[c.field]!;
        return (
          <View key={c.id} className="mt-2">
            <Text className="actual-sub">
              {c.label}: {s.players} players{s.uploaded_at ? ` · uploaded ${formatEt(s.uploaded_at)}` : ''}
              {s.mae != null ? ` · projection missed by ${s.mae.toFixed(1)} pts on average` : ''}
            </Text>
            <Text className="actual-miss-head">Biggest misses (actual vs projected)</Text>
            {s.misses.slice(0, 6).map((m) => {
              const diff = (m.actual ?? 0) - (m.projected ?? 0);
              return (
                <Text key={`${m.name}-${m.team}`} className="actual-miss">
                  {m.name} <Text className="dfs-meta">{m.position} · {m.team}</Text> {m.actual?.toFixed(1)}% vs {m.projected?.toFixed(1)}%{' '}
                  <Text className={diff > 0 ? 'text-negative' : 'text-positive'}>
                    ({diff > 0 ? '+' : ''}
                    {diff.toFixed(1)})
                  </Text>
                </Text>
              );
            })}
          </View>
        );
      })}
      {master && userId ? (
        <View className="mt-3">
          <Text className="actual-help">
            {HELP}
          </Text>
          <View className="mt-2 flex-row flex-wrap gap-2">
            {CONTESTS.map((c) => {
              const active = c.id === type;
              return (
                <Pressable
                  key={c.id}
                  className={`filter-chip ${active ? 'filter-chip-active' : ''}`}
                  onPress={() => setType(c.id)}
                  accessibilityRole="button"
                  aria-pressed={active}>
                  <Text className={`filter-chip-text ${active ? 'filter-chip-text-active' : ''}`}>{c.label}</Text>
                </Pressable>
              );
            })}
          </View>
          <Pressable className={`btn-accent mt-2 ${busy ? 'opacity-60' : ''}`} onPress={upload} disabled={busy} accessibilityRole="button">
            {busy ? <ActivityIndicator /> : <Text className="btn-text">Upload contest standings CSV</Text>}
          </Pressable>
          {message ? <Text className={`actual-help mt-1.5 ${message.error ? 'text-negative' : ''}`}>{message.text}</Text> : null}
        </View>
      ) : null}
    </View>
  );
}
