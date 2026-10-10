# `/chain` — Lane C: the engine's client for Avalanche

**Owner:** Lane C. In v0 this package is a skeleton: `FujiChain()` raises `NotImplementedError` and the conformance test is skipped. The contracts themselves live in [`/contracts`](../contracts).

## Interface to implement

`sylo_chain.FujiChain` implements `sylo_spec.ports.ChainPort` (see `spec/python/sylo_spec/ports.py`):

- `domain()`, `commit()`, `deposit()`, `record_verification()`, `revoke()`, `release()`, `refund()`, `mark_executed()`, `status()`, `intent_hash()`.
- Calls are synchronous (the engine runs them in a worker thread). A revert raises `ChainReverted(reason=<Solidity custom error name>, tx=<TxRef or None>)`.
- `TxRef.explorerUrl` points at `https://testnet.snowtrace.io/tx/<hash>`; `TxRef.simulated` is `False`.
- `FujiChain.from_env()` reads `FUJI_RPC_URL`, `REGISTRY_ADDRESS`, `ESCROW_ADDRESS`, `TOKEN_ADDRESS` and the role keys from `.env` (see `docs/setup.md`).
- If construction fails, the engine falls back to `MockChain` and shows "chain" as degraded in the banner.

## Run

```bash
cd chain
uv sync
uv run pytest                                  # skipped until FujiChain exists
SYLO_RUN_FUJI_TESTS=1 uv run pytest            # against Fuji, with funded role wallets
```

`sylo_spec.devkeys` holds public Anvil keys: never fund them on Fuji.

## Tasks

See [`docs/roadmap-and-lanes.md`](../docs/roadmap-and-lanes.md), Lane C (C1.x for v1).
