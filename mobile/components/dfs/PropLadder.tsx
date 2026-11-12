import { Text, View } from 'react-native';

import { Glossed } from '@/components/Term';

const STAT_LABEL: Record<string, string> = {
  pass_yd: 'Pass yds',
  rush_yd: 'Rush yds',
  rec_yd: 'Rec yds',
  rec: 'Receptions',
};
const ORDER = ['pass_yd', 'rush_yd', 'rec_yd', 'rec'];

function pct(p: number) {
  if (p < 0.01) return '<1%';
  if (p > 0.99) return '>99%';
  return `${Math.round(p * 100)}%`;
}

/**
 * A player's prop medians and ladder chances (app.prop_pricer): per stat, the
 * median and the chance he reaches each rung. Rungs he's nearly sure to clear
 * or miss are left out.
 */
export default function PropLadder({ props }: { props: Record<string, PropPrice> }) {
  const stats = ORDER.filter((s) => props[s]);
  return (
    <View className="props-panel">
      {stats.map((s) => {
        const { median, ladder } = props[s];
        const rungs = Object.entries(ladder).filter(([, p]) => p >= 0.02 && p <= 0.98);
        return (
          <View key={s} className="gap-1">
            <Text className="props-stat">
              {STAT_LABEL[s] ?? s} · median <Text className="props-median">{s === 'rec' ? median.toFixed(1) : Math.round(median)}</Text>
            </Text>
            {rungs.length ? (
              <View className="props-rungs">
                {rungs.map(([rung, p]) => (
                  <View key={rung} className="props-rung">
                    <Text className="props-rung-text">
                      {rung}+ {pct(p)}
                    </Text>
                  </View>
                ))}
              </View>
            ) : null}
          </View>
        );
      })}
      <Text className="caption">
        <Glossed text="Prop median: half his games land above it. Prop ladder: the model's chance he reaches each rung." />
      </Text>
    </View>
  );
}
