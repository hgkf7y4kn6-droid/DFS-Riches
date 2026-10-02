// DFSRiches API (the FastAPI app in this repo). Set EXPO_PUBLIC_API_URL to
// point at a local server, e.g. http://192.168.1.20:8000 on the same Wi-Fi.
export const API_BASE_URL = (process.env.EXPO_PUBLIC_API_URL ?? 'https://dfs-riches.onrender.com').replace(/\/$/, '');

/** DraftKings Classic and Showdown salary cap. */
export const SALARY_CAP = 50000;
/** Lineups the builder can hold per slate (same as the website). */
export const MAX_LINEUPS = 5;
