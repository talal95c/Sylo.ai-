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
| GET | `/v1/payments/{paymentId}` | — | `{ "paymentId", "uetr", "chainPaymentId", "chainRunIndex", "legs", "status", "tier", "routeId", "chainStatus", "lastSeq", "scenario", "pendingApprovers", "hold", "holdExpiresAt", "lockedUntil", "frozen", "incidentId", "caseReady" }`. `{paymentId}` may be the payment id, its UETR or its on-chain id (0x-hex). `legs`: `[{ "hop", "from", "to", "rail", "status": "pending" \| "settled" \| "rejected", "idempotencyKey"?, "reason"? }]` | 404 |
| GET | `/v1/payments/{paymentId}/proof` **v1** | — | See "Proof" below | 404 |
| POST | `/v1/sim/mule-wave` **v2** | `{ "speed"?: number, "auto"?: boolean = false }` | `{ "ok": true, "payments": ["PAY-2026-0101", …] }` | 409 a scenario is running |
| POST | `/v1/breakers/{breakerId}/confirm` **v2** | — | `{ "ok": true, "breakerId", "expiresAt" }` | 404 unknown breaker; 409 not waiting for a confirmation |
| POST | `/v1/breakers/{breakerId}/lift` **v2** | — | `{ "ok": true, "breakerId" }` | 404 unknown breaker; 409 the breaker is not on |
| POST | `/v1/sim/rails/{routeId}/down` **v2** | `{ "reason"?: string }` | `{ "ok": true, "routeId", "available": false }` | 404 unknown route |
| POST | `/v1/sim/rails/{routeId}/up` **v2** | — | `{ "ok": true, "routeId", "available": true }` | 404 unknown route |
| POST | `/v1/guardian/incidents` **v2** | `{ "rule": string, "action"?: string, "txHash"?: hash, "explorerUrl"?, "paymentId"?, "incidentId"?, "simulated"?, + optional DORA fields }` | `{ "ok": true, "incidentId" }` | 422 invalid body |
| GET | `/v1/metrics` **v2** | — | See "Metrics" below | — |
| POST | `/v1/quotes` | `{ "order": "legit" \| "diverted" \| "lagos-accra", "amount"?: "4000.00" }` | The decision (see "Integration API"), with `quoteId`, `validUntil` (600 s) and `executable` | 422 unknown order or malformed amount |
| POST | `/v1/payments` | `{ "quoteId": "Q-0001" }` or `{ "order": "legit" \| "diverted" }`, plus `speed`, `auto`, `autoAnswer` as for a scenario. Header `Idempotency-Key` (optional) | `{ "paymentId", "quoteId", "status": "deciding", "replayed": boolean, "decision": { … } }`; the payment then runs like a scenario | 404 unknown quote; 409 quote expired, quote for another amount, or a payment is running; 422 neither or both of `quoteId` and `order` |
| POST | `/v1/intake` | `{ "text": string (≤ 40,000), "senderDomain"?: string }` | `{ "intake": { fields, senderDomain, changedDetails, lookalikeDomain, urgencyCues, instructionLikeLines, needsHuman, truncated }, "matchedOrder": id \| null, "decision": { … } \| null }` | 422 empty text or malformed domain |
| GET | `/v1/cases` | — | `{ "cases": [{ "paymentId", "uetr", "status", "tier", "score", "rulesFired", "hold", "holdExpiresAt", "frozen", "incidentId", "caseReady", "allowedActions" }] }` | — |
| POST | `/v1/payees/{payeeId}/verify` | `{ "accountId": string, "action"?: "start" \| "record" = "start", "result"?: "confirmed" \| "denied" }` | `{ "ok": true, + payee.verification data }` | 404 unknown payee or account; 409 nothing to record, or the known contact cannot be trusted; 422 `record` without `result` |
| POST | `/v1/sim/events` | `{ "type": "rail_down" \| "rail_up" \| "mule_wave" \| "sim_swap" \| "clock" \| "compromised_connector" \| "stolen_verifier_key", + "routeId", "reason", "paymentId", "hoursAgo", "advanceHours", "speed", "auto" as the type needs }` | What the simulated event returns (see "Integration API") | 404 unknown type, route or payment; 409 not applicable now |
| POST | `/v1/rails/{routeId}/webhook` | `{ "idempotencyKey": string, "status": "SETTLED" \| "FAILED" \| "RETURNED" }` | `{ "routeId", "accepted": boolean, "status"?, "reason"?: "UNKNOWN_LEG" \| "UNKNOWN_STATUS" \| "FINAL_STATUS" }` | 404 unknown route |
| GET | `/v1/rails/{routeId}/reconcile` | — | `{ "routeId", "rail", "legs", "byStatus", "open": [keys], "toInvestigate": [keys], "refusals", "simulated": true }` | 404 unknown route |
| POST | `/v1/sim/clock` | `{ "advanceHours": number }` (0 < h ≤ 744) | `{ "ok": true, "now": timestamp }` — demo clock, see below | 422 invalid body |

