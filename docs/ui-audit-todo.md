# UI / UX / animation audit: to-do list

Audit of `main` on 11 Oct 2026, morning. Method: a live walkthrough of every scene in the browser (landing, `/test`, scenes 1, 2, 3 and 5, the Nodes view, Replay, at large-screen, 1366×768 laptop and phone sizes), plus a code review of `/web`. Paths are relative to `web/`; line numbers can drift as people push.

Items already fixed on `main` since the audit are left out: the "Sample" cluster label, the raw "Event received: approval.required / case.action" lines, and globe arcs reused from the previous scene (the arc cache key now includes the endpoints). Re-check them once after your changes.

`/web` is Lane D (Maria). The work is split between Talal and Youssef (see "Who does what"); tell Maria too, so nobody edits the same component at the same time.

**Priorities:** P0 = breaks or embarrasses the live demo. P1 = clearly visible to the jury. P2 = nice to have.

## Who does what

**Talal: front end.** Every item in the UI sections below (P0, P1, P2), **except** the ones tagged **[Youssef]**. Suggested order:
1. Scene 3 shows almost nothing.
2. Buttons fail silently (toast).
3. UI ignores events after an engine restart.
4. "Simulated" gets cut off.
5. Globe slow on big screens.
6. `/test` page.
7. Raw revert reason in the attack climax.
8. Then P1: globe and camera, panels and state, animations, layout. Then P2.

**Youssef: engine, ML, deploy, docs, and the web items tied to wording or engine logic.** That is every item in "Backend, rules and docs", plus the web items tagged **[Youssef]**:
- the "Wording: raw codes reaching the screen" section (mostly `web/lib/feed.ts`);
- reason counts disagree;
- Scene 4 not runnable live;
- attack narration and the web inferring "escrow" (`web/lib/flow.ts`);
- the two replay items in P2.

Suggested order:
1. Rule 3 leg check, with its test.
2. Rule 6 model-crash fallback, and rule 2 tier.
3. `DEMO_PUBLIC` flag on the shared Render session.
4. Scene 4 live button.
5. Docs drift (run sheet, README, pitch handoff).
6. Then wording, and the rest of P1 and P2.

**To avoid stepping on each other:**
- Talal owns `web/components/*` and the globe.
- Youssef only edits `web/lib/feed.ts`, `web/lib/flow.ts`, and the attack and replay parts of `web/lib/store.ts`. Talal edits the scene-3 and sequence-number parts of `store.ts`. Keep these commits small and rebase often.
- `engine/` is Lane A (Oscar) and `ml/` is Lane B. Tell them before pushing there.
- Run `make test` and `make demo-check` before each push to `main`.

---

## P0: before the demo

- [ ] **Scene 3 (mule wave) shows almost nothing on screen.**
  - The fixture and the live engine send `scenario.started` twice. The second one resets the state and empties the feed, so the three `traffic.sample`, `cluster.detected` and `breaker.on` events vanish about a second after appearing (`lib/store.ts` ~208-235).
  - `mule_wave` is mapped to `"legit"` (`lib/store.ts` ~235), so the camera zooms into **Lyon** while the cluster is in **Ghana (Volta, Aflao)**.
  - The reducer ignores `traffic.sample`, `cluster.detected` and `breaker.on`, so no wave arcs, cluster ring or breaker zone is drawn on the globe.
  - **Fix:** keep the feed on a second `scenario.started` within the same run, map `mule_wave` to its own scenario, draw the three `bank_fr → mule_bank` arcs plus a ring or zone around Aflao, and fly the camera there.

- [x] **[Youssef] Scene 4 (guardian and stolen key) cannot be run live.** Done: live, "Guardian incident" runs the stolen-key attack on the payment held in escrow (Diverted invoice, wait for the hold, then More scenes, Guardian incident). `components/DemoControls.tsx:71` enables "Guardian incident" only when `sourceKind === "replay"`. The engine runs it fine in mock and Fuji modes (`POST /v1/attacks/stolen_verifier_key`; `make demo-check` passes). Enable it in live mode after a diverted payment is held.

- [ ] **"Simulated" gets cut off.** The project rules require simulated things to be labelled, but:
  - `components/PaymentCard.tsx` ~90/183 puts `Signed intent 0x…abcde · Simulated` in a 9.5px truncated line, so "Simulated" is always the part that disappears;
  - `components/EventFeed.tsx` ~386-406 appends "· simulated" to a `line-clamp-2` paragraph, which hides it on long lines.
  - **Fix:** show "Simulated" as its own chip, never inside truncated text.

