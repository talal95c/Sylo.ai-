# Sylo.ai — roadmap and lanes: who does what in each version

> Read [`project-context.md`](./project-context.md) first. The exact v0 content is in [`v0-build-spec.md`](./v0-build-spec.md); tools, wallets and keys are in [`setup.md`](./setup.md).
> This document replaces PRD §21.2–21.4 (roles, milestones, cut order) where they differ.

---

## 1. How to read this document

- **Task IDs:** `<lane><version>.<n>`. Example: `A1.3` = Lane A, version 1, task 3.
- **Priority:** **MUST** = needed for the version to be "done". **SHOULD** = only if time; otherwise it moves to the next version or to a slide.
- **Each task gives:** what to build, where (files), what it depends on, when it is done, and an estimate.
- **"Done"** for any task means: code and tests merged to `main` through a pull request with green CI, the lane's README updated in one line, and `make demo-check` (from v1) still green.

## 2. Timeline (Saturday 10 → Sunday 11 October 2026)

| Time | What happens |
|---|---|
| Sat 22:15 – 23:45 | **v0** built by one coding agent from `v0-build-spec.md`. Everyone else does the v0 tasks of their lane (§6.2): setup, wallets, research, drafts |
| 23:45 – 00:00 | v0 review by all four lanes (§6.3); tag `v0` |
| Sun 00:00 – 03:00 | **v1** build. Spec additions merged by 00:20. Handoffs at fixed times (§7.2) |
| 03:00 | v1 merge cutoff |
| 03:00 – 03:30 | v1 integration check (§5); tag `v1` |
| 03:30 – 07:00 | **Sleep, shift 1: Lanes B and C** |
| 03:30 – 04:30 | Lanes A and D start v2 (spec additions, stubs, visuals against sample fixtures) |
| 04:30 – 08:00 | **Sleep, shift 2: Lanes A and D** |
| 07:00 – 09:00 | **v2** build: B and C from 07:00, A and D from 08:00 |
| 09:00 | v2 merge cutoff |
| 09:00 – 09:15 | v2 integration check; tag `v2` |
| 09:15 – 09:45 | Record the backup video from tag `v2` (or `v1` if `v2` is not green) |
| 09:45 – 11:00 | **v3** stretch (one item per lane, behind a flag) **and** pitch materials (§11) |
| 11:00 | v3 cutoff |
| 11:00 – 11:45 | Two full rehearsals on the demo laptop |
| 11:45 | Final tag `demo` (last green tag) |
| 12:00 | **Code freeze.** Jury at 13:00 (to confirm with organisers) |

The two sleep shifts are staggered on purpose: A (integration) and D (demo UI) stabilise v1 right after the checkpoint, while B and C, whose outputs are self-contained packages, sleep first and wake first to start the long v2 tasks (cluster detection, guardian, eERC).

## 3. Lanes

| | Lane A — Engine | Lane B — Risk & data | Lane C — Chain | Lane D — Experience |
|---|---|---|---|---|
| **Owner** | _(fill in)_ | _(fill in)_ | _(fill in)_ | _(fill in)_ |
| **Profile** | Python backend, systems, integration | Data science, ML, graphs | Solidity, web3, security | React, Three.js, design, storytelling |
| **Folders** | `/engine`, `/scripts`, root files, `.github/` | `/ml` | `/contracts`, `/chain` | `/web` |
| **Branch prefix** | `lane-a/` | `lane-b/` | `lane-c/` | `lane-d/` |
| **Runs alone with** | `RISK_MODE=rules`, `CHAIN_MODE=mock` | `pytest`, golden cases from `sylo_spec.scenarios` | `forge test`, Anvil | `NEXT_PUBLIC_SOURCE=replay` and fixtures |
| **Provides** | API, events, fixtures, integration, demo runner | `sylo_risk.ModelRisk`, cluster detection, metrics | Contracts on Fuji, `sylo_chain.FujiChain`, guardian, eERC | Globe and every panel, deck, video |
| **Consumes** | `RiskPort` (B), `ChainPort` (C) | Spec models and scenarios | Spec EIP-712 vector and ports | Events and fixtures (A), metrics (B), explorer links (C) |
| **Pitch duty** | Demo driver, playbook | Metrics slide, model card | Compliance and proof slides | Deck, video, defense sheet |

## 4. Rules that keep one person's mistake from breaking the others

