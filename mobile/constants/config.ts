import { Platform } from 'react-native';

// DFSRiches API (the FastAPI app in this repo). Set EXPO_PUBLIC_API_URL to
// point at a local server, e.g. http://192.168.1.20:8000 on the same Wi-Fi.
// The web build is served by that same server (the website), so on the web
// it calls its own origin; the phone app calls the hosted server.
export const API_BASE_URL = (
  process.env.EXPO_PUBLIC_API_URL ?? (Platform.OS === 'web' ? '' : 'https://dfs-riches.onrender.com')
).replace(/\/$/, '');

/** DraftKings Classic and Showdown salary cap. */
export const SALARY_CAP = 50000;
/** Lineups the builder can hold per slate (same as the website). */
export const MAX_LINEUPS = 5;

/** Clerk (sign-in). Public by design; override with EXPO_PUBLIC_CLERK_PUBLISHABLE_KEY. */
export const CLERK_PUBLISHABLE_KEY =
  process.env.EXPO_PUBLIC_CLERK_PUBLISHABLE_KEY ?? 'pk_test_cmVsYXRlZC1jb3VnYXItMjE5MC5jbGVyay5hY2NvdW50cy5kZXYk';
