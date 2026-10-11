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
| `RISK_MODE` | `model` once Lane B's model is installed | `rules`: diverted is MEDIUM 64 instead of HIGH 77, same hold |
| `LLM_MODE` | `cached` once Lane B's case writer exists | `off`: the case file is built from the rules |
| `HUMAN_STEPS` | `manual` once the payer panel and the analyst drawer call the API | `auto`: the engine plays the approvals and the analyst |
| `DEMO_SPEED` | `1` | `2` if the slot is short |

On macOS the model needs the OpenMP library (`brew install libomp`). Without it the engine starts with the rules, made stricter, and the banner says `risk` is degraded.

## Scenes

Times are at speed 1. "UI" means a button exists on the demo screen today; "curl" means it does not yet.

| # | Scene | How | What must appear | Time |
|---|---|---|---|---|
| 1 | Legitimate payment | UI: **Legitimate payment** | R4 excluded by Ghana's export-proceeds rule; LOW 10; R3 chosen; two approvals; intent committed; five hops; "Credited" | 16 s |
| 2 | Diverted invoice | UI: **Diverted invoice** | Four reasons; conditional approval; the comet stops on the Avalanche arc; "Payment held"; case file; Kwame is asked | held after 11 s |
| 2 | Supplier denies | UI: **"We never changed it"** | Denial recorded; analyst confirms; revoked; refunded; freeze request to the mule's bank; "Payment stopped" | 7 s |
| 2 | Supplier confirms (variant) | UI: **"Yes, it's our account"** | Released; two more hops; credited at the new account | 5 s |
| 2b | Attack 1: release a revoked payment | UI: **Try release() attack** | `tx.reverted`, `PaymentNotReleasable` | 1 s |
| 2b | Attack 2: swap the beneficiary | `curl -X POST $E/v1/attacks/swap_beneficiary -H 'content-type: application/json' -d '{"paymentId":"PAY-2026-0002"}'` | `leg.rejected` `INTENT_HASH_MISMATCH` at hop 3, then `tx.reverted` `CommitmentMismatch` | 2 s |
| 2b | Attack 3: replay the intent | same with `/v1/attacks/replay` | `tx.reverted` `InvalidTransition` | 1 s |
| 3 | Mule wave | `curl -X POST $E/v1/sim/mule-wave -H 'content-type: application/json' -d '{"auto":true}'` | Three payments seen on the network; `cluster.detected` near Aflao; `breaker.on` for 24 h | 6 s |
| 3 | Next payment into the region | UI: **Diverted invoice** | Rule `R-CB-01` among the reasons; HIGH and held (rules), or CRITICAL and blocked (model) | 11 s |
| 5 | Rail outage | `curl -X POST $E/v1/scenarios/outage/run -H 'content-type: application/json' -d '{"auto":true}'` | `rail.down` R3; the payment goes through R1 (fees €80); still LOW; `rail.up` | 16 s |
| — | Kill switch | Attack 2 twice | `killswitch.on` for R3; the next legitimate payment goes through R1 | 3 s |
| — | Proof | `curl $E/v1/payments/PAY-2026-0002/proof` then `make verify-log` | Typed data and three signatures; `decision log OK` | — |
| — | "Edit a decision" | change one value in `engine/data/log.jsonl`, then `make verify-log` | `decision log TAMPERED: line N` | — |

Order for four minutes: 1, 2 with the denial, 2b. Scenes 3 and 5 only if time is left. Press **Reset** between two runs of Scene 3 or after the kill switch: it removes the breaker and restores every rail.

With `HUMAN_STEPS=manual` and no panel yet, the human steps are:

```bash
curl -X POST $E/v1/payments/PAY-2026-0002/approve -H 'content-type: application/json' -d '{"approver":"claire"}'
curl -X POST $E/v1/payments/PAY-2026-0002/approve -H 'content-type: application/json' -d '{"approver":"marc"}'
curl -X POST $E/v1/cases/PAY-2026-0002/actions -H 'content-type: application/json' -d '{"action":"CONFIRM_REVOCATION"}'
curl -X POST $E/v1/breakers/CB-CL-AFLAO-01/confirm
```

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
