# eERC confidential leg (C2.2)

Avalanche **EncryptedERC** (`ava-labs/EncryptedERC@8dc98cd`) in **converter mode** over our
MockEURC on Fuji (43113). EU CASP wraps MockEURC into eEURC, sends it **confidentially** to GH VASP
with encrypted metadata `{paymentId}`. The auditor decrypts the amount, and GH VASP unwraps back to
MockEURC. Live on Fuji, not simulated. Synthetic data and test-only keys.

## Deployed (Fuji, `deployments/43113.json`)

| Contract | Address |
|---|---|
| EncryptedERC (converter, 2 decimals) | [`0x6112a283a43C3f6522D5Ee55d349Cc841062Ec26`](https://testnet.snowtrace.io/address/0x6112a283a43C3f6522D5Ee55d349Cc841062Ec26) |
| Registrar | [`0xF36620B74Db9b584A15Bd1CF2474Acec0C2ba33A`](https://testnet.snowtrace.io/address/0xF36620B74Db9b584A15Bd1CF2474Acec0C2ba33A) |
| BabyJubJub (library) | `0xeF1C0F4bBbFf3E9451718c112cf9c9DBFB0b6211` |
| Registration / Mint / Withdraw / Transfer / Burn verifiers (upstream `contracts/prod`) | see `deployments/43113.json` |

Registered: auditor (deployer `0xbDB6…`), EU CASP (`0xBCf6…`), GH VASP (`0x4B83…`). The auditor key is set.
Demo runs (tx hashes, auditor result) are in `deployments/demo-runs-43113.json`. The 85,000 EUR run is
[deposit](https://testnet.snowtrace.io/tx/0x40352f4fe095e8f37be722e730d041dfafa6b3daa09a75186df24394bf93933c),
[confidential transfer](https://testnet.snowtrace.io/tx/0x137f2ebe5cab9fe1d50eb59411bfc7da669c3caffc20942f5c22ebf4b4482d3e) and
[withdraw](https://testnet.snowtrace.io/tx/0x68ffba7cff7c751fd9946306362b7da3ca496604cc9a60e2e4535569e15d32f1).
The auditor decrypted **EUR 85,000**.

## How it works

- **Proofs**: generated with `snarkjs.groth16.fullProve` from the upstream prebuilt production circuits
  (`circom/build/*`). We do not recompile circuits or run a trusted setup. `src/check-local.mjs` checks that every
  `contracts/prod/*Verifier.sol` constant equals the `circom/build` verification key, and that local proofs verify.
- **Keys**: each institution's BabyJubJub key is derived deterministically from its EVM key:
  `keccak256(EIP-191 signature of a fixed message) >> 3`, then `formatPrivKeyForBabyJub`. Registration is done once,
  and reruns reuse it.
- **Amounts**: MockEURC has 6 decimals and eEURC has 2. So 85,000 EUR = 85,000,000,000 token units = 8,500,000 eERC units.

## Run

```bash
./setup.sh                      # clone pinned upstream into vendor/, npm ci --ignore-scripts, compile, local check
node src/deploy.mjs             # idempotent; reuses deployments/43113.json (only deploys if absent)
node src/cli.mjs PAY-2026-0001 85000
node src/server.mjs             # http://127.0.0.1:8010 (EERC_PORT / EERC_HOST)
curl -X POST localhost:8010/transfer -H 'content-type: application/json' \
  -d '{"paymentId":"PAY-2026-0001","amountEur":85000}'
```

The keys come from the repo-root `.env` (`FUJI_RPC_URL`, `DEPLOYER_PK`, `EU_CASP_PK`, `GH_VASP_PK`). A response contains
`txs`, `links` (Snowtrace), `auditor.decryptedAmountEur` and `receiverMetadata`. Requests are serialised, and one leg
takes about 30 s (3 txs and 2 proofs). `vendor/` and `node_modules` are git-ignored.

## Honest limits

- **Test-only keys.** BabyJubJub keys are derived from demo EVM keys. Do not use them for anything real.
- **Auditor key holder is still to decide** (PRD §13.6). For the PoC the deployer holds it.
- **A contract cannot hold or release eEURC.** It has no BabyJubJub key and cannot make proofs. So MEDIUM payments
  (hold, then release) keep the **public escrow (Mode A)**. This confidential leg is only for payments that need no hold.
  A confidential escrow (Mode B) is P2.
- **What stays visible:** sender and receiver addresses, and the wrap (deposit) and unwrap (withdraw) amounts in
  MockEURC. **What is hidden:** the eEURC transfer amount, the eEURC balances and the metadata (`paymentId`).
  Only the receiver can decrypt the metadata; the auditor can decrypt amounts.
- The contracts are deployed from unmodified upstream sources (audited upstream; not re-audited by us).
