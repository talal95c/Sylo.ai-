# Sylo.ai — contracts (Lane C)

Foundry project (solc 0.8.28, EVM Cancun, OpenZeppelin Contracts v5) for the on-chain part of Sylo.ai. v0 runs them in tests and on a local Anvil node only; Fuji comes in v1.

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

## Signatures

Signers are plain keys (65-byte ECDSA signatures) or contract wallets such as a multisig: pass `abi.encodePacked(walletAddress, walletSignature)` and the registry checks it with ERC-1271.

Interfaces and acceptance rules: [`docs/v0-build-spec.md`](../docs/v0-build-spec.md) §4.4 and §6; product design: [`prd-final-v4.md`](../prd-final-v4.md) §13.