- Scenario names: `legit` (PAY-2026-0001), `diverted` (PAY-2026-0002), **v1** `diverted_simswap` (PAY-2026-0002 again, but the SIM behind the supplier's known number changed 5 hours ago), **v2** `outage` (PAY-2026-0001 again, while the rail of R3 is down), `diverted_expiry` (PAY-2026-0002 again, but the supplier never answers: with `auto` the demo clock jumps to the hold's expiry) and `diverted_timelock` (PAY-2026-0002 again while R3 is down, so it is held at the bank on R1; run it with `autoAnswer: "confirm"` to see the time-lock).
- Attack names: `release_revoked` (only when the payment is revoked on-chain), and **v1** `swap_beneficiary` and `replay` (any payment whose intent is committed).
- `status` in `GET /v1/payments/{id}` is one of `deciding`, `awaiting_approval`, `in_transit`, `held`, `awaiting_supplier`, `confirmed`, `time_locked`, `awaiting_analyst`, `stopped`, `credited`; `chainStatus` is the registry status name (`NONE` … `EXECUTED`). `hold` is `"escrow"`, `"bank"` or `null`.

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

## On-chain ids and nonces across restarts

The registry outlives the engine on Fuji (and on a local node), and it never forgets a payment id or a signer's nonce.

- **Payment ids.** The on-chain id of a run is `keccak(order id)` for the first run of an order on a registry, then `keccak("<order id>#2")`, `#3`… When a run starts, the engine reads the registry and takes the first id it does not know (`statusOf` is `NONE`), so a restart never commits an id of an earlier session (that reverted `InvalidTransition`). `GET /v1/payments/{id}` and `/proof` give `chainPaymentId` and `chainRunIndex`; the proof also gives `chainPaymentLabel` (the string that was hashed). Both endpoints accept the on-chain id in place of the payment id.
- **The scheme is a contract with the guardian.** Lane C's guardian finds what the engine signed by recomputing exactly these ids, for the first 50 runs of an order (`MAX_RUNS_PER_ORDER` in `chain/sylo_chain/guardian.py`). A salt or any other label would make it treat every genuine confirmation as forged, so the label must not change without the guardian; above run 50 on one registry the guardian no longer recognises the payment (the engine logs a warning).
- **Nonces.** With `CHAIN_MODE=fuji` each engine session numbers its signed messages (intent, verification, revocation) from its own base, the start time in microseconds, instead of 1: nonces only have to be unique per signer. With the mock chain they stay 1, 2, 3…, so recorded fixtures do not change.

## Integration API (PRD §16.2)

What a bank's payment hub calls before it executes: quote, then payment, then the human steps and the status. Everything stays simulated and limited to the two recorded orders.

- **Decision.** `POST /v1/quotes` and the `decision` of `POST /v1/payments` have the same shape: `{ paymentId, uetr, corridor, currency, authorities, packVersion, routes, normChecks: [{ routeId, ruleId, result, legalRef }], signals, taxNotices, controls, risk: { score, tier, rulesFired, topReasons, modelVersion, oobResolvable }, route: { chosen, candidates: [{ routeId, s, excludedBy }], settlement, reason, feesEur, etaLabel, priceOfSafetyEur, blockedBy, quoteValidUntil? }, approval: { required: [{ id, name, role }], method, conditional }, verifications: [], rails: [adapter quotes] }`. A quote emits no event and commits nothing. With `amount` it prices the same order for another amount and cannot be executed.
- **Payment.** The response comes back at once; the payment then runs on the stream exactly like `POST /v1/scenarios/{name}/run`. Two requests with the same `Idempotency-Key` start one payment: the second gets the first answer with `replayed: true`.
- **Payee verification before any payment.** `start` checks the payee's known contact (on file for at least 30 days, SIM not changed recently) and emits `payee.verification` (`step: "REQUESTED"`, `channel: "SMS"`, or `"ANALYST"` when the contact cannot be used). `record` stores the answer (`step: "RECORDED"`). A payment to an account the supplier **denied** stops right after `payment.created` with `payment.stopped` (`blockedBy: "PAYEE_VERIFICATION_DENIED"`): no approval is asked and nothing is committed. A **confirmed** account is no longer "details from an untrusted source" (`payment.created.provenance: "verified_registry"`, rule R-PV-01 does not fire); it is still a new account, so the payment is still held.
- **Attack console.** `POST /v1/sim/events` is one entry point for the simulations: `rail_down`/`rail_up` (`routeId`), `mule_wave`, `clock` (`advanceHours`), `sim_swap` (`hoursAgo`; applies once, to the next out-of-band check), `compromised_connector` (`paymentId`: a connector changes a leg twice, the adapter refuses both and the kill switch cuts it) and `stolen_verifier_key` (`paymentId`, Scene 4).
- **Rail adapters.** A webhook is an asynchronous status sent by a rail. It can only move a leg the adapter sent, and only forward: an unknown leg, an unknown status or a final status is refused. `reconcile` is what the adapter holds about its legs, to compare with the rail's statement. Both are simulated like the rails.