- [ ] **Buttons fail silently when the engine refuses or is down.** `lib/useSylo.ts` ~105-126 and `components/DemoControls.tsx` ~191-235: action promises are never caught. A 409 (scenario busy, late supplier answer) or an engine outage does nothing visible. Catch the error and show a toast ("Engine refused: …").

- [ ] **After an engine restart the UI ignores every event.** `lib/store.ts` ~203 drops events with `seq <= lastSeq`, but the engine's sequence restarts at 0. That happens on Render after a cold start or redeploy, with viewers still connected. Treat `session.reset`, or any seq going backwards, as a fresh session.

- [ ] **The `/test` page is a mock, and it is the landing page's first button ("Test the project").** `components/TestTransaction.tsx` runs four timers, never calls the engine, and only says "Preview only… no decision was computed" at the end. Choose one:
  - wire it to the real API (`POST /v1/intake` with invoice text, then `POST /v1/quotes` and `POST /v1/payments`, then show the decision or redirect to `/demo`). Talal's unmerged `devin/1791701630-live-invoice` branch may already do this;
  - or hide the button until it is wired.

- [ ] **The attack climax shows a raw revert reason.** `components/AlertOverlay.tsx` ~174 prints "The smart contract rejected PaymentNotReleasable". Map the codes (`PaymentNotReleasable`, `CommitmentMismatch`, `InvalidTransition`, `INTENT_HASH_MISMATCH`) to sentences, for example "The escrow refused to release a revoked payment."

- [ ] **The globe is slow on big screens.** The WebGL canvas is drawn at full device pixel ratio: 3840×2160 on a 2560×1440 screen. It measured 22 fps at rest and 9 fps after Reset, with one-second frames. Cap the pixel ratio (for example `Math.min(devicePixelRatio, 1.5)`) and re-check on the presenting laptop and projector.

## P1: visible to the jury

### Globe and camera

- [ ] **The globe drifts away from the corridor when idle.** After Reset, or once a scene ends, auto-rotate turns to the Americas. France and Ghana end up on the far edge, and the "Revoked · refunded" marker floats off the surface. Reset should call `pointOfView(CORRIDOR_VIEW)` (`components/GlobeCanvas.tsx` ~738); either stop auto-rotate after a scene or rotate slowly around the corridor.
- [ ] **Labels of points behind the globe stay visible** ("Rhône Cosmétiques · Lyon" floating past the edge). Hide labels whose point faces away from the camera.
- [ ] **Framing at key moments is inconsistent.**
  - End of scene 1 is zoomed so far into Ghana that the globe overflows the screen and France is gone.
  - "Payment held" in scene 2 is seen from below Africa, with the escrow lock floating above the globe.
  - **Fix:** one rule per climax, with the whole corridor in view and the hold or credit point centred.
- [ ] **Labels collide and miss the key place.** "Kente Digital Assets · Accra" and "Savanna Shea · Tamale" stack on each other. The mule's bank (Volta Rural Bank, Aflao), the actual threat, has no label at the hold moment. On the legitimate run only the French nodes are labelled.
- [ ] **The camera pull-back is cancelled by any later event.** `components/GlobeCanvas.tsx` ~761-850: the effect re-runs on every event and its cleanup clears the pull-back timer. In the rail outage scene, `rail.up` arrives after `payment.credited`, so the camera stays zoomed. Keep the camera timers in a ref that only camera events clear.
- [ ] **Camera moves can stutter.** `components/GlobeCanvas.tsx` ~569-578: `onZoom` sets `particleSize` state up to 10 times a second during flights, which can rebuild the 14,654-dot layer. Fix the size per breakpoint, or update only when the move ends.
- [ ] **The label layout loop never stops.** `components/GlobeCanvas.tsx` ~584-704 runs 10 times a second forever, mixing `getBoundingClientRect()` reads with style writes, including in the Nodes view where the globe is hidden. Pause it when the globe is hidden or the camera is still.
- [ ] **At 2× speed, the moving dot on each arc still runs at 1×** (`components/GlobeCanvas.tsx` ~329), so legs settle halfway and the arc snaps. Use `durationMs / speed`.