1. **One lane, one set of folders.** Edit only your folders. CODEOWNERS enforces it on pull requests.
2. **Spec first.** At the start of each version, the producing lane opens a `/spec` pull request with the new event types, endpoints or port methods **and hand-written sample fixtures**. Consumers build against those samples immediately, without waiting for the real implementation.
3. **Spec changes are additive** and need approval from two lanes (producer and a consumer). Never rename or delete a field or event.
4. **Ports and conformance tests.** Lane B and Lane C deliver packages that pass the conformance suites in `sylo_spec.conformance`. Lane A switches a flag only after the suite passes. Until then the mock stays the default.
5. **Feature flags with safe defaults.** `RISK_MODE=rules`, `CHAIN_MODE=mock`, `LLM_MODE=off` in v0 and `cached` from v1, `NEXT_PUBLIC_SOURCE=live` with automatic fallback to replay. If a real component fails at start-up, the engine falls back to the mock and shows a "degraded" banner. If it fails mid-payment, the payment stays held: nothing is released by default.
6. **Small pull requests, green CI, one review.** Merge your own lane's pull request after CI is green and one teammate has looked at it (any lane). No direct pushes to `main`. Never force-push `main`.
7. **CI per lane.** Each lane's workflow runs only on its paths, so your red build never blocks another lane's merge.
8. **Fixtures belong to Lane A.** Only Lane A re-records `/spec/fixtures` (`make fixtures`). Lane D may add hand-written sample fixtures in a spec pull request when A is busy, marked `samples-*`.
9. **Revert first.** If `main` breaks within 30 minutes of a checkpoint, revert the offending pull request (`git revert`) and fix it on the branch.
10. **The demo runs from a tag.** The demo laptop only runs the last green tag (`v1`, `v2`, `demo`), never a working branch.
11. **Status at each checkpoint** in the team channel, using this template:
    ```
    [Lane X] <version> checkpoint
    Done: <IDs and PR links>
    Not done: <IDs> → moved to <version> / cut
    Flags for the demo: <e.g. RISK_MODE=model, CHAIN_MODE=fuji>
    Blocked by: <ID or nothing>
    Next: <IDs>
    ```
12. **Coding agents follow the same rules.** Give them the prompt template in §13.

## 5. Checkpoint procedure (v1 at 03:00, v2 at 09:00)

1. **T − 30 min:** each lane opens its last pull request; nothing new starts.
2. **T:** merge cutoff. Unmerged work waits for the next version.
3. **T + 0–15 min:** Lane A runs `make test` and `make demo-check` on `main` (live flags), then with mock flags. Lane D runs scenes 1, 2 and 2b in the browser in live mode and in replay mode. Lane C opens every explorer link of one live run.
4. **T + 15–30 min:** fix or revert. Lane A tags (`git tag v1 && git push origin v1`) and posts the flags to use for the demo.

---

## 6. v0 — walking skeleton (Saturday 22:15 → Sunday 00:00)

**Goal:** the whole story runs on one laptop with mocks, on the globe, and the interfaces between lanes are frozen. **Done** = the acceptance checks of `v0-build-spec.md` §12 pass and `main` is tagged `v0`.

### 6.1 Who builds it

One coding agent, run by Youssef in this repository, on branch `v0/skeleton`, following `docs/v0-build-spec.md` exactly. Nobody else commits to `/spec`, `/engine`, `/ml`, `/chain`, `/contracts` or `/web` until the `v0` tag.

### 6.2 What each person does while the agent builds

**Lane A — Engine**

- **A0.1** Read `project-context.md` and `v0-build-spec.md` §4–5; list questions for the review. (15 min)
- **A0.2** Create a Mistral API key, store it in the team password manager, test one call. (10 min)
- **A0.3** Ask the repository owner (talal95c) to give all four members write access and to protect `main`: pull requests required, status checks required, no force push. (10 min)
- **A0.4** Draft the v1 spec additions (task A1.0) on paper, ready to open as a pull request right after the `v0` tag. (30 min)
- **A0.5** Write the cached case file for the diverted scenario (content of A1.7): summary of at most 120 words, each sentence citing a rule ID or an event. (20 min)

**Lane B — Risk & data**

- **B0.1** Read `project-context.md`, PRD §10 and §17. (15 min)
- **B0.2** Write the simulator design: entity counts (scaled from PRD §17.1), typology rates, distributions, mule-cluster geography (Aflao and the Togo border, Kumasi), honest noise, seeds A and B. Pick LightGBM (macOS: `brew install libomp`) or scikit-learn HistGradientBoosting, and check that it installs. (30 min)
- **B0.3** Start coding the simulator in **new files only** under `ml/sylo_risk/sim/` on branch `lane-b/simulator` (numpy and pandas only). Do not create `ml/pyproject.toml`: the v0 build creates it. Rebase on the `v0` tag. (45 min)
- **B0.4** Draft `spec/metrics.schema.json` (task B1.0). (10 min)

**Lane C — Chain** (follow [`setup.md`](./setup.md) §4–6)

