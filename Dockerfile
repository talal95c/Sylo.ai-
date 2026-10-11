FROM node:22-bookworm-slim AS web-build

RUN corepack enable

WORKDIR /app
COPY spec ./spec
COPY web ./web

WORKDIR /app/web
RUN pnpm install --frozen-lockfile

ENV NEXT_OUTPUT=standalone \
    ENGINE_INTERNAL_URL=http://127.0.0.1:8000 \
    NEXT_PUBLIC_SOURCE=live \
    NEXT_PUBLIC_ENGINE_URL= \
    NEXT_PUBLIC_ENGINE_CONNECT_TIMEOUT_MS=15000 \
    NEXT_TELEMETRY_DISABLED=1

RUN pnpm build

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS runtime

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=node:22-bookworm-slim /usr/local/bin/node /usr/local/bin/node

WORKDIR /app

COPY spec ./spec
COPY ml/pyproject.toml ./ml/pyproject.toml
COPY ml/sylo_risk ./ml/sylo_risk
COPY ml/models ./ml/models
COPY ml/reports/metrics.json ./ml/reports/metrics.json
COPY chain/pyproject.toml ./chain/pyproject.toml
COPY chain/sylo_chain ./chain/sylo_chain
COPY contracts/deployments/43113.json ./contracts/deployments/43113.json
COPY engine/pyproject.toml ./engine/pyproject.toml
COPY engine/uv.lock ./engine/uv.lock
COPY engine/sylo ./engine/sylo
COPY engine/packs ./engine/packs
COPY engine/profiles ./engine/profiles
COPY engine/reports/integrity.json ./engine/reports/integrity.json
COPY scripts/start-render.sh ./scripts/start-render.sh

WORKDIR /app/engine
RUN uv sync --frozen --no-dev --all-extras
RUN /app/engine/.venv/bin/python -c "import sylo_chain, web3"

ENV PATH=/app/engine/.venv/bin:$PATH
ENV RISK_MODE=model
ENV LLM_MODE=cached
ENV JEV_MODE=cached
ENV CHAIN_MODE=mock

COPY --from=web-build /app/web/.next/standalone/ /app/web/
COPY --from=web-build /app/web/.next/static /app/web/.next/static
COPY --from=web-build /app/web/public /app/web/public

RUN test -f /app/web/server.js

EXPOSE 10000

CMD ["/app/scripts/start-render.sh"]
