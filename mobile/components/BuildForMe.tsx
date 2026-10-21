import { useState } from 'react';
import { Modal, Pressable, Text, View } from 'react-native';

import { ProSheet } from '@/components/ProLock';
import { Term } from '@/components/Term';
import { useAccountSync } from '@/lib/account-sync';
import { track } from '@/lib/analytics';
import { buildLineups } from '@/lib/api';
import { emptyLineup } from '@/lib/lineups';
import { useWeek } from '@/lib/week-context';

const COUNTS = [1, 2, 3, 4, 5];
const EXPOSURES = [1, 0.8, 0.6, 0.4];

/**
 * "Build for me": the model builds up to 5 distinct lineups for the slate
 * (best projection or best ceiling), keeping the players already in the
 * open lineup if asked and capping how often anyone repeats. They replace
 * the builder's lineups (not saved until the user saves).
 */
export default function BuildForMe({
  visible,
  onClose,
  current,
  pool,
  onBuilt,
}: {
  visible: boolean;
  onClose: () => void;
  /** The open lineup (its players can be kept). */
  current: BuilderLineup;
  pool: Player[];
  onBuilt: (lineups: BuilderLineup[], message: string) => void;
}) {
  const { season, week, selectedSlate } = useWeek();
  const { locked: proLocked } = useAccountSync();
  const [count, setCount] = useState(3);
  const [metric, setMetric] = useState<'proj_points' | 'ceiling'>('proj_points');
  const [exposure, setExposure] = useState(0.6);
  const [keep, setKeep] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [proOpen, setProOpen] = useState(false);
  const kept = current.filter(Boolean) as Player[];

  const run = async () => {
    if (!season || !week || !selectedSlate) return;
    if (count > 1 && proLocked('multiple_lineups')) return setProOpen(true);
    setBusy(true);
    setError(null);
    try {
      const res = await buildLineups(season, week, selectedSlate.slate_id, {
        metric,
        count,
        locked: keep ? kept.map((p) => p.dk_draftable_id).filter((id): id is number => id != null) : [],
        excluded: [],
        max_exposure: count > 1 ? exposure : 1,
      });
      const byId = new Map(pool.map((p) => [p.dk_draftable_id, p]));
      const lineups = res.lineups.map((lu) => {
        const slots = emptyLineup(selectedSlate.slate_type);
        lu.players.forEach((p, i) => {
          if (i < slots.length) slots[i] = byId.get(p.dk_draftable_id) ?? null;
        });
        return slots;
      });
      if (!lineups.length) throw new Error('No valid lineup fits those settings. Try keeping fewer players or allowing more repeats.');
      track('build_for_me', { count, built: lineups.length, metric, kept: keep ? kept.length : 0 });
      onBuilt(
        lineups,
        lineups.length < count
          ? `Built ${lineups.length} of ${count}: those settings only allow ${lineups.length} different lineups.`
          : `Built ${lineups.length} lineup${lineups.length === 1 ? '' : 's'}. Save them to keep them.`,
      );
      onClose();
    } catch (e) {
      const err = e as Error & { status?: number };
      if (err.status === 402) setProOpen(true);
      else setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const chip = (label: string, active: boolean, onPress: () => void) => (
    <Pressable key={label} className={`filter-chip mb-2 ${active ? 'filter-chip-active' : ''}`} onPress={onPress} accessibilityRole="radio" aria-checked={active}>
      <Text className={`filter-chip-text ${active ? 'filter-chip-text-active' : ''}`}>{label}</Text>
    </Pressable>
  );

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <Pressable className="week-backdrop" onPress={onClose} accessibilityLabel="Close">
        <Pressable className="week-sheet intro-sheet" onPress={() => {}}>
          <Text className="week-sheet-title">Build for me</Text>
          <Text className="caption mb-3">The model builds the best lineups that fit the salary cap. They replace the lineups in the builder.</Text>
          <Text className="input-label">How many lineups</Text>
          <View className="flex-row flex-wrap">{COUNTS.map((n) => chip(String(n), count === n, () => setCount(n)))}</View>
          <Text className="input-label mt-2">Aim for</Text>
          <View className="flex-row flex-wrap">
            {chip('Best projection', metric === 'proj_points', () => setMetric('proj_points'))}
            {chip('Best ceiling', metric === 'ceiling', () => setMetric('ceiling'))}
          </View>
          <Text className="caption mb-2">
            Projection suits <Term id="cash">cash games</Term>, <Term id="ceiling">ceiling</Term> suits <Term id="gpp">tournaments</Term>
          </Text>
          {count > 1 ? (
            <>
              <Text className="input-label mt-1">Most lineups any one player can be in</Text>
              <View className="flex-row flex-wrap">{EXPOSURES.map((x) => chip(`${Math.round(x * 100)}%`, exposure === x, () => setExposure(x)))}</View>
            </>
          ) : null}
          {kept.length ? (
            <Pressable className="check-row mt-1" onPress={() => setKeep((k) => !k)} accessibilityRole="checkbox" aria-checked={keep}>
              <View className={`check-box ${keep ? 'check-box-on' : ''}`}>{keep ? <Text className="check-mark">✓</Text> : null}</View>
              <Text className="check-label">
                Keep the {kept.length} player{kept.length === 1 ? '' : 's'} already in this lineup
              </Text>
            </Pressable>
          ) : null}
          {error ? <Text className="error-text text-left">{error}</Text> : null}
          <View className="mt-2 flex-row gap-2">
            <Pressable className="btn-outline flex-1 justify-center" onPress={onClose} accessibilityRole="button">
              <Text className="btn-outline-text">Cancel</Text>
            </Pressable>
            <Pressable className={`btn flex-1 ${busy ? 'opacity-60' : ''}`} onPress={run} disabled={busy} accessibilityRole="button">
              <Text className="btn-text">{busy ? 'Building…' : 'Build'}</Text>
            </Pressable>
          </View>
        </Pressable>
      </Pressable>
      <ProSheet feature="multiple_lineups" visible={proOpen} onClose={() => setProOpen(false)} />
    </Modal>
  );
}
