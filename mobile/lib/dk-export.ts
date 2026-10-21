import { Platform, Share } from 'react-native';

import { template } from '@/lib/lineups';

/**
 * DraftKings' lineup upload file: a header of slot names (QB,RB,...,DST or
 * CPT,FLEX,...) and one row of DraftKings player ids per lineup -- the IDs
 * DraftKings' own salary file uses, which are the draftable ids. Only
 * complete lineups are included.
 */
export function dkUploadCsv(lineups: BuilderLineup[], slateType: SlateType): { csv: string; count: number } {
  const header = template(slateType).map((d) => d.label);
  const rows = lineups.filter((lu) => lu.length === header.length && lu.every((p) => p?.dk_draftable_id != null)).map((lu) => lu.map((p) => String(p!.dk_draftable_id)).join(','));
  return { csv: [header.join(','), ...rows].join('\n') + '\n', count: rows.length };
}

/** Downloads the file on the web; opens the share sheet (save to Files, email, etc.) on phones. */
export async function shareDkUpload(csv: string, filename: string) {
  if (Platform.OS === 'web') {
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    return;
  }
  await Share.share({ title: filename, message: csv });
}
