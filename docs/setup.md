# Sylo.ai — setup: tools, MCPs, accounts, wallets, keys

> Everything the team must install, create or configure, who does it, and by when. Task IDs (C0.2, A0.3…) refer to [`roadmap-and-lanes.md`](./roadmap-and-lanes.md).

---

## 0. Checklist

| Item | Who | By | Section |
|---|---|---|---|
| Tools on every laptop | Everyone | Sat 23:45 | §1 |
| Write access for all four, `main` protected | Repository owner (talal95c), requested by A (A0.3) | Sun 00:00 | §2 |
| Avalanche Builder Hub MCP in Cursor | Everyone | Sat 23:45 | §3 |
| Builder Hub account and test AVAX | C (backup: A) | Sat 23:30 | §4 |
| Nine role wallets, funded | C | Sun 00:00 | §5, §6 |
| Routescan verification tested | C | Sun 00:00 | §7 |
| Mistral API key | A | Sun 00:00 | §9 |
| `.env` on each laptop | A (engine values), C (chain values) | Sun 01:00 | §8 |
| Demo laptop ready | D | Sun 09:00 | §10 |

## 1. Tools (every laptop)

| Tool | Needed by | Install | Check |
|---|---|---|---|
| git, GitHub CLI | All | `brew install git gh` then `gh auth login` | `gh auth status` |
| Node.js ≥ 20 and pnpm | All (web), C (eERC scripts) | `brew install node` then `corepack enable` | `node -v`, `pnpm -v` |
| uv and Python 3.12 | All (engine, ml, chain) | `curl -LsSf https://astral.sh/uv/install.sh \| sh` then `uv python install 3.12` | `uv --version` |
| Foundry (`forge`, `cast`, `anvil`) | All (to run `make test`); C daily | `curl -L https://foundry.paradigm.xyz \| bash` then `foundryup` | `forge --version` |
| libomp | B, only if LightGBM | `brew install libomp` | `python -c "import lightgbm"` |
| Chrome | D, demo laptop | — | WebGL works on `https://globe.gl` examples |

Then, in the repository: `make setup` and `make test` (from v0 on).

## 2. Repository access

- Repository: `https://github.com/talal95c/Sylo.ai-`. Clone it once; work on branches named `lane-<x>/<topic>`.
- The owner (talal95c) adds the other three as collaborators with **write** access.
- Branch protection on `main` (Settings → Branches): require a pull request before merging, require status checks to pass (the five `ci-*` workflows, once they exist), block force pushes and deletion.
- After the v0 review, Lane A fills `.github/CODEOWNERS` with the four GitHub usernames.

## 3. Cursor: rules and MCP

- **Rules:** `AGENTS.md` at the root is loaded automatically by Cursor agents. It points to `docs/project-context.md` and the lane rules. Do not remove it.
- **Avalanche Builder Hub MCP** (read-only documentation: Fuji, C-Chain, L1 creation, eERC, faucets, tooling). Add it in Cursor Settings → MCP, or in `~/.cursor/mcp.json`:

  ```json
  {
    "mcpServers": {
      "avalanche-builder-hub": {
        "url": "https://build.avax.network/api/mcp"
      }
    }
  }
  ```

  It answers questions; it does not deploy anything or hold keys. Deployments go through Foundry (§7) and the Builder Console (§4).
- **Optional:** disable MCP servers you do not need for this project, so agents see fewer irrelevant tools.
- **Never paste a private key into a chat.** Agents read keys from `.env` at runtime only.

## 4. Builder Hub account and test AVAX (Lane C)

1. Sign in at `https://build.avax.network` (Builder Hub). The account is also needed for the Console tools used later: faucet, eERC (C2.2, optional), L1 with a managed testnet node (C3.2, stretch; nodes expire after 3 days).
2. Console → **Faucet** (`https://build.avax.network/console/primary-network/faucet`), network Fuji C-Chain, address = the **deployer** wallet (§5). You must be logged in.
3. Fallbacks, in order: the Core faucet (`https://core.app/tools/testnet-faucet`) needs a mainnet balance or a coupon code — ask the organisers or the Avalanche mentor for a coupon; or ask the mentor to send test AVAX directly.

**How much is needed.** Gas on Fuji is cheap (the C-Chain minimum base fee is 1 nAVAX since the Etna upgrade). A typical contract call costs well under 0.01 AVAX; the three deployments together cost about 0.1 AVAX. About 3.5 AVAX in total covers the whole weekend with margin (table in §5).

