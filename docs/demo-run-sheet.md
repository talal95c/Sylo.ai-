# Demo run sheet (Lane A)

Who drives: Lane A. Screen: `http://localhost:3000/demo`. Everything below works with the mock chain and the rules; the real components only change the labels (`simulated`, explorer links, model name).

Endpoints and events are described in [`spec/api.md`](../spec/api.md). `$E` is the engine URL (`http://localhost:8000`).

## Before the jury

| Step | Command | Expected |
|---|---|---|
| Install | `make setup` | no error |
| Check everything | `make test` | green |
| Start | `make dev` | engine on :8000, web on :3000 |
| Check the scenes | `make demo-check` | `demo check OK: 10 checks`, with the flags of `.env` on the first line |
| Clean session | `curl -X POST $E/v1/reset` | banner without "degraded" |

Flags in `.env` (the banner shows what is really running):

| Flag | For the demo | If the component is not ready |
|---|---|---|
| `CHAIN_MODE` | `fuji` once Lane C's client passes conformance | `mock`: same story, events labelled simulated, no explorer link |
| `RISK_MODE` | `model` (rehearsed 11 Oct: legitimate LOW 25, diverted HIGH 77 held in escrow, model `gbm-20261011`) | `rules`: diverted is MEDIUM 64 instead of HIGH 77, same hold |
| `LLM_MODE` | `cached` (rehearsed 11 Oct: the scene 2 case file shows `llm: cached`, the reviewed Mistral text) | `off`: the case file is built from the rules |
| `HUMAN_STEPS` | `manual` once the payer panel and the analyst drawer call the API | `auto`: the engine plays the approvals and the analyst |
| `DEMO_SPEED` | `1` | `2` if the slot is short |

On macOS the model needs the OpenMP library (`brew install libomp`). Without it the engine starts with the rules, made stricter, and the banner says `risk` is degraded.

## Scenes

Times are at speed 1. "UI" means a button exists on the demo screen today; "curl" means it does not yet.

