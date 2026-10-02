# DFSRiches mobile

An Expo Router + NativeWind app for the DFSRiches API (the FastAPI app in the
repo root). It reads live data: this week's schedule, every DraftKings slate
(Sunday Main, Full Week, and a Showdown for each island game -- weeknight,
Sunday night, international and holiday games), projected optimal lineups, a
lineup builder, and Lines & Performance.

```bash
cd mobile
npm install
npx expo start            # scan the QR code with Expo Go, or press i / a / w
```

The app talks to `https://dfs-riches.onrender.com` by default. To use a local
API server instead (`python -m uvicorn app.main:app --host 0.0.0.0` from the
repo root), set its address before starting:

```bash
EXPO_PUBLIC_API_URL=http://<your-computer's-LAN-IP>:8000 npx expo start
```

## Layout

| Path | What's there |
| --- | --- |
| `app/_layout.tsx` | Root stack: safe-area provider, week data provider, `global.css` |
| `app/(tabs)/_layout.tsx` | Bottom tabs, mapped from `tabs` in `constants/data.ts`; padded with `useSafeAreaInsets()` |
| `app/(tabs)/index.tsx` | Home: header with add-entry button, balance card (money spent on entries, next lineup lock), upcoming games, all games, profit/loss tracker, slates, lineups, builder, Lines & Performance |
| `app/(tabs)/lineups.tsx` | Slates, projected optimal lineups and the lineup builder |
| `app/(tabs)/lines.tsx` | Lines & Performance for every game |
| `components/` | The pieces those screens are built from |
| `constants/data.ts` | Tabs, Home user, Home sections, builder filters |
| `constants/icons.ts`, `constants/images.ts` | Centralized icon and image imports |
| `lib/utils.ts` | `formatCurrency` and other formatters |
| `lib/api.ts`, `lib/week-context.tsx` | API client and shared week/slate/lineup state |
| `lib/submissions.ts`, `lib/submissions-context.tsx` | Logged contest entries (saved on the device) and the profit/loss math |
| `lib/lineups.ts` | Lineup rules, ported from the website's `static/lineups.js` |
| `lib/lines.ts` | Lines & Performance formatting, ported from `static/app.js` |
| `lib/games.ts` | Turns API games into the `UpcomingGame` cards (team logos from Sleeper's CDN) |
| `type.d.ts` | Global types for tabs, Home data and every API response |
| `global.css` | Tailwind layers plus the app's component classes (auth, home, games, players, lineups, forms, profit/loss) |

`assets/images/avatar.png` and `assets/images/splash-pattern.png` are
placeholders: replace them with the design's files (same names) and nothing
else needs to change.

Before committing: `npx tsc --noEmit && npx expo lint`.
