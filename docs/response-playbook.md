# Response playbook (Lane A)

One page: what happens at each risk level, who acts, who is told, and what is kept as evidence. Source: PRD §12. The last column says what the engine does today; "simulated" means the step runs but the outside party is a mock.

The order never changes: **norms → risk → cost → commit → action**. Fraud risk decides the tier; it never enters the route score. A model or a case file can only make a decision stricter. The signed intent is committed before any money moves.

## By risk tier

| Tier | Automatic | Human | Who is told | When it ends | In the engine today |
|---|---|---|---|---|---|
| **LOW** (0–39) | Commit the intent; send on the cheapest legal route | Payer approval (two people from EUR 20,000) | — | When the last leg settles | Built. Rails simulated |
| **MEDIUM** (40–69) | Commit; hold the money (escrow on R3, bank hold on R1); check the SIM of the supplier's known number; ask that number; open a case | Payer approves a conditional payment; analyst confirms the revocation, or releases after confirmation, or freezes | Payer (in the app or by SMS), analyst, and after a revocation the beneficiary's bank | Release when the supplier confirms; revoke and refund when the supplier denies; refund possible by anyone after 24 h | Built. Supplier, SIM check and alerts simulated |
| **HIGH** (70–89) | No route, nothing is sent; case file | Analyst decides | Analyst | When a person decides | Built up to the case file. **Exception:** when only the beneficiary's identity is in doubt (`oobResolvable`), the payment is handled like MEDIUM and held |
| **CRITICAL** (90–100) | Block; report draft | AML officer validates and files | AML officer; never the customer under suspicion | Per the reporting deadline | Blocked, with a case file that recommends escalation. No filing |

## Overlays (they only make things stricter)

| Event | Automatic | Human | In the engine today |
|---|---|---|---|
| Wave of linked payments to one cluster | A regional circuit breaker is proposed: payments into the region at least MEDIUM, thresholds 20 points lower, 24 h (rule R-CB-01) | Analyst confirms; only a person lifts it early | Built. The cluster comes from a sample until Lane B's detector is installed |
| The known contact's SIM changed in the last 7 days | No text is sent (rule R-OOB-01) | Analyst decides | Built (scenario `diverted_simswap`) |
| A leg was changed or replayed | The rail adapter refuses it before sending; the chain reverts a modified or replayed intent | Security lead revokes the caller | Built: three attacks, 300 integrity cases, none gets through |
| Two such refusals on one adapter in 10 minutes | Kill switch: the adapter is cut; a payment held on that route is revoked and refunded; later payments take another route | Security lead rotates the keys, then restores the adapter | Built. Restoring is one call (`/v1/sim/rails/{id}/up`) |
| Rail outage | The rail is not eligible; the payment takes the best remaining legal route. The tier does not change | Operations | Built (scenario `outage`) |
| On-chain incident reported by the guardian | Incident shown with a DORA incident draft; the engine stops trying to release a frozen payment | Security lead confirms; compliance files if major | Intake built. The guardian itself is Lane C's |
| Model, chain or case writer down | Banner; rules (stricter) instead of the model, mock chain at start-up, case file from the rules; a payment to an account not on file is at least MEDIUM (rule R-DG-01); a chain failure during a payment releases nothing | Operations | Built |

## Rules of thumb

| Rule | Value |
|---|---|
| Dual control | From EUR 20,000, or from EUR 5,000 to a new account. The author approves first and cannot be the second approver |
| Approval with untrusted bank details | Conditional: funds are released only after the supplier confirms on a known contact |
| Out-of-band check | Outbound, on a contact already on file, after a SIM-swap check |
| Hold | 24 hours, then the release is impossible and the refund is open to anyone |
| Payer alerts | In the app or by SMS. Never by e-mail: the event schema has no e-mail channel |
| Who can release money | Nobody but the escrow contract, and only for a confirmed payment. No model, no case file, no administrator function |

## Evidence kept for every payment

- The norm checks with their legal references, the risk score with its reasons, the route scores.
- The approval records and their hash, which is part of the signed intent.
- The EIP-712 typed data and signatures of the intent, the verification and the revocation (`GET /v1/payments/{id}/proof`).
- Every transaction (hash, explorer link when the chain is real).
- The case file, where every sentence cites a rule or an event.
- One line per event in a hash-chained log: changing any line breaks the chain (`make verify-log`).

## Honest limits

Everything outside the engine is simulated: rails, banks, the supplier's phone, the telecom check, strong authentication. The thresholds above are defaults to confirm on validation data. Reporting to TRACFIN or to the FIC is a draft, never a filing. Nothing here has run on real payment flows.
