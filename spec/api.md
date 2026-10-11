# Sylo.ai engine API (v1 and v2)

Base URL `http://localhost:8000`. JSON everywhere. CORS allows `http://localhost:3000` (env `CORS_ORIGINS`).
Event payloads are defined in [`events.schema.json`](events.schema.json). Changes to this file follow the rules in [`README.md`](README.md): additive only. Rows marked **v1** were added by roadmap task A1.0, rows marked **v2** by task A2.0.

| Method | Path | Body | Response | Errors |
|---|---|---|---|---|
| GET | `/health` | — | `{ "ok": true, "mode": { ...system.mode data } }` | — |
| GET | `/v1/stream` | — | Server-sent events (see below) | — |
| POST | `/v1/scenarios/{name}/run` | `{ "speed"?: number = DEMO_SPEED, "auto"?: boolean = false, "autoAnswer"?: "confirm" \| "deny" = "deny" }` | `{ "paymentId": "PAY-2026-0001" }` | 404 unknown name; 409 a scenario is running |
| POST | `/v1/payments/{paymentId}/approve` **v1** | `{ "approver": "claire" \| "marc" }` | `{ "ok": true, "pending": ["marc"] }` (`pending`: approvers still missing) | 404 unknown payment; 409 not waiting for an approval, not an approver, already approved, the author must approve first, the author cannot co-approve |
| POST | `/v1/payments/{paymentId}/supplier-response` | `{ "answer": "confirm" \| "deny" }` | `{ "ok": true }` | 404 unknown payment; 409 not waiting for an answer |
| POST | `/v1/cases/{paymentId}/actions` **v1** | `{ "action": "CONFIRM_REVOCATION" \| "RELEASE" \| "FREEZE" }` | `{ "ok": true }` | 404 unknown payment; 409 the action makes no sense in the payment's state; 422 unknown action; 503 the chain did not answer |
| POST | `/v1/attacks/{name}` | `{ "paymentId": "PAY-2026-0002" }` | `{ "ok": true, "reverted": boolean, "reason": string \| null, "legRejected"?: string \| null, "incidentId"?: string }` | 404 unknown attack or payment; 409 payment not in a state where the attack makes sense |
| POST | `/v1/reset` | — | `{ "ok": true }` — cancels the running scenario and emits `session.reset` | — |
| GET | `/v1/payments/{paymentId}` | — | `{ "paymentId", "status", "tier", "routeId", "chainStatus", "lastSeq", "scenario", "pendingApprovers", "hold", "holdExpiresAt", "frozen", "caseReady" }` | 404 |
| GET | `/v1/payments/{paymentId}/proof` **v1** | — | See "Proof" below | 404 |
| POST | `/v1/sim/mule-wave` **v2** | `{ "speed"?: number, "auto"?: boolean = false }` | `{ "ok": true, "payments": ["PAY-2026-0101", …] }` | 409 a scenario is running |
| POST | `/v1/breakers/{breakerId}/confirm` **v2** | — | `{ "ok": true, "breakerId", "expiresAt" }` | 404 unknown breaker; 409 not waiting for a confirmation |
| POST | `/v1/breakers/{breakerId}/lift` **v2** | — | `{ "ok": true, "breakerId" }` | 404 unknown breaker; 409 the breaker is not on |
| POST | `/v1/sim/rails/{routeId}/down` **v2** | `{ "reason"?: string }` | `{ "ok": true, "routeId", "available": false }` | 404 unknown route |
| POST | `/v1/sim/rails/{routeId}/up` **v2** | — | `{ "ok": true, "routeId", "available": true }` | 404 unknown route |
| POST | `/v1/guardian/incidents` **v2** | `{ "rule": string, "action"?: string, "txHash"?: hash, "explorerUrl"?, "paymentId"?, "incidentId"?, "simulated"?, + optional DORA fields }` | `{ "ok": true, "incidentId" }` | 422 invalid body |
| GET | `/v1/metrics` **v2** | — | See "Metrics" below | — |

