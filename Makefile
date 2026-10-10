# Sylo.ai — one entry point for setup, dev and tests (see docs/v0-build-spec.md §9.1)

FORGE ?= $(shell command -v forge 2>/dev/null || echo $(HOME)/.foundry/bin/forge)
ANVIL ?= $(shell command -v anvil 2>/dev/null || echo $(HOME)/.foundry/bin/anvil)

.PHONY: setup dev engine web test test-spec test-engine test-ml test-chain test-contracts test-web \
        fixtures fixtures-check anvil-deploy

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
	cd engine && uv run uvicorn sylo.main:app --reload --port 8000

web:
	pnpm -C web dev

test: test-spec test-engine test-ml test-chain test-contracts test-web

test-spec:
	cd spec/python && uv run pytest && uv run python ../scripts/validate.py

test-engine:
	cd engine && uv run pytest

test-ml:
	cd ml && uv run pytest

test-chain:
	cd chain && uv run pytest

test-contracts:
	cd contracts && $(FORGE) build && $(FORGE) test

test-web:
	pnpm -C web typecheck && pnpm -C web test && pnpm -C web build

fixtures:
	cd engine && uv run python -m sylo.record_fixtures

fixtures-check:
	cd engine && uv run python -m sylo.record_fixtures --check

# Deploys the three contracts on a throwaway local Anvil node with the public dev keys.
anvil-deploy:
	./scripts/anvil-deploy.sh
