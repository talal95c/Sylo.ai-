#!/usr/bin/env bash
# Deploys the contracts to a throwaway local Anvil node with the public Anvil dev keys, then stops Anvil.
# Output: contracts/deployments/31337.json (git-ignored).
set -euo pipefail

cd "$(dirname "$0")/../contracts"

PORT="${ANVIL_PORT:-8545}"
RPC_URL="http://127.0.0.1:${PORT}"
# Public development mnemonic (same accounts as sylo_spec.devkeys). Never fund these keys on a real network.
MNEMONIC="test test test test test test test test test test test junk"

for tool in anvil cast forge; do
  command -v "$tool" >/dev/null || { echo "anvil-deploy: '$tool' not found; install Foundry (docs/setup.md)" >&2; exit 1; }
done

anvil --port "$PORT" --mnemonic "$MNEMONIC" --silent &
ANVIL_PID=$!
trap 'kill "$ANVIL_PID" 2>/dev/null || true' EXIT

for _ in $(seq 1 50); do
  cast chain-id --rpc-url "$RPC_URL" >/dev/null 2>&1 && break
  sleep 0.1
done
cast chain-id --rpc-url "$RPC_URL" >/dev/null || { echo "anvil-deploy: Anvil did not start on port $PORT" >&2; exit 1; }

key() { cast wallet private-key "$MNEMONIC" "$1"; }
addr() { cast wallet address --private-key "$(key "$1")"; }

# Account indexes follow sylo_spec.devkeys.ROLES.
DEPLOYER_PK="$(key 0)"
RELAYER_ADDRESS="$(addr 1)"
ROUTER_SIGNER_ADDRESS="$(addr 2)"
VERIFIER_SIGNER_ADDRESS="$(addr 3)"
ANALYST_SIGNER_ADDRESS="$(addr 4)"
GUARDIAN_ADDRESS="$(addr 5)"
EU_CASP_ADDRESS="$(addr 6)"
export DEPLOYER_PK RELAYER_ADDRESS ROUTER_SIGNER_ADDRESS VERIFIER_SIGNER_ADDRESS ANALYST_SIGNER_ADDRESS \
  GUARDIAN_ADDRESS EU_CASP_ADDRESS

forge script script/Deploy.s.sol --rpc-url "$RPC_URL" --broadcast

echo "anvil-deploy: deployed; addresses in contracts/deployments/31337.json (Anvil stopped)"