- Scenario names: `legit` (PAY-2026-0001), `diverted` (PAY-2026-0002), **v1** `diverted_simswap` (PAY-2026-0002 again, but the SIM behind the supplier's known number changed 5 hours ago), and **v2** `outage` (PAY-2026-0001 again, while the rail of R3 is down).
- Attack names: `release_revoked` (only when the payment is revoked on-chain), and **v1** `swap_beneficiary` and `replay` (any payment whose intent is committed).
- `status` in `GET /v1/payments/{id}` is one of `deciding`, `awaiting_approval`, `in_transit`, `held`, `awaiting_supplier`, `confirmed`, `awaiting_analyst`, `stopped`, `credited`; `chainStatus` is the registry status name (`NONE` … `EXECUTED`). `hold` is `"escrow"`, `"bank"` or `null`.

## Human steps (v1)

Three steps belong to people: the payer's approvals (Claire, then Marc from EUR 20,000, or from EUR 5,000 to a new account), the supplier's answer (Kwame), and the analyst's decision (Julien).

| Run option | Engine flag `HUMAN_STEPS` | Payer approvals | Supplier's answer | Analyst |
|---|---|---|---|---|
| `auto: true` | any | by the engine, 600 ms apart | by the engine after 3,000 ms, with `autoAnswer` | by the engine after 1,500 ms |
| `auto: false` | `auto` (default) | by the engine, 600 ms apart | **waits** for `supplier-response` | by the engine after 1,500 ms |
| `auto: false` | `manual` | **waits** for `approve` (twice) | **waits** for `supplier-response` | **waits** for `CONFIRM_REVOCATION` |

All delays are divided by `speed`. `HUMAN_STEPS=auto` is the default so that a screen without the payer panel and the analyst drawer still runs the whole story; set `HUMAN_STEPS=manual` in `.env` once those panels call the two endpoints. `system.mode.data.humanSteps` tells a client which one applies.

Approvals: `approval.required` is emitted when the approval starts and again after each approval while one is missing. `required` always lists every approver; `pending` lists the ids still missing and `received` the approvals already given. The author of the payment (the first approver) approves first and cannot give the second approval. `approval.granted.approvalHash` covers every approval record and is part of the signed intent, which is committed only after the approval.

Analyst actions on a held payment:

| Action | When | Effect |
|---|---|---|
| `CONFIRM_REVOCATION` | While the payment waits for the supplier or for the analyst | `case.action`, then the `Revocation` is signed with the analyst key: `intent.revoked` (`SUPPLIER_DENIED` after a denial, otherwise `ANALYST_DECISION`), `escrow.refunded`, `payment.stopped` |
| `FREEZE` | While the money is held | `case.action` with the freeze transaction. A frozen hold cannot be released: if the supplier then confirms, `release` reverts (`tx.reverted`) and the payment waits for the analyst |
| `RELEASE` | Only in status `confirmed` (the supplier confirmed, the money is still held) | `case.action`; the engine releases (it would do so by itself after 1,000 ms) |

## Events added in v1

| Type | Emitted when | `data` |
|---|---|---|
| `approval.required` | The payer must approve; again after each approval while one is missing | `{ required: [{ id, name, role }], received: [{ id, name, role, at }], pending: string[], method: "SCA" \| "DUAL_CONTROL", conditional: boolean, note, warning? }` |
| `leg.rejected` | A rail adapter refused a leg before sending it | `{ hop, rail, reason: "INTENT_HASH_MISMATCH" \| "NONCE_USED" \| "REVOKED" \| "EXPIRED" \| "NOT_CONFIRMED" \| "RAIL_DOWN" \| "KILL_SWITCH", from, to, text }` |
| `case.ready` | The analyst's case file exists (after `payment.held`, or after a payment blocked at HIGH or CRITICAL) | A `CaseFile` (`sylo_spec.models`): `{ paymentId, summary, sentences: [{ text, refs }], timeline: [{ at, eventId, text }], typology, recommendedAction: "CONFIRM_REVOCATION" \| "RELEASE_AFTER_CONFIRMATION" \| "ESCALATE_AML" \| "NO_ACTION", explanation, citations: [{ ref, source }], reportDraft, llm: "off" \| "cached" \| "live", promptVersion, model }` |
| `case.action` | The analyst (or the engine, with `auto`) decided | `{ action: "CONFIRM_REVOCATION" \| "RELEASE" \| "FREEZE", by, detail?, txHash?, explorerUrl? }` |
| `alert.raised` | A person or an institution is told something | `{ audience: "payer" \| "supplier" \| "analyst" \| "beneficiary_bank", to, channel: "IN_APP" \| "SMS" \| "NETWORK", text, headline?, uetr? }` |

Additive fields on v0 events: `approval.granted.by[]` carries `id` and `at`; `leg.sent` carries `uetr`, `intentHash` and `idempotencyKey` (what the rail adapter checked before sending); `payment.held.reasons` may end with rule `R-OOB-01`; `verification.requested.channel` may be `"ANALYST"` (the known number was SIM-swapped, nobody is texted); `intent.revoked.reasonCode` may be `ANALYST_DECISION`; `attack.attempted.attack` may be `swap_beneficiary` or `replay`; `system.mode` carries `humanSteps` and is emitted again (with a normal `seq`) when a dependency fails while running.

- **No e-mail.** `alert.raised.channel` has no e-mail value: payers and suppliers are told in the app or by SMS, the beneficiary's bank over the network (`NETWORK`, with the UETR and a freeze request).
- **Case file.** `citations[].ref` and `sentences[].refs` are rule ids (`R-PV-01`), reason refs, norm signals or event ids (`evt-000016`) of the same payment. With `llm: "off"` the file is built by the engine from the rules that fired (`promptVersion: "rules-v1"`); `cached` and `live` come from Lane B's `CasePort` (`sylo_risk.CaseWriter`), and the engine falls back to the rules when the answer cites something unknown or is longer than 120 words. A case file never changes a decision: `recommendedAction` is advice for the analyst.
- **HIGH but resolvable out of band.** `risk.scored.oobResolvable` is true when only the beneficiary's identity is in doubt. A HIGH payment is then handled like a MEDIUM one: `route.selected.tier` and `intent.committed.tier` say `MEDIUM` (conditional settlement), while `risk.scored.tier` and `payment.held.tier` keep `HIGH`, and `payment.held.nextStep` says why. HIGH without it, and CRITICAL always, get no route.
- **Attacks.** `swap_beneficiary` emits `attack.attempted`, `leg.rejected` (`INTENT_HASH_MISMATCH`, at the first pay-out hop), then `tx.reverted` (`deposit`, `CommitmentMismatch`). `replay` emits `attack.attempted`, then `tx.reverted` (`commit`, `InvalidTransition` or `NonceUsed`).
- **Chain failure.** If the chain stops answering during a payment, the engine emits `system.mode` (with `chain` in `degraded`) and `alert.raised` for the analyst. Nothing is released: money already in escrow stays there (`status: "held"`); a payment that had not moved is stopped.

## Network defence and incidents (v2)

Events added in v2 (`paymentId` is `null` unless the event concerns one payment):

| Type | Emitted when | `data` |
|---|---|---|
| `cluster.detected` | The cluster detector finds a mule cluster among the payments of the last hour | `{ clusterId, accounts: number, agents: number, region, regionName, institutions: InstitutionId[], centroid: { lat, lng }, points: [{ lat, lng, weight }], linkedPayments: string[], detector, proposedBreaker: { breakerId, scope, thresholdsDelta: -20, hours: 24, text } }` |
| `breaker.on` | The analyst (or the engine, with `auto`) confirms the proposed breaker | `{ breakerId, clusterId, scope: { region, regionName, corridor, institutions }, thresholdsDelta: -20, expiresAt, confirmedBy, text }` |
| `breaker.off` | A person lifts the breaker, or its 24 hours are over | `{ breakerId, reason: "LIFTED" \| "EXPIRED", by? }` |
| `rail.down` | A rail stops (`/v1/sim/rails/{routeId}/down`, or scenario `outage`) | `{ routeId, name, reason }` |
| `rail.up` | The rail is back | `{ routeId, name }` |
| `killswitch.on` | Two legs changed or replayed on one adapter within 10 minutes | `{ adapter: routeId, name, reason, refusals, windowSeconds, revoked: paymentId[] }` |
| `guardian.incident` | The guardian reports an on-chain incident | `{ incidentId, rule, txHash, explorerUrl, action, headline, dora: { clientsAffected, amountEur, durationMinutes, geographicSpread, criticality, thirdParties, major, draft: true } }` |
| `traffic.sample` | Payments seen on the network that the engine does not route (here: the mule wave) | `{ arcs: [{ from, to, kind }], wave?: boolean, payer?, beneficiary?, amount?, text? }` |

- **Scene 3, mule wave.** `POST /v1/sim/mule-wave` emits `scenario.started` (`scenario: "mule_wave"`), then three `traffic.sample` events (`paymentId` PAY-2026-0101 to 0103, `data.wave: true`, one arc each from the payer's bank to the cluster's bank, with `payer`, `beneficiary`, `amount` and a `text`): three unrelated payers are each sent to the same nine-day-old account. The engine does not route these payments: they are what the network sees, so they are not `payment.created`. The detector is Lane B's `sylo_risk.clusters` behind `ClusterPort` when it is installed (`system.mode.clusters: "detector"`, `cluster.detected.detector: "networkx-mule-clusters"`): it links an account that is new or has little history once three different payers pay it, and the engine adds the institutions that hold the cluster's accounts. Without Lane B's package, or with `CLUSTER_MODE=sample`, a stub reads `fixtures/cluster-sample.json` (`clusters: "sample"`, `detector: "cluster-sample"`) and reports that cluster once three payments of the last hour reach its accounts. Both count the payments of the normal scenarios too. `cluster.detected` proposes a breaker; `POST /v1/breakers/{id}/confirm` switches it on (with `auto`, or `HUMAN_STEPS=auto`, the engine confirms after 1,500 ms).
- **Circuit breaker (rule R-CB-01).** For 24 hours, a payment whose beneficiary's institution is in `scope.institutions` is at least MEDIUM, and the bands are read 20 points lower (a score of 64 is HIGH). The score itself and the route score do not change. `risk.scored.rulesFired` ends with `R-CB-01` and the reason is on the alert. Only `POST /v1/breakers/{id}/lift` ends it early.
- **Scene 5, outage.** A rail that is down is not eligible: `route.selected.scores[]` shows it with `excludedBy: "RAIL_DOWN"` and the payment takes the best remaining route. An outage never changes the tier. A MEDIUM payment still needs a route that can hold the money: with R3 down it is held at the sending bank (`payment.held.at: "bank"`, no escrow events); with R1 down too it is not sent.
- **Kill switch.** Each `leg.rejected` with `INTENT_HASH_MISMATCH` or `NONCE_USED` counts. At the second one within 10 minutes on the same adapter: `killswitch.on`, the adapter refuses everything (`leg.rejected.reason: "KILL_SWITCH"`, `excludedBy: "KILL_SWITCH"` in route scores), and a payment held on that route is revoked and refunded (`intent.revoked.reasonCode: "KILL_SWITCH"`, by "Kill switch (automatic)", no `case.action`). `POST /v1/sim/rails/{routeId}/up` restores the adapter (the keys were rotated); `POST /v1/reset` restores every rail and removes every breaker.
- **Degraded mode (rule R-DG-01).** While `system.mode.degraded` is not empty, a payment to an account that is not on file for the payee is at least MEDIUM.
- **Scene 4, guardian.** `POST /v1/guardian/incidents` is for Lane C's guardian. The engine emits `guardian.incident` with a DORA incident draft (also written to `engine/data/incidents/`), and when the action contains `FREEZE` it stops trying to release that payment: the supplier is no longer waited for (`supplier-response` answers 409), the analyst is alerted, and the payment ends with `intent.revoked` and `escrow.refunded` once the analyst sends `CONFIRM_REVOCATION` (played by the engine with `HUMAN_STEPS=auto`). When the action contains `PAUSE`, the escrow route is closed (`rail.down`, reason "Corridor paused by the guardian…") and payments are rerouted until `POST /v1/sim/rails/{routeId}/up`; on Fuji the corridor itself is reopened with the admin key (Lane C). `GET /v1/payments/{id}` carries `incidentId`. If the registry refuses the supplier's answer because its state changed outside the engine (`tx.reverted` on `recordVerification`), the engine also hands the payment to the analyst and refunds: it never ends as "stopped" with money left in escrow.
- **Scene 4 on a simulated chain.** `POST /v1/attacks/stolen_verifier_key` on a payment held in escrow and waiting for the supplier plays the thief and the guardian: a CONFIRMED attestation signed with the verifier key that the engine never recorded, freeze and pause, `guardian.incident`, then the thief's `release()` reverts `PaymentNotReleasable`. The answer carries `incidentId`. With `CHAIN_MODE=fuji` it answers 409: run Lane C's `sylo_chain.stolen_verifier_key` with the guardian watching.

## Metrics (`GET /v1/metrics`)

Lane B's `ml/reports/metrics.json` (schema: [`metrics.schema.json`](metrics.schema.json)) when it exists, otherwise the labelled sample with `"sample": true`. Two fields are added: `source` (which file was served) and `integrity` (the engine's `engine/reports/integrity.json`, written by `make integrity`: 300 changed or replayed payments run through the adapters and the chain). `metrics.diversionRate` is taken from that report.

