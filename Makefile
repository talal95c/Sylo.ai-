SHELL := /bin/bash
.DEFAULT_GOAL := help

LOAD_ENV := set -a; if [ -f ../.env ]; then . ../.env; fi; set +a

.PHONY: help setup dev engine web test test-spec test-engine test-ml test-chain test-contracts test-web \
        fixtures fixtures-check demo-check verify-log integrity data train eval anvil-deploy

help:
	@echo "Sylo.ai — make targets"
	@echo "  setup           install Python (uv), web (pnpm) and Foundry dependencies"
	@echo "  dev             engine on :8000 and web on :3000 (Ctrl-C stops both)"
	@echo "  engine | web    run one of them"
	@echo "  test            every test suite (spec, engine, ml, chain, contracts, web)"
	@echo "  fixtures        re-record /spec/fixtures from the engine"
	@echo "  fixtures-check  fail if re-recording would change the fixtures"
	@echo "  demo-check      run the demo scenes and the three attacks against the engine and assert the events"
	@echo "  verify-log      recompute the hash chain of the decision log (engine/data/log.jsonl)"
	@echo "  integrity       run 300 changed or replayed payments through the adapters; writes engine/reports/integrity.json"
	@echo "  eval            evaluate the frozen Lane B model (SEED=B or C)"
	@echo "  data            generate seeded Lane B data (SEED=A, B or C)"
	@echo "  train           train the Lane B model on seed A"
	@echo "  anvil-deploy    deploy the contracts to a throwaway local Anvil node"

setup:
	git submodule update --init --recursive
	uv python install 3.12
	cd spec/python && uv sync
	cd ml && uv sync
	cd chain && uv sync
	cd engine && uv sync --all-extras
	pnpm -C web install

dev:
	./scripts/dev.sh

engine:
	cd engine && $(LOAD_ENV) && uv run uvicorn sylo.main:app --reload --port $${ENGINE_PORT:-8000}

web:
	cd web && $(LOAD_ENV) && pnpm dev

test: test-spec test-engine test-ml test-chain test-contracts test-web

test-spec:
	cd spec/python && uv run pytest -q && uv run python ../scripts/validate.py

test-engine:
	cd engine && uv run pytest -q

test-ml:
	cd ml && uv run pytest -q

test-chain:
	cd chain && uv run pytest -q

test-contracts:
	cd contracts && forge build && forge test

test-web:
	pnpm -C web exec next typegen && pnpm -C web typecheck && pnpm -C web test && pnpm -C web build

fixtures:
	cd engine && uv run python -m sylo.record_fixtures

fixtures-check:
	cd engine && uv run python -m sylo.record_fixtures --check

# Uses the engine that answers on ENGINE_PORT (so the flags of .env apply), or starts a temporary one.
demo-check:
	cd engine && $(LOAD_ENV) && uv run python ../scripts/demo_check.py

verify-log:
	cd engine && $(LOAD_ENV) && uv run python -m sylo.journal verify $${JOURNAL_PATH:-data/log.jsonl}

integrity:
	cd engine && uv run python -m sylo.integrity

eval:
	@test -n "$(SEED)" || (echo "Usage: make eval SEED=B" >&2; exit 2)
	cd engine && uv run --extra model python -m sylo_risk.evaluate --seed "$(SEED)"

data:
	@test -n "$(SEED)" || (echo "Usage: make data SEED=A" >&2; exit 2)
	cd ml && uv run python -m sylo_risk.sim --seed "$(SEED)"

train:
	cd ml && uv run python -m sylo_risk.train

anvil-deploy:
	./scripts/anvil_deploy.sh
