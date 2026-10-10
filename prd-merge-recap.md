# PRD merge recap: what was kept and rejected

> Secure Horizons, ESSEC, 10–11 October 2026 · Track 1 (Fintech Security: Guardians of Value)
> Result of the merge: [`prd-final-v4.md`](./prd-final-v4.md)
> Originals: branch `devin/1791653676-prd-final` of `talal95c/hackathon-Essec` (`docs/prd-sources/`, `docs/prd.md`, `docs/projet.md`, `docs/comparaison-prd.md`).

## The four source PRDs

| Code | PRD | Author | One-line idea |
|---|---|---|---|
| **A** | *Risk-Aware Payment Router* | Not named | African router with AI agents; separates fraud risk from route risk |
| **B** | *L'Aiguilleur* | Oscar | Lagos – Accra – Abidjan router with geographic fraud signals, graduated response and a live 3D globe |
| **C** | *Payment Integrity Router* v1.1 + `projet.md` | Talal | Signed payment intent checked by every rail, out-of-band verification, Jev/Mistral, built on an existing codebase |
| **D** | *L'Aiguilleur* v4 | Youssef | Norms → risk → cost decision order, country profiles, France → Ghana, on-chain EIP-712 proof, mentor feedback |

## How we decided

Something was kept if it improves what the Track 1 jury scores (detection 30%, response 20%, feasibility 20%, compliance 15%, pitch 15%) or answers the mentor. It was rejected if it contradicts another PRD's stronger idea, depends on code we are not using, or does not fit the ≈ 15 hours left.

---

## A — Risk-Aware Payment Router

### Kept

| What | Why | In v4 |
|---|---|---|
| **Fraud risk and route risk are separate.** Fraud risk decides whether the payment may leave; route risk (outage, unreliable intermediary, compromised connector) only helps choose the rail. Rerouting never fixes fraud | Strongest design idea across the four PRDs; resolves B's main flaw | §6.3, §11.1 |
| Recipient **accessibility** in the route score (can the beneficiary use the money where they are?) | Real-world difference between "credited" and "usable" | §11.3 (`pUnusable`) |
| **Attack simulation screen** that judges can use themselves | Strong pitch moment | §7.4 (attack console) |
| Pseudonymised risk signals shared between institutions under access control | Explains the cross-institution view without sharing customer files | §5, §22.3 |
| AI recommends, deterministic rules enforce; an AI failure never authorises a payment | Core safety principle | §6.3, §14 |
| "Use blockchain only where it brings a clear benefit" | Keeps the on-chain part justified | §13.1 |

### Rejected

| What | Why |
|---|---|
| Three LLM agents performing detection (fraud agent, cross-network agent, decision agent) | Detection must be fast, measurable and reproducible; LLMs in the detection loop are not. One investigator agent remains, after the decision |
| Generic "two African countries, three routes" corridor | Replaced by the concrete France → Ghana scenario |
| Consumer senders as end users | Focus on business payments (larger amounts, BEC exposure) |
| WebSockets | One-way server-sent events are enough |

---

## B — L'Aiguilleur (Oscar)

### Kept

| What | Why | In v4 |
|---|---|---|
| The buyer is the institution (fintech, PSP, bank); the daily user is its **fraud and compliance analyst** | Clear customer and user for Track 1 | §5 |
| **Geographic signals**: account region vs supplier region, wallet opened in one region and emptied in another, cash-outs near a border, impossible travel, regional fraud wave; gain from geography measured separately | Detection that no single institution can do; measurable | §10.1 (family G), §17.2 |
| **Four response tiers** with timings; **regional circuit breaker** (thresholds −20 points for 24 h, only a human lifts it early) | Graduated, proportionate response | §12.1, §12.2 |
| Who is notified per country, reporting deadlines, **no tipping-off** | Compliance criterion | §12.3 |
| **Seeds A/B** evaluation; baselines including the **isolated institution**; amount withheld; time to detect | Credible, reproducible numbers | §17 |
| **3D globe as the main view (P0)**: the route of each payment traced hop by hop across institution nodes (decision of 10 October evening; v4.0 had it as P1) | Shows the cross-institution view that is the product's central argument | §0.1, §8 (M13) |
| **Event-driven UI**: one server-sent-event stream, events carry the UETR; the view only draws events; text feed works without graphics | Reliable demo | §15.3 |
| Routing mechanics: Yen's k-shortest paths, quote valid 600 s, cut-offs and time zones, **reroute on rail outage**, labelled technical splits | Realistic routing; "Recover" function | §11.3, §7.7 |
| ISO 20022 `pacs.008` pivot format with UETR; name check | Integration criterion | §16 |
| Sourced West African rail parameters and country compliance (NFIU, FIC, CENTIF, data-protection laws) | Ready-made content for the extension packs | Appendix A |
| **NIST CSF 2.0** and **MITRE ATT&CK** defense sheet | Expected deliverable | §22.2 |
| Practical risks: OpenZeppelin 5 has no escrow module, request test AVAX early, AWS credits, Docker Compose | Avoids known pitfalls | §13.3, §15.4, §24 |

