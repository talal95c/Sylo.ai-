# Lane D plan — status and prioritized to-do (Sunday 11 October)

For Maria (Lane D, `/web`). Written by Youssef's agent at 06:20, from the code on `main` and `frontend-v2` and from the review of 05:20. Code freeze is **12:00** and the jury is at **13:00** (both to confirm with the organisers), so this plan only lists what fits in the next few hours. Items marked *nice-to-have* can be dropped without hurting the demo.

Each item has: **What** to build, **Why** (which demo scene or pitch point needs it), **Where** (files), and **Done when** (the check to run before ticking the box). Roadmap IDs (D1.x, D2.x) come from [`docs/roadmap-and-lanes.md`](roadmap-and-lanes.md) §7.6 and §8.6 on `main`.

## Where Lane D is today

**On `main`** (last web change 00:38): v0 globe, payment card with metric tiles (fraud risk, route cost, arrival) and the "Nominated / New account" pill, route cost table, excluded route as a red dashed line, candidate routes and grey pending legs on the globe, held alert with the analyst case file, event feed, demo controls (Scene 1, Scene 2 deny / confirm, attack 1), landing page, Nodes tab.

**On `frontend-v2`** (your restyle, 05:15): glowing panels, timeline of engine decisions, richer event feed, auto-placed globe labels. It merges cleanly with `main` and tests (16/16) and lint pass on the merged tree, but the branch is 57 commits behind `main`, and the review found regressions:

- Removed: the route cost table, the red dashed excluded route and the candidate routes on the globe, the grey pending legs, the payment card metric tiles and the "Nominated / New account" pill. The pitch needs these (handoff §14 item 1: "Fraud risk never enters the route score", "New account").
- Hard-coded "France to Ghana", "FRA", "GHA" in `PaymentCard.tsx` and `DecisionSteps.tsx`.
- Badges decided by searching free text: "Confirmed / Fraud" in `EventFeed.tsx` and "Low risk" from `item.text.includes("LOW")`. This breaks two rules (the web never decides; text is data). They must read the structured fields: `verification.recorded.data.result` (`CONFIRMED` | `DENIED`) and `risk.scored.data.tier`.
- Globe label layout runs on every animation frame (`GlobeCanvas.tsx`, `requestAnimationFrame(layoutLabels)`): stutter risk on the demo laptop.
- Truncated labels ("R4 exc…", "Route select…") and the "Held in escrow" tag overlapping the EuroLedger label.

**Not drawn anywhere yet** (the events exist in [`spec/events.schema.json`](../spec/events.schema.json) and in sample fixtures on `main`): `guardian.incident`, `rail.down` / `rail.up`, `killswitch.on`, `cluster.detected`, `breaker.on` / `breaker.off`, `leg.rejected`, `alert.raised`, `approval.required`. `case.ready` is drawn on `main` (case file in the alert) but not on `frontend-v2`. Explorer links are not clickable. No proof panel, no metrics page, no approval or analyst buttons (so the demo runs with `HUMAN_STEPS=auto`).

**Replay mode:** `web/scripts/sync-spec.mjs` copies `../spec/fixtures` into `web/public/spec` before `dev` and `build`, so on `main` replay already plays the re-recorded fixtures. The gaps are: `web/lib/source.ts` only maps five scenes (no Scene 3, 4, 5, no attacks 2 and 3), `frontend-v2` carries the old v0 copies of `spec/fixtures` because it is behind `main`, and the fallback in `web/samples/fixtures` (used when `/spec` is missing) is still v0.

**Scenes on screen today:** Scene 1, Scene 2 (deny and confirm) and attack 1 have buttons. Attacks 2 and 3, Scene 3, Scene 5, the kill switch and the proof are curl-only (see [`docs/demo-run-sheet.md`](demo-run-sheet.md) on `main`). Scene 4 (guardian) runs from three terminals and is not in the run sheet yet.

---

## 0. Start here (≈ 20 min)

