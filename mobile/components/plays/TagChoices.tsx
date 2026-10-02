import { Pressable, Text, View } from 'react-native';

import { TAG_STYLE } from '@/components/plays/TagPill';
import type { Pool } from '@/lib/pool-tags-context';

const ORDER: PlayTag[] = ['prioritize', 'neutral', 'fade'];
// Selected choice: the tag's own colors.
const ACTIVE: Record<PlayTag, string> = {
  prioritize: 'tag-choice tag-prioritize border-success',
  neutral: 'tag-choice tag-neutral border-muted-foreground',
  fade: 'tag-choice tag-fade border-danger',
};

/** The user's Prioritize / Neutral / Fade call for this player in their pool, with the model's tag for reference. */
export default function TagChoices({ player, pool, onDone }: { player: PlayPlayer; pool: Pool; onDone?: () => void }) {
  const current = pool.tagOf(player);
  const mine = pool.isMine(player);
  return (
    <View className="tag-choices">
      <Text className="tag-choice-label">Your pool</Text>
      <View className="tag-choice-row">
        {ORDER.map((t) => {
          const active = t === current;
          return (
            <Pressable
              key={t}
              className={active ? ACTIVE[t] : 'tag-choice'}
              onPress={() => (pool.setTag(player, t), onDone?.())}
              accessibilityRole="radio"
              accessibilityState={{ selected: active }}>
              <Text className={active ? TAG_STYLE[t].text : 'tag-choice-text'}>{TAG_STYLE[t].label}</Text>
            </Pressable>
          );
        })}
      </View>
      <Text className="dfs-reason">
        Model: {TAG_STYLE[player.tag].label} · {player.tag_reason}
      </Text>
      {mine ? (
        <Pressable onPress={() => (pool.setTag(player, player.tag), onDone?.())} accessibilityRole="button">
          <Text className="tag-choice-reset">Reset to the model&apos;s tag</Text>
        </Pressable>
      ) : null}
    </View>
  );
}