### Panels and state

- [ ] **The payment card contradicts itself.** The header pill and the Status row disagree: "Decision in progress" vs "In transit" in scene 1, and "In transit" vs "Supplier credited" at the end of the outage. Derive both from the same field, or drop the pill and use the row for risk or intent (`components/PaymentCard.tsx` ~52 and ~85-92).
- [ ] **Panels lag each other.** After "We never changed it", the outcome message said "Payment stopped" while the card said "Awaiting supplier" for about 5 s. Drive every panel from the same reduced state at the same time.
- [ ] **The outage outcome reads "€216 all-in vs €216 via SWIFT · Saved €0"** (`components/AlertOverlay.tsx` ~168-172, `components/DecisionSteps.tsx` ~96). When the payment was rerouted to SWIFT, say so instead: "Rerouted to SWIFT: Avalanche rail was down · €216 · 1–3 days."
- [ ] **The outage banner stays after "Payment rail restored."** Clear it on `rail.up`.
- [ ] **The savings line is the best pitch number but is tiny grey text** ("Saved €36.79 vs SWIFT" in the credited toast). Make it the headline of the credited card.
- [ ] **[Youssef] Reason counts disagree.** The decisions panel says "77 / HIGH / 4 rules fired" while the alert lists 7 reasons, and two pairs say the same thing:
  - "first payment ever to this account" / "Only 0 successful payments on this account";
  - "name match 0.38" / "name match score is 38%".
  - **Fix:** de-duplicate in the web, or ask Lane B to stop the model reasons repeating the rules. Use one count everywhere.
- [ ] **`/demo` opens on whoever ran last.** The Render engine is shared, so a jury member opening the link lands mid-scene in someone else's run. Option: show a "Ready: press a scene" state until this viewer starts or resets something, or reset the engine on the first click.
- [ ] **Decisions and feed panels start collapsed** (`components/SyloApp.tsx:27-28`), so the audience sees empty headers while the engine works. Open both on `scenario.started`, or default them open on wide screens.
- [ ] **The final decision box is below the fold on a laptop.** The decisions panel scrolls, but its conclusion sits at the bottom; pin the decision box to the top of the panel.
- [ ] **Steps never reached stay "Pending" forever** after an early stop (blocked payment, mule wave). Mark them "Skipped" once the payment is final (`components/DecisionSteps.tsx` ~101-111).

### Wording: raw codes reaching the screen [Youssef]

Where a fix is inside a component Talal is editing (`DecisionSteps`, `StatusBanner`, `IncidentDrawer`), give him the sentence instead of editing the file.

- [ ] Rule IDs: `GH_FX_EXPORT_PROCEEDS_NOMINATED_BANK` (feed, and cut to 96px in red in the route list), `TIER_MEDIUM_REQUIRES_CONDITIONAL_SET`, `PAYER_LIMIT`, `RAIL_DOWN` (`lib/feed.ts` ~97, `components/DecisionSteps.tsx` ~133).
- [ ] "Scenario started: diverted" / "mule_wave" / "outage": use the scene names from the controls.
- [ ] `IN_APP alert to Claire Martin`, `NETWORK alert to mule_bank`. The title "Security alert sent" is wrong for the in-app reassurance. Build the title from the `audience` and `channel` fields (`lib/feed.ts` ~225).
- [ ] `FREEZE_AND_PAUSE` (`components/StatusBanner.tsx` ~23, `components/IncidentDrawer.tsx` ~55).
- [ ] Case file refs `V · R-PV-01 · evt-000328`, "T1 supplier impersonation", "(p=1.00)": fine for an analyst view, but put them in a hover or small-print line.
- [ ] Amounts in three formats: "€85,000.00", "EUR 85,000" and an unformatted "EUR 85000.00" (`lib/feed.ts` ~86, ~135). Use one formatter.
- [ ] "1 accounts", and other unpluralised counts.

### Animations