- [ ] **Adopt `web-best-of` as your base.**
  - **What:** Youssef is preparing `web-best-of` = your `frontend-v2` design + `main`'s payment card tiles and pill, route table, route lines on the globe, structured badges, clickable Snowtrace links and a throttled label layout. Review it in the browser; if you are happy, merge it into `frontend-v2` (`git fetch origin && git merge origin/web-best-of`) and continue from there instead of redoing those fixes. Tell Youssef what you would change; don't rebuild the regressions list above by hand.
  - **Why:** saves about two hours and brings the 57 commits from `main` (new fixtures, case file, Nodes tab).
  - **Where:** branch `web-best-of` (it was not on `origin` yet at 06:20; Youssef pushes it when ready).
  - **Done when:** `frontend-v2` contains `web-best-of`, and the checks below are green.
- [ ] **Run it.**
  - Live: `make dev` from the repo root (engine `:8000`, web `:3000`), open `http://localhost:3000/demo`.
  - Web only: `pnpm -C web dev`, then switch the top bar source to **Replay** (no engine needed; it plays `spec/fixtures`).
  - Checks before every push: `pnpm -C web test`, `pnpm -C web lint`, `pnpm -C web typecheck`, `pnpm -C web build`.

---

## 1. P0 — before the demo (must, ≈ 3 h 30)

Do them in this order. The first three are Youssef's UX requests.

### P0.1 Minimal alert box (≈ 40 min)

- [ ] **What:** the held alert currently shows the tier line, a headline, every reason with its label, the protection text, the verification block and the case file. Reduce the closed state to:
  1. one headline (`payment.held.data.headline`);
  2. one line of "why": the **first** reason the engine sent (`payment.held.data.reasons[0].text`), clamped to one line; the web does not pick or rank reasons;
  3. two or three chips: tier and score (`risk.scored`: e.g. "MEDIUM · 64"), where the money is (`held.at`: "In escrow" / "At the bank"), and the supplier check status ("Asking Kwame by SMS" → "Supplier denied" / "Supplier confirmed", from `verification.result`);
  4. the primary action(s): **Details** toggle and the close button (plus, later, the analyst buttons of P1.2).

  Everything else (all reasons with Provenance / Behaviour / Regulation / Network labels, the protection text, the verification detail with SIM-swap status, the analyst case file from `case.ready` with its citations, `rulesFired`) goes behind **Details**, collapsed by default.
