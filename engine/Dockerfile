FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY spec/python/pyproject.toml ./spec/python/pyproject.toml
COPY spec/python/sylo_spec ./spec/python/sylo_spec
COPY ml/pyproject.toml ./ml/pyproject.toml
COPY ml/sylo_risk ./ml/sylo_risk
COPY ml/models ./ml/models
COPY ml/reports/metrics.json ./ml/reports/metrics.json
COPY chain/pyproject.toml ./chain/pyproject.toml
COPY chain/sylo_chain ./chain/sylo_chain
COPY engine/pyproject.toml ./engine/pyproject.toml
COPY engine/uv.lock ./engine/uv.lock
COPY engine/sylo ./engine/sylo
COPY engine/packs ./engine/packs
COPY engine/profiles ./engine/profiles
COPY engine/reports/integrity.json ./engine/reports/integrity.json

WORKDIR /app/engine
RUN uv sync --frozen --no-dev --all-extras

ENV PATH=/app/engine/.venv/bin:$PATH
ENV RISK_MODE=model
ENV LLM_MODE=cached
ENV JEV_MODE=cached
ENV CHAIN_MODE=mock

EXPOSE 8000

CMD uvicorn sylo.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1
