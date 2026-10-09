import { Modal, Pressable, ScrollView, Text, View } from 'react-native';

export interface LeverageExplanation {
  value: number;
  detail: LeverageDetail | null;
  name?: string | null;
}

const sign = (v: number, digits = 1) => `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toFixed(digits)}`;
const sigma = (z: number) => `${sign(z)}σ`;

const VERDICT: Record<string, string> = {
  'Efficient secret': 'Under-owned and in an efficient matchup: the kind of edge worth targeting.',
  'Public trap': 'Heavily owned (15%+), over-owned by 3+ points and in a poor matchup: the field is overpaying.',
  Mirage: 'Barely owned, but with little real upside, so low ownership alone is not an edge.',
};

function reading(v: number): string {
  if (v >= 1.5) return `The field is expected to play him about ${Math.abs(v).toFixed(1)} percentage points less than his odds justify: an edge if he hits.`;
  if (v <= -1.5) return `The field is expected to play him about ${Math.abs(v).toFixed(1)} points more than his odds justify: you'd be paying for popularity.`;
  return 'His ownership is about in line with his odds: no real edge either way.';
}

/** What a leverage number means, and how this player's was built. */
export default function LeverageExplainer({ shown, onClose }: { shown: LeverageExplanation | null; onClose: () => void }) {
  const d = shown?.detail;
  return (
    <Modal visible={shown != null} transparent animationType="fade" onRequestClose={onClose}>
      <Pressable className="week-backdrop" onPress={onClose} accessibilityLabel="Close">
        <Pressable className="week-sheet" onPress={() => {}}>
          {shown ? (
            <ScrollView style={{ maxHeight: 520 }}>
              <Text className="week-sheet-title">
                {shown.name ? `${shown.name} · ` : ''}Leverage {sign(shown.value)}
              </Text>
              <Text className="lev-explain-text">{reading(shown.value)}</Text>

              <Text className="lev-explain-head">What leverage is</Text>
              <Text className="lev-explain-text">
                {"Fair ownership minus the field's ownership, in percentage points. Fair ownership is how often he should be played given his odds of a big game after adjusting for matchup efficiency; the field's is the projected (or uploaded actual) ownership. Positive means under-owned for his upside; negative means the field is over-exposed to him."}
              </Text>

              {d ? (
                <>
                  <Text className="lev-explain-head">His numbers</Text>
                  {d.fair_own != null && d.own != null ? (
                    <Text className="lev-explain-text">
                      Fair ownership {d.fair_own.toFixed(1)}% vs {d.own.toFixed(1)}% {d.own_is_actual ? 'actual' : 'projected'}
                    </Text>
                  ) : null}
                  <Text className="lev-explain-text">
                    Matchup efficiency ×{d.mem.toFixed(2)}: his offense {sigma(d.off_z)}, the opposing defense {sigma(d.def_z)}, that defense vs his
                    position {sigma(d.pos_z)} (league standard deviations; above ×1.00 helps him)
                  </Text>
                  {d.teap != null ? <Text className="lev-explain-text">Efficiency-adjusted projection {d.teap.toFixed(1)} pts</Text> : null}
                  {d.p != null ? <Text className="lev-explain-text">Odds of a big game {(d.p * 100).toFixed(0)}%</Text> : null}
                  {d.verdict ? (
                    <Text className="lev-explain-text">
                      <Text className="font-sans-bold">{d.verdict}: </Text>
                      {VERDICT[d.verdict] ?? ''}
                    </Text>
                  ) : null}
                </>
              ) : null}

              <Text className="lev-explain-head">Colors</Text>
              <Text className="lev-explain-text">
                Green: under-owned. Gold: about even (within 1.5 points). Red: over-owned. A stronger shade means a bigger gap (1.5, 4 and 8
                points).
              </Text>
            </ScrollView>
          ) : null}
          <View className="mt-3">
            <Pressable className="btn-outline" onPress={onClose} accessibilityRole="button">
              <Text className="btn-outline-text">Close</Text>
            </Pressable>
          </View>
        </Pressable>
      </Pressable>
    </Modal>
  );
}
