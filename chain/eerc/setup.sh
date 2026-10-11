#!/usr/bin/env bash
# Reproduce the eERC toolchain: pinned ava-labs/EncryptedERC + deps + compiled contracts.
# Does NOT run the vendor postinstall (`hardhat zkit make`): we use the prebuilt production
# circuits in circom/build and the matching verifiers in contracts/prod.
set -euo pipefail
cd "$(dirname "$0")"

COMMIT=8dc98cd
if [ ! -d vendor/EncryptedERC/.git ]; then
	mkdir -p vendor
	git clone https://github.com/ava-labs/EncryptedERC.git vendor/EncryptedERC
fi
git -C vendor/EncryptedERC checkout -q "$COMMIT"

(cd vendor/EncryptedERC && npm ci --ignore-scripts && npx hardhat compile)
ln -sfn vendor/EncryptedERC/node_modules node_modules

node src/check-local.mjs
echo "OK. Next: node src/deploy.mjs (only if deployments/43113.json is absent), node src/cli.mjs, node src/server.mjs"
