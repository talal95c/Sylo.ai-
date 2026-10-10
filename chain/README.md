# /chain — Lane C (chain client)

**Owner:** Lane C. **Package:** `sylo-chain` (`sylo_chain`). **Status in v0:** skeleton.
The Solidity contracts live in [`/contracts`](../contracts).

## What to implement (v1)

`sylo_chain.FujiChain` implements `sylo_spec.ports.ChainPort`:
`domain`, `commit`, `deposit`, `record_verification`, `revoke`, `release`, `refund`, `mark_executed`, `status`, `intent_hash`.

- web3.py 7; refuse to start unless the chain id is 43113; two RPC endpoints with fallback.
- The relayer key sends the transactions; wait for receipts; one nonce manager per sender.
- Custom errors decoded to their names → `ChainReverted(reason)`; `TxRef` carries the explorer URL.
- For attacks (`caller="attacker"`), send with a fixed gas limit so the failed transaction is mined and visible.

The engine's `MockChain` (`engine/sylo/chain_mock.py`) mirrors the contract rules and is the reference behaviour.

## How to check

```bash
cd chain && uv sync && uv run pytest     # test_conformance.py is skipped while FujiChain raises NotImplementedError
CHAIN_MODE=fuji make engine              # the engine falls back to the mock and shows "degraded: chain" if the import fails
```

`run_chain_conformance(make_chain, keys=..., token=..., id_prefix=..., nonce_start=...)` accepts the real role keys,
the token address and fresh ids, so the same seven steps run on Anvil and on Fuji.

## Tasks

See [`docs/roadmap-and-lanes.md`](../docs/roadmap-and-lanes.md): C1.0 (spec additions), C1.1 (contract hardening),
C1.2 (Fuji deployment and verification), C1.3 (`FujiChain`), C1.4 (visible failed transactions), C1.5 (attack scripts), then v2.

Never fund the public dev keys of `sylo_spec.devkeys` on Fuji.
