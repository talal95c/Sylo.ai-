#!/usr/bin/env bash
# Reproduce the eERC PoC toolchain: pinned ava-labs/EncryptedERC + deps + Solidity artifacts.
# Uses the vendored prebuilt production circuits (circom/build) - no circuit compilation,
# no ptau download. Needs ~1.2 GB disk (node_modules) and network for npm + solc 0.8.27.
set -euo pipefail
cd "$(dirname "$0")"

COMMIT=8dc98cd
if [ ! -d vendor/EncryptedERC/.git ]; then
	mkdir -p vendor
	git clone https://github.com/ava-labs/EncryptedERC.git vendor/EncryptedERC
fi
git -C vendor/EncryptedERC checkout -q "$COMMIT"

# --ignore-scripts: upstream postinstall runs `hardhat zkit make` (recompiles circuits).
(cd vendor/EncryptedERC && npm ci --ignore-scripts && npx hardhat compile)

ln -sfn vendor/EncryptedERC/node_modules node_modules
node src/check-local.mjs
echo "OK. Next: node src/deploy.mjs (only if deployments/43113.json is absent), node src/cli.mjs, node src/server.mjs"
