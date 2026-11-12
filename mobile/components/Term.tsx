import { Fragment, type ReactNode } from 'react';
import { type GestureResponderEvent, Text } from 'react-native';

import { GLOSSARY } from '@/constants/glossary';
import { useGlossary } from '@/lib/glossary-context';

// Dotted on iOS and the web; Android draws a solid underline.
const TERM_STYLE = { textDecorationLine: 'underline', textDecorationStyle: 'dotted' } as const;

/**
 * A jargon word with a dotted underline: tap it for its plain-language
 * definition (constants/glossary.ts). Renders as nested text, so it sits
 * inside any <Text> line; the tap stays with the word even inside a
 * tappable card.
 */
export function Term({ id, children }: { id: string; children: ReactNode }) {
  const { define } = useGlossary();
  return (
    <Text
      style={TERM_STYLE}
      onPress={(e: GestureResponderEvent) => {
        e?.stopPropagation?.();
        define(id);
      }}
      accessibilityRole="button"
      accessibilityHint="Shows what this means"
      suppressHighlighting>
      {children}
    </Text>
  );
}

const escape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const SPELLINGS = GLOSSARY.flatMap((g) => [g.term, ...(g.match ?? [])].map((text) => ({ text: text.toLowerCase(), id: g.id }))).sort(
  (a, b) => b.text.length - a.text.length,
);
const ID_BY_SPELLING = new Map(SPELLINGS.map((s) => [s.text, s.id]));
// Whole words only: no letter or digit right before or after the match (no
// lookbehind, so the lead character is captured and skipped).
const PATTERN = new RegExp(`(^|[^\\w$])(${SPELLINGS.map((s) => escape(s.text)).join('|')})(?![\\w%])`, 'gi');

/**
 * Plain text with every glossary term in it tappable (the first mention of
 * each term only, so a sentence doesn't turn into a row of links). Use it
 * inside a <Text> that carries the styling.
 */
export function Glossed({ text }: { text: string }) {
  const seen = new Set<string>();
  const out: ReactNode[] = [];
  let last = 0;
  for (const m of text.matchAll(PATTERN)) {
    const word = m[2];
    const id = ID_BY_SPELLING.get(word.toLowerCase());
    if (!id || seen.has(id) || m.index == null) continue;
    seen.add(id);
    const start = m.index + m[1].length;
    if (start > last) out.push(text.slice(last, start));
    out.push(
      <Term key={`${id}-${start}`} id={id}>
        {word}
      </Term>,
    );
    last = start + word.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return <Fragment>{out}</Fragment>;
}
