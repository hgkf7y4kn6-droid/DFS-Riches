import { useAuth } from '@clerk/expo';
import * as DocumentPicker from 'expo-document-picker';
import { useState } from 'react';
import { ActivityIndicator, Pressable, Text, View } from 'react-native';

import { useAccountSync } from '@/lib/account-sync';
import { postActualOwnership, postOwnershipVideo, type VideoUploadResult } from '@/lib/api';
import { formatEt } from '@/lib/utils';
import { useWeek } from '@/lib/week-context';

const HELP =
  "On DraftKings, open a contest after lock and export its standings (CSV), then upload it here -- it's applied to the slate its players and points match (this week's or last week's). Mid-slate, DraftKings hides players whose games haven't started (shown as LOCKED) -- upload again after later kickoffs to fill them in. Players with actual ownership use it for leverage.";
const VIDEO_HELP =
  "No CSV? Screen-record the contest's GameCenter Players tab (sorted by Ownership), scrolling slowly through the whole list, and upload the recording or a screenshot. Each player's ownership, salary and fantasy points are read from it -- this takes up to a couple of minutes.";
const READ_SHOWN = 8;

/** "Applied to Week 6 · Classic - Sunday Main: " -- the slate the server matched the upload to. */
const appliedTo = (slate?: { week: number; label: string } | null) => (slate ? `Applied to Week ${slate.week} · ${slate.label}: ` : 'Uploaded: ');

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
 * kickoffs: DraftKings hides players whose games haven't started. Or upload a
 * screen recording / screenshot of the contest's GameCenter Players tab: the
 * server reads ownership, salary and fantasy points from it.
 */
export default function ActualOwnershipCard({ contest, plays, onUploaded }: { contest: PlayContest; plays: PlaysResponse; onUploaded: () => void }) {
  const { master, userId } = useAccountSync();
  const { getToken } = useAuth();
  const { season, week } = useWeek();
  const [type, setType] = useState<UploadContest>(contest === 'cash' ? 'cash' : 'gpp');
  const [busy, setBusy] = useState<'csv' | 'video' | null>(null);
  const [read, setRead] = useState<VideoUploadResult['players'] | null>(null);
  const [message, setMessage] = useState<{ text: string; error?: boolean } | null>(null);
  const summaries = plays.actual_ownership ?? {};
  const shown = CONTESTS.filter((c) => summaries[c.field]);
  if (!master && !shown.length) return null;

  const upload = async () => {
    setMessage(null);
    const picked = await DocumentPicker.getDocumentAsync({ type: ['text/csv', 'text/comma-separated-values', 'text/plain', '*/*'], copyToCacheDirectory: true });
    if (picked.canceled || !picked.assets?.[0]) return;
    setBusy('csv');
    setRead(null);
    try {
      const text = await (await fetch(picked.assets[0].uri)).text();
      if (!text.includes('%Drafted')) throw new Error("That file doesn't look like a DraftKings contest standings export (no %Drafted column).");
      const token = await getToken();
      if (!token || !season || !week) throw new Error('Sign in first.');
      const res = await postActualOwnership(token, { season, week, slate_id: 'auto', contest: type, text });
      setMessage({
        text:
          appliedTo(res.slate) +
          `${res.added} players with actual ownership` +
          (res.entries ? ` from ${res.entries.toLocaleString()} entries` : '') +
          (res.unmatched.length ? ` · ${res.unmatched.length} names not on this slate` : '') +
          (res.persisted === false ? ' · not saved to the database (kept until the next deploy)' : ''),
      });
      onUploaded();
    } catch (e) {
      setMessage({ text: e instanceof Error ? e.message : String(e), error: true });
    } finally {
      setBusy(null);
    }
  };

  const uploadVideo = async () => {
    setMessage(null);
    const picked = await DocumentPicker.getDocumentAsync({ type: ['video/*', 'image/*'], copyToCacheDirectory: true });
    const asset = picked.canceled ? null : picked.assets?.[0];
    if (!asset) return;
    setBusy('video');
    setRead(null);
    try {
      const token = await getToken();
      if (!token || !season || !week) throw new Error('Sign in first.');
      const res = await postOwnershipVideo(token, { season, week, slate_id: 'auto', contest: type }, asset.uri,
        asset.mimeType ?? 'application/octet-stream');
      const mismatched = res.players.filter((p) => p.salary_mismatch).length;
      setMessage({
        text:
          appliedTo(res.slate) +
          `read ${res.added} players from ${res.frames} frame${res.frames === 1 ? '' : 's'}` +
          (res.unmatched.length ? ` · ${res.unmatched.length} names not matched on this slate` : '') +
          (mismatched ? ` · ${mismatched} salaries differ from this slate's (is it this slate's contest?)` : '') +
          (res.persisted === false ? ' · not saved to the database (kept until the next deploy)' : ''),
      });
      setRead(res.players);
      onUploaded();
    } catch (e) {
      setMessage({ text: e instanceof Error ? e.message : String(e), error: true });
    } finally {
      setBusy(null);
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
          <Pressable className={`btn-accent mt-2 ${busy ? 'opacity-60' : ''}`} onPress={upload} disabled={!!busy} accessibilityRole="button">
            {busy === 'csv' ? <ActivityIndicator /> : <Text className="btn-text">Upload contest standings CSV</Text>}
          </Pressable>
          <Text className="actual-help mt-3">{VIDEO_HELP}</Text>
          <Pressable
            className={`btn-accent mt-2 ${busy ? 'opacity-60' : ''}`}
            onPress={uploadVideo}
            disabled={!!busy}
            accessibilityRole="button"
            accessibilityLabel={busy === 'video' ? 'Reading the screen recording' : undefined}>
            {busy === 'video' ? <ActivityIndicator /> : <Text className="btn-text">Upload screen recording</Text>}
          </Pressable>
          {message ? (
            <Text className={`actual-help mt-1.5 ${message.error ? 'text-negative' : ''}`} accessibilityLiveRegion="polite">
              {message.text}
            </Text>
          ) : null}
          {read?.length ? (
            <View className="mt-1.5">
              <Text className="actual-miss-head">Read from the recording</Text>
              {read.slice(0, READ_SHOWN).map((p) => (
                <Text key={`${p.name}-${p.team}`} className="actual-miss">
                  {p.name} <Text className="dfs-meta">{p.position} · {p.team}</Text> {p.pct.toFixed(2)}%
                  {p.salary != null ? ` · $${p.salary.toLocaleString()}` : ''}
                  {p.points != null ? ` · ${p.points.toFixed(2)} pts` : ''}
                </Text>
              ))}
              {read.length > READ_SHOWN ? <Text className="dfs-meta">+{read.length - READ_SHOWN} more</Text> : null}
            </View>
          ) : null}
        </View>
      ) : null}
    </View>
  );
}
