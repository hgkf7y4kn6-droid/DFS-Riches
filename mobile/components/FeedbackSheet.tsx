import { useState } from 'react';
import { Modal, Pressable, Text, TextInput, View } from 'react-native';

import { useThemeColors } from '@/constants/theme';
import { track } from '@/lib/analytics';

/** Settings' "Send feedback": a note that goes to the team (as a PostHog event tied to the account). */
export default function FeedbackSheet({ visible, onClose }: { visible: boolean; onClose: () => void }) {
  const colors = useThemeColors();
  const [text, setText] = useState('');
  const [sent, setSent] = useState(false);
  const close = () => {
    onClose();
    setSent(false);
  };
  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={close}>
      <Pressable className="week-backdrop" onPress={close} accessibilityRole="button" accessibilityLabel="Close">
        <Pressable className="week-sheet intro-sheet" onPress={() => {}}>
          <Text className="week-sheet-title">{sent ? 'Thanks!' : 'Send feedback'}</Text>
          {sent ? (
            <Text className="intro-text">We read every note. It helps decide what to build next.</Text>
          ) : (
            <>
              <Text className="caption mb-2">A bug, an idea, something confusing: tell us.</Text>
              <TextInput
                className="input"
                style={{ minHeight: 110, textAlignVertical: 'top' }}
                value={text}
                onChangeText={setText}
                multiline
                maxLength={2000}
                placeholder="What's on your mind?"
                placeholderTextColor={colors.mutedForeground}
                accessibilityLabel="Your feedback"
              />
            </>
          )}
          <View className="mt-3 flex-row gap-2">
            {sent ? null : (
              <Pressable className="btn-outline flex-1 justify-center" onPress={close} accessibilityRole="button">
                <Text className="btn-outline-text">Cancel</Text>
              </Pressable>
            )}
            <Pressable
              className={`btn flex-1 ${!sent && !text.trim() ? 'opacity-60' : ''}`}
              disabled={!sent && !text.trim()}
              onPress={() => {
                if (sent) return close();
                track('feedback_submitted', { message: text.trim() });
                setText('');
                setSent(true);
              }}
              accessibilityRole="button">
              <Text className="btn-text">{sent ? 'Close' : 'Send'}</Text>
            </Pressable>
          </View>
        </Pressable>
      </Pressable>
    </Modal>
  );
}
