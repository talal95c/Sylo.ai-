#!/usr/bin/env bash
# Copies the contracts' ABIs into sylo_chain/abi/ so the package works without a Foundry build.
# Re-run after any change to contracts/src; tests/test_abi_sync.py fails while they differ.
set -euo pipefail

CHAIN="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$CHAIN/../contracts"
for contract in PaymentRegistry PaymentEscrow MockEURC; do
  forge inspect "$contract" abi --json | jq --sort-keys . > "$CHAIN/sylo_chain/abi/$contract.json"
  echo "wrote sylo_chain/abi/$contract.json"
done
