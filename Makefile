SHELL := /bin/bash
.DEFAULT_GOAL := help

LOAD_ENV := set -a; if [ -f ../.env ]; then . ../.env; fi; set +a

.PHONY: help setup dev engine web test test-spec test-engine test-ml test-chain test-contracts test-web \
        fixtures fixtures-check anvil-deploy

help:
	@echo "Sylo.ai — make targets"
	@echo "  setup           install Python (uv), web (pnpm) and Foundry dependencies"
	@echo "  dev             engine on :8000 and web on :3000 (Ctrl-C stops both)"
	@echo "  engine | web    run one of them"
	@echo "  test            every test suite (spec, engine, ml, chain, contracts, web)"
	@echo "  fixtures        re-record /spec/fixtures from the engine"
	@echo "  fixtures-check  fail if re-recording would change the fixtures"
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
	pnpm -C web dev

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
	pnpm -C web typecheck && pnpm -C web test && pnpm -C web build

fixtures:
	cd engine && uv run python -m sylo.record_fixtures

fixtures-check:
	cd engine && uv run python -m sylo.record_fixtures --check

anvil-deploy:
	./scripts/anvil_deploy.sh
