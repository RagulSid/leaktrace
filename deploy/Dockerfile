# One image: FalkorDB 6.0.2 + the LeakTrace API + the helpers + the built web app.
# Build from the repo root:   docker build -f deploy/Dockerfile -t leaktrace:local .
# Run (practice data, rebuilt on every empty start):
#   docker run -p 8000:8000 -e LEAKTRACE_SECRET=... -e LEAKTRACE_DEMO_PASSWORD=... -e LEAKTRACE_MANAGER_PASSWORD=... leaktrace:local

# ---- the web app (static files)
FROM node:22.13.0-bookworm-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# ---- FalkorDB (the exact image used in development, pinned by tag and digest) + Python
FROM falkordb/falkordb:6.0.2@sha256:107455e862a824e45e8e9f5a7fbfdf5e00a08b14e13eae2577c72fd9e3f59ba6

RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv tini \
    && rm -rf /var/lib/apt/lists/* && python3 -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY app ./app
COPY packs ./packs
COPY scenario_generator ./scenario_generator
COPY --from=web /web/dist ./web/dist
COPY deploy/start.sh ./start.sh

# No FalkorDB browser in this image; FalkorDB listens on localhost only. The fixed rules choose the helpers' steps
# and fixed sentences word Ask LeakTrace answers unless these are changed (a model also needs LLM_* settings).
ENV BROWSER=0 PORT=8000 LEAKTRACE_DEMO_TENANT=demo FALKORDB_HOST=127.0.0.1 FALKORDB_PORT=6379 \
    LEAKTRACE_AGENT_CHOOSER=rules LEAKTRACE_ASK_PHRASER=template
EXPOSE 8000
ENTRYPOINT ["tini", "--", "bash", "/app/start.sh"]