## Proof (`GET /v1/payments/{paymentId}/proof`)

What an auditor needs to recompute a payment. The salt of the off-chain fields is included, so this endpoint is for auditors only.

```
{
  "paymentId": "PAY-2026-0002", "chainPaymentId": "0x…", "chainStatus": "REVOKED", "simulated": true,
  "domain": { "name", "version", "chainId", "verifyingContract" },
  "signed": [ { "type": "PaymentIntent" | "VerificationAttestation" | "Revocation", "role", "signer",
                "typedData": { "types", "primaryType", "domain", "message" }, "digest", "signature" } ],
  "offchain": { "salt": "0x…", "fields": { "creditorName", "account", "bank", "invoiceRef", "uetr" } },
  "approval": { "method", "conditional", "records": [{ "id", "name", "role", "at" }], "approvalHash" },
  "transactions": [ { "event", "eventId", "txHash", "explorerUrl", "simulated" } ],
  "log": [ { "seq", "prevHash", "type", "payload", "hash" } ], "logHead": "0x…"
}
```

`typedData` is standard EIP-712 JSON (bytes32 as 0x-hex, integers as decimal strings): hashing it gives `digest`, and `signature` recovers `signer`. `offchainHash` in the intent is `keccak256(salt ‖ canonical_json(fields))`. `log` holds the payment's lines of the hash-chained decision log (`hash = keccak256(canonical_json({ seq, prevHash, type, payload }))`); `make verify-log` checks the whole file.

