# `/chain` — Lane C: the engine's client for Avalanche

**Owner:** Lane C. `sylo_chain.FujiChain` implements `sylo_spec.ports.ChainPort` against the deployed `PaymentRegistry` and `PaymentEscrow` (addresses in [`contracts/deployments/43113.json`](../contracts/deployments/43113.json)). The contracts themselves live in [`/contracts`](../contracts).

## Interface

- `domain()`, `commit()`, `deposit()`, `record_verification()`, `revoke()`, `release()`, `refund()`, `mark_executed()`, `status()`, `intent_hash()`, plus `freeze()` and `pause_corridor()` (same names as `MockChain`).
- Calls are synchronous and serialised by a lock (the engine runs them in a worker thread).
- Every write is simulated first. A revert raises `ChainReverted(reason=<Solidity custom error name>, tx=None)` and spends no gas.
- Attacks are sent anyway, so the failure is mined and visible on Snowtrace: `release(pid, caller="attacker")`, or any call inside `with chain.visible_failures():`. They raise `ChainReverted(reason, tx=<TxRef of the failed tx>)`.
- `TxRef.explorer_url` is `https://testnet.snowtrace.io/tx/<hash>` on Fuji (`None` on Anvil); `TxRef.simulated` is `False`.
- Reads and simulations are pinned to the block of our last mined transaction: public Fuji RPCs are load balanced and a plain "latest" read can return stale state.

## Configuration

`FujiChain.from_env()` reads (see [`docs/setup.md`](../docs/setup.md)):

| Variable | Use |
|---|---|
| `FUJI_RPC_URL`, `FUJI_RPC_URL_2` | RPC endpoints; the second is the fallback on a network error |
| `CHAIN_ID` | Must be `43113`; any other value, or a node on another chain, refuses to start |
| `REGISTRY_ADDRESS`, `ESCROW_ADDRESS` | Optional; default to `contracts/deployments/43113.json` |
| `RELAYER_PK` | Required: sends the engine's transactions (router and executor roles) |
| `ANALYST_SIGNER_PK`, `GUARDIAN_PK`, `ATTACKER_PK` | Optional: `freeze`, `pause_corridor`, scene 2b attacks |
| `EXPLORER_BASE_URL` | Defaults to `https://testnet.snowtrace.io` |

The router, verifier and analyst keys sign EIP-712 messages in the engine; `FujiChain` only relays them. If construction fails, the engine falls back to `MockChain` and shows "chain" as degraded in the banner.

## Run

```bash
cd chain
uv sync
uv run pytest                          # Anvil tests (need Foundry) + ABI checks
SYLO_RUN_FUJI_TESTS=1 uv run pytest    # also the conformance suite on Fuji (funded role wallets in .env)
```

The Anvil tests start a throwaway node, deploy with `script/Deploy.s.sol` and `script/Approve.s.sol`, then run `run_chain_conformance` and the attack, freeze, pause and RPC-fallback cases.

After a change in `contracts/src`, run `scripts/export-abi.sh`: the ABIs in `sylo_chain/abi/` are copied from Foundry, and `tests/test_abi.py` fails while they differ.

`sylo_spec.devkeys` holds public Anvil keys: never fund them on Fuji.

## Tasks

See [`docs/roadmap-and-lanes.md`](../docs/roadmap-and-lanes.md), Lane C (C1.x for v1).
