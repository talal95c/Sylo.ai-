# Sylo.ai engine API (v1)

Base URL `http://localhost:8000`. JSON everywhere. CORS allows `http://localhost:3000` (env `CORS_ORIGINS`).
Event payloads are defined in [`events.schema.json`](events.schema.json). Changes to this file follow the rules in [`README.md`](README.md): additive only. Rows marked **v1** were added by roadmap task A1.0.

| Method | Path | Body | Response | Errors |
|---|---|---|---|---|
| GET | `/health` | — | `{ "ok": true, "mode": { ...system.mode data } }` | — |
| GET | `/v1/stream` | — | Server-sent events (see below) | — |
| POST | `/v1/scenarios/{name}/run` | `{ "speed"?: number = DEMO_SPEED, "auto"?: boolean = false, "autoAnswer"?: "confirm" \| "deny" = "deny" }` | `{ "paymentId": "PAY-2026-0001" }` | 404 unknown name; 409 a scenario is running |
| POST | `/v1/payments/{paymentId}/approve` **v1** | `{ "approver": "claire" \| "marc" }` | `{ "ok": true, "pending": ["marc"] }` (`pending`: approvers still missing) | 404 unknown payment; 409 not waiting for an approval, not an approver, already approved, the author must approve first, the author cannot co-approve |
| POST | `/v1/payments/{paymentId}/supplier-response` | `{ "answer": "confirm" \| "deny" }` | `{ "ok": true }` | 404 unknown payment; 409 not waiting for an answer |
| POST | `/v1/cases/{paymentId}/actions` **v1** | `{ "action": "CONFIRM_REVOCATION" \| "RELEASE" \| "FREEZE" }` | `{ "ok": true }` | 404 unknown payment; 409 the action makes no sense in the payment's state; 422 unknown action; 503 the chain did not answer |
| POST | `/v1/attacks/{name}` | `{ "paymentId": "PAY-2026-0002" }` | `{ "ok": true, "reverted": boolean, "reason": string \| null, "legRejected"?: string \| null }` | 404 unknown attack or payment; 409 payment not in a state where the attack makes sense |
| POST | `/v1/reset` | — | `{ "ok": true }` — cancels the running scenario and emits `session.reset` | — |
| GET | `/v1/payments/{paymentId}` | — | `{ "paymentId", "status", "tier", "routeId", "chainStatus", "lastSeq", "scenario", "pendingApprovers", "hold", "holdExpiresAt", "frozen", "caseReady" }` | 404 |
| GET | `/v1/payments/{paymentId}/proof` **v1** | — | See "Proof" below | 404 |

- Scenario names: `legit` (PAY-2026-0001), `diverted` (PAY-2026-0002), and **v1** `diverted_simswap` (PAY-2026-0002 again, but the SIM behind the supplier's known number changed 5 hours ago).
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
| `case.ready` | The analyst's case file exists (after `payment.held`, or after a payment blocked at HIGH or CRITICAL) | `{ summary, citations: [{ ref, source }], explanation?, reportDraft?, llm: "off" \| "cached" \| "live" }` |
| `case.action` | The analyst (or the engine, with `auto`) decided | `{ action: "CONFIRM_REVOCATION" \| "RELEASE" \| "FREEZE", by, detail?, txHash?, explorerUrl? }` |
| `alert.raised` | A person or an institution is told something | `{ audience: "payer" \| "supplier" \| "analyst" \| "beneficiary_bank", to, channel: "IN_APP" \| "SMS" \| "NETWORK", text, headline?, uetr? }` |

Additive fields on v0 events: `approval.granted.by[]` carries `id` and `at`; `leg.sent` carries `uetr`, `intentHash` and `idempotencyKey` (what the rail adapter checked before sending); `payment.held.reasons` may end with rule `R-OOB-01`; `verification.requested.channel` may be `"ANALYST"` (the known number was SIM-swapped, nobody is texted); `intent.revoked.reasonCode` may be `ANALYST_DECISION`; `attack.attempted.attack` may be `swap_beneficiary` or `replay`; `system.mode` carries `humanSteps` and is emitted again (with a normal `seq`) when a dependency fails while running.

- **No e-mail.** `alert.raised.channel` has no e-mail value: payers and suppliers are told in the app or by SMS, the beneficiary's bank over the network (`NETWORK`, with the UETR and a freeze request).
- **Case file.** `citations[].ref` is a rule id (`R-PV-01`), a reason ref, a norm signal or an event id (`evt-000016`) of the same payment. With `llm: "off"` the file is built by the engine from the rules that fired; `cached` and `live` come from Lane B's case writer (`CasePort`). A case file never changes a decision.
- **Attacks.** `swap_beneficiary` emits `attack.attempted`, `leg.rejected` (`INTENT_HASH_MISMATCH`, at the first pay-out hop), then `tx.reverted` (`deposit`, `CommitmentMismatch`). `replay` emits `attack.attempted`, then `tx.reverted` (`commit`, `InvalidTransition` or `NonceUsed`).
- **Chain failure.** If the chain stops answering during a payment, the engine emits `system.mode` (with `chain` in `degraded`) and `alert.raised` for the analyst. Nothing is released: money already in escrow stays there (`status: "held"`); a payment that had not moved is stopped.

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
```
