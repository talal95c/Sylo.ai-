# Sylo.ai — contracts (Lane C)

Foundry project (solc 0.8.28, EVM Cancun, OpenZeppelin Contracts v5) for the on-chain part of Sylo.ai. Deployed and verified on Avalanche Fuji; addresses in [`deployments/43113.json`](deployments/43113.json).

| Fuji (43113) | Address |
|---|---|
| `PaymentRegistry` | [`0xea43E7349B9006078335b29d28D8Ac77C976Fad1`](https://testnet.snowtrace.io/address/0xea43E7349B9006078335b29d28D8Ac77C976Fad1) |
| `PaymentEscrow` | [`0xC54dDE5D3eaBf988bcB4Aaa37bDf24C6CeFD159E`](https://testnet.snowtrace.io/address/0xC54dDE5D3eaBf988bcB4Aaa37bDf24C6CeFD159E) |
| `MockEURC` (tEURC) | [`0xd1A86C8Fc2a693E9C81E6ddC2924179e82A407bD`](https://testnet.snowtrace.io/address/0xd1A86C8Fc2a693E9C81E6ddC2924179e82A407bD) |

| Contract | Role |
|---|---|
| `PaymentRegistry` | Records the EIP-712 attestations (intent, verification, revocation) and each payment's status. A signature counts only if its signer holds the matching role; nonces are single-use per signer. |
| `PaymentEscrow` | Holds MEDIUM payments until the supplier's known contact confirms. Money leaves only to the intent's beneficiary (`release`, after CONFIRMED) or back to the payer (`refund`). |
| `MockEURC` | Simulated 6-decimal euro token (`tEURC`) for local and test networks. |
| `SyloTypes` | The three EIP-712 structs, the enums and the type hashes. |

The status machine, the order of checks and the custom error names are the ones the engine's `MockChain` simulates (`engine/sylo/chain_mock.py`), so the demo behaves the same on either.

## Commands

```bash
git submodule update --init --recursive   # forge-std and openzeppelin-contracts (make setup does it)
forge build
forge test                                # includes the shared EIP-712 vector from ../spec/eip712.json
make -C .. anvil-deploy                   # deploy to a throwaway Anvil node; writes deployments/31337.json
```

## Security testing

PRD §13.3 invariants, beyond the unit tests in `PaymentRegistry.t.sol` and `PaymentEscrow.t.sol`:

| Test | What it checks |
|---|---|
| `EscrowInvariants.t.sol` + `EscrowHandler.sol` | Random sequences (256 runs × 100 calls) of commit, deposit, tampered deposit, verify, revoke, markExecuted, release, refund, freeze, pause, nonce replay and time jumps, from random callers. The handler predicts every outcome from the rules and counts disagreements. After each call: (1) escrow balance = open holds; (2) tokens stay with the payer, the escrow or intent beneficiaries; (3–6) no disagreement; holds mirror their committed intent; REVOKED and EXECUTED are final. |
| `EscrowFuzz.t.sol` | One action, random inputs: any altered intent field reverts `CommitmentMismatch`; release pays exactly the committed beneficiary, whoever calls; release needs CONFIRMED and an unexpired hold; anyone refunds after revoke or expiry, nobody but the analyst before; one deposit per payment; single-use nonces; only MEDIUM is escrowed; only the router key commits and only the router role deposits. |
| `Reentrancy.t.sol` (invariant 7) | A hostile token calls back into `release` and `refund` during every transfer of `deposit`, `release` and `refund`; the guard blocks each, and money moves once. |
| `script/mutation-check.sh` | Plants 11 known bugs in `src/` one at a time (skipped freeze or pause check, early refund, no digest check, any tier, double deposit, wrong refund recipient, lost accounting, no reentrancy guard, nonce not recorded, executed payment revocable) and checks the suites above catch each: 11/11. Restores `src/` afterwards. |

Gas (median, `forge test --gas-report`): `commit` 171k, `deposit` 204k, `recordVerification` 65k, `release` 84k, `revoke` 61k, `refund` 64k, `freeze` 33k, `markExecuted` 27k. A full MEDIUM flow (commit, deposit, verify, release) is about 525k gas.

Slither (`uvx --from slither-analyzer slither . --filter-paths "lib/|test/|script/"`) reports, after triage:
- `arbitrary-send-erc20` in `deposit`: the escrow pulls from the `payer` argument, which the signed intent does not bind. Only the router role can call it, and only for a committed intent whose beneficiary is fixed, so the money still goes to that beneficiary or back to the account it came from. A compromised relayer could make another treasury that approved the escrow fund the intent. Today only the EU CASP approves it. Fix in the roadmap: add `payer` to `PaymentIntent` (EIP-712 change for every lane).
- `unused-return` on `ECDSA.tryRecoverCalldata`: the ignored value is the error argument; the error code is checked.
- `timestamp`: holds last hours, so validator drift of seconds does not matter (also excluded in `foundry.toml`).

`script/Deploy.s.sol` reads `DEPLOYER_PK` and the role addresses (`RELAYER_ADDRESS`, `ROUTER_SIGNER_ADDRESS`, `VERIFIER_SIGNER_ADDRESS`, `ANALYST_SIGNER_ADDRESS`, `GUARDIAN_ADDRESS`, `EU_CASP_ADDRESS`) from the environment. `make anvil-deploy` fills them with the public Anvil development accounts; never fund those keys on a real network.

## Fuji

```bash
script/new-wallets.sh                        # role wallets into ../.env (addresses printed, keys never)
DRY_RUN=1 script/fund-wallets.sh             # then without DRY_RUN: top up the roles from the deployer
set -a && source ../.env && set +a
forge script script/Deploy.s.sol --rpc-url fuji --broadcast --slow --verify   # writes deployments/43113.json
forge script script/Approve.s.sol --rpc-url fuji --broadcast                  # EU CASP lets the escrow pull tEURC
```

Verification goes through Routescan (configured in `foundry.toml`). After a redeploy, update `REGISTRY_ADDRESS`, `ESCROW_ADDRESS` and `TOKEN_ADDRESS` in every `.env` and the table above.

### Attack scripts (demo backup, no engine needed)

Each script sets up its own payment, sends the attack with a fixed gas limit so it is mined as a failed transaction, and prints the Snowtrace link and the revert reason:

```bash
script/attacks/release-revoked.sh     # attacker calls release() on a revoked payment -> PaymentNotReleasable
PAYMENT_ID=0x... script/attacks/release-revoked.sh   # same, on an engine payment that is already REVOKED
script/attacks/swap-beneficiary.sh    # escrow the committed payment with the attacker as beneficiary -> CommitmentMismatch
script/attacks/replay-intent.sh       # resubmit a signed intent that is already committed -> InvalidTransition
```

They read `../.env`; set `RPC_URL` to point them at another chain that has a `deployments/<chainId>.json` (the chain tests run them on Anvil).

If a signer key leaks, `script/rotate-signer.sh ROUTER_SIGNER` (or `VERIFIER_SIGNER`, `ANALYST_SIGNER`) grants the role to a fresh wallet, rewrites `.env` and revokes the old address. Run it in a shell where no old `*_PK` variables are exported, and share the new `.env` values with whoever runs the engine on Fuji.

## Signatures

Signers are plain keys (65-byte ECDSA signatures) or contract wallets such as a multisig: pass `abi.encodePacked(walletAddress, walletSignature)` and the registry checks it with ERC-1271.

Interfaces and acceptance rules: [`docs/v0-build-spec.md`](../docs/v0-build-spec.md) §4.4 and §6; product design: [`prd-final-v4.md`](../prd-final-v4.md) §13.
