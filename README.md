# Sylo.ai

> **The cheapest compliant route when everything is fine. A window to stop the money when something is wrong.**

Sylo.ai is a decision and control layer for cross-border business payments, built for the
**Secure Horizons** hackathon (ESSEC, 10–11 October 2026, Track 1 — Fintech Security: Guardians of Value).
It sits above licensed payment rails and holds no money. For every payment, **before any money moves**, it keeps
only the routes that are legal in both countries, scores the fraud risk, picks the cheapest safe route, seals the
approved payment on Avalanche as a signed EIP-712 record, and stops a diverted payment in an escrow smart contract
until the supplier confirms on a known contact. The demo shows it live on a 3D globe.

**Everything is simulated.** Rails, banks, people, invoices and data are fictional and synthetic. In v0 the chain is
a mock that mirrors the smart-contract rules; no real payment system and no real network is touched.

## Quickstart

Prerequisites: git, Node.js ≥ 20 with pnpm ≥ 9 (`corepack enable`), [uv](https://docs.astral.sh/uv/) (it installs
Python 3.12), and [Foundry](https://book.getfoundry.sh/) for the contract tests. Details: [`docs/setup.md`](docs/setup.md).

```bash
make setup      # Python environments (uv), web dependencies (pnpm), contract libraries (git submodules)
make dev        # engine on http://localhost:8000, web app on http://localhost:3000
```

Open <http://localhost:3000> and use the demo buttons:

| Button | What you see |
|---|---|
| **Run legit payment** | The mobile-wallet route flashes red and disappears (Ghana's export-proceeds rule); the payment travels the five hops of the stablecoin route, with a high violet arc for Avalanche; the card ends on "Credited" |
| **Run diverted invoice** | The comet stops on the Avalanche arc with a lock; the alert explains the four reasons, what protects the money and what happens next |
| **Supplier: deny** | "Revoked"; the money flies back to Lyon; "Payment stopped. EUR 85,000 returned to Rhône Cosmétiques." |
| **Attack: release revoked payment** | The smart contract rejects it: `PaymentNotReleasable` |
| **Supplier: confirm** (after running the diverted invoice again) | The lock opens and the payment is credited |

If the engine is not running, the web app says so and replays the recorded events of [`spec/fixtures`](spec/fixtures).

No API key and no wallet is needed for v0. Copy `.env.example` to `.env` only to change the flags
(`RISK_MODE`, `CHAIN_MODE`, `LLM_MODE`, `DEMO_SPEED`).

## Tests

```bash
make test             # spec, engine, ml and chain skeletons, contracts (Foundry), web (typecheck, tests, build)
make fixtures-check   # the recorded fixtures are what the engine produces today
```

| Command | Runs |
|---|---|
| `make test-spec` | EIP-712 vector, event schema, scenarios, fixture validation |
| `make test-engine` | Norms, risk rules, router, signer, both conformance suites, scenario timelines, API and stream |
| `make test-ml`, `make test-chain` | Package skeletons (the conformance tests are skipped until v1) |
| `make test-contracts` | `forge build && forge test` (registry, escrow, shared EIP-712 vector) |
| `make test-web` | Typecheck, reducer tests on every fixture, production build |
| `make fixtures` | Re-records `spec/fixtures` (Lane A only) |
| `make anvil-deploy` | Deploys the three contracts on a throwaway local Anvil node with the public dev keys |

## How a decision is made

```
1. NORMS  : which routes are legal at origin, transit and destination?       hard filter
2. RISK   : fraud risk sets the tier (LOW / MEDIUM / HIGH / CRITICAL)        hard filter on routes
3. COST   : best remaining route by cost, time, failure, usability           fraud risk is NEVER in this score
4. COMMIT : approved intent signed (EIP-712) and recorded on-chain
5. ACTION : execute / hold in escrow / pause / block
```

Models can only make a decision stricter; they never approve a payment or release funds. If a dependency is
missing, the engine falls back to its rules and its mock chain, and the banner turns amber.

## Repository map

| Path | Lane | Content |
|---|---|---|
| [`spec/`](spec) | shared | Event schema, API, EIP-712 vector, geography, recorded fixtures, `sylo_spec` (models, ports, conformance suites) |
| [`engine/`](engine) | A | FastAPI app: norms, rules-based risk, router, signer, mock chain, orchestrator, event stream |
| [`ml/`](ml) | B | `sylo_risk`: simulator, model and evaluation (skeleton in v0) |
| [`contracts/`](contracts) | C | Foundry project: `PaymentRegistry`, `PaymentEscrow`, `MockEURC` |
| [`chain/`](chain) | C | `sylo_chain`: `FujiChain` on Avalanche Fuji (skeleton in v0) |
| [`web/`](web) | D | Next.js app with the globe, payment card, alert, event feed and demo controls |
| [`scripts/`](scripts), `Makefile` | A | Dev and demo scripts |

## Documentation

- [`docs/project-context.md`](docs/project-context.md) — what we build, the architecture and the rules every contributor follows.
- [`docs/roadmap-and-lanes.md`](docs/roadmap-and-lanes.md) — versions v0 to v4 and who does what.
- [`docs/v0-build-spec.md`](docs/v0-build-spec.md) — the exact interfaces of the first version.
- [`docs/setup.md`](docs/setup.md) — tools, wallets, environment variables.
- [`prd-final-v4.md`](prd-final-v4.md) — the product requirements. [`prd-final.md`](prd-final.md) (v3, in French) is superseded by it and kept for history.
- [`AGENTS.md`](AGENTS.md) — short rules for coding agents.

## Safety notes

- Synthetic data only; no action on real systems; no secrets in the repository (`.env` is git-ignored).
- `sylo_spec.devkeys` holds the **public** Anvil development keys. They are for the mock chain and a local Anvil
  node only. Never fund them on Fuji or any real network.