## 5. Role wallets (Lane C generates them in C0.3)

One key per role, as in production (separation of duties). All are **test-only** wallets created for this weekend.

| Role | `.env` variable | Purpose | Sends transactions? | Fund with |
|---|---|---|---|---|
| Deployer / admin | `DEPLOYER_PK` | Deploys contracts, grants roles, mints tEURC | Yes | 1.0 AVAX (faucet target) |
| Relayer | `RELAYER_PK` | Engine's sender: commit, deposit, record verification, revoke, refund, mark executed | Yes, most of them | 1.0 AVAX |
| Router signer | `ROUTER_SIGNER_PK` | Signs `PaymentIntent` (EIP-712) | No (signs off-chain) | 0 |
| Verifier signer | `VERIFIER_SIGNER_PK` | Signs `VerificationAttestation` | No | 0 |
| Analyst signer | `ANALYST_SIGNER_PK` | Signs `Revocation`; sends `freeze` | Rarely | 0.2 AVAX |
| Guardian | `GUARDIAN_PK` | Sends `freeze` and `pauseCorridor` (v2) | Rarely | 0.3 AVAX |
| EU CASP (payer treasury) | `EU_CASP_PK` | Holds tEURC, approves the escrow; eERC sender (v2) | Yes, a few | 0.3 AVAX |
| GH VASP (beneficiary) | `GH_VASP_PK` | Receives released funds; eERC receiver (v2) | Only for eERC | 0.2 AVAX |
| Attacker | `ATTACKER_PK` | Sends the attack transactions so the failures are public | Yes, a few | 0.3 AVAX |

**Generate** (prints an address and a private key each time):

```bash
for role in DEPLOYER RELAYER ROUTER_SIGNER VERIFIER_SIGNER ANALYST_SIGNER GUARDIAN EU_CASP GH_VASP ATTACKER; do
  echo "== $role"; cast wallet new
done
```

**Store:** each key and address in the team password manager (one entry per role); the keys go in each laptop's `.env` only as needed (§8). Addresses are public and are written to `contracts/deployments/43113.json` by the deploy script.

**Never** fund the public Anvil development keys (`sylo_spec.devkeys`) on Fuji: anyone can sweep them.

## 6. Funding and tokens (Lane C, C0.4 and C1.2)

```bash
export FUJI_RPC_URL=https://api.avax-test.network/ext/bc/C/rpc
cast send <RELAYER_ADDRESS> --value 1ether --private-key $DEPLOYER_PK --rpc-url $FUJI_RPC_URL
cast balance <RELAYER_ADDRESS> --ether --rpc-url $FUJI_RPC_URL
```

(`1ether` means 1 AVAX: the C-Chain native token also has 18 decimals.)

**Settlement token.** Circle's Fuji faucet gives only 20 EURC per request and is rate-limited, so demo amounts (EUR 85,000) use **MockEURC (`tEURC`, 6 decimals)**, deployed by `Deploy.s.sol`, which mints 10,000,000 tEURC to the EU CASP wallet. Then `Approve.s.sol`, run with the EU CASP key, approves the escrow. The UI labels it "test token".

**Optional real-EURC smoke test:** `https://faucet.circle.com`, network Avalanche Fuji, to the EU CASP address. Circle's EURC on Fuji: `0x5E44db7996c682E92a960b65AC713a54AD815c6B`.

**Browser wallet (optional, only for Console tools such as eERC):** Core or MetaMask in a **separate browser profile**, Fuji network added (chain ID 43113, RPC above, symbol AVAX, explorer `https://testnet.snowtrace.io`). Import only the EU CASP and GH VASP test keys, and only if a tool needs them.

## 7. Network configuration and contract verification

| Item | Value |
|---|---|
| Chain ID | 43113 (`0xa869`) |
| RPC, primary | `https://api.avax-test.network/ext/bc/C/rpc` |
| RPC, secondary | `https://avalanche-fuji-c-chain-rpc.publicnode.com` |
| Explorer | `https://testnet.snowtrace.io` (also `https://subnets-test.avax.network/c-chain`) |
| Verification API (Routescan) | `https://api.routescan.io/v2/network/testnet/evm/43113/etherscan`, API key: the literal string `verifyContract` |

**Health checks:**

```bash
cast chain-id --rpc-url $FUJI_RPC_URL          # 43113
cast chain-id --rpc-url $FUJI_RPC_URL_2        # 43113
cast block-number --rpc-url $FUJI_RPC_URL
```

