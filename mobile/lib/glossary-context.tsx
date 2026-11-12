import { router } from 'expo-router';
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react';
import { Modal, Pressable, Text, View } from 'react-native';

import { GLOSSARY_BY_ID } from '@/constants/glossary';
import { track } from '@/lib/analytics';

interface GlossaryValue {
  /** Open the definition sheet for a glossary id. */
  define: (id: string) => void;
}

const GlossaryContext = createContext<GlossaryValue | null>(null);

/** One shared definition sheet, opened by tapping a <Term> anywhere in the app. */
export function GlossaryProvider({ children }: { children: ReactNode }) {
  const [shown, setShown] = useState<string | null>(null);
  const define = useCallback((id: string) => {
    if (!GLOSSARY_BY_ID[id]) return;
    track('glossary_term_opened', { term: id });
    setShown(id);
  }, []);
  const value = useMemo(() => ({ define }), [define]);
  const entry = shown ? GLOSSARY_BY_ID[shown] : null;
  const close = () => setShown(null);

  return (
    <GlossaryContext.Provider value={value}>
      {children}
      <Modal visible={entry != null} transparent animationType="fade" onRequestClose={close}>
        <Pressable className="week-backdrop" onPress={close} accessibilityLabel="Close">
          <Pressable className="week-sheet" onPress={() => {}}>
            {entry ? (
              <>
                <Text className="week-sheet-title">{entry.term}</Text>
                <Text className="lev-explain-text">{entry.definition}</Text>
              </>
            ) : null}
            <View className="mt-3 flex-row gap-2">
              <Pressable
                className="btn-outline flex-1 justify-center"
                onPress={() => {
                  close();
                  router.push('/glossary');
                }}
                accessibilityRole="button">
                <Text className="btn-outline-text">Full glossary</Text>
              </Pressable>
              <Pressable className="btn flex-1 justify-center" onPress={close} accessibilityRole="button">
                <Text className="btn-text">Got it</Text>
              </Pressable>
            </View>
          </Pressable>
        </Pressable>
      </Modal>
    </GlossaryContext.Provider>
  );
}

export function useGlossary(): GlossaryValue {
  const ctx = useContext(GlossaryContext);
  if (!ctx) throw new Error('useGlossary must be used inside <GlossaryProvider>');
  return ctx;
}
