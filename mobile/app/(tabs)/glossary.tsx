import { useState } from 'react';
import { ScrollView, Text, TextInput, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import BackLink from '@/components/BackLink';
import BrandHeader from '@/components/BrandHeader';
import SafeAreaView from '@/components/SafeAreaView';
import { GLOSSARY } from '@/constants/glossary';
import { FLOATING_TAB_BAR, useThemeColors } from '@/constants/theme';

/** Every DFS term the app uses, in plain language (from Settings and any definition sheet). */
export default function GlossaryScreen() {
  const insets = useSafeAreaInsets();
  const colors = useThemeColors();
  const [query, setQuery] = useState('');
  const q = query.trim().toLowerCase();
  const entries = [...GLOSSARY]
    .sort((a, b) => a.term.localeCompare(b.term))
    .filter((g) => !q || g.term.toLowerCase().includes(q) || g.definition.toLowerCase().includes(q) || g.match?.some((m) => m.toLowerCase().includes(q)));

  return (
    <SafeAreaView className="flex-1 bg-background" edges={['top', 'left', 'right']}>
      <ScrollView
        showsVerticalScrollIndicator={false}
        contentContainerClassName="screen-content"
        contentContainerStyle={{ paddingBottom: insets.bottom + FLOATING_TAB_BAR.space }}
        keyboardShouldPersistTaps="handled">
        <BrandHeader title="Glossary" />
        <BackLink />
        <Text className="screen-subtitle">
          What the app&apos;s DFS terms mean. Words with a dotted underline anywhere in the app open their definition.
        </Text>
        <TextInput
          className="input mb-3"
          value={query}
          onChangeText={setQuery}
          placeholder="Search terms"
          placeholderTextColor={colors.mutedForeground}
          autoCapitalize="none"
          autoCorrect={false}
          accessibilityLabel="Search terms"
        />
        <View className="settings-group mt-0">
          {entries.map((g, i) => (
            <View key={g.id} className={`glossary-row ${i === entries.length - 1 ? 'settings-row-last' : ''}`}>
              <Text className="settings-label">{g.term}</Text>
              <Text className="glossary-text">{g.definition}</Text>
            </View>
          ))}
          {!entries.length ? <Text className="home-empty-state px-4">No terms match “{query}”.</Text> : null}
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}