| # | Scene | How | What must appear | Time |
|---|---|---|---|---|
| 1 | Legitimate payment | UI: **Legitimate payment** | R4 excluded by Ghana's export-proceeds rule; LOW 10 (rules) or LOW 25 (model); R3 chosen; two approvals; intent committed; five hops; "Credited" | 16 s |
| 2 | Diverted invoice | UI: **Diverted invoice** | Four reasons (six with the model); HIGH 77 with the model, handled like MEDIUM because only the beneficiary's identity is in doubt; conditional approval; the comet stops on the Avalanche arc; "Payment held"; case file; Kwame is asked | held after 11 s |
| 2 | Supplier denies | UI: **"We never changed it"** | Denial recorded; analyst confirms; revoked; refunded; freeze request to the mule's bank; "Payment stopped" | 7 s |
| 2 | Supplier confirms (variant) | UI: **"Yes, it's our account"** | Released; two more hops; credited at the new account | 5 s |
| 2b | Attack 1: release a revoked payment | UI: **Try release() attack** | `tx.reverted`, `PaymentNotReleasable` | 1 s |
| 2b | Attack 2: swap the beneficiary | `curl -X POST $E/v1/attacks/swap_beneficiary -H 'content-type: application/json' -d '{"paymentId":"PAY-2026-0002"}'` | `leg.rejected` `INTENT_HASH_MISMATCH` at hop 3, then `tx.reverted` `CommitmentMismatch` | 2 s |
| 2b | Attack 3: replay the intent | same with `/v1/attacks/replay` | `tx.reverted` `InvalidTransition` | 1 s |
| 3 | Mule wave | `curl -X POST $E/v1/sim/mule-wave -H 'content-type: application/json' -d '{"auto":true}'` | Three payments seen on the network; `cluster.detected` near Aflao; `breaker.on` for 24 h | 6 s |
| 3 | Next payment into the region | UI: **Diverted invoice** | Rule `R-CB-01` among the reasons; HIGH and held (rules), or CRITICAL and blocked (model) | 11 s |
| 4 | Stolen verifier key (guardian) | Fuji only, see [Scene 4](#scene-4-stolen-verifier-key-fuji-only) | Forged `CONFIRMED` on Snowtrace; guardian freezes the hold and pauses FR-GH; attacker's `release()` mined and failed (`PaymentNotReleasable`); `guardian.incident` with a DORA draft | ~15 s after the payment is held |
| 5 | Rail outage | `curl -X POST $E/v1/scenarios/outage/run -H 'content-type: application/json' -d '{"auto":true}'` | `rail.down` R3; the payment goes through R1 (fees €80); still LOW; `rail.up` | 16 s |
| — | Kill switch | Attack 2 twice | `killswitch.on` for R3; the next legitimate payment goes through R1 | 3 s |
| — | Proof | `curl $E/v1/payments/PAY-2026-0002/proof` then `make verify-log` | Typed data and three signatures; `decision log OK` | — |
| — | "Edit a decision" | change one value in `engine/data/log.jsonl`, then `make verify-log` | `decision log TAMPERED: line N` | — |

Order for four minutes: 1, 2 with the denial, 2b. Scenes 3, 4 and 5 only if time is left (Scene 4 needs `CHAIN_MODE=fuji`; otherwise show its Snowtrace links on a slide). Press **Reset** between two runs of Scene 3 or after the kill switch: it removes the breaker and restores every rail.

With `HUMAN_STEPS=manual` and no panel yet, the human steps are:

```bash
curl -X POST $E/v1/payments/PAY-2026-0002/approve -H 'content-type: application/json' -d '{"approver":"claire"}'
curl -X POST $E/v1/payments/PAY-2026-0002/approve -H 'content-type: application/json' -d '{"approver":"marc"}'
curl -X POST $E/v1/cases/PAY-2026-0002/actions -H 'content-type: application/json' -d '{"action":"CONFIRM_REVOCATION"}'
curl -X POST $E/v1/breakers/CB-CL-AFLAO-01/confirm
```

## Scene 4: stolen verifier key (Fuji only)

The attacker has the verifier key (simulated theft) and records a fake "supplier confirmed" on-chain, then tries to release the held money. The guardian sees that the engine never signed that confirmation, freezes the hold and pauses the France–Ghana corridor; the attacker's `release()` is mined and fails. Last rehearsed on Fuji on 11 Oct at 06:47 from `main` `970a538`: [forged confirmation](https://testnet.snowtrace.io/tx/0x701bd587026d4ad3a46e7f784b584429d32f7feb53811089eb67f1aed6d1827b), [failed release](https://testnet.snowtrace.io/tx/0x26ec26f301a62dd79326aafc56806db59816b6a3601cab93e30c679e34d246dd).

Three terminals, from the repository root:

```bash
# 1. Engine on Fuji. HUMAN_STEPS=manual is required: with auto the engine answers for the supplier and revokes the payment before the attack.
cd engine && set -a && . ../.env && set +a && CHAIN_MODE=fuji RISK_MODE=model LLM_MODE=cached HUMAN_STEPS=manual uv run uvicorn sylo.main:app --port 8000

# 2. Guardian (polls both RPC endpoints every 2 s, posts incidents to the engine)
cd chain && uv run python -m sylo_chain.guardian watch

# 3. The scene
curl -X POST $E/v1/reset
curl -X POST $E/v1/scenarios/diverted/run -H 'content-type: application/json' -d '{}'
# wait until the payment asks for approval (about 4 s), then:
curl -X POST $E/v1/payments/PAY-2026-0002/approve -H 'content-type: application/json' -d '{"approver":"claire"}'
curl -X POST $E/v1/payments/PAY-2026-0002/approve -H 'content-type: application/json' -d '{"approver":"marc"}'
# wait until the payment is held on-chain, waiting for the supplier (about 15 s), then:
cd chain && uv run python -m sylo_chain.stolen_verifier_key PAY-2026-0002
```

Expected output of the last command: `1. forged CONFIRMED recorded: <link>`, `3. release refused on chain (PaymentNotReleasable): <link>`, `hold frozen: True, corridor paused: True`. Open the failed release on Snowtrace: that is the proof moment.

What to say: "The attacker stole the key that records supplier confirmations. The guardian checks every confirmation against what our engine actually signed. This one was never signed, so it froze the money and paused the corridor before the attacker could take it. The release was mined and rejected by the contract. The guardian opened an incident with a DORA report draft."

**After the scene (mandatory):** reopen the corridor, otherwise every France–Ghana payment stays blocked:

```bash
cd chain && uv run python -m sylo_chain.guardian unpause
```

The frozen hold keeps its test euros (testnet only, harmless).

Known traps:

| Trap | Do this |
|---|---|
| `stolen_verifier_key` says `is REVOKED` or `is NONE` | The payment was not held. Check `HUMAN_STEPS=manual` and that both approvals returned `200` |
| Engine log says `chain refused commit: InvalidTransition` | The engine reuses on-chain payment ids after a restart (first run = `keccak("PAY-2026-0002")`, then `#2`, `#3`… counted in memory), and that id was already used on Fuji. Run the scenario again **without restarting the engine**: the next run gets a new id. Fix requested from Lane A: add a per-boot salt to the label |
| `3. release WENT THROUGH` | The guardian lost the race (it was not running, or the attacker released in the same block). Say it honestly: the challenge window on the roadmap closes this race |
| Every later France–Ghana payment is refused | The corridor is still paused: run `guardian unpause` |

## If something breaks

| Symptom | Do this |
|---|---|
| A scene does not start: "a scenario is running" | **Reset**, then start again |
| The engine does not answer | Switch the screen to **Replay**: it plays the recorded events of the same scenes. Restart the engine with `make engine` when you can |
| Banner says `chain` is degraded | The Fuji client did not load: the mock chain is used. Say "simulated chain" and do not open the explorer |
| The chain stops answering during Scene 2 | The payment stays held and the analyst is alerted; nothing is released. **Reset** and run with `CHAIN_MODE=mock` |
| Banner says `risk` is degraded | The model did not load: the stricter rules decide. Scene 2 still holds the payment |
| The screen is frozen | Reload the page: it reconnects and receives the whole session again |
| Nothing works | Play the backup video, then show `make demo-check` in a terminal |

## What is simulated

Rails, banks, people, accounts, the supplier's phone, the SIM-swap check, strong customer authentication, the mule cluster (a sample until Lane B's detector is installed) and, in mock mode, the chain. Every such event carries `simulated: true`. Nothing has been measured on real payment flows.