- **C0.1** Install Foundry; check `forge --version` and `cast --version`. (10 min)
- **C0.2** Create a Builder Hub account; request test AVAX for the deployer wallet; use the fallbacks of `setup.md` if the faucet refuses. (15 min)
- **C0.3** Generate the nine role wallets, store them in the password manager, fill your private `.env`. (15 min)
- **C0.4** Fund the wallets from the deployer and check balances. (10 min)
- **C0.5** Check both Fuji RPC endpoints (`cast chain-id` returns 43113). Deploy and verify a five-line throwaway contract through Routescan to make sure verification works before v1. (20 min)
- **C0.6** Optional: get 20 EURC from Circle's faucet to the EU CASP wallet for a real-EURC smoke test. (5 min)
- **C0.7** Read the eERC documentation and choose the deployment path for C2.2 (time-box 20 min).

**Lane D — Experience**

- **D0.1** Read `project-context.md` and `v0-build-spec.md` §8. (15 min)
- **D0.2** Download the globe textures (earth night, night sky, topology) for the offline demo (task D1.1). (5 min)
- **D0.3** Outside the repository, test react-globe.gl on the demo laptop: 200 animated arcs and 20 HTML markers at 60 frames per second. Note the limits. (25 min)
- **D0.4** Design sheet: colors (tiers, hop kinds), fonts, payment card and alert mock-ups, camera path per scene (storyboard of scenes 1, 2, 2b). (30 min)
- **D0.5** Deck skeleton: title, problem, live demo, how it works, proof, numbers, compliance, business model, team. (20 min)

### 6.3 v0 review (23:45 → 00:00)

Everyone pulls `v0/skeleton`, runs `make setup && make test`, and checks their own part:

| Lane | Checks |
|---|---|
| A | Acceptance checks 1–7 end to end; `make fixtures-check`; fills `CODEOWNERS` usernames; merges the pull request; tags `v0` |
| B | `sylo_spec.scenarios` matches §4.6 of the v0 spec; `run_risk_conformance` makes sense for a model; `ml/` skeleton is usable |
| C | Contracts and tests match PRD §13.3; the EIP-712 vector passes in Python and Solidity; `make anvil-deploy` works |
| D | Globe frame rate on the demo laptop; replay fallback; layout readable from 3 metres |

A defect that takes under 10 minutes goes back to the agent; anything larger becomes a v1 task of the owning lane.

---

## 7. v1 — real proof (Sunday 00:00 → 03:30)

### 7.1 Goal and done criteria

**Goal:** Scenes 1, 2 and 2b run live with real Fuji transactions, the trained model and every human touchpoint (payer, supplier, analyst), and three attacks fail visibly.

**v1 is done when:**

1. With `CHAIN_MODE=fuji`, every chain event of scenes 1, 2 and 2b links to a real transaction on Snowtrace, and the three contracts are verified.
2. With `RISK_MODE=model`, legit is LOW and diverted is MEDIUM (score 40–69) with at least three reasons, at least one of them from the model.
3. Claire and Marc approve in the payer panel, Kwame answers in his phone panel, the analyst confirms the revocation in the analyst drawer.
4. The attack console runs three attacks (release a revoked payment, swap the beneficiary, replay an intent); each fails, with the reason on the globe, in the feed and in the proof panel, and an explorer link for on-chain failures.
5. With `CHAIN_MODE=mock` and `RISK_MODE=rules`, everything above still works (labelled simulated).
6. Fixtures are re-recorded; `make test` and `make demo-check` are green.

### 7.2 Handoffs

| Due | From | Delivers | To |
|---|---|---|---|
| 00:20 | A (A1.0) | Spec: v1 events, endpoints, `samples-v1.jsonl` | D, C |
| 00:20 | B (B1.0) | Spec: `metrics.schema.json`, `ml/reports/metrics.sample.json` | D (v2), A |
| 00:20 | C (C1.0) | Spec: `ChainPort.freeze`, `pause_corridor`, deployment file format | A |
| 01:00 | C (C1.2) | Contracts deployed and verified on Fuji; `contracts/deployments/43113.json`; addresses posted | A, D |
| 02:00 | A (A1.3, A1.4, A1.8) | Approve, supplier-response and case-action endpoints | D (D1.2, D1.3, D1.5) |
| 02:15 | B (B1.4) | `sylo_risk.ModelRisk` passing conformance and golden cases | A (A1.2) |
| 02:15 | C (C1.3) | `sylo_chain.FujiChain` passing conformance on Fuji | A (A1.1) |
| 02:30 | A (A1.9) | Re-recorded fixtures, `make demo-check` | D, all |

If a handoff is late, the consumer keeps working on the mock or the sample fixture and integrates later; nobody waits idle.

### 7.3 Lane A — Engine (v1)

