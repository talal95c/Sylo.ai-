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

## Tests

```bash
make test            # spec, engine, ml, chain, contracts (forge test) and web (typecheck, tests, build)
make fixtures-check  # recorded events still match the engine
make anvil-deploy    # deploy the contracts to a throwaway local Anvil node
```

## Repository

| Folder | Lane | Contents |
|---|---|---|
| [`spec/`](spec/) | Shared | Event schema, API, EIP-712 vector, geography, fixtures, Python models and conformance suites |
| [`engine/`](engine/) | A | FastAPI engine: norms, rules-based risk, router, signer, simulated chain, orchestrator, event stream |
| [`ml/`](ml/) | B | Fraud model package (skeleton in v0) |
| [`contracts/`](contracts/) | C | `PaymentRegistry`, `PaymentEscrow`, `MockEURC` (Foundry) |
| [`chain/`](chain/) | C | Fuji adapter package (skeleton in v0) |
| [`web/`](web/) | D | Next.js demo screen with the globe |

## Documents

- [`docs/project-context.md`](docs/project-context.md): what we build, architecture and rules. Start here.
- [`docs/roadmap-and-lanes.md`](docs/roadmap-and-lanes.md): who does what in each version.
- [`docs/v0-build-spec.md`](docs/v0-build-spec.md): exact interfaces between the parts.
- [`docs/setup.md`](docs/setup.md): tools, wallets and environment variables.
- [`prd-final-v4.md`](prd-final-v4.md): the product requirements. It supersedes [`prd-final.md`](prd-final.md) (v3, in French); [`prd-merge-recap.md`](prd-merge-recap.md) explains how the team's four PRDs were merged.

## Everything is simulated

All companies, people, banks, accounts and amounts are fictional and synthetic. In v0 the payment rails and the blockchain are simulated and labelled as such on screen; no real money, network or key is involved. Secrets live only in a git-ignored `.env` (see [`.env.example`](.env.example)).
