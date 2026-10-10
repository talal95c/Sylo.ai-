# `/spec` — the contract between the four lanes

Everything that two lanes must agree on lives here: event schema, API, EIP-712 types and test vector, geography, canonical scenario data, port interfaces, conformance suites and recorded fixtures.

## Rules for changing the spec

1. Changes are **additive only**: new event types, new optional fields, new endpoints. Never rename or remove.
2. Every data object allows additional properties, so consumers ignore unknown fields.
3. A spec pull request touches only `/spec` and needs approval from **two lanes** (producer and at least one consumer).
4. Changing an event's content requires re-recording fixtures (`make fixtures`) in the same pull request.

## Contents

| Path | What | Produced by |
|---|---|---|
| `events.schema.json` | JSON Schema (draft 2020-12) of every event; per-type `data` checks | hand-written |
| `api.md` | Engine HTTP API and stream | hand-written |
| `metrics.schema.json` / `metrics.sample.json` | Lane B risk metrics (`ml/reports/metrics.json`); the sample is labelled `sample: true` | hand-written |
| `eip712.json` | EIP-712 domain, type strings, enums and one test vector per type | **generated**: `cd spec/python && uv run python -m sylo_spec.eip712 --write` |
| `geo/institutions.json` | Fictional institutions with coordinates (globe nodes) | hand-written |
| `fixtures/*.jsonl` | Recorded event streams of the demo scenes (replay mode, web tests) | **generated**: `make fixtures` |
| `scripts/validate.py` | Validates fixtures against the schema and geography; checks `eip712.json` is current | — |
| `python/` | Package `sylo-spec`: models, ports, EIP-712 helpers, dev keys, scenarios, conformance suites | — |

## Fixtures

| File | Content |
|---|---|
| `scene1-legit.jsonl` | Scene 1: the legitimate payment, from `scenario.started` to `payment.credited` |
| `scene2-diverted.jsonl` | Scene 2 up to `verification.requested` (the money is held in escrow) |
| `scene2-deny.jsonl` | Continues Scene 2 after the supplier answers "deny": revoked, refunded, stopped |
| `scene2-confirm.jsonl` | Continues Scene 2 after "confirm": released, credited |
| `scene2b-release-revoked.jsonl` | Continues `scene2-deny`: the attacker's `release()` is rejected |

Recorded with a virtual clock starting `2026-10-11T09:00:00.000Z`, seed 42, speed 1. Recording twice gives identical files (`make fixtures-check`).

## Ports

- `RiskPort.score(order, ctx) -> RiskResult` — implemented by `RulesRisk` (engine) and `ModelRisk` (Lane B, v1). Must pass `sylo_spec.conformance.run_risk_conformance`.
- `CasePort.write(payment_id, events) -> CaseFile` — System 2 case file, implemented by `sylo_risk.CaseWriter` (Lane B). Advisory: no decision reads it; the engine emits it as `case.ready`.
- `RiskResult.oobResolvable` (optional, default false) — true when only the beneficiary's identity is in doubt, so an out-of-band confirmation can lift the risk.
- `ChainPort` — implemented by `MockChain` (engine) and `FujiChain` (Lane C, v1). Must pass `sylo_spec.conformance.run_chain_conformance`.

`sylo_spec.devkeys` holds the **public** Anvil keys (mnemonic `test test … junk`). Use them only in mock and local mode; never fund them on Fuji.

## Checks

```bash
cd spec/python
uv run pytest                       # vector, scenarios, fixtures against the schema
uv run python ../scripts/validate.py
```