**A1.0 — v1 spec additions** · MUST · 20 min · first thing at 00:00
- Events: `approval.required { required: [{ name, role }], conditional, note }`; `leg.rejected { hop, rail, reason: INTENT_HASH_MISMATCH | NONCE_USED | REVOKED | EXPIRED | NOT_CONFIRMED }`; `case.ready { summary, citations: [{ ref, source }], reportDraft?, llm: off | cached | live }`; `case.action { action, by }`.
- Endpoints: `POST /v1/payments/{id}/approve { approver: "claire" | "marc" }`; `POST /v1/cases/{paymentId}/actions { action: CONFIRM_REVOCATION | RELEASE | FREEZE }`; `POST /v1/attacks/swap_beneficiary`; `POST /v1/attacks/replay`; `GET /v1/payments/{id}/proof`. Scenario option `auto: true` now also auto-approves and auto-confirms the analyst step.
- Hand-written sample events in `spec/fixtures/samples-v1.jsonl`.
- Done when: merged with approval from A and D.

**A1.1 — Fuji chain integration** · MUST · 30 min · depends on C1.3
- `CHAIN_MODE=fuji` loads `FujiChain`; EIP-712 domain read from the chain; `explorerUrl` on every chain event; `simulated: false` on chain events.
- Start-up failure → mock + `degraded: ["chain"]`. Failure mid-payment → the payment stays held, banner, nothing released.
- Done when: diverted + deny on Fuji shows five working explorer links (commit, deposit, verification, revocation, refund).

**A1.2 — Model integration** · MUST · 15 min · depends on B1.4
- `RISK_MODE=model`; final tier = max(rule floor, model band); reasons merge rule reasons and model reasons; `risk.scored.model` carries the model version; fallback to rules + `degraded: ["risk"]`.
- Done when: engine tests pass with the model installed and the golden cases give LOW and MEDIUM.

**A1.3 — Payer approval and dual control** · MUST · 30 min
- After `route.selected`: `approval.required` (conditional for MEDIUM, note "Funds are released only after the supplier confirms on a known contact"). Claire approves, then Marc (dual control at ≥ EUR 20,000) → `approval.granted` with `approvalHash` over both records. The intent's author cannot be the second approver.
- Done when: without `auto`, the scenario waits for both approvals; with `auto`, it continues.

**A1.4 — Out-of-band check and SIM-swap mock** · MUST · 15 min
- CAMARA-shaped `sim_swap.check(msisdn, max_age_hours)`. A recent swap on the supplier's known number fires R-OOB-01: no SMS, analyst path instead. `verification.requested.simSwapRecent` reflects the result.
- SHOULD: scenario variant `diverted_simswap`.

**A1.5 — Rail adapters R1–R4 and integrity attacks** · MUST · 45 min
- One adapter interface (`quote`, `initiate`, `status`). Before `initiate`: recompute the intent digest from the leg fields and salt, compare with `chain.intent_hash`; check validity window, nonce and registry status (COMMITTED for LOW, CONFIRMED for MEDIUM). Any failure → `leg.rejected`. One idempotency key per leg.
- Attack `swap_beneficiary`: the leg's beneficiary is changed in transit → the adapter refuses (`leg.rejected`), then a deposit with the modified intent reverts on-chain (`tx.reverted` `CommitmentMismatch`).
- Attack `replay`: the same signed intent is committed again → `tx.reverted` (`InvalidTransition` or `NonceUsed`).
- Done when: both attacks emit the events above in mock and Fuji modes.

**A1.6 — Hash-chained decision log and proof endpoint** · SHOULD · 30 min
- `engine/data/log.jsonl`: `{ seq, prevHash, type, payload, hash }`. `GET /v1/payments/{id}/proof` returns typed data, signatures, transactions and log entries. `make verify-log` recomputes the chain; editing one line makes it fail (demo of "edit a decision").

**A1.7 — Investigator case file** · SHOULD · 45 min
- `LLM_MODE=cached` reads `engine/sylo/agents/cache/diverted.json` (written in A0.5). `LLM_MODE=live` calls Mistral with JSON-schema output. A validator rejects any sentence without a citation (rule ID, reason ref or event ID) and falls back to the cached file. Emits `case.ready` less than 60 s after `payment.held`. The agent has no tools and cannot change any decision.

**A1.8 — Analyst actions** · MUST · 20 min
- `POST /v1/cases/{paymentId}/actions`: `CONFIRM_REVOCATION` (signs the `Revocation` with the analyst key, revokes, refunds), `RELEASE` (only when CONFIRMED), `FREEZE`. Emits `case.action`. With `auto`, confirmation happens after 1.5 s.

