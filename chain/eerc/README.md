# eERC confidential leg (C2.2)

Avalanche **EncryptedERC** (`ava-labs/EncryptedERC@8dc98cd`) in **converter mode** over our
MockEURC on Fuji (43113). It runs the way institutions would run it: EU CASP keeps a **pre-funded
eEURC float**, each payment is a **confidential transfer** from that float to GH VASP with encrypted
metadata `{paymentId}`, the **auditor** decrypts every amount, and GH VASP **unwraps a netted total**
later. Live on Fuji, not simulated. Synthetic data and test-only keys.

## Deployed (Fuji, `deployments/43113.json`)

| Contract | Address |
|---|---|
| EncryptedERC (converter, 2 decimals) | [`0x6112a283a43C3f6522D5Ee55d349Cc841062Ec26`](https://testnet.snowtrace.io/address/0x6112a283a43C3f6522D5Ee55d349Cc841062Ec26) |
| Registrar | [`0xF36620B74Db9b584A15Bd1CF2474Acec0C2ba33A`](https://testnet.snowtrace.io/address/0xF36620B74Db9b584A15Bd1CF2474Acec0C2ba33A) |
| BabyJubJub (library) | `0xeF1C0F4bBbFf3E9451718c112cf9c9DBFB0b6211` |
| Registration / Mint / Withdraw / Transfer / Burn verifiers (upstream `contracts/prod`) | see `deployments/43113.json` |

All 8 contracts are source-verified on Snowtrace (`node src/verify.mjs`, Routescan API, no key).

## Why a float and netting

With one wrap and one unwrap per payment, the public MockEURC `deposit` and `withdraw` amounts equal
the hidden transfer amount, so anyone can match them. Institutions do not move money that way. They
keep standing balances and settle net positions:

1. **`float`**: EU CASP wraps a large float once (EUR 1,000,000). It is top-up only. If the
   balance, decrypted locally by EU CASP, is above a threshold (default EUR 250,000), nothing is wrapped.
   A top-up wraps up to the target, never a payment amount.
2. **`transfer`**: this is only a confidential transfer, with no wrap or unwrap. The balance proof uses the
   **current** encrypted balance (`balancePCT` plus pending `amountPCTs`, checked against the on-chain
   ElGamal ciphertext), so the contract accepts it and clears the pending history. If the float cannot
   cover the payment, it is topped up first (`floatTopUp` in the response).
3. **`settle`**: GH VASP unwraps a **netted** amount later, for example EUR 300,000 against three payments
   that total EUR 327,400.75. No public wrap or unwrap amount matches any single payment.

## Roles and wallets

| Role | Address | Does |
|---|---|---|
| Deployer | [`0xbDB6…7d2a`](https://testnet.snowtrace.io/address/0xbDB63aB91DFA5dfA5C8251b1FFbbE3820F5e7d2a) | Deploys only. It has no rights after the handover. |
| Admin (`EERC_ADMIN_*`) | [`0x543c…f315`](https://testnet.snowtrace.io/address/0x543c3081DD0879fb4512147231768e270ae8f315) | Owns EncryptedERC (`Ownable2Step`): `setAuditorPublicKey`, `setTokenBlacklist`. |
| Auditor (`AUDITOR_*`) | [`0x6AcA…c145`](https://testnet.snowtrace.io/address/0x6AcA6b52befC051af9b88C0d64C5b136B249c145) | Holds the audit decryption key. It decrypts amounts only and cannot move funds. |
| EU CASP | `0xBCf6…135D` | Payer-side institution. It holds the eEURC float. |
| GH VASP | `0x4B83…DeB9` | Payee-side institution. It reads the metadata and settles netted amounts. |

`node src/roles.mjs` (idempotent) did the rotation. It created the auditor and admin keys in the repo-root
`.env` and printed only the addresses. It funded each with 0.02 AVAX, registered the auditor
([tx](https://testnet.snowtrace.io/tx/0xc4603f9576008b74b27525e182d5685655b05dd30537faa67801382a695dae3d)),
pointed the auditor key at it
([setAuditorPublicKey](https://testnet.snowtrace.io/tx/0xfd470464d138f44346079b6d99630914794839316d4f648ff5c56b41cdb90042)),
and handed ownership to the admin
([transferOwnership](https://testnet.snowtrace.io/tx/0x38ea8a545fd8a9ddd17d9c371e6840a60bffbba17d2c9f53520b779924debe47),
[acceptOwnership](https://testnet.snowtrace.io/tx/0x9a27e06bcbcbe308ee5633d8c160d4f0541c5b29a7b16f5683c0239c31c176ea)).
The Registrar has no owner. The service checks that the on-chain auditor matches `AUDITOR_PK` before
each operation. If they differ, it refuses with a 503.

**Rotation caveat.** Each audit ciphertext is encrypted for the auditor key that was active at the time. Transfers
before the rotation (`PAY-2026-0001`, `PAY-2026-0002`) can only be decrypted with the **previous** auditor key
(the deployer's), not the new one. We checked this on-chain. A real rotation must keep the old key
in escrow for the retention period.

In production, the auditor key holder is the **compliance function or supervisor**, not the operator. The
key can be split (threshold or HSM) and rotated by the admin. The admin would be a multisig.

## Demo run (float + netting, Fuji)

| Step | Tx | Auditor decrypted |
|---|---|---|
| Float, top-up to EUR 1,000,000 | [deposit](https://testnet.snowtrace.io/tx/0x904ff9c88f0ac3b13d9c7bc996402d37ca529dacea53d900713f492cb04d019b) | (public wrap: EUR 998,749.50, since EUR 1,250.50 was already held) |
| `PAY-2026-0101` | [transfer](https://testnet.snowtrace.io/tx/0x9a08aebebe5ffcc2090ee88cc1a2472201e6be9ebdc73e69b3a127b204a16b9c) | EUR 85,000 |
| `PAY-2026-0102` | [transfer](https://testnet.snowtrace.io/tx/0xeb011a5d5814e7552a3a95353c96d701f2a565ffac98121e0ce87a1756b66c65) | EUR 12,400.75 |
| `PAY-2026-0103` | [transfer](https://testnet.snowtrace.io/tx/0x1b8cd84674010e669c20e758f22a8d1373f61a76332ede8a0bcb45042c7e8bca) | EUR 230,000 |
| Netted settle by GH VASP | [withdraw](https://testnet.snowtrace.io/tx/0x6f55d7fcb23b2a2a540f61d52cd6f51256fc97e20f7f2a20741ef8d6d728e9a4) | EUR 300,000 (EUR 27,400.75 remains unsettled) |

GH VASP decrypted each `{paymentId}`. All records are in `deployments/demo-runs-43113.json`. The first
runs (per-payment wrap/unwrap) are kept there too.

## How it works

- **Proofs**: generated with `snarkjs.groth16.fullProve` from the upstream prebuilt production circuits
  (`circom/build/*`). We do not recompile circuits or run a trusted setup. `src/check-local.mjs` checks that every
  `contracts/prod/*Verifier.sol` constant equals the `circom/build` verification key, and that local proofs verify.
- **Keys**: each institution's BabyJubJub key is derived deterministically from its EVM key:
  `keccak256(EIP-191 signature of a fixed message) >> 3`, then `formatPrivKeyForBabyJub`. Registration is done once,
  and reruns reuse it.
- **Amounts**: MockEURC has 6 decimals and eEURC has 2. Amounts are limited to 2 decimals.

## Run

```bash
./setup.sh                              # pinned upstream into vendor/, npm ci --ignore-scripts, compile, local check
node src/deploy.mjs                     # idempotent; only deploys if deployments/43113.json is absent
node src/roles.mjs                      # idempotent; auditor/admin wallets, auditor rotation, ownership handover
node src/cli.mjs float 1000000          # wrap the float (no-op above the threshold; 2nd arg = threshold)
node src/cli.mjs transfer PAY-2026-0101 85000
node src/cli.mjs settle 300000
node src/cli.mjs status                 # decrypted float / unsettled balances
node src/server.mjs                     # http://127.0.0.1:8010 (EERC_PORT / EERC_HOST; EERC_RECORD=1 logs runs)
```

The CLI appends each run to `deployments/demo-runs-43113.json` (pass `--no-record` to skip this). Keys come from the repo-root `.env`:
`FUJI_RPC_URL`, `DEPLOYER_PK`, `EERC_ADMIN_PK`, `AUDITOR_PK`, `EU_CASP_PK`, `GH_VASP_PK`. In a git worktree, the
main checkout's `.env` is used, and `SYLO_ENV_FILE` overrides it. Float settings: `EERC_FLOAT_EUR` (default 1,000,000)
and `EERC_FLOAT_MIN_EUR` (default 250,000).

### HTTP service

| Endpoint | Body | Does |
|---|---|---|
| `POST /transfer` | `{paymentId, amountEur}` | Confidential transfer only (about 10 s, 1 tx and 1 proof). It auto-tops-up the float if it is short. |
| `POST /settle` | `{amountEur}` | GH VASP unwraps a netted amount. The response is 409 if it exceeds the unsettled balance. |
| `POST /float` | `{targetEur?, minEur?}` | Wraps or tops up the float. It does nothing above `minEur`. |
| `GET /status` | | Decrypted float and unsettled balances. |
| `GET /health` | | Deployment, owner, auditor, endpoints. |

A `/transfer` response contains `txs.transfer`, `links.transfer`, `floatTopUp` (null, or the wrap txs),
`auditor.decryptedAmountEur` and `auditor.matches`, `receiverMetadata`, and `balances`
(`euCaspFloatEur`, `ghVaspUnsettledEur`). It no longer has `txs.deposit` or `txs.withdraw`.
Fail closed: every error is a non-2xx JSON `{error}`. 400 is a bad input, 409 is an insufficient balance,
503 is an auditor key mismatch, and 502 is a chain or RPC failure. Requests are serialised.

## Honest limits

- **Addresses are visible.** The participants are regulated institutions (CASP/VASP), not end customers.
  The parties of a transfer are public; the amounts, balances and `paymentId` are not.
- **The float size is public.** The float wrap (deposit) and the netted settle (withdraw) amounts are public
  MockEURC movements. They show the overall flow volume, not individual payments. A single payment followed
  by a full settle would still be linkable, so settle on a schedule and in amounts that net several payments.
- **A contract cannot hold or release eEURC.** It has no BabyJubJub key and cannot make proofs. So MEDIUM payments
  (hold, then release) keep the **public escrow (Mode A)**. This confidential leg is only for payments that need no hold.
  A confidential escrow (Mode B) is P2.
- **The service holds all keys in the demo** (EU CASP, GH VASP, auditor) so it can show every view. In production,
  each institution and the auditor run their own key.
- **Test-only keys.** BabyJubJub keys are derived from demo EVM keys. Do not use them for anything real.
- The contracts are deployed from unmodified upstream sources (audited upstream; not re-audited by us).