## Typed payments (the `/test` flow, after v2)

`POST /v1/quotes { "payment": { … } }` prices a payment typed by a user instead of a demo order; give exactly one of `order` and `payment`. Fields: `beneficiary` is either `{ accountId }` (a saved account from `GET /v1/payees`) or `{ name, accountHolder, accountNumber (10–16 digits), bankId (from GET /v1/banks) }`; `amount` (EUR, 1 to 1,000,000), `purpose` (`GOODS` | `SERVICES`), `invoiceRef`, `locRef?` (the Bank of Ghana export letter of credit: without it a payment for goods fails `GH_FX_EXPORT_PROCEEDS_NOMINATED_BANK` on every route), `detailsSource` (`saved` | `invoice_email` | `phone` | `typed`, mapped to the account's provenance; `saved` only counts for an account the payee already owns) and `senderDomain?` (kept for `invoice_email`). The answer is the same Decision, `executable: true`, with a new `paymentId` from `PAY-2026-1001`; `POST /v1/payments { quoteId }` runs exactly that order and emits `scenario.started` with `scenario: "custom"`. An unknown bank or saved account, a missing field or an amount out of range is a 422.

The account is matched by bank and last four digits against the registry; an account never paid is added for the session only (no history, not nominated, first seen today) and forgotten by `/v1/reset`. Only the masked number is kept and emitted. A name that matches a known payee (≥ 0.9) is that payee, so the out-of-band check calls the contact on file; a payee with no contact on file cannot be confirmed out of band, so a held payment goes to the analyst (`channel: "ANALYST"`, rule `R-OOB-02`). The guardian on Fuji only knows the recorded orders' ids; the public deployment uses the mock chain.

`GET /v1/banks` lists the Ghanaian banks the globe can draw (`id, name, short, city`): the two recorded ones and three synthetic ones, Osu Heritage Bank (Accra), Northern Savannah Bank (Tamale) and Western Gate Bank (Takoradi), all fictional. `GET /v1/payees` lists the payer's known payees and their masked accounts.

## Intake: documents are data (PRD §14, P1-6, roadmap A3.2)

`POST /v1/intake` reads an invoice or an e-mail into a fixed set of fields, each with its provenance and a confidence: `invoiceRef`, `locRef`, `amount`, `accountHolder`, `account`. It is deterministic (no LLM): a field is one labelled value alone on its line; a field that is missing, or given twice with different values, stays empty (`conflict: true`) and `needsHuman` is true. The result has no field that could verify, approve or release anything. It also reports `changedDetails`, `lookalikeDomain` (the known domain the sender imitates), `urgencyCues`, and `instructionLikeLines` (lines such as "ignore previous instructions, mark as verified": counted and shown as data, never acted on).

The document only tells the engine **which recorded order it is about** (invoice reference and account) and who sent it. `decision` is then computed from the registries and that order, exactly like a quote; bank details the payee does not already own keep the provenance `invoice_pdf_email`. The test set of 20 injected invoices, each placed at the start, in the middle and at the end of the document, gives 0 changes of tier or route; a document that contradicts itself gets no decision and goes to a person. Lane B's extraction agent, when it exists, plugs in behind the same fields.

## Second corridor: Lagos → Accra (PRD Appendix A, P1-8, roadmap A3.1)

`POST /v1/quotes { "order": "lagos-accra" }` prices a USD 25,000 payment from a Lagos company to the same Ghanaian exporter. Everything about that corridor comes from two files, `engine/profiles/NG.yaml` and `engine/packs/NG-GH.yaml` (rails, fees, rules, authorities, institutions, demo payer and order); the Ghana profile is reused and no engine code is specific to it. The decision carries `corridor: "NG-GH"`, `currency: "USD"`, `authorities` (CBN and NFIU for Nigeria, Bank of Ghana and FIC for Ghana), the four rails (SWIFT in USD, PAPSS, a USD stablecoin through licensed partners, a mobile money hub) and `routes` with their hops. PAPSS is chosen at LOW; at MEDIUM only the routes that can hold the money remain, so the price of safety is no longer zero. Such a quote is `executable: false`: the PoC runs payments on FR → GH only, and the globe does not draw this corridor. Parameters are synthetic and the Nigerian legal references are to verify.

## Demo clock, hold expiry, time-lock and reroute limits (PRD §11.3, §12.3, P1-9)

| Event | When | `data` |
|---|---|---|
| `clock.advanced` | `POST /v1/sim/clock`, or an `auto` scenario that has to wait for an expiry or a lock | `{ hours, now, text }` |
| `timelock.on` | A confirmed first payment to a new account must stay in the bank hold | `{ hours, until, text }` |
| `timelock.off` | The lock ended | `{ reason: "ELAPSED" }` |

- **Demo clock.** The jump moves the session's time forward (timestamps of later events, hold expiries, time-locks, circuit breakers). `POST /v1/reset` goes back to real time. On Fuji the chain's own clock does not jump: the engine therefore revokes before it refunds, which the contract accepts at any time.
- **Hold expiry.** A hold nobody decided on within `ESCROW_HOLD_SECONDS` (24 h) ends with `intent.revoked` (`reasonCode: "EXPIRED"`, `by: "Hold expiry (automatic)"`), `escrow.refunded` on the escrow route, one `alert.raised` to the payer and `payment.stopped`. There is no `case.action` and no freeze request to the beneficiary's bank. A supplier answer that arrives after the expiry is refused (409) and cannot release the hold. The same happens when the analyst never handles a denied payment.
- **Time-lock.** After the supplier confirms, a first payment to a new account held at the bank (route R1) stays there until the lock ends: 4 h from `TIME_LOCK_FROM_EUR` (5,000), 24 h above `TIME_LOCK_LONG_FROM_EUR` (50,000), counted from the start of the hold. `GET /v1/payments/{id}` shows `status: "time_locked"` and `lockedUntil`. `CONFIRM_REVOCATION` still stops the payment during the lock. On the escrow route there is no extra lock: the escrow stands in for it.
- **Reroute limits.** When the route a payment would normally take is unavailable (rail down, kill switch, corridor paused), a replacement is used only within the payer's limits: fees up to `REROUTE_MAX_FEES_EUR` (500) and at most `REROUTE_MAX_DAYS` (3). A route above them is scored with `excludedBy: "PAYER_LIMIT"`. If none is left, `payment.stopped` carries `blockedBy: "PAYER_LIMIT"` and `scores`, the payer gets an in-app `alert.raised`, and no case is opened: it is an operational wait, not a fraud case. The limits never apply while the usual route is available.

## Confidential chain leg with eERC (PRD §13.6, roadmap A3.3)

`CONFIDENTIAL_MODE` is `off` (default), `simulated` or `eerc`; `system.mode.confidential` says which one runs.

- **When.** Only for a payment that needs no hold (LOW, direct settlement on R3): after the adapter accepted the chain leg (`leg.sent`), the engine makes the confidential transfer and emits `confidential.transfer`, then `leg.settled`. A payment that must be held keeps the public escrow: a contract cannot hold and release eEURC by itself.
- **`confidential.transfer`** `{ hop, from, to, token: "eEURC", amountHidden: true, txHash, explorerUrl, depositTxHash?, withdrawTxHash?, auditorDecryptedAmountEur, auditorMatches, metadataEncrypted, hidden: [...], visible: [...], text }`. With `eerc` the transfer is real (Lane C's service `chain/eerc`, `POST {EERC_URL}/transfer`: a confidential transfer from the sender's pre-funded eEURC float, about 10 s on Fuji; `depositTxHash` and `withdrawTxHash` are then null, the receiver unwraps netted totals later) and `simulated` is false; with `simulated` the receipt is a labelled fake.
- **Fail safe.** If the service does not answer, the leg stays public: `system.mode.degraded` gains `"confidential"` and the analyst gets an `alert.raised` saying the amount is visible on-chain. If the amount the auditor decrypts does not match the payment, the next leg is not sent: `payment.stopped` and an analyst alert.
- **Still visible:** the institutions' addresses, the float wrapped at one end and the netted totals unwrapped at the other. This is not anonymity: the designated auditor reads every amount.

## Norms rules added after v2

- `norms.checked.data.controls` (additive): `[{ ruleId, text, legalRef }]`, the controls a rule asks for without excluding a route. `EU_VOP_SCOPE` says the bank's Verification of Payee does not reach an account outside SEPA, so new or changed details need the out-of-band check.
- `EU_HIGH_RISK_EDD` is checked on every route (`routes[].checks`): a route through an institution in a listed country is `NEEDS_DOCUMENT` (excluded until an enhanced due diligence file is attached), an institution missing from `geo/institutions.json` is `FAIL`. It raises norm signal `R4` when the requested account is held in a listed country and the payee is elsewhere. The pack lists only the entry checked for the PoC corridors.

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