**A1.9 — Fixtures and demo check** · MUST · 20 min · due 02:30
- Re-record fixtures in mock mode. `scripts/demo_check.py` and `make demo-check`: run legit, diverted + deny, diverted + confirm and the three attacks against a running engine at speed 20 and assert the event sequences.

### 7.4 Lane B — Risk & data (v1)

**B1.0 — Metrics schema** · MUST · 15 min · first thing at 00:00
- `spec/metrics.schema.json`: `dataset { seedTrain, seedEval, payments, days }`, `metrics { recallT1, recallAll, precisionHigh, fprMediumPlus, ttdP95Ms, valueStoppedPct, diversionRate, stpRate }`, `baselines [{ name, recallAll, fprMediumPlus }]`, `ablations [{ step, recallAtFpr }]`, `modelVersion`, `generatedAt`, `sample: boolean`. Plus `ml/reports/metrics.sample.json` with `sample: true`. Approval: B and D.

**B1.1 — Simulator** · MUST · 60 min
- Seeded France → Ghana generator: entities scaled from PRD §17.1, generation under 2 minutes on a laptop; typologies T1–T4 at the PRD rates; about 3% honest noise; seeds A and B with **disjoint** mule clusters; regions with coarse coordinates only. `make data SEED=A` writes to `ml/data/` (git-ignored).
- Integrity cases I1–I3 (substitution, replay, modified amount) exported to `ml/data/integrity_cases.jsonl` for Lane A's adapter tests.

**B1.2 — Features** · MUST · 30 min
- Families B, V, P, G, H, N, S, R computed from `PaymentOrder`, `RiskContext` and B-owned aggregates (history per payer and account). The same code serves training and inference. Unit tests on the golden cases.

**B1.3 — Model, calibration, thresholds** · MUST · 30 min
- Gradient-boosted trees with monotonic constraints where the risk direction is known; isotonic calibration on seed A days 21–25; thresholds tuned so legitimate MEDIUM+ ≤ 2% and precision at HIGH ≥ 90%. `make train` writes `ml/models/` (commit the artifact only if it is under 5 MB).

**B1.4 — `ModelRisk`** · MUST · 30 min · due 02:15
- Implements `RiskPort`: calibrated score 0–100, band tier, `floorTier = LOW`, top three reasons in plain English (LightGBM `pred_contrib=True` gives TreeSHAP values; otherwise feature deltas), `model = "gbm-<date>"`.
- Passes `run_risk_conformance`. Golden cases: legit < 40; diverted 40–69.
- If the honest model scores diverted ≥ 70, tell A and D immediately: Scene 2 would become HIGH (no escrow). Fix it with honest features (for example, at Scene 2 time the mule account is not yet linked to a known cluster), never by hard-coding the case.

**B1.5 — First evaluation** · SHOULD · 30 min
- `make eval SEED=B` writes a schema-valid `ml/reports/metrics.json` with the model and two baselines (rules only, logistic regression).

### 7.5 Lane C — Chain (v1)

**C1.0 — Spec additions** · MUST · 15 min · first thing at 00:00
- `ChainPort.freeze(payment_id)`, `ChainPort.pause_corridor(corridor_id)`; explorer URL convention `${EXPLORER_BASE_URL}/tx/<hash>`; format of `contracts/deployments/<chainId>.json`. Approval: C and A.

**C1.1 — Contract hardening** · MUST · 45 min
- Fuzz tests and handler-based invariant tests for PRD §13.3 invariants 1–7 (escrow balance equals open holds; funds only to payer or intent beneficiary; mismatch reverts; release only when CONFIRMED and not frozen, expired or paused; permissionless refund; one deposit per payment and one use per nonce; reentrancy). Gas report. Slither if available.

**C1.2 — Fuji deployment and verification** · MUST · 30 min · due 01:00
- Run `Deploy.s.sol` on Fuji with the real role addresses; `Approve.s.sol` with the EU CASP key; verify the three contracts on Snowtrace through Routescan (`setup.md` §7); write `contracts/deployments/43113.json`; post the addresses in the team channel.
- Done when: the three contracts show "verified" on Snowtrace and `cast call` on `statusOf` works.

**C1.3 — `FujiChain`** · MUST · 75 min · due 02:15
- web3.py 7: refuse to start unless chain ID is 43113; two RPC endpoints with fallback; the relayer key sends `commit`, `deposit`, `recordVerification`, `revoke`, `refund`, `markExecuted`; wait for receipts (60 s timeout); one nonce manager per sender; custom errors decoded to their names → `ChainReverted(reason)`; `TxRef` with explorer URL.
- Done when: `run_chain_conformance` passes on Anvil (fast, in CI) and on Fuji (slow, marked, run by hand).

