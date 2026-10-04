# DFSRiches -- a normal long-running ASGI app, meant to run on any regular
# container host behind Cloudflare's proxy/CDN or a Cloudflare Tunnel (see
# README.md's "Deploying behind Cloudflare" section). This image does NOT
# run inside a Cloudflare Worker -- that's a different execution model
# (V8 isolates/Pyodide) that can't run Uvicorn or httpx's socket transport.

# Stage 1: the website -- the mobile app's web build (mobile/, Expo).
FROM node:22-slim AS web
WORKDIR /mobile
COPY mobile/package.json mobile/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY mobile/ ./
# No EXPO_PUBLIC_API_URL: the web build calls the server it's served from.
# Clerk's publishable key (public) can come from the host's build settings,
# else the app's built-in production key.
ARG EXPO_PUBLIC_CLERK_PUBLISHABLE_KEY
ENV EXPO_PUBLIC_CLERK_PUBLISHABLE_KEY=${EXPO_PUBLIC_CLERK_PUBLISHABLE_KEY}
RUN npx expo export --platform web --output-dir /web

# Stage 2: the API server, which also serves the web build.
FROM python:3.11-slim

WORKDIR /app

# Dependencies first so this layer is cached across code-only changes.
# libgomp1: LightGBM's OpenMP runtime (field-ownership model, app/field_ownership.py)
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/
COPY static/ static/
COPY templates/ templates/
COPY --from=web /web web/
COPY data/dk_overrides.json data/name_aliases.json data/optimal_lineups.json data/source_accuracy.json data/weather_effects.json data/

# Run as non-root. app/config.py creates data/cache/ on import; give the
# app user ownership so that succeeds.
RUN useradd --create-home --uid 1000 appuser \
    && chown -R appuser:appuser /app
USER appuser

ENV PYTHONUNBUFFERED=1
# Fewer glibc malloc arenas: the worker threads (asyncio.to_thread) otherwise
# each grow their own arena, adding tens of MB of fragmentation on a 512 MB host.
ENV MALLOC_ARENA_MAX=2
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT','8000') + '/healthz', timeout=3)"

CMD ["python", "-m", "app.main"]