### Rejected

| What | Why |
|---|---|
| Fraud risk inside the route score (`ρ·R(r,p)`) | A suspicious payment could become eligible because another rail is cheaper; contradicts A |
| Lagos – Accra – Abidjan triangle as the main scenario | Mentor asked for an intercontinental example; Lagos → Accra becomes the P1 extension pack, Paris → Abidjan stays on paper |
| Cost (≤ 1%) and speed (≥ 75% < 1 h) as headline goals | The jury scores detection and response, and our rails are simulated; shown as illustrative only |
| Rural family-remittance persona | Outside the business-payment scenario |
| Five roles | We are four |

---

## C — Payment Integrity Router v1.1 and `projet.md` (Talal)

### Kept

| What | Why | In v4 |
|---|---|---|
| Guiding principle: **the payer's approved intent is the source of truth; components can only restrict or verify it; models propose, rules dispose, humans decide** | Best one-sentence statement of the product's integrity | §6.1 |
| **Rail adapter contract** (`quote`, `initiate`, `status`, `onWebhook`, `reconcile`); leg states; before `initiate`, check intent hash, validity window, nonce and revocation; idempotency keys | Makes in-transit substitution impossible, not just detected; integration criterion | §13.5 |
| **Field provenance** (`invoice_pdf_email`, `verified_registry`, …) and **verified payee registry** (`first_seen`, successful payments, verification) | Strongest early BEC signal | §10.1 (family V), §16.1 |
| **Approval blocked** (not just warned) when details come from an untrusted source, until out-of-band verification on an **already-registered contact** | "Protect before approval" | §6.3, §10.2 (R-PV-01), §12.3 |
| **Time-lock** on first payment to a new account; **dual control** above a threshold | Fiat equivalent of escrow; step-up | §12.3 |
| **Payer alerts never by email** | In BEC the mailbox is compromised | §6.3, §12.3 |
| **Alert budget** (3% over 30 days, tuning only in the grey zone) and **degraded mode** stricter, never looser | Response quality; fail-safe | §10.3, §12.2 |
| **Kill switch** on a compromised connector, revocation visible to all rails, reroute | Track 1 area 3 (kill switch) | §12.2 |
| Simulated **phone panels** and **demo clock** | Makes out-of-band verification and expiries visible in the demo | §7.1, §8 |
| **Integrity attack set** (substitution, replay, modified amount) and **diversion rate = 0** | Measurable integrity claim | §17.1, §17.3 |
| Mistral writes a **≤ 120-word explanation** and never acts | Explainability for payer and analyst | §14 |
| Insight: **bank fraud engines miss BEC because the real customer authorises the payment** | Sharpest problem statement | §1, §3.3 |
| Competitive landscape and **adoption path** (shadow mode → verification → hold → enforcement) | Feasibility and business case | §16.3, §23 |
| Honeytokens, supplier-signed account attestation, verifiable credentials, ISO 20022 exports | Good ideas without time to build | P2 / roadmap |

### Rejected

| What | Why |
|---|---|
| The existing codebase (web app, optimiser service, Supabase, `TradeEscrow`, shared packages) | Team decision: requirements first, built from scratch for this problem |
| France → China corridor | China bans crypto and has strict capital controls; replaced by France → Ghana |
| Payer signing with a key held in the browser | A CFO paying through her bank has no crypto key; she approves with strong authentication in the app and the bank's services sign on-chain |
| Local dedicated L1 as the demo target | A local chain cannot show public proof; Fuji is P0, hosted L1 is P2 |
| Online bandit predictors, convex optimiser, multi-path splitting | No gain for detection or response; costly |
| Jev as a P0 "System 1" with three live questions; "System 1 / System 2" framing; Track 3 positioning | Track 1 only; Jev becomes an optional P1 feature, kept only if the ablation shows a recall gain |
| PSP sandbox (Airwallex), registry imports (GLEIF, INPI, Chinese registries), three languages, Supabase row-level roles | Out of scope for ≈ 15 hours |
| ≈ 134 person-hours of P0 | Does not fit; v4 P0 is 32.5 person-hours with the globe |

