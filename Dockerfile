# DFSRiches -- a normal long-running ASGI app, meant to run on any regular
# container host behind Cloudflare's proxy/CDN or a Cloudflare Tunnel (see
# README.md's "Deploying behind Cloudflare" section). This image does NOT
# run inside a Cloudflare Worker -- that's a different execution model
# (V8 isolates/Pyodide) that can't run Uvicorn or httpx's socket transport.

FROM python:3.11-slim

WORKDIR /app

# Dependencies first so this layer is cached across code-only changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/
COPY static/ static/
COPY templates/ templates/
COPY data/dk_overrides.json data/name_aliases.json data/optimal_lineups.json data/

# Run as non-root. app/config.py creates data/cache/ on import; give the
# app user ownership so that succeeds.
RUN useradd --create-home --uid 1000 appuser \
    && chown -R appuser:appuser /app
USER appuser

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT','8000') + '/healthz', timeout=3)"

CMD ["python", "-m", "app.main"]