**Deploy and verify (C1.2)** — `foundry.toml` already declares the `fuji` RPC endpoint and the Routescan verifier:

```bash
cd contracts
forge script script/Deploy.s.sol --rpc-url fuji --broadcast --verify
```

**Verify one contract by hand** if `--verify` fails:

```bash
forge verify-contract <ADDRESS> src/PaymentRegistry.sol:PaymentRegistry \
  --chain-id 43113 \
  --verifier-url https://api.routescan.io/v2/network/testnet/evm/43113/etherscan \
  --etherscan-api-key verifyContract \
  --constructor-args $(cast abi-encode "constructor(address)" <ADMIN_ADDRESS>)
```

Test this once in C0.5 with a throwaway contract, so verification is not discovered broken at 01:00.

## 8. Environment variables

`.env.example` (committed) lists every variable; each laptop has its own `.env` (git-ignored). Share values through the password manager, never through the repository or a chat.

| Variable | Used by | Set by | From |
|---|---|---|---|
| `RISK_MODE`, `CHAIN_MODE`, `LLM_MODE`, `DEMO_SPEED` | Engine | Each person; A posts the demo values at each checkpoint | v0 |
| `MISTRAL_API_KEY` | Engine (A1.7) | A | v1 |
| `FUJI_RPC_URL`, `FUJI_RPC_URL_2`, `CHAIN_ID`, `EXPLORER_BASE_URL` | Engine, chain, contracts | C | v1 |
| `REGISTRY_ADDRESS`, `ESCROW_ADDRESS`, `TOKEN_ADDRESS` | Engine, chain | C after C1.2 | v1 |
| `RELAYER_PK`, `ROUTER_SIGNER_PK`, `VERIFIER_SIGNER_PK`, `ANALYST_SIGNER_PK` | Engine with `CHAIN_MODE=fuji` | C | v1 |
| `DEPLOYER_PK`, `EU_CASP_PK` | Contracts scripts | C only | v1 |
| `RELAYER_ADDRESS`, `ROUTER_SIGNER_ADDRESS`, `VERIFIER_SIGNER_ADDRESS`, `ANALYST_SIGNER_ADDRESS`, `GUARDIAN_ADDRESS`, `EU_CASP_ADDRESS` | `Deploy.s.sol`, engine | C | v1 |
| `GUARDIAN_PK` | Guardian (C2.1) | C | v2 |
| `GH_VASP_ADDRESS`, `GH_VASP_PK` | Engine (address), eERC (key) | C | v1, v2 |
| `ATTACKER_PK` | Attacks (C1.4) | C | v1 |
| `NEXT_PUBLIC_ENGINE_URL`, `NEXT_PUBLIC_SOURCE` | Web | D | v0 |

Who needs which keys: **A, C and the demo laptop** need the engine keys; **B and D** need none (they run with mocks and fixtures). Fewer copies, fewer leaks.

## 9. LLM key (Lane A)

- Mistral (`MISTRAL_API_KEY`), created in A0.2. Used only by the investigator agent (A1.7) when `LLM_MODE=live`.
- The demo runs with `LLM_MODE=cached` by default: the case file is pre-generated, labelled "cached", and the demo does not depend on the network or on rate limits.

## 10. Demo laptop (Lane D, by 09:00)

- [ ] Chrome up to date; hardware acceleration on; zoom 100%; notifications off (macOS Focus mode).
- [ ] Repository checked out at the last green tag (`git checkout v2`, later `demo`); `make setup` done.
- [ ] Globe textures served locally (no internet needed for the globe).
- [ ] `.env` with the demo flags posted by A (`CHAIN_MODE=fuji`, `RISK_MODE=model`, `LLM_MODE=cached`) and a mock fallback ready (`CHAIN_MODE=mock`).
- [ ] One full run of scenes 1 → 5 in live mode and in replay mode.
- [ ] Explorer tabs pre-opened for the contracts.
- [ ] Backup video on the desktop and on a USB stick.
- [ ] Charger, display adapter (HDMI / USB-C), mirroring tested.

## 11. Security rules

1. Test wallets only. No mainnet funds anywhere near this project.
2. `.env` is git-ignored; run `git status` before every commit.
3. Never fund the public Anvil keys on Fuji.
4. Never show a private key on screen; the demo shows addresses and transaction hashes only.
5. If a key leaks (commit, screenshot, chat): generate a new wallet, re-grant the role from the deployer, revoke the old address's role, and tell the team.
