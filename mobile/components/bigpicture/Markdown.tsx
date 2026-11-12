import { Fragment } from 'react';
import { Text, View } from 'react-native';

type Block =
  | { kind: 'h'; text: string }
  | { kind: 'p'; text: string }
  | { kind: 'li'; text: string; marker: string }
  | { kind: 'table'; rows: string[][] };

const cells = (line: string) => line.trim().replace(/^\||\|$/g, '').split('|').map((c) => c.trim());

/** The report's markdown: headings, paragraphs, bullet and numbered lists, simple tables. */
function parseMarkdown(md: string): Block[] {
  const blocks: Block[] = [];
  let para: string[] = [];
  const flush = () => {
    if (para.length) blocks.push({ kind: 'p', text: para.join(' ') });
    para = [];
  };
  for (const raw of (md || '').split('\n')) {
    const line = raw.trimEnd();
    const t = line.trim();
    if (!t) {
      flush();
      continue;
    }
    if (t.startsWith('|')) {
      flush();
      if (/^\|[\s:|-]+\|?$/.test(t)) continue; // the header separator
      const last = blocks[blocks.length - 1];
      if (last?.kind === 'table') last.rows.push(cells(t));
      else blocks.push({ kind: 'table', rows: [cells(t)] });
      continue;
    }
    const h = /^#{1,4}\s+(.*)$/.exec(t);
    const li = /^([-*•])\s+(.*)$/.exec(t);
    const ol = /^(\d{1,2})[.)]\s+(.*)$/.exec(t);
    if (h) {
      flush();
      blocks.push({ kind: 'h', text: h[1] });
    } else if (li || ol) {
      flush();
      blocks.push({ kind: 'li', marker: li ? '•' : `${ol![1]}.`, text: (li ? li[2] : ol![2]) as string });
    } else {
      const last = blocks[blocks.length - 1];
      // A wrapped list item continues on the next indented line.
      if (!para.length && last?.kind === 'li' && /^\s{2,}/.test(raw)) last.text += ` ${t}`;
      else para.push(t);
    }
  }
  flush();
  return blocks;
}

/** **bold** spans inside a line. */
function Inline({ text }: { text: string }) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return (
    <>
      {parts.map((p, i) =>
        p.startsWith('**') && p.endsWith('**') && p.length > 4 ? (
          <Text key={i} className="bp-strong">
            {p.slice(2, -2)}
          </Text>
        ) : (
          <Fragment key={i}>{p}</Fragment>
        ),
      )}
    </>
  );
}

export default function Markdown({ text }: { text: string }) {
  const blocks = parseMarkdown(text);
  return (
    <View>
      {blocks.map((b, i) => {
        if (b.kind === 'h')
          return (
            <Text key={i} className="bp-md-h">
              <Inline text={b.text.replace(/\*\*/g, '')} />
            </Text>
          );
        if (b.kind === 'li')
          return (
            <View key={i} className="bp-md-li">
              <Text className="bp-md-marker">{b.marker}</Text>
              <Text className="bp-md-text flex-1">
                <Inline text={b.text} />
              </Text>
            </View>
          );
        if (b.kind === 'table')
          return (
            <View key={i} className="bp-md-table">
              {b.rows.map((r, j) => (
                <Text key={j} className={j === 0 ? 'bp-md-th' : 'bp-md-td'}>
                  {r.join('  ·  ')}
                </Text>
              ))}
            </View>
          );
        return (
          <Text key={i} className="bp-md-p">
            <Inline text={b.text} />
          </Text>
        );
      })}
    </View>
  );
}
