#!/usr/bin/env bash
# Cloudflare Pages / Workers build (wrangler.jsonc runs it on deploy): the app's website as static files, calling the API
# server on Render for data and account sync.
#
# Pages project settings:
#   Build command:           bash scripts/build_pages.sh
#   Build output directory:  pages-dist
#   Environment variables (optional):
#     API_URL                          default https://dfs-riches.onrender.com
#     EXPO_PUBLIC_CLERK_PUBLISHABLE_KEY  Clerk *publishable* key (pk_...); the
#                                      app has the current one built in.
#   Never put CLERK_SECRET_KEY or DATABASE_URL on Pages: they belong to the
#   Render server only.
set -euo pipefail
cd "$(dirname "$0")/.."
export EXPO_PUBLIC_API_URL="${API_URL:-https://dfs-riches.onrender.com}"
cd mobile
npm ci --no-audit --no-fund
rm -rf ../pages-dist
npx expo export --platform web --output-dir ../pages-dist --clear
# Hashed bundles never change; pages revalidate.
cat > ../pages-dist/_headers <<'HEADERS'
/_expo/*
  Cache-Control: public, max-age=31536000, immutable
HEADERS
# Client-side routes Expo didn't pre-render fall back to the app shell
# (Workers does this with not_found_handling in wrangler.jsonc).
[ -n "${CF_WORKERS:-}" ] || echo '/* /index.html 200' > ../pages-dist/_redirects
echo "Built pages-dist (API: $EXPO_PUBLIC_API_URL)"
