# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:0.12.23 AS uv
FROM node:24.19.0-bookworm-slim AS node

FROM python:3.12.14-slim-bookworm AS python-runtime
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_PYTHON_DOWNLOADS=never \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN --mount=type=secret,id=system_ca \
    if [ -f /run/secrets/system_ca ]; then export SSL_CERT_FILE=/run/secrets/system_ca; fi; \
    uv sync --locked --no-dev --no-editable

FROM python-runtime AS web-build
# Node is needed only while building the existing frontend and checking its schema.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libstdc++6 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm
COPY web/package.json web/package-lock.json ./web/
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/proxy_ca; fi; \
    npm --prefix web ci --strict-ssl=true
RUN --mount=type=secret,id=system_ca \
    if [ -f /run/secrets/system_ca ]; then export SSL_CERT_FILE=/run/secrets/system_ca; fi; \
    uv sync --locked
COPY web ./web
COPY scripts/export_web_schema.py ./scripts/export_web_schema.py
RUN npm --prefix web run build

FROM python-runtime AS app
COPY --from=web-build /app/web/dist ./web/dist
COPY deploy/entrypoint.sh /usr/local/bin/agenttinker-entrypoint
RUN chmod 0555 /usr/local/bin/agenttinker-entrypoint \
    && useradd --uid 10001 --create-home agenttinker \
    && mkdir /data \
    && chown agenttinker:agenttinker /data
USER agenttinker
EXPOSE 8000
STOPSIGNAL SIGTERM
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c 'import os,urllib.request; urllib.request.urlopen("http://127.0.0.1:"+os.environ.get("PORT","8000")+"/api/v1/scenarios", timeout=3).close()'
ENTRYPOINT ["agenttinker-entrypoint"]