- **Why:** Scene 2 is the heart of the pitch ("the diverted payment is stopped"); the jury must read the alert in two seconds while the presenter talks. The globe must stay visible behind it.
- **Where:** `web/components/AlertOverlay.tsx` (keep `main`'s `CaseFile` component inside the details), chips can reuse `Tag` / `Dot` from `web/components/ui.tsx`.
- **Done when:**
  - [ ] Closed state: headline + one line + at most 3 chips + one action row, no scrolling inside the card, about 160 px tall or less at 1440 × 900.
  - [ ] **Details** is a `<button aria-expanded aria-controls>`; Enter and Space toggle it; it animates height smoothly and respects `prefers-reduced-motion`.
  - [ ] Details shows every reason, the case file with citations and the verification block, exactly as before (nothing lost, only folded).
  - [ ] No text from the invoice, the email or the supplier's answer is used to choose a colour, chip or badge: only `tier`, `result`, `held.at`.
  - [ ] Replay of Scene 2 deny and confirm: the chips update when the supplier answers; the outcome card ("Payment stopped" / "Credited") still appears.

### P0.2 Panels 02 and 03 closed by default, with a toggle (≈ 40 min)

- [ ] **What:** the three panels are numbered by the `Tag` component: **01 Payment** (`PaymentCard.tsx`, left), **02 Engine decisions** (`DecisionSteps.tsx`, left, under 01) and **03 Event feed** (`EventFeed.tsx`, right). Make **02** and **03** start closed: only their header row shows (tag, title, a chevron and a small count such as "5 / 8 steps" or "24 events"). Clicking the header opens or closes the panel. Panel 01 stays open.
- **Why:** gives the globe the whole screen during Scene 1 and 2, so the comet, the escrow stop and the red dashed route are what the jury sees. The detail is one click away when the presenter wants it.
- **Where:** `web/components/DecisionSteps.tsx`, `web/components/EventFeed.tsx` (header becomes the toggle), `web/components/SyloApp.tsx` (open state per panel, the right `aside` shrinks to the header when 03 is closed). A small shared `CollapsiblePanel` in `web/components/ui.tsx` avoids writing it twice.
- **Done when:**
  - [ ] On page load 02 and 03 are closed, 01 is open.
  - [ ] Each header is a `<button>` with `aria-expanded` and `aria-controls`; Tab reaches it, Enter and Space toggle it; visible focus ring.
  - [ ] Each panel keeps its own state (opening 02 does not open 03); the state survives new events and a **Reset**.
  - [ ] Open and close animate height and opacity (about 200–250 ms), no layout jump in panel 01, reduced motion respected.
  - [ ] The event feed keeps receiving events while closed (open it mid-scene: everything is there).
  - [ ] Auto-opening on important events is **not** built until Youssef answers open question 1.

### P0.3 Visible scrollbars (≈ 20 min)

- [ ] **What:** the left `aside` in `SyloApp.tsx` and the feed list in `EventFeed.tsx` use `no-scrollbar`, so nobody can tell they scroll. Replace it with a thin styled scrollbar class (e.g. `.thin-scrollbar` in `web/app/globals.css`): about 6 px wide, rounded thumb in a light grey (`rgba(0,0,0,.22)`, darker on hover), transparent track.
  - Tip: style `::-webkit-scrollbar`, `::-webkit-scrollbar-thumb` and `::-webkit-scrollbar-track` for Chrome and Safari, and put `scrollbar-width: thin; scrollbar-color: …` inside `@supports not selector(::-webkit-scrollbar)` for Firefox. Since Chrome 121, setting `scrollbar-width` or `scrollbar-color` makes Chrome ignore the `::-webkit-scrollbar` rules, and the macOS overlay scrollbars then hide again.
  - The `scroll-fade` mask also fades the scrollbar at the top and bottom; keep it, but check the thumb stays readable, or reduce the fade.
- **Why:** the presenter must be able to scroll the decisions and the feed during the questions (proof links, case file) without guessing.
- **Where:** `web/app/globals.css`, `web/components/SyloApp.tsx`, `web/components/EventFeed.tsx`.
- **Done when:**
  - [ ] The scrollbar is visible in Chrome and Safari on the demo Mac, including with System Settings → Appearance → "Show scroll bars: When scrolling".
  - [ ] Mouse wheel, trackpad and dragging the thumb all scroll; the globe does not zoom while the pointer is over a panel.
  - [ ] No `no-scrollbar` left on a scrollable panel (`rg no-scrollbar web/components`).

### P0.4 Guardian incident, Scene 4 (D2.4, ≈ 45 min)

- [ ] **What:** draw `guardian.incident`. Data (see `spec/fixtures/samples-scene4-guardian.jsonl` on `main`): `incidentId`, `rule` (e.g. `CONFIRMED_WITHOUT_OOB_RECORD`), `action` (`FREEZE_AND_PAUSE`), `headline`, `txHash`, `explorerUrl`, and `dora` { `clientsAffected`, `amountEur`, `durationMinutes`, `geographicSpread`, `criticality`, `thirdParties`, `major`, `draft` }.
  - Store: a new `incident` slot in `web/lib/store.ts`, cleared on `session.reset`.
  - Globe: a red shield on the Avalanche / escrow node and a "Corridor FR → GH paused" label when `action` contains `PAUSE`.
  - Payment card: status "Frozen by the guardian" (red).
  - A **DORA incident draft** drawer (opened from the incident banner or the feed row) listing the six DORA fields, labelled **"Draft, not filed"**, plus the Snowtrace link of the freeze.
  - Feed: a red row "Guardian incident · INC-…".
  - When the payment has a guardian incident, do not show a green "Supplier confirmed" chip for that payment: show the incident instead (the forged confirmation is exactly what the guardian caught).
- **Why:** pitch slide 7 "Even a stolen key isn't enough" and the DORA line on the compliance slide. Today the event only shows as a plain feed row (handoff §14 item 3).
- **Where:** `web/lib/events.ts` (type), `web/lib/store.ts`, `web/lib/feed.ts`, `web/components/GlobeCanvas.tsx`, `web/components/PaymentCard.tsx`, new `web/components/IncidentDrawer.tsx`, `web/components/AlertOverlay.tsx`.
- **Done when:**
  - [ ] Replay of `samples-scene4-guardian.jsonl` shows the shield, the paused corridor, the frozen status and the drawer with the six DORA fields and "Draft, not filed".
  - [ ] A store test in `web/lib/__tests__/store.test.ts` feeds the sample and checks `incident.dora.amountEur === 85000` and that `session.reset` clears it.
  - [ ] Simulated incidents (`simulated: true`) show the "simulated" badge; live ones show the Snowtrace link.

### P0.5 Clickable Snowtrace links, failed transactions in red (part of D1.4, ≈ 30 min; already in `web-best-of`, check it)

- [ ] **What:** every chain event that has `explorerUrl` (`intent.committed`, `escrow.deposited`, `verification.recorded`, `intent.revoked`, `escrow.refunded`, `escrow.released`, `intent.executed`, `tx.reverted`, `guardian.incident`) shows a short hash that opens the explorer in a new tab. `tx.reverted` rows are red with the function and the revert reason (`PaymentNotReleasable`, `CommitmentMismatch`, `InvalidTransition`). When `explorerUrl` is `null` (mock chain), show a grey "simulated" badge and no link.
- **Why:** pitch slides 6 and 9 ("anyone can verify"): the presenter clicks the failed `release()` on Snowtrace live.
- **Where:** `web/lib/feed.ts` (already carries `explorerUrl`), `web/components/EventFeed.tsx`, `web/components/DecisionSteps.tsx`.
- **Done when:**
  - [ ] Links use `target="_blank" rel="noopener noreferrer"` and are only rendered for `https://` URLs (never `javascript:`).
  - [ ] With `CHAIN_MODE=fuji`, the attack 1 row is red and its link opens the failed transaction on `testnet.snowtrace.io`.
  - [ ] In replay (mock data) no row has a dead link; each chain row says "simulated".

### P0.6 Rail outage and kill switch banner, Scene 5 (D2.2 + kill switch part of D2.4, ≈ 40 min)

- [ ] **What:**
  - Store: `rails: Record<routeId, { down: boolean; reason; name }>` from `rail.down` / `rail.up`, and `killSwitch` from `killswitch.on` (`adapter`, `reason`, `refusals`, `revoked`), cleared on `rail.up` for that route and on `session.reset`.
  - Banner under the top bar: amber "R3 Euro stablecoin on Avalanche is down (simulated outage). Payments use another legal route." and red "Kill switch: adapter R3 cut after 2 refused legs." Text comes from the event fields, not invented.
  - Globe: the downed route drawn red dashed; the next payment's comet follows the route the engine chose (`route.selected`); `rail.up` restores it.
  - Route table: R3 shown excluded with the engine's `excludedBy` (`RAIL_DOWN` or `KILL_SWITCH`).
  - Feed: `leg.rejected` rows in red with the hop and reason (`INTENT_HASH_MISMATCH`, `KILL_SWITCH`…).
- **Why:** run sheet Scene 5 and the kill switch line ("no single failure stops payments; a tampered adapter is cut automatically"). The fail-safe rule says a degraded system must show a banner.
- **Where:** `web/lib/store.ts`, `web/lib/feed.ts`, new `web/components/StatusBanner.tsx` (mounted in `SyloApp.tsx` under `TopBar`), `web/components/GlobeCanvas.tsx`.
- **Done when:**
  - [ ] Replay of `samples-scene5-outage.jsonl`: amber banner at `rail.down`, payment goes through R1 with fees €80, banner disappears at `rail.up`.
  - [ ] Live: `curl -X POST $E/v1/scenarios/outage/run -H 'content-type: application/json' -d '{"auto":true}'` gives the same picture.
  - [ ] Live kill switch (attack 2 twice): red banner, the next legitimate payment goes through R1; **Reset** clears the banner.
  - [ ] Store tests for `rail.down` → `rail.up` and `killswitch.on` → `session.reset`.

### P0.7 Replay covers every scene (fail-safe fallback, ≈ 30 min)

- [ ] **What:** add the missing scenes to `fixtureFiles` in `web/lib/source.ts`: `muleWave` → `samples-scene3-mule-wave.jsonl`, `guardian` → `samples-scene4-guardian.jsonl`, `outage` → `samples-scene5-outage.jsonl`, `swap` → `scene2b-swap-beneficiary.jsonl`, `replayAttack` → `scene2b-replay.jsonl`. Add the matching buttons to `DemoControls.tsx` (in live mode they call the engine endpoints of the run sheet: `/v1/sim/mule-wave`, `/v1/scenarios/outage/run`, `/v1/attacks/swap_beneficiary`, `/v1/attacks/replay`; in replay they play the fixture). Refresh the fallback copies in `web/samples/fixtures` from `spec/fixtures` so replay works even without `/spec`.
- **Why:** "If the engine does not answer, switch to Replay" is the run sheet's fallback. Today it only covers three scenes, so a crash during Scene 3, 4 or 5 leaves nothing to show. It also removes curl from the stage.
- **Where:** `web/lib/source.ts`, `web/components/DemoControls.tsx`, `web/samples/fixtures/`.
- **Done when:**
  - [ ] With the engine stopped, every scene of the run sheet plays in replay from a button, start to finish, with no console error.
  - [ ] Every event type in those fixtures is either drawn or shown as a plain feed row; none crashes the store.
  - [ ] Buttons only start scenarios; they never decide an outcome.

### P0.8 Backup video (D2.7, ≈ 30 min, at about 11:00)

- [ ] **What:** screen recording of scenes 1 → 2 (deny) → 2b → 4 → 5 (and 3 if it is drawn) at speed 1, from the build that will be demoed.
- **Why:** run sheet "Nothing works → play the backup video".
- **Where:** outside the repo (demo laptop + shared drive). Do not commit the video.
- **Done when:** the file plays offline on the demo laptop, and the screenshots for the deck come from the same build (handoff §14 item 1).

---

## 2. P1 — if P0 is done (≈ 2 h, pick in order)

- [ ] **P1.1 Mule cluster and breaker on the globe (D2.1, ≈ 45 min).**
  - **What:** from `cluster.detected`: pulsing hexagon bins (or dots) at `points` near `centroid` (Aflao, Volta Region), label "Mule cluster · 6 accounts · 3 agents". From `breaker.on`: tint the region, label "Circuit breaker · 24 h" with expiry from `expiresAt`; remove it on `breaker.off`. The next diverted payment shows `R-CB-01` among the reasons (already in `risk.scored`). The three `traffic.sample` arcs drawn pale.
  - **Why:** Scene 3, "the network defends everyone". The handoff (§9 item 10) says the cluster on screen is a **sample** for now: show a "sample cluster" label unless Lane A confirms the detector is live.
  - **Where:** `web/lib/store.ts`, `web/components/GlobeCanvas.tsx`, `web/components/EventFeed.tsx`.
  - **Done when:** replay of `samples-scene3-mule-wave.jsonl` shows arcs → cluster → breaker → held payment with `R-CB-01`; **Reset** removes the breaker; the "sample" label is visible.
- [ ] **P1.2 Human steps from the screen (D1.2, D1.5), or keep `HUMAN_STEPS=auto`.**
  - **What:** when the latest `approval.required` lists a missing approver, show "Approve (Claire)" / "Co-approve (Marc)" calling `POST /v1/payments/{id}/approve`. In the alert details, "Confirm revocation", "Release", "Freeze" calling `POST /v1/cases/{id}/actions`. Buttons appear only when the events say the engine is waiting, and the screen changes only when the next event arrives (no optimistic success).
  - **Why:** lets the demo run with `HUMAN_STEPS=manual` and shows dual control. Not required: with `auto` the engine plays these steps and the story is identical.
  - **Decision:** if this is not done and tested live by **10:00**, keep `HUMAN_STEPS=auto` for the demo (open question 2).
  - **Done when:** with `HUMAN_STEPS=manual`, Scene 2 deny runs end to end from the screen with no curl; a 409 answer shows a short message, not a crash.
- [ ] **P1.3 Proof panel (rest of D1.4, ≈ 30 min).**
  - **What:** a "Proof" drawer for the current payment: the signed intent fields and the three signatures from `GET /v1/payments/{id}/proof`, plus the list of chain events (function, short hash link or "simulated", failed ones in red). In replay, hide the API part and keep the chain list.
  - **Why:** pitch slide 9, auditor walk-through.
  - **Where:** new `web/components/ProofDrawer.tsx`, `web/lib/source.ts` (GET helper).
  - **Done when:** after Scene 2 live, the drawer shows the intent hash that matches the `intent.committed` row and three signatures.
- [ ] **P1.4 Metrics page (D2.3, ≈ 40 min).**
  - **What:** route `/metrics` with honest numbers. Live: `GET /v1/metrics`. Fallback: extend `web/scripts/sync-spec.mjs` to copy `../ml/reports/metrics.json` (or `spec/metrics.sample.json` if missing) into `web/public/`. Headline tiles: recall on all fraud 98.1%, AUC 0.998, value stopped 99.4%, **false-positive rate 6.72% against a 2% target (missed, shown in amber)**, **precision at HIGH 89.9% against 90% (just missed)**; a line explaining that 80.5% of the legitimate holds come from guarantee rules (new or changed payee) and the model alone is at 1.06%; model vs the three baselines; ablation bars. "Measured on seed B, synthetic data". A large **SAMPLE** banner if `sample` is `true`.
  - **Why:** pitch slide 8 and backup B4; the handoff insists the misses are said before the jury finds them.
  - **Where:** new `web/app/metrics/page.tsx`, `web/scripts/sync-spec.mjs`, link from `TopBar.tsx`.
  - **Done when:** every number on the page matches `metrics.json` (`metrics.fprMediumPlus`, `metrics.precisionHigh`, `modelOnlyMetrics.B.fprMediumPlus`, `legitimateHoldBreakdown`); no target miss is hidden or rounded up.
- [ ] **P1.5 Attack console buttons for attacks 2 and 3 (D1.6, ≈ 15 min, mostly done by P0.7).**
  - **What:** red cross on the globe at the hop where `leg.rejected` happened (hop 3 for the swap) and at the escrow for `tx.reverted`.
  - **Done when:** attacks 2 and 3 run from buttons, live and in replay, each ending with a red row and a red cross.

---

## 3. P2 — nice-to-haves (only with time left)

- [ ] *Nice-to-have.* **P2.1 eERC auditor card (D2.6, ≈ 30 min).** A card "Confidential payment (eERC)": "Amount on the explorer: encrypted" next to "Auditor view: EUR 85,000", with the Snowtrace link of the transfer and the text "Not a mixer: addresses stay visible, a designated auditor reads every amount". The eERC service (`127.0.0.1:8010`) now returns `txs.transfer` / `links.transfer`, `auditor.decryptedAmountEur`, `receiverMetadata`, `balances` { `euCaspFloatEur`, `ghVaspUnsettledEur` } and `floatTopUp`; settlement is a separate netted `/settle`, so the only visible amounts on chain are the float wrap and the netted settle. The engine does not emit an event yet (`confidential.transfer` is listed in the schema without a data shape), so build the card from a hand-written `web/samples/samples-eerc.json` labelled "recorded run", and ask Oscar for the event. Done when the card shows the recorded EUR 85,000 transfer with a working Snowtrace link and a "recorded" label. Pitch slide 10.
- [ ] *Nice-to-have.* **P2.2 Polish.** No truncated labels ("R4 exc…", "Route select…"); the "Held in escrow" tag never overlaps the EuroLedger label; label layout throttled (if `web-best-of` does not already do it); camera move per scene (D1.1); route names, countries and codes read from events (`norms.checked`, `payment.created`), never hard-coded.
- [ ] *Nice-to-have, cut first.* **P2.3 Background traffic (D2.5).** Pale arcs from `traffic.sample` behind the demo payment.

---

## 4. Rules checklist (check before every push)

- [ ] **The web draws events, it never decides.** No tier, badge, colour or outcome computed from free text or from local logic; only from structured fields (`tier`, `result`, `excludedBy`, `reason`, `action`, `status`).
- [ ] **Text is data.** Invoice, email and supplier answer text is displayed as text (no `dangerouslySetInnerHTML`, never parsed to decide something).
- [ ] **Label simulated things.** Every event with `simulated: true` (rails, banks, people, phone, SIM-swap check, mock chain, sample cluster) shows "simulated"; recorded data shows "recorded"; the metrics page shows "SAMPLE" if it is the sample.
- [ ] **Fail safe.** Degraded mode (`system.mode.degraded`), rail down and kill switch show a banner; if the engine is unreachable the screen offers Replay instead of going blank.
- [ ] **Never alert the payer by email.** Alerts show their channel (`IN_APP`, `SMS`, `NETWORK`); no "email" wording anywhere.
- [ ] **Fraud risk never enters the route score.** The route table shows cost only; keep the line "Fraud risk never changes the price".
- [ ] **Models and LLMs only make things stricter.** The case file is shown as advisory ("Analyst case file, drafted by the model"); no button lets a model approve.
- [ ] **No secrets, no build output** (`.env`, `web/.next`, `web/public/spec`) in the diff. Only `/web` (and `/docs` if needed) changed.
- [ ] `pnpm -C web test`, `lint`, `typecheck`, `build` green; PR names the task ID (e.g. "D2.4 guardian incident"), what changed and how to check it.

---

## 5. Open questions

**For Youssef**
1. Panels 02 and 03 auto-open: should they open by themselves on important events (e.g. 02 on `payment.held`, 03 on `tx.reverted`, `guardian.incident`, `killswitch.on`), or always stay as the presenter left them?
2. Is Scene 4 run live during the demo (three terminals, `CHAIN_MODE=fuji`) or only from replay with the recorded Snowtrace links? If replay, should we add a `samples-scene4-guardian-live.jsonl` with the real freeze and pause transaction links from the handoff §6?
3. Which explorer link should the incident drawer open first: the guardian freeze or the forged confirmation?

**For Oscar (Lane A, engine)**
4. Demo mode: `HUMAN_STEPS=auto` or `manual`? (Depends on P1.2.)
5. After a guardian freeze, the engine stays "awaiting supplier". Can the analyst's revoke run from the UI on a frozen payment, or should the screen hide those buttons?
6. Can the engine emit an eERC event (`confidential.transfer` with a data shape) so the auditor card reads live data instead of a recorded sample?
7. Is the Scene 3 cluster still the sample (`spec/fixtures/cluster-sample.json`)? The globe label depends on it.
8. Exact code freeze and jury times.
