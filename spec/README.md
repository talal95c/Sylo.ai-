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
| `scene2b-swap-beneficiary.jsonl` | v1. Continues `scene2-deny`: a leg with a changed beneficiary is refused by the rail adapter, then `deposit` of the modified intent reverts |
| `scene2b-replay.jsonl` | v1. Continues `scene2-deny`: the signed intent is committed a second time and reverts |
| `scene2-simswap.jsonl` | v1. Scenario `diverted_simswap`, complete: the known number was SIM-swapped, nobody is texted, the analyst revokes |
| `samples-v1.jsonl` | v1. The diverted scenario with `HUMAN_STEPS=manual`: two approvals, the supplier's denial, the analyst's confirmation, then the three attacks. One example of every v1 event |
| `samples-scene3-mule-wave.jsonl` | v2. Three payments of other payers (`traffic.sample`), `cluster.detected`, `breaker.on`, then the diverted payment into the same region: HIGH with rule R-CB-01, held, revoked |
| `samples-scene4-guardian.jsonl` | v2. While the diverted payment is held, `guardian.incident` (the guardian froze it); the supplier confirms, `release` reverts, the analyst revokes |
| `samples-scene5-outage.jsonl` | v2. Scenario `outage`: `rail.down` for R3, the legitimate payment goes through R1, `rail.up` |
| `cluster-sample.json` | v2. One synthetic mule cluster near Aflao (coarse points only), the engine's fallback when Lane B's detector is not installed, and the three payments of the mule wave (three payers, one young account; `accountAgeDays` and `successfulPayments` feed the detector) |

Recorded with a virtual clock starting `2026-10-11T09:00:00.000Z`, seed 42, speed 1. Recording twice gives identical files (`make fixtures-check`). The scenes are recorded with `auto: true`; from v1 they contain `approval.required`, `alert.raised`, `case.ready` and `case.action` (see [`api.md`](api.md)). The three `scene2b-*` files each start right after `scene2-deny`, so they can be replayed in any order.

## Ports

- `RiskPort.score(order, ctx) -> RiskResult` — implemented by `RulesRisk` (engine) and `ModelRisk` (Lane B, v1). Must pass `sylo_spec.conformance.run_risk_conformance`.
- `CasePort.write(payment_id, events) -> CaseFile` — System 2 case file, implemented by `sylo_risk.CaseWriter` (Lane B). Advisory: no decision reads it; the engine emits it as `case.ready`. The engine checks the answer (summary of at most 120 words, every citation and sentence ref is a rule, signal or event of the payment) and otherwise builds the case file from the rules (`llm: "off"`).
- `RiskResult.oobResolvable` (optional, default false) — true when only the beneficiary's identity is in doubt, so an out-of-band confirmation can lift the risk. The engine then treats a HIGH payment like a MEDIUM one: conditional settlement, never a direct payment.
- `ClusterPort.detect(window) -> list[Cluster]` — v2. `window` is the payments of the last hour (`WindowPayment`: ids, amount, time, and when known the payer id, payee id, account age in days and number of past payments; no names). Implemented by the engine's adapter over Lane B's `sylo_risk.clusters.detect` (`DetectorClusterPort`), with the sample (`SampleClusterPort`, which reads `fixtures/cluster-sample.json`) as the fallback. A returned cluster proposes a circuit breaker.
- `ChainPort` — implemented by `MockChain` (engine) and `FujiChain` (Lane C, v1). Must pass `sylo_spec.conformance.run_chain_conformance`. The engine also calls `freeze(payment_id)` when the chain client has it (analyst action `FREEZE`).

`sylo_spec.devkeys` holds the **public** Anvil keys (mnemonic `test test … junk`). Use them only in mock and local mode; never fund them on Fuji.

## Checks

```bash
cd spec/python
uv run pytest                       # vector, scenarios, fixtures against the schema
uv run python ../scripts/validate.py
```