- [ ] **New feed items draw on top of each other while they animate in** (seen right after the supplier's answer). Check the `layout` / `AnimatePresence` setup in `components/EventFeed.tsx` ~284-288.
- [ ] **Layout animations reuse the entrance transition** (0.7 s with a 0.1–0.25 s delay) in `components/PaymentCard.tsx:49`, `components/DecisionSteps.tsx:174` and `components/EventFeed.tsx` ~284. Every height change lags, then stretches the text. Use `transition={{ layout: { duration: 0.25 } }}` or `layout="position"`.
- [ ] **The held card and the outcome card sit side by side for about 0.45 s on deny.** Use one `AnimatePresence mode="wait"` (`components/AlertOverlay.tsx` ~68-180).
- [ ] **Framer animations ignore the system "reduce motion" setting.** Wrap the app in `<MotionConfig reducedMotion="user">` (`app/layout.tsx` or `components/SyloApp.tsx`).

### Layout, accessibility, banners

- [ ] **The degraded-mode banner can be hidden** by a kill switch, incident or rail banner, because only one banner shows at a time. That breaks the "fail safe and show a banner" rule. Stack the banners and write a sentence instead of `chain · llm` (`components/StatusBanner.tsx` ~8-45).
- [ ] **The top-bar mode line (`Chain · simulated`, `Rails · simulated`) disappears below 1280px** (`components/TopBar.tsx` ~165, `hidden xl:block`), so the simulated labels vanish on a 1024px projector. LLM mode is never shown there.
- [ ] **The status banner overlaps both side panels at 1280px**, and in the Nodes view it sits on top of the flow-graph pill (`components/StatusBanner.tsx` ~57).
- [ ] **The expanded alert covers the globe at 1366×768 and smaller.** Cap the details at about 30vh on short screens, or open them in a side drawer (`components/AlertOverlay.tsx` ~127).
- [ ] **Contrast and text size are too low for a projector.** `--ink-3` is 40% black (about 2.8:1) on 8.5–10.5px text in the feed, badges and payment details. Use at least 11px and about 55% black (`app/globals.css:11`).
- [ ] **The "live" pill pulses green before the stream is connected.** Show amber "Connecting…" until the first event or `onopen` (`components/TopBar.tsx` ~204).
- [ ] **Keyboard support is incomplete.** The alert, the incident drawer and the "More scenes" menu don't take focus, don't close on Escape and don't return focus. The menu also has no outside-click close and an invisible focus ring (`components/DemoControls.tsx` ~93-105).
- [ ] **On a phone the demo is unusable.** The feed covers the card and decisions panel, the control bar is wider than the screen ("Legitimate payment" cut off), and the Globe tab text overlaps. Either stack the panels under 768px, or show a "Best viewed on a laptop" screen with a link to the recorded replay.
- [ ] **The Nodes view drops the alert,** but the supplier buttons remain with no context. It also only covers the legitimate and diverted paths (nothing for mule wave, guardian or outage).

## P2: nice to have

- [ ] **[Youssef]** Replay mode shows "Risk · rules" until the first score arrives, but the fixtures are recorded with the model (`lib/store.ts:166`). Default replay to `model`.
- [ ] Times are shown in UTC (`ts.slice(11,19)`), so they look two hours behind in Paris, and replay always shows 09:00. Use local time or "+12 s".
- [ ] The incident drawer stays open across Reset; a dismissed held alert can't be reopened (add "View alert" on the card).
- [ ] Two different reds (`#FF3B30` vs `--danger #e5484d`), `lib/colors.ts` duplicating CSS variables, and hard-coded halo and hover colours.
- [ ] Separators " / " vs " · "; corridor named "Lyon → Ghana", "FR → GH" and "France to Ghana"; final state named "Payment completed / Settled" vs "Supplier credited".
- [ ] **[Youssef]** "Swap beneficiary" and "Replay intent" are enabled after a legitimate payment, and then replay diverted fixtures (`lib/store.ts` ~500).
- [ ] If the map data fails to load, the globe is blank with no banner (`components/SyloApp.tsx` ~34-39).
- [ ] At 1280×720 the flow graph scales to about 0.76×, making its 12px text about 9px.
- [ ] Dead code: `Metric` (`components/ui.tsx`), `IRIDESCENT`, unused state fields (`rejectedLeg`, `routeReason`, `feesEur`, `intentTxHash`), `public/geo/countries.geojson` (174 KB) and the Next.js template SVGs in `public/`.
- [ ] `FlowGraph` re-measures the DOM on every event (`useLayoutEffect` with no dependencies); the globe arc cache grows without limit and never disposes materials.
- [ ] The landing page is a single hero and globe with no one-line explanation of the three things Sylo does, and "Test the project" vs "Watch the demo" is ambiguous. Rename the buttons, for example "Try a payment" and "Watch the 3-minute demo".

---

## Backend, rules and docs (engine / ml / deploy) [Youssef]

All of this section is Youssef's, including the two web items in P1. From a read-only review of `engine/`, `ml/`, `chain/`, the deploy files and `docs/` against the rules in `AGENTS.md`. Owners: `engine/` is Lane A (Oscar), `ml/` is Lane B, `chain/` and `contracts/` are Lane C, `docs/` is anyone. Paths are from the repo root.

**Verified OK:**
- Fraud risk never enters the route score (`engine/sylo/router.py`).
- The payer is never alerted by email (`engine/sylo/texts.py`, and the event schema has no email channel).
- Invoice and email text is treated as data: intake only counts instruction-like lines, and the case writer withholds documents that look like injections and validates its output.
- No secrets are tracked; the only key is the public Anvil dev mnemonic.
- No junk is tracked (no `node_modules`, `.next`, `__pycache__` or `.env`).

### P0

- [x] **Rule 3 gap: a pay-out leg is not compared with the signed intent** (Lane A). `RailAdapter.initiate` (`engine/sylo/rails.py:139-175`) only checks the intent hash rebuilt from the leg's name, account, bank, invoice reference and UETR. The leg's **amount, hop, sender, receiver and rail are never compared** with the intent or route, and pay-out legs are allowed after `EXECUTED`. Probe: after diverted+confirm, a leg with `hop=99` and **10× the sealed amount** was accepted. The integrity harness (`engine/sylo/integrity.py`) only tampers `intent.amount`, so "0 of 300 got through" (`docs/pitch-handoff.md`, `docs/response-playbook.md`) doesn't cover it.
  - **Fix:** refuse unless the amount matches `intent.amount` in EUR, `leg.rail == self.id`, `(sender, receiver)` equals `route.hops[hop]`, and the hop was never sent before.
  - Add an integrity case for a tampered leg amount or an extra hop.
- [x] **Rule 6: a model crash at run time falls back to the *lenient* rules, with no banner** (Lane A). `engine/sylo/risk_rules.py:142-145`: on an exception, `CombinedRisk` returns non-strict `RulesRisk()` and nothing marks `risk` as degraded. Use `RulesRisk(strict=True)` and call `_degrade("risk")`.
- [x] **Rule 2: the model can lower the tier the rules would give** (Lane A). `engine/sylo/risk_rules.py:150` computes `max(base.floor_tier, band(model))`, which ignores the rules' own score band. Example: rules 74 is HIGH; model 50 makes it MEDIUM. The breaker path has the same issue (`engine/sylo/breakers.py:152`). The demo scenes are unaffected. Use `max(base.tier, band(model))`.
- [ ] **Rule 6 again: degraded mode is measured as looser** (Lane B). In `ml/reports/metrics.json`, `degraded[*].neverLooser` is `false`: rules-only gives 554 HIGH→MEDIUM transitions on seed C. Either make strict mode floor at MEDIUM (HIGH when R-PV-01 or R-FL-01 fire) and re-run `make eval`, or reword the claim before judging.
- [x] **The public Render URL is one shared, unauthenticated session** (engine side done: `DEMO_PUBLIC=1` in `render.yaml` closes the operator endpoints; Reset and scenarios stay open, so still press Reset before going on stage) (Lane A, plus web). Covered on the UI side above. On the engine side:
  - any visitor can `POST /v1/reset`;
  - a diverted run started with `auto:false` holds the engine busy, so everyone else gets 409 until it ends;
  - a mule wave leaves the breaker on for the next visitor;
  - `POST /v1/guardian/incidents` and `POST /v1/payees/{id}/verify` are open (anyone can close R3, or mark an account as verified).
  - **Fix:** a `DEMO_PUBLIC=1` flag that disables the mutating debug endpoints and Reset on the public URL, or a private instance for the presenters. Press Reset just before going on stage.

### P1

- [ ] **An unexpected exception in a run freezes the UI.** `engine/sylo/orchestrator.py:1396-1398` sets the status to `stopped` without emitting an event, and calls money in a hold "stopped". Emit `payment.stopped`, or keep `held`, and degrade.
- [ ] **Every attack or chain revert is narrated as "release() on the revoked payment"** (web). `web/lib/flow.ts:116-118` and `web/lib/store.ts:413-434`. Read `attack.attempted.data.attack` and narrate per attack.
- [ ] **The web infers "escrow" from the tier** (`web/lib/flow.ts:42-45`, `:139-141`), which is wrong for a bank hold (time-lock on R1) and for a blocked payment. The rules say the web never decides, so use `route.selected.settlement` and `payment.stopped`.
- [ ] **A Mistral failure is silent** (Lane B / A). A failed live call falls back to the template without degrading `llm` (`ml/sylo_risk/case/writer.py:367-375`). Degrade when the returned case's `llm` differs from the requested mode.
- [ ] **A hung eERC service stalls Scene 1 for up to 120 s** (`engine/sylo/confidential.py:72`). Set the timeout to about 25 s; the public-leg fallback already exists.
- [ ] **Render free plan:** the service sleeps after 15 minutes and takes about a minute to wake, and state and the journal are lost on sleep. The engine peaks at about 196 MB, which fits in 512 MB with Next.js, but tightly. Ping `/health` a few minutes before the slot, and don't enable eERC or Fuji there.
- [ ] **The run sheet has drifted** (`docs/demo-run-sheet.md`):
  - "six with the model" should be 7 reasons;
  - the "UI vs curl" column is stale (Mule wave, Outage, Swap and Replay are UI buttons now);
  - there are no Render instructions (`E=https://sylo-0wck.onrender.com`);
  - Reset does not clear run-time degradations.
- [ ] **The README Quickstart is stale** (`README.md:20-25`, `:85`). The demo is at `/demo`, the button names are wrong, and `chain/` is no longer a skeleton.
- [ ] **The pitch handoff doesn't match the metrics** (`docs/pitch-handoff.md`):
  - p95 says 0.73 ms, but `metrics.json` and `BENCHMARKS.md` say 2.60 ms;
  - the "generated" time is stale;
  - open issues 3 and 4 are resolved (Scene 4 is in the run sheet, and the deploy reports `clusters: detector`).

### P2

- [ ] Fuji mode silently signs with the Anvil dev keys when a signer key is missing (`engine/sylo/signer.py:27-37`). Pass `allow_dev_keys=False` on Fuji.
- [ ] `ChainReverted` isn't caught in some API routes (attack, FREEZE, proof), giving a 500 (`engine/sylo/main.py:233-255`, `:380-392`). Map it to 409.
- [ ] A Fuji receipt timeout is treated as a revert (`chain/sylo_chain/fuji.py:323-325`). Treat it as "chain unavailable" instead.
- [ ] Mistyped `RISK_MODE`, `CHAIN_MODE` or `LLM_MODE` values are silently ignored (`engine/sylo/config.py:85-112`). Validate them like `TELECOM_MODE`.
- [ ] `reset()` keeps run-time degradations and incidents (`engine/sylo/orchestrator.py:487-513`). An attack on an old payment overwrites the session pacer (`:2211`).
- [ ] `verification.recorded` is always labelled simulated, even on Fuji, where its transaction is real (`engine/sylo/orchestrator.py:2041`).
- [ ] `ml/models/gbm-20261010.txt` (417 KB) is tracked but unused. `ml/pyproject.toml` and `chain/pyproject.toml` still say "skeleton". The pitch handoff has one open TODO (team credits).

## What already works well (keep it)

- The route-selection moment (blue candidate arcs, red dashed excluded route) and the final "Revoked · refunded" marker read clearly.
- The held alert is strong: plain-language reasons, "Asking Kwame Asante on +233 •• ••• 4471 · known contact since 2024-03-12 · SIM swap not recent", and "Mistral · cached · advisory only".
- The Nodes view is clean and easy to follow.
- The payer is alerted by SMS or in-app only, never by email; simulated events carry the flag; there are no hydration risks.

## How to verify

```bash
make dev                     # engine :8000, web :3000
pnpm -C web test && pnpm -C web lint && pnpm -C web typecheck
make demo-check              # 12/12 must stay green
```

Then click through, at 1366×768 and at the projector's resolution: Legitimate payment → Diverted invoice → "We never changed it" → Try release() attack → Mule wave → Guardian incident → Rail outage → Reset. Live site: https://sylo-0wck.onrender.com/demo (redeploys from `main` automatically).
