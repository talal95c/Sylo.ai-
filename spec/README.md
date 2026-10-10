# /spec — the shared contracts of Sylo.ai

Everything two lanes must agree on lives here: the event schema, the API, the EIP-712
types and test vector, the geography, the recorded scenario fixtures, and the Python
package `sylo_spec` (models, ports, scenarios, conformance suites).

## Rules for changing the spec

1. Changes are **additive only**: new event types, new optional fields, new endpoints. Never rename or remove.
2. Every data object allows additional properties, so consumers ignore unknown fields.
3. A spec pull request touches only `/spec` and needs approval from **two lanes** (producer and at least one consumer).
4. Changing an event's content requires re-recording fixtures (`make fixtures`) in the same pull request.

## What is here

| Path | Content | Produced by |
|---|---|---|
| `events.schema.json` | Event envelope and, per type, the required `data` fields (JSON Schema 2020-12) | hand-written, additive |
| `api.md` | Engine HTTP API | hand-written |
| `eip712.json` | EIP-712 domain, type strings, typehashes and one test vector per type | `python -m sylo_spec.eip712` (never edit by hand) |
| `geo/institutions.json` | Fictional institutions with coordinates, and the chain arc altitude | hand-written |
| `fixtures/*.jsonl` | Recorded event streams of the demo scenarios (one event per line) | `make fixtures` (Lane A only) |
| `scripts/validate.py` | Validates every fixture against the schema | — |
| `python/sylo_spec/` | Pydantic models, ports, EIP-712 helpers, dev keys, canonical scenarios, conformance suites | — |

## Commands

```bash
make test-spec                                   # package tests + fixture validation
cd spec/python && uv run python -m sylo_spec.eip712 --check   # the vector file matches the code
```

## Ports and conformance

- `RiskPort.score(order, ctx) -> RiskResult` — implemented by `engine/sylo/risk_rules.py` (v0) and `ml/sylo_risk` (v1).
- `ChainPort` (`commit`, `deposit`, `record_verification`, `revoke`, `release`, `refund`, `mark_executed`, `status`, `intent_hash`) — implemented by `engine/sylo/chain_mock.py` (v0) and `chain/sylo_chain` (v1).

```python
from sylo_spec.conformance import run_chain_conformance, run_risk_conformance
run_risk_conformance(MyRisk())
run_chain_conformance(lambda: MyChain())   # a FRESH chain per call
```

## Dev keys

`sylo_spec.devkeys` derives the public Anvil accounts (mnemonic `test test … junk`).
They are public: mock chain and local Anvil only. **Never fund them on Fuji.**
