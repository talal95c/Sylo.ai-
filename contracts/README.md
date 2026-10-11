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

If a signer key leaks, `script/rotate-signer.sh ROUTER_SIGNER` (or `VERIFIER_SIGNER`, `ANALYST_SIGNER`) grants the role to a fresh wallet, rewrites `.env` and revokes the old address. Run it in a shell where no old `*_PK` variables are exported, and share the new `.env` values with whoever runs the engine on Fuji.

## Signatures

Signers are plain keys (65-byte ECDSA signatures) or contract wallets such as a multisig: pass `abi.encodePacked(walletAddress, walletSignature)` and the registry checks it with ERC-1271.

Interfaces and acceptance rules: [`docs/v0-build-spec.md`](../docs/v0-build-spec.md) §4.4 and §6; product design: [`prd-final-v4.md`](../prd-final-v4.md) §13.