**C1.4 — Visible failed transactions** · MUST · 20 min
- For attacks (`caller="attacker"`), send with a fixed gas limit (skip gas estimation) so the failed transaction is mined and visible on Snowtrace with its revert reason; `ChainReverted.tx` carries the `TxRef`.

**C1.5 — Attack scripts** · SHOULD · 15 min
- `contracts/script/attacks/*.sh` with `cast` for the three attacks, usable without the engine (backup during the demo).

### 7.6 Lane D — Experience (v1)

**D1.1 — Globe polish** · MUST · 60 min
- Textures in `web/public/textures` (works offline); camera choreography per scene; a glowing comet head in addition to the dash; Avalanche label at the chain arc apex; SVG lock; smoother reverse comet; 60 frames per second on the demo laptop.

**D1.2 — Payer panel (Claire's bank app)** · MUST · 30 min · uses A1.3 (samples first)
- Route options with the score breakdown, excluded routes with their rule and reason, tax notice, price of safety, conditional-approval explanation; buttons "Approve (Claire)" and "Co-approve (Marc)".

**D1.3 — Phone panels** · MUST · 25 min · uses A1.4
- Claire's phone (in-app and SMS alerts only, never email) and Kwame's phone (SMS request with Confirm / Deny calling `supplier-response`); SIM-swap check status shown.

**D1.4 — Proof panel and mode banner** · MUST · 25 min · uses A1.1, C1.2
- Every chain event: function, status before → after, short transaction hash linking to the explorer, or a "simulated" badge. Failed transactions in red with the reason. Banner from `system.mode`, amber when degraded.

**D1.5 — Analyst drawer** · MUST · 30 min · uses A1.7, A1.8
- Reasons with refs; case file with clickable citations (scrolls to the feed event); buttons Confirm revocation, Release, Freeze; 24-hour expiry countdown.

**D1.6 — Attack console** · MUST · 15 min · uses A1.5
- Three buttons; a red cross where the attack was refused (adapter hop or escrow lock); the reason in the feed and the proof panel.

---

## 8. v2 — network defence and incidents (Sunday 03:30 → 09:15)

### 8.1 Goal and done criteria

**Goal:** show the network behind the fraud and the operational incidents (PRD scenes 3–5), with measured numbers.

**v2 is done when:**

1. **Scene 3 (mule wave):** three linked payments → cluster detected → hexagons light up near the Aflao border → the analyst confirms a regional circuit breaker → the next payment into that region is held at MEDIUM at least.
2. **Scene 5 (rail outage):** R3 goes down → the next legitimate payment is rerouted (R3 dashed red) → R3 comes back.
3. **Kill switch:** repeated integrity refusals from one adapter cut that connector, visibly.
4. **Scene 4 (guardian)**, if C2.1 is done: a fake confirmation signed with a stolen verifier key is detected and the payment frozen within a block; the attacker's release then reverts; an incident with DORA fields appears.
5. The metrics page shows numbers measured on seed B, with baselines and ablations.
6. The backup video is recorded.

### 8.2 Handoffs

| Due | From | Delivers | To |
|---|---|---|---|
| 03:45 | A (A2.0) | Spec: v2 events, `ClusterPort`, endpoints, sample fixtures for scenes 3–5 | D, B, C |
| 08:00 | B (B2.1) | `sylo_risk.clusters.detect` implementing `ClusterPort` | A (A2.1) |
| 08:30 | C (C2.1) | Guardian service posting incidents to the engine | A (A2.4), D (D2.4) |
| 08:45 | B (B2.2) | `ml/reports/metrics.json` from seed B | D (D2.3), A |

### 8.3 Lane A — Engine (v2)

**A2.0 — v2 spec additions** · MUST · 15 min · 03:30
- Events: `cluster.detected { clusterId, accounts, agents, region, centroid: { lat, lng }, points: [{ lat, lng, weight }], linkedPayments }`; `breaker.on { breakerId, scope: { region, corridor }, thresholdsDelta: -20, expiresAt, confirmedBy }`; `breaker.off`; `rail.down { routeId, reason }`; `rail.up`; `killswitch.on { adapter, reason, refusals }`; `guardian.incident { incidentId, rule, txHash, action, dora }`; `traffic.sample { arcs }`.
- Port: `ClusterPort.detect(window) -> list[Cluster]`.
- Endpoints: `POST /v1/sim/mule-wave`, `POST /v1/sim/rails/{routeId}/down` and `/up`, `POST /v1/breakers/{id}/confirm`, `POST /v1/guardian/incidents`, `GET /v1/metrics`.
- Sample fixtures: `samples-scene3-mule-wave.jsonl`, `samples-scene4-guardian.jsonl`, `samples-scene5-outage.jsonl`, `cluster-sample.json`. Approval: A and D.

**A2.1 — Regional circuit breaker** · MUST · 60 min · uses B2.1 (stub first)
- `sim/mule-wave` injects three payments from three payers to accounts of one cluster. Until B2.1 lands, a stub `ClusterPort` reads `cluster-sample.json`. `cluster.detected` fires after the third payment; the breaker is proposed; the analyst confirms (auto in fixtures) → `breaker.on`. Payments in scope get rule R-CB-01 (floor MEDIUM) and thresholds −20 for 24 hours; only a human lifts it early.

**A2.2 — Rail outage and reroute** · MUST · 30 min
- `rail.down` makes the route ineligible; the next payment takes the best remaining route within the payer's limits (a MEDIUM payment still needs conditional settlement); `rail.up` restores it. Scenario `outage`.

**A2.3 — Kill switch and degraded mode** · MUST · 30 min
- Two integrity refusals from one adapter within 10 minutes → `killswitch.on` for that adapter; affected intents revoked with reason `KILL_SWITCH`; healthy payments rerouted. If the model, chain or LLM is down: stricter mode (new payees at least MEDIUM), banner through `system.mode`.

**A2.4 — Guardian incident intake** · SHOULD · 20 min · uses C2.1
- `POST /v1/guardian/incidents` → `guardian.incident` and a DORA incident draft (clients affected, amount, duration, geographic spread, criticality, third parties) in `engine/data/incidents/`.

**A2.5 — Leftovers from v1** · SHOULD
- Finish A1.6 (log) and A1.7 (case file) if they slipped.

**A2.6 — Integrity evaluation and metrics endpoint** · SHOULD · 20 min
- Run B's I1–I3 cases through the adapters → `engine/reports/integrity.json` (diversion rate, expected 0). `GET /v1/metrics` serves `ml/reports/metrics.json` merged with the integrity result, or the labelled sample.

### 8.4 Lane B — Risk & data (v2, from 07:00)

**B2.1 — Mule-cluster detection** · MUST · 60 min · due 08:00
- Graph (NetworkX) over accounts, wallets and cash-out agents: fan-out, minutes from credit to forward, shared agents, young fast-cash-out clusters. `sylo_risk.clusters.detect(window)` implements `ClusterPort`, with centroid and points at region level (never precise locations). Measures time to detect per campaign against the isolated-institution baseline.

**B2.2 — Final evaluation** · MUST · 60 min · due 08:45
- Seed B numbers for every metric of PRD §17.3 that B owns, the three baselines (rules only, isolated institution, logistic regression) and the ablation ladder. `make data SEED=A && make train && make eval SEED=B` regenerates everything.

**B2.3 — Background traffic** · SHOULD · 15 min
- 300 sampled payments with routes and coordinates as `spec/fixtures/traffic.jsonl` (spec pull request, approval from D).

**B2.4 — Model card and analyst test protocol** · SHOULD · 30 min
- `docs/model-card.md` (purpose, data, metrics, limits, EU AI Act position) and `docs/analyst-test.md` (5 cases, 2 testers, timed with and without the case file).

### 8.5 Lane C — Chain (v2, from 07:00)

**C2.1 — Guardian** · MUST · 60 min · due 08:30
- `chain/sylo_chain/guardian.py`: polls registry and escrow logs every 2 s through both RPC endpoints; rules: CONFIRMED without a matching out-of-band record in the engine, release without a prior intent, unknown caller on a privileged function; actions: `freeze` or `pauseCorridor` with the guardian key; posts the incident to the engine.
- Scene script `stolen_verifier_key.py`: on a fresh MEDIUM payment, records a fake CONFIRMED signed with the verifier key, then tries `release` a few seconds later. The guardian freezes first; the release reverts. Say honestly in the pitch that a challenge window (roadmap) closes the remaining race.

**C2.2 — eERC confidential leg** · SHOULD · time-box 90 min
- eERC in converter mode over tEURC on Fuji (official EncryptedERC scripts or the Builder Console, chosen in C0.7); register EU CASP and GH VASP; wrap → confidential transfer → unwrap; auditor decryption. A small Node service in `chain/eerc/` exposes `POST /transfer` returning transaction hashes and the auditor-decrypted amount. If the time-box runs out: one slide with the design and its honest limit (PRD §13.6).

**C2.3 — Explorer check** · SHOULD · 15 min
- Every demo link opens; any new contract is verified.

### 8.6 Lane D — Experience (v2: 03:30–04:30, then from 08:00)

**D2.1 — Mule cluster and breaker on the globe** · MUST · 45 min · samples first
- Hexagon bins from `cluster.detected` points near the Aflao border, pulsing; the breaker's region tinted with label and expiry; camera for Scene 3.

**D2.2 — Outage and reroute** · MUST · 20 min
- `rail.down`: the route turns dashed red; the next payment's comet takes the new route; `rail.up` restores.

**D2.3 — Metrics page** · MUST · 40 min · uses B2.2 (sample first)
- Route `/metrics`: headline numbers, model vs baselines, ablation chart, "measured on seed B, never seen in training". Shows "sample" in large letters while the sample file is used.

**D2.4 — Incident visuals** · MUST · 20 min
- `killswitch.on`: adapter node greyed with a cross. `guardian.incident`: red shield on the contract and a drawer with the DORA draft.

**D2.5 — Background traffic** · SHOULD · 20 min · uses B2.3
- Pale arcs from `traffic.jsonl` behind the demo payment.

**D2.6 — Auditor view of eERC** · SHOULD · 20 min · uses C2.2
- "Amount encrypted on the explorer" next to "Auditor view: EUR 85,000".

**D2.7 — Backup video** · MUST · 09:15–09:45
- Screen recording of scenes 1 → 5 from the `v2` tag at 1× speed; copy it to the demo laptop and a shared drive.

---

## 9. v3 — platform stretch (Sunday 09:45 → 11:00)

Rules: **at most one item per lane**, behind a flag that is off by default, merged only if `make demo-check` stays green. Otherwise it becomes a slide.

| Lane | Pick one |
|---|---|
| A | **A3.1** Pack 2 Lagos → Accra from files only (`NG.yaml`, `NG-GH.yaml` with PAPSS and mobile money rails, scenario `lagos-accra`): "a new corridor is one file". **A3.2** Intake agent: invoice and email text → fixed schema with provenance; 20 prompt-injection cases → 0 tier changes. **A3.3** eERC in the engine flow (`confidential.transfer`) if C2.2 is done |
| B | **B3.1** Nigerian data and golden cases for pack 2. **B3.2** Run the analyst timing test and add the result (labelled indicative) |
| C | **C3.1** `DecisionAnchor`: Merkle root of the decision log every 60 s, inclusion proof. **C3.2** Consortium L1 through the Builder Console with a managed testnet node (3-day lifetime), same contracts, roots anchored on the C-Chain |
| D | **D3.1** Auditor page: recompute an intent digest in the browser from `/proof` and match the on-chain event. **D3.2** Receiving-bank view (Ama). **D3.3** Pack 2 corridor on the globe |

## 10. v4 — vision (pitch only, no code)

| Slide | Owner |
|---|---|
| Adoption path: four-week shadow-mode pilot with one bank | A |
| Federated detection across institutions without sharing raw data | B |
| Intent hash carried in ISO 20022 `pacs.008` supplementary data; consortium L1 in production | C |
| "Every corridor on one globe": the network view | D |

## 11. Pitch and deliverables

| Deliverable | Owner | Due |
|---|---|---|
| Metrics slide and model card | B | 10:00 |
| Demo run sheet (buttons, timings, fallbacks: replay, attack scripts, video) | A | 10:30 |
| Response playbook one-pager (PRD §12) | A | 10:30 |
| Compliance slide (PRD §18.1) and on-chain proof slide | C | 10:30 |
| Defense sheet (PRD §22.3) | all; D consolidates | 11:00 |
| Deck assembled and designed | D | 11:00 |
| Two rehearsals on the demo laptop | all | 11:00–11:45 |

## 12. If you are late: cut order per lane

| Lane | Cut first → last | Never cut |
|---|---|---|
| A | A1.7 live LLM (keep cached) → A1.6 → A2.4 → A2.2 | Approval (A1.3), adapters and attacks (A1.5), analyst actions (A1.8), Fuji integration (A1.1), fixtures and demo check |
| B | B2.4 → B2.3 → ablations → B2.1 | A model passing the golden cases (fallback: rules + logistic regression); numbers measured on seed B |
| C | C2.2 eERC (slide) → C1.5 → C2.1 guardian (slide) | Fuji deployment and verification, `FujiChain`, attacks failing on-chain with explorer links |
| D | D2.5 → D2.6 → D1.1 extras | Alert overlay, payer, phone and proof panels, attack console, replay fallback |

## 13. Prompt template for a coding agent working in a lane

```
You are working on Sylo.ai, Lane <X> (<name>).
Read AGENTS.md, docs/project-context.md, and the Lane <X> sections of docs/roadmap-and-lanes.md.
Task: <ID> — <title>.
Done when: <copy the task's "done when" lines>.
Only edit files under <your folders>. If you need a change in /spec or in another lane's folder,
stop and write the request (what, why, which consumer) instead of making it.
Before finishing, run <lane test command> and make sure it is green.
Never commit .env files, private keys or build output.
```
