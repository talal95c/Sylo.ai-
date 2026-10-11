# Sylo.ai

> The cheapest compliant route when everything is fine. A window to stop the money when something is wrong.

Hackathon project for **Secure Horizons** (ESSEC, 10–11 October 2026), **Track 1 — Fintech Security: Guardians of Value**.

## What it is

Sylo.ai is a decision and control layer above licensed payment rails for cross-border business payments; it never holds the money. Before any money moves, it keeps only the routes that are legal in both countries, scores the fraud risk, picks the cheapest safe route and seals the approved payment on Avalanche as a signed EIP-712 intent. When a payment looks diverted, the money waits in an escrow smart contract until the supplier confirms on a contact we already know, and it flies back to the payer if they say no. The demo shows all of it live on a 3D globe.

## Quickstart

Prerequisites: [uv](https://docs.astral.sh/uv/) (Python 3.12), Node.js ≥ 22.12 with pnpm 10, and [Foundry](https://getfoundry.sh). Details in [`docs/setup.md`](docs/setup.md).

```bash
make setup      # submodules, Python 3.12, Python packages, web packages
make dev        # engine on http://localhost:8000, web on http://localhost:3000 (Ctrl-C stops both)
```

Open <http://localhost:3000> and use the demo buttons at the bottom left:

1. **Run legit payment**: the illegal mobile-wallet route flashes red and disappears, the payment travels five hops with a high violet arc for Avalanche, and the card ends on "Credited".
2. **Run diverted invoice**: the payment stops on the Avalanche arc behind an escrow lock and the alert explains why.
3. **Supplier: deny**: the payment is revoked on-chain and the money flies back to Lyon. Or **Supplier: confirm**: the lock opens and the payment reaches the supplier.
4. **Attack: release revoked payment** (after deny): the smart contract rejects it, on the globe and in the feed.

Without a running engine, the page replays recorded events (`spec/fixtures`) and says so in the banner.

### Engine v1 (Lane A)

The engine now also runs the human steps and the integrity checks of v1 ([`spec/api.md`](spec/api.md)):

- **Payer approval with dual control** (Claire, then Marc from EUR 20,000), **analyst actions** (confirm the revocation, release, freeze) and the supplier's answer. By default the approvals and the analyst are played by the engine (`HUMAN_STEPS=auto`); set `HUMAN_STEPS=manual` in `.env` when the payer panel and the analyst drawer call the API.
- **Rail adapters**: every leg is checked against the sealed intent before it is sent. Three attacks fail visibly: `release_revoked`, `swap_beneficiary`, `replay`.
- **SIM-swap check** before the supplier is texted (scenario `diverted_simswap`: nobody is texted, the analyst decides).
- **Case file** for the analyst (`case.ready`), **alerts** in the app or by SMS, never by e-mail (`alert.raised`).
- **Decision log** chained by hash in `engine/data/log.jsonl` and `GET /v1/payments/{id}/proof`.

And the network defence of v2:

- **Mule wave and circuit breaker** (`POST /v1/sim/mule-wave`): three linked payments reveal a cluster near Aflao; once the analyst confirms, payments into that region are at least MEDIUM for 24 hours.
- **Rail outage** (scenario `outage`, or `POST /v1/sim/rails/R3/down`): the payment takes the best remaining route; an outage never changes the tier.
- **Kill switch**: two legs changed or replayed on one adapter cut it, and a payment held on that route is revoked and refunded.
- **Guardian incidents** with a DORA incident draft, and `GET /v1/metrics`.

```bash
make demo-check   # scenes 1, 2, 2b, 3, 5, the kill switch and the proof against the running engine (or a temporary one)
make verify-log   # recompute the hash chain of the decision log; an edited line makes it fail
make integrity    # 300 changed or replayed payments through the adapters: 0 must get through
```

## Tests

```bash
make test            # spec, engine, ml, chain, contracts (forge test) and web (typecheck, tests, build)
make fixtures-check  # recorded events still match the engine
make demo-check      # the demo scenes and the three attacks, end to end over HTTP
make anvil-deploy    # deploy the contracts to a throwaway local Anvil node
```

## Repository

| Folder | Lane | Contents |
|---|---|---|
| [`spec/`](spec/) | Shared | Event schema, API, EIP-712 vector, geography, fixtures, Python models and conformance suites |
| [`engine/`](engine/) | A | FastAPI engine: norms, rules-based risk, router, signer, simulated chain, orchestrator, event stream |
| [`ml/`](ml/) | B | Synthetic fraud-risk model, simulator and evaluation pipeline |
| [`contracts/`](contracts/) | C | `PaymentRegistry`, `PaymentEscrow`, `MockEURC` (Foundry) |
| [`chain/`](chain/) | C | Fuji adapter package (skeleton in v0) |
| [`web/`](web/) | D | Next.js demo screen with the globe |

Lane B runs with `RISK_MODE=model`; `LLM_MODE=cached|live` controls case generation and `JEV_MODE` controls advisory document screening. Use `make data SEED=A`, `make train` and `make eval SEED=B` for the model workflow. The cached demo needs no API key. See the [model card](docs/model-card.md) and [benchmark journal](ml/reports/BENCHMARKS.md). `make dev` loads `.env`, which overrides shell flags.

## Documents

- [`docs/project-context.md`](docs/project-context.md): what we build, architecture and rules. Start here.
- [`docs/roadmap-and-lanes.md`](docs/roadmap-and-lanes.md): who does what in each version.
- [`docs/v0-build-spec.md`](docs/v0-build-spec.md): exact interfaces between the parts.
- [`docs/setup.md`](docs/setup.md): tools, wallets and environment variables.
- [`prd-final-v4.md`](prd-final-v4.md): the product requirements. It supersedes [`prd-final.md`](prd-final.md) (v3, in French); [`prd-merge-recap.md`](prd-merge-recap.md) explains how the team's four PRDs were merged.

## Everything is simulated

All companies, people, banks, accounts and amounts are fictional and synthetic. In v0 the payment rails and the blockchain are simulated and labelled as such on screen; no real money, network or key is involved. Secrets live only in a git-ignored `.env` (see [`.env.example`](.env.example)).