---

## D — L'Aiguilleur v4 (Youssef)

### Kept

| What | Why | In v4 |
|---|---|---|
| Decision order **norms → risk → cost → commit → action** | Structure of the whole product | §6.2 |
| **Jurisdiction profiles + one-file corridor packs** | Mentor's "norms differ by country"; easy extension | §4.3, §9 |
| France → Ghana scenario with sourced norms; **norm signals R1–R4** (R1: export proceeds not paid to the nominated bank) | Intercontinental case; norms as fraud signals | §7, §9.3 |
| Verification of Payee stops at SEPA; **SIM-swap check on the known contact** before out-of-band verification | Closes the gap that makes cross-border BEC work | §3.3, §7.3 |
| **EIP-712 intent, verification and revocation** checked on-chain; escrow whose `release` requires `CONFIRMED` | Mentor's attestations and immutability proof | §13.3, §13.4 |
| **Scene 2b** tamper attempts | "An attack that is blocked", visible on the explorer | §7.4 |
| eERC with the **honest limit** (contracts cannot produce eERC proofs) and modes A/B | Mentor's confidentiality point, without overclaiming | §13.6 |
| Chainlist, chain-ID check, two-provider reads | Mentor's RPC advice | §13.8 |
| Tax as information only; proof map; threat model; compliance mapping; DORA incident draft | Mentor and compliance criterion | §9.4, §7.8, §18, §19 |

### Rejected

| What | Why |
|---|---|
| Length (≈ 1,600 lines) and research detail not needed for the build | Must be usable tonight |
| "Track 3 angle" | Track 1 only |
| Guardian and Merkle anchoring close to P0 | Both moved to P1 |
| Separate tax scene (1b) | Tax becomes one line in Scene 1 |
| Reliance on the mentor for the L1 in the main plan | L1 is P2 |
| 5-minute pitch | 4 minutes |

---

## Contradictions and how they were resolved

| Topic | A | B | C | D | v4 decision |
|---|---|---|---|---|---|
| Main corridor | Two African countries | Lagos – Accra – Abidjan | France → China | France → Ghana + packs | **France → Ghana**; Lagos → Accra as P1 pack; Paris → Abidjan on paper |
| Fraud risk vs route score | Separate | Inside the score | Integrity first | Risk filters routes | **Separate** (A) |
| Intent / proof | Light audit | Log on Fuji | Signed intent checked by adapters | EIP-712 + escrow | **Signed intent (C) recorded as EIP-712 (D)**, checked by adapters (C) and contracts (D) |
| Response | 3 levels | 4 levels + circuit breaker | pass / hold / block | 3 levels + circuit breaker | **4 levels** (B) + escrow (D) + time-lock and dual control (C) |
| AI | 3 detection agents | LLM summary | Jev + Mistral | Investigator + intake + watch | **Rules + calibrated model decide**; one investigator (Mistral); intake P1; Jev optional P1 |
| Live view | Dashboard | Globe P0 | Timeline | Proof panel | **Globe as the main view, P0**; text feed and proof panel P0 beside it |
| Chain | C-Chain, optional | Fuji | Local L1, Fuji fallback | Fuji P0, L1 P2 | **Fuji P0**, hosted L1 P2 |
| Who signs | — | — | Payer's browser key | Router service | **Payer approves with strong authentication; bank services sign** |
| Track | Not stated | Track 1 | Track 1 + Track 3 | Track 1 + "Track 3 angle" | **Track 1 only** (mentor) |

## What each PRD contributes to v4, in one line

- **A:** the separation between fraud risk and route risk, and the jury-facing attack screen.
- **B:** the field (West Africa, geography), the analyst's workflow, the four-tier response, the evaluation protocol and the live event view.
- **C:** the integrity backbone (signed intent checked by every rail), the payee and provenance controls, the business rules and the adoption path.
- **D:** the decision order, country profiles and packs, the France → Ghana norms, and the on-chain proof answering the mentor.
