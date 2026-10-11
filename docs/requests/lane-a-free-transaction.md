# Request to Lane A (and `/spec` owners) — run a payment described by the user

From: Lane D (web). Status: proposed, not implemented. Lane D does not edit `/engine` or `/spec`.

## Why

`/test` now prices the two FR → GH recorded orders on the real engine (`POST /v1/quotes`, recorded quote shown offline) and launches them into the globe and nodes views (`POST /v1/payments`). Two limits remain, both on the engine side:

1. **Only recorded orders run.** `QuoteBody.order` is `legit | diverted | lagos-accra` and `PaymentBody.order` is `legit | diverted` (`engine/sylo/main.py`). A quote with another `amount` is `executable: false` (`Orchestrator.quote`). So a user cannot run "their own" payment: amount, invoice reference or beneficiary account cannot change the run.
2. **The globe cannot draw Lagos → Accra.** The NG institutions live only in `engine/packs/NG-GH.yaml` (`payer_lagos`, `bank_ng`, `corr_us`, `papss_hub`, `vasp_ng`, `momo_ng`) and have no coordinates; `spec/geo/institutions.json` has FR/EU/GH institutions only. spec/api.md says it: "the globe does not draw this corridor".

## What we ask

### A. A payment order the client describes (engine)

`POST /v1/quotes` and `POST /v1/payments` accept, as an alternative to `order`, a **custom order** built on a recorded corridor and recorded parties:

```json
{
  "custom": {
    "corridor": "FR-GH",
    "payerId": "payer_rhone",
    "payeeId": "payee-ssx",
    "creditorAccountId": "acc-ssx-nominated",
    "amount": { "value": "48500.00", "currency": "EUR" },
    "invoiceRef": "INV-2026-0418"
  }
}
```

Rules we expect the engine to enforce (the web only displays them):

- `corridor` must be a loaded pack (`FR-GH`, `NG-GH`); `payerId` must be the pack's payer, its country = the corridor's debtor country; the payee and the account must exist in the registries and the account's country = the corridor's creditor country. Otherwise 422 with the field in error. This is what keeps "pays de l'émetteur / pays du bénéficiaire" coherent: the client cannot send a GH account on an NG debtor by mistake, and cannot invent a party.
- Currency = the corridor's debtor currency (EUR for FR-GH, USD for NG-GH).
- Amount bounds: > 0, ≤ the pack's limit; the dual-approval and time-lock thresholds apply as for recorded orders.
- The quote is `executable: true` when the custom order is valid, and the payment then runs on `/v1/stream` exactly like a scenario (same events, same `payment.created` shape with debtor/creditor and their institutions).
- Untrusted account (`provenance` other than `verified_registry`) keeps today's behaviour: held, known-contact check. Free text fields (invoiceRef) are data, never instructions.
- Everything stays simulated (rails, chain on Fuji), as today.

### B. Execute NG → GH (engine), optional

Allow `POST /v1/payments` for `lagos-accra` (or a custom NG-GH order) so the second corridor also runs on the stream. If that's too much for this version, keep it quote-only — the web already labels it "quote only".

### C. Institutions for the second corridor (`/spec`, additive)

Add to `spec/geo/institutions.json` (additive change; needs Lane A + Lane D approval), with fictional names already in `NG-GH.yaml` and city-centre coordinates:

| id | name | city | country | lat | lng |
|---|---|---|---|---|---|
| payer_lagos | Lekki Foods Ltd | Lagos | NG | 6.5244 | 3.3792 |
| bank_ng | Lagoon Merchant Bank | Lagos | NG | 6.4550 | 3.3941 |
| corr_us | Hudson Correspondent Bank | New York | US | 40.7128 | -74.0060 |
| papss_hub | PAPSS settlement hub (simulated) | Cairo | EG | 30.0444 | 31.2357 |
| vasp_ng | Niger Delta Digital (registered provider) | Lagos | NG | 6.6018 | 3.3515 |
| momo_ng | NairaLink Wallets | Ibadan | NG | 7.3775 | 3.9470 |

`payer_lagos`, `bank_ng` and `vasp_ng` all sit in Lagos: the slightly different coordinates keep their globe points apart. Please also emit, in `payment.created`, the debtor's and creditor's `country` (already in the order model) so the web can title the corridor from the event instead of the hard-coded "Lyon → Ghana".

## What Lane D does once it lands

- `/test`: the beneficiary account and amount become editable within the corridor's registered parties (picker, not free text), country pills derived from the corridor; the quote → payment flow is unchanged.
- Globe: draws NG-GH routes from the new institutions; the top bar shows the corridor from `payment.created`.
- Tests: a replay fixture for one custom FR-GH order and one NG-GH order (`make fixtures`, Lane A).

## How to verify (Lane A)

- `cd engine && uv run pytest` with tests for: valid custom order executes; mismatched country → 422; unknown payee/account → 422; untrusted account → held.
- `make fixtures-check` and `make test` green (spec touched).
