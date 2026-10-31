import { Text, View } from 'react-native';

import { Term } from '@/components/Term';

/**
 * A number over its name: the value is larger and darker than the label, so a
 * row of stats scans by its numbers. `term` links the label to its glossary
 * definition (constants/glossary.ts). `tone` is for real thresholds only
 * (a warning, a stale input); a plain metric stays neutral.
 */
export default function Stat({
  value,
  label,
  term,
  tone = 'neutral',
  hero = false,
}: {
  value: string;
  label: string;
  term?: string;
  tone?: 'neutral' | 'good' | 'warn' | 'bad';
  /** The one headline number on a card. */
  hero?: boolean;
}) {
  return (
    <View className="stat" accessible accessibilityLabel={`${label}: ${value}`}>
      <Text className={`${hero ? 't-value-hero' : 't-value'} ${TONE[tone]}`}>{value}</Text>
      <Text className="t-label">{term ? <Term id={term}>{label}</Term> : label}</Text>
    </View>
  );
}

const TONE = { neutral: '', good: 'text-success', warn: 'text-warning', bad: 'text-danger' } as const;
