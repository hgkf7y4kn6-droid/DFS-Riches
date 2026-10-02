import { useState } from 'react';
import { Pressable, Text, View } from 'react-native';

import { formatPercent } from '@/lib/utils';

const MODEL_LABEL: Record<string, string> = {
  sim: 'field simulation',
  bt: 'Bradley-Terry choice',
  frac_logit: 'fractional logit',
  gbm: 'LightGBM',
};

/** How the ownership numbers were made, and whether the trained models have data yet. Tap for details. */
export default function OwnershipModelNote({ models }: { models: PlaysResponse['ownership_models'] }) {
  const [open, setOpen] = useState(false);
  const entries = Object.values(models).filter(Boolean) as OwnershipModelInfo[];
  const first = entries[0];
  if (!first) return null;
  const t = first.training;
  return (
    <Pressable className="env-stack mb-3" onPress={() => setOpen((o) => !o)} accessibilityRole="button" accessibilityState={{ expanded: open }}>
      <Text className="dfs-stats mt-0">
        {first.simulated_lineups.toLocaleString('en-US')} simulated lineups per contest ·{' '}
        {Object.entries(first.weights)
          .map(([k, w]) => `${MODEL_LABEL[k] ?? k} ${formatPercent(w, 0)}`)
          .join(' + ')}
      </Text>
      <Text className="dfs-reason">
        {t.frac_logit || t.gbm
          ? `Fractional logit${t.gbm ? ' and LightGBM' : ''} trained on ${t.slates} slates of actual ownership.`
          : `Fractional logit and LightGBM switch on once 3 slates have actual ownership uploaded (${t.slates} so far).`}{' '}
        {open ? '▲' : 'How it works ▼'}
      </Text>
      {open ? (
        <View className="mt-2 gap-1">
          <Text className="dfs-reason">
            • Field simulation: each contest&apos;s field is simulated 10,000 times. Every entrant runs a quick optimizer on
            projections randomized by the player&apos;s own spread, with a shared team shock so lineups stack; ownership is how
            often each player shows up. Cash fields chase median and floor and agree more; GPP fields chase ceiling and
            disagree more (large field most).
          </Text>
          <Text className="dfs-reason">
            • Bradley-Terry: the slate is a marketplace with a fixed budget. Each player&apos;s strength comes from projection,
            value, implied total, floor or ceiling, and salary priced at the simulated field&apos;s cost of $1k
            {` (${entries.map((m) => `${m.label} ${m.price_per_k.toFixed(2)} pts`).join(', ')})`}; P(A over B) = strength A /
            (A + B).
          </Text>
          <Text className="dfs-reason">
            • Fractional logit and LightGBM learn from past slates&apos; actual ownership using the engineered features
            (value ratio, position value rank, salary vs position average, team implied total, position scarcity, backup
            injury starts). Ownership stays between 0% and 100% and each position sums to its roster slots.
          </Text>
        </View>
      ) : null}
    </Pressable>
  );
}
