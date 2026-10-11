# eERC confidential leg (C2.2)

Avalanche **EncryptedERC in converter mode** over our MockEURC on Fuji (43113). EU CASP wraps
MockEURC into eEURC, sends it confidentially to GH VASP with encrypted metadata
(`{paymentId}`), the auditor decrypts the amount, GH VASP unwraps back to MockEURC.
PRD §13.6, roadmap §8.5 C2.2.

Contracts are the unmodified [ava-labs/EncryptedERC](https://github.com/ava-labs/EncryptedERC)
@ `8dc98cd` (production verifiers from `contracts/prod`, production circuits from
`circom/build`). Proofs are generated with snarkjs; no circuit compilation needed.
`src/check-local.mjs` verifies the prod verifier constants equal the circuit verification keys.

## Deployed (Fuji)

See [`deployments/43113.json`](deployments/43113.json). Main contract:
EncryptedERC `0x6112a283a43C3f6522D5Ee55d349Cc841062Ec26`, Registrar
`0xF36620B74Db9b584A15Bd1CF2474Acec0C2ba33A`, eERC decimals 2 (85,000 EUR = 8,500,000 units).
Registered: auditor (deployer), EU CASP, GH VASP.

Demo run `PAY-2026-0001`, EUR 85,000, auditor decrypted **EUR 85,000**:
[deposit](https://testnet.snowtrace.io/tx/0x40352f4fe095e8f37be722e730d041dfafa6b3daa09a75186df24394bf93933c) ·
[confidential transfer](https://testnet.snowtrace.io/tx/0x137f2ebe5cab9fe1d50eb59411bfc7da669c3caffc20942f5c22ebf4b4482d3e) ·
[withdraw](https://testnet.snowtrace.io/tx/0x68ffba7cff7c751fd9946306362b7da3ca496604cc9a60e2e4535569e15d32f1)

## Run

```bash
./setup.sh                          # clone pinned vendor, npm ci --ignore-scripts, compile, offline check
node src/cli.mjs PAY-2026-0001 85000  # one full leg on Fuji (~30 s)
node src/server.mjs                 # :8010 (EERC_PORT)
curl -XPOST localhost:8010/transfer -H 'content-type: application/json' \
  -d '{"paymentId":"PAY-2026-0001","amountEur":85000}'
```

Response: `txs` + `links` (deposit / transfer / withdraw on Snowtrace), `auditor.decryptedAmountEur`,
`receiverMetadata`, `visibility`. Requests are serialised. Keys come from the repo-root `.env`
(`FUJI_RPC_URL`, `DEPLOYER_PK`, `EU_CASP_PK`, `GH_VASP_PK`). `node src/deploy.mjs` is idempotent
(reuses `deployments/43113.json`, skips done registrations).

BabyJubJub keys are deterministic per institution: `keccak256(EIP-191 signature of a fixed
message) >> 3`, so registration is done once and reruns work.

## Honest limits

- **Test-only keys**, synthetic data. The BabyJubJub key is derived from the EVM key; a real
  institution would keep it in its own HSM/KMS.
- **Auditor key holder is to be decided** (PRD §13.6). In this PoC the deployer holds it.
- **A contract cannot hold or release eEURC**: it has no private key and cannot produce proofs.
  So MEDIUM payments that need a hold keep the **public escrow (Mode A)**. A contract-held
  confidential escrow (Mode B) is P2.
- **What stays visible**: sender and receiver addresses, the wrap (deposit) and unwrap
  (withdraw) amounts, and the fact that a transfer happened. Hidden: the eEURC transfer amount,
  eEURC balances, and the metadata (paymentId). In this demo the full amount is wrapped and
  unwrapped in one go, so an observer can match them. Real privacy needs institutions to keep
  standing eEURC balances.
- Proof generation runs in the service process (~8 s for a transfer on a laptop).
