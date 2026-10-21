// "What's new" after an update (components/WhatsNew.tsx): the newest entry
// shows once to people who used an earlier version. Add an entry for a
// release worth telling users about; patch updates without one show nothing.
export interface WhatsNewEntry {
  /** The app version (mobile/app.json) this note is for. */
  version: string;
  title: string;
  items: string[];
}

export const WHATS_NEW: WhatsNewEntry[] = [
  {
    version: '1.1.29',
    title: "What's new",
    items: [
      'Tell us what you play (Settings → Your game): Home leads with your top plays and Best contests with fees that fit your budget.',
      'Your last slate, tab and builder sorts follow you to every device.',
      'One lineup builder: open Lineups and switch between Cash and Tournament to see that field’s ownership.',
      'Faster: the model is ready the moment you open it, and the last week stays readable offline.',
      'Bigger, easier-to-read text throughout.',
    ],
  },
];
