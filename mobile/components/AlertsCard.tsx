import AsyncStorage from '@react-native-async-storage/async-storage';
import { router } from 'expo-router';
import { useEffect, useMemo, useState } from 'react';
import { Pressable, Text, View } from 'react-native';

import ProLock from '@/components/ProLock';
import { slateTitle } from '@/components/SlateList';
import { PLAYABLE_STATUSES } from '@/constants/data';
import { track } from '@/lib/analytics';
import { useChooseSlate } from '@/lib/slate-choice';
import { useWeek, type LineupScope } from '@/lib/week-context';

const SEEN_KEY = 'dfsriches:slates-with-salaries';
const LOCK_SOON_MS = 60 * 60 * 1000;
const SCOPES: LineupScope[] = ['', 'cash', 'gpp'];
// DraftKings' status codes (app/dfs_model.py STATUS_LABEL).
const STATUS_TEXT: Record<string, string> = { O: 'out', OUT: 'out', D: 'doubtful', IR: 'on IR' };

interface Alert {
  id: string;
  tone: 'danger' | 'warning' | 'info';
  text: string;
  action?: { label: string; onPress: () => void };
}

/**
 * Personal alerts for the slate being worked on: players in the user's
 * lineups now ruled out (Out, Doubtful, IR), lineups that lock within the
 * hour, and slates whose DraftKings salaries just came out. A Pro feature
 * once billing is on. (In the app for now; push notifications need a new
 * app build with expo-notifications.)
 */
export default function AlertsCard() {
  const { season, week, weekData, selectedSlate, players, lineupsFor } = useWeek();
  const choose = useChooseSlate();
  const [now, setNow] = useState(() => Date.now());
  const [newSalaries, setNewSalaries] = useState<string[]>([]);
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());

  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 60_000);
    return () => clearInterval(t);
  }, []);

  // Slates whose salaries came out since this device last looked.
  const slates = weekData.data?.slates;
  useEffect(() => {
    if (!slates || !season || !week) return;
    const key = `${season}:${week}`;
    const available = slates.filter((s) => s.available).map((s) => s.slate_id);
    AsyncStorage.getItem(SEEN_KEY)
      .then((raw) => {
        const seen = raw ? (JSON.parse(raw) as { key: string; ids: string[] }) : null;
        if (seen?.key === key) setNewSalaries(available.filter((id) => !seen.ids.includes(id)));
        AsyncStorage.setItem(SEEN_KEY, JSON.stringify({ key, ids: available })).catch(() => {});
      })
      .catch(() => {});
  }, [slates, season, week]);

  const alerts = useMemo(() => {
    const out: Alert[] = [];
    const slate = selectedSlate;
    if (slate && players.data?.slate.slate_id === slate.slate_id) {
      const latest = new Map(players.data.players.map((p) => [p.dk_draftable_id, p]));
      const lineups = SCOPES.flatMap((scope) => lineupsFor(scope).lineups);
      const out_ = new Map<string, { name: string; status: string; count: number }>();
      let filled = 0;
      for (const lu of lineups) {
        if (lu.some(Boolean)) filled += 1;
        for (const p of lu) {
          if (!p) continue;
          const status = latest.get(p.dk_draftable_id)?.injury ?? p.injury ?? 'Healthy';
          if (!PLAYABLE_STATUSES.has(status)) {
            const cur = out_.get(p.name) ?? { name: p.name, status, count: 0 };
            out_.set(p.name, { ...cur, count: cur.count + 1 });
          }
        }
      }
      for (const o of out_.values()) {
        out.push({
          id: `out:${slate.slate_id}:${o.name}`,
          tone: 'danger',
          text: `${o.name} is ${STATUS_TEXT[o.status] ?? o.status} and in ${o.count} of your ${slateTitle(slate)} lineup${o.count === 1 ? '' : 's'}.`,
          action: { label: 'Swap him ›', onPress: () => router.push('/lineups') },
        });
      }
      const next = slate.games.map((g) => new Date(g.kickoff_utc).getTime()).filter((t) => t > now).sort((a, b) => a - b)[0];
      if (filled && next && next - now <= LOCK_SOON_MS) {
        const mins = Math.max(1, Math.round((next - now) / 60000));
        out.push({ id: `lock:${slate.slate_id}:${next}`, tone: 'warning', text: `Your ${slateTitle(slate)} lineups start locking in ${mins} minute${mins === 1 ? '' : 's'}.` });
      }
    }
    for (const id of newSalaries) {
      const s = slates?.find((x) => x.slate_id === id);
      if (!s) continue;
      out.push({
        id: `salaries:${id}`,
        tone: 'info',
        text: `DraftKings salaries are out for ${slateTitle(s)}.`,
        action: {
          label: 'Build ›',
          onPress: () => {
            choose(id);
            router.push('/lineups');
          },
        },
      });
    }
    return out.filter((a) => !dismissed.has(a.id));
  }, [selectedSlate, players.data, lineupsFor, now, newSalaries, slates, dismissed, choose]);

  useEffect(() => {
    for (const a of alerts) track('alert_shown', { kind: a.id.split(':')[0] });
    // count each alert kind as it appears
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [alerts.length]);

  if (!alerts.length) return null;
  return (
    <ProLock feature="alerts" minHeight={90}>
      <View className="mb-3 gap-2">
        {alerts.map((a) => (
          <View key={a.id} className={`alert alert-${a.tone}`}>
            <Text className="alert-text">{a.text}</Text>
            <View className="mt-1 flex-row items-center justify-end gap-4">
              {a.action ? (
                <Pressable onPress={a.action.onPress} accessibilityRole="button" hitSlop={8}>
                  <Text className="link-text text-sm">{a.action.label}</Text>
                </Pressable>
              ) : null}
              <Pressable onPress={() => setDismissed((d) => new Set(d).add(a.id))} accessibilityRole="button" accessibilityLabel="Dismiss" hitSlop={8}>
                <Text className="caption">Dismiss</Text>
              </Pressable>
            </View>
          </View>
        ))}
      </View>
    </ProLock>
  );
}
