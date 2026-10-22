import { useState } from 'react';
import { Modal, Pressable, ScrollView, Text, View } from 'react-native';

import { slateMeta, slateTitle } from '@/components/SlateList';
import { Term } from '@/components/Term';
import { useDfsModel } from '@/lib/dfs-model-context';
import { useChooseSlate } from '@/lib/slate-choice';
import { useWeek } from '@/lib/week-context';

interface Option {
  id: string;
  kicker: string;
  title: string;
  meta: string;
}

/**
 * The slate half of the header's picker card ("Sunday Main ▾"), beside the
 * week. Tap to switch slates. `scope="model"` lists only the Classic
 * slates the DFS model runs on (DFS Model, Safe Plays, Tournaments);
 * otherwise every slate this week (Home, Lineups).
 */
export default function SlatePill({ scope = 'week', slates: modelSlates }: { scope?: 'week' | 'model'; slates?: { slate_id: string; label: string }[] }) {
  const { weekData, selectedSlate } = useWeek();
  const { model, slateId } = useDfsModel();
  const choose = useChooseSlate();
  const [open, setOpen] = useState(false);
  const all = weekData.data?.slates ?? [];

  const options: Option[] =
    scope === 'week'
      ? all.map((s) => ({ id: s.slate_id, kicker: s.slate_type === 'showdown' ? 'Showdown' : 'Classic', title: slateTitle(s), meta: slateMeta(s) }))
      : // The model's list once it loads; until then (a new slate builds for a few seconds) the Classic slates with salaries.
        (modelSlates ?? model?.slates ?? all.filter((x) => x.slate_type === 'classic' && x.available).map((x) => ({ slate_id: x.slate_id, label: x.label }))).map((m) => {
          const s = all.find((x) => x.slate_id === m.slate_id);
          return { id: m.slate_id, kicker: 'Classic', title: s ? slateTitle(s) : m.label, meta: s ? slateMeta(s) : m.label };
        });
  const selectedId = scope === 'week' ? selectedSlate?.slate_id : slateId ?? model?.slate?.slate_id;
  const current = options.find((o) => o.id === selectedId);
  if (!options.length || !current) return null;

  return (
    <>
      <Pressable
        className="picker-seg"
        onPress={() => setOpen(true)}
        accessibilityRole="button"
        accessibilityLabel={`${current.kicker} slate: ${current.title}. Change slate`}
        hitSlop={4}>
        <Text className="picker-seg-text" numberOfLines={1} style={{ maxWidth: 118 }}>
          {current.title}
        </Text>
        <Text className="picker-seg-caret">▾</Text>
      </Pressable>
      <Modal visible={open} transparent animationType="fade" onRequestClose={() => setOpen(false)}>
        <Pressable className="week-backdrop" onPress={() => setOpen(false)} accessibilityLabel="Close">
          <Pressable className="week-sheet" onPress={() => {}}>
            <Text className="week-sheet-title">Pick a slate</Text>
            <Text className="caption mb-3">
              A <Term id="slate">slate</Term> is the set of games a contest uses.{' '}
              {scope === 'model' ? (
                <>
                  The model runs on <Term id="classic">Classic</Term> slates; open Lineups for <Term id="showdown">Showdowns</Term>.
                </>
              ) : (
                'Every tab follows the slate you pick.'
              )}
            </Text>
            <ScrollView style={{ maxHeight: 380 }}>
              {options.map((o) => {
                const active = o.id === selectedId;
                return (
                  <Pressable
                    key={o.id}
                    className={`slate-option ${active ? 'slate-option-active' : ''}`}
                    onPress={() => {
                      choose(o.id);
                      setOpen(false);
                    }}
                    accessibilityRole="radio"
                    aria-checked={active}>
                    <View className="flex-1">
                      <Text className="slate-chip-kicker">{o.kicker}</Text>
                      <Text className="slate-card-title">{o.title}</Text>
                      <Text className="slate-card-meta">{o.meta}</Text>
                    </View>
                    {active ? <Text className="slate-option-check">✓</Text> : null}
                  </Pressable>
                );
              })}
            </ScrollView>
          </Pressable>
        </Pressable>
      </Modal>
    </>
  );
}