## Stream (`GET /v1/stream`)

Each message is

```
id: <seq>
data: <event JSON on one line>
```

On connect the engine sends one `system.mode` event (`seq: 0`, no `id:` line, not stored in the session), then every event of the current session in order — or only the events after `Last-Event-ID` when the browser reconnects with that header — then live events. A heartbeat comment is sent every 15 s.

`seq` keeps increasing for the life of the engine process (a reset does not restart it); `system.mode.data.bootId` changes when the engine restarts, so a client can tell that it must forget what it has seen.

## Example

```bash
curl -N http://localhost:8000/v1/stream &
curl -X POST http://localhost:8000/v1/scenarios/diverted/run -H 'content-type: application/json' -d '{"speed": 2}'
# with HUMAN_STEPS=manual only:
curl -X POST http://localhost:8000/v1/payments/PAY-2026-0002/approve -H 'content-type: application/json' -d '{"approver": "claire"}'
curl -X POST http://localhost:8000/v1/payments/PAY-2026-0002/approve -H 'content-type: application/json' -d '{"approver": "marc"}'
curl -X POST http://localhost:8000/v1/payments/PAY-2026-0002/supplier-response -H 'content-type: application/json' -d '{"answer": "deny"}'
# with HUMAN_STEPS=manual only:
curl -X POST http://localhost:8000/v1/cases/PAY-2026-0002/actions -H 'content-type: application/json' -d '{"action": "CONFIRM_REVOCATION"}'
curl -X POST http://localhost:8000/v1/attacks/release_revoked -H 'content-type: application/json' -d '{"paymentId": "PAY-2026-0002"}'
curl -X POST http://localhost:8000/v1/attacks/swap_beneficiary -H 'content-type: application/json' -d '{"paymentId": "PAY-2026-0002"}'
curl -X POST http://localhost:8000/v1/attacks/replay -H 'content-type: application/json' -d '{"paymentId": "PAY-2026-0002"}'
curl http://localhost:8000/v1/payments/PAY-2026-0002/proof
# v2
curl -X POST http://localhost:8000/v1/sim/mule-wave -H 'content-type: application/json' -d '{"speed": 2}'
curl -X POST http://localhost:8000/v1/breakers/CB-CL-AFLAO-01/confirm
curl -X POST http://localhost:8000/v1/sim/rails/R3/down
curl -X POST http://localhost:8000/v1/scenarios/legit/run -H 'content-type: application/json' -d '{"auto": true}'
curl -X POST http://localhost:8000/v1/sim/rails/R3/up
curl http://localhost:8000/v1/metrics
```
