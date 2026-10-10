#!/usr/bin/env bash
# Deploy MockEURC, PaymentRegistry and PaymentEscrow on a throwaway local Anvil node,
# with the PUBLIC Anvil dev keys (sylo_spec.devkeys). Never use these keys on a real network.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FORGE="${FORGE:-$(command -v forge || echo "$HOME/.foundry/bin/forge")}"
ANVIL="${ANVIL:-$(command -v anvil || echo "$HOME/.foundry/bin/anvil")}"
PORT="${ANVIL_PORT:-8545}"
RPC_URL="http://127.0.0.1:$PORT"

if [ ! -x "$FORGE" ] || [ ! -x "$ANVIL" ]; then
  echo "Foundry is not installed (forge / anvil not found). See docs/setup.md §1." >&2
  exit 1
fi

# Role addresses and the deployer key, derived from the public dev mnemonic.
eval "$(cd "$ROOT/spec/python" && uv run python - <<'PY'
from sylo_spec.devkeys import dev_keys
k = dev_keys()
print(f'export DEPLOYER_PK={k["deployer"].private_key if k["deployer"].private_key.startswith("0x") else "0x" + k["deployer"].private_key}')
for env, role in [("RELAYER_ADDRESS", "relayer"), ("ROUTER_SIGNER_ADDRESS", "router_signer"),
                  ("VERIFIER_SIGNER_ADDRESS", "verifier_signer"), ("ANALYST_SIGNER_ADDRESS", "analyst_signer"),
                  ("GUARDIAN_ADDRESS", "guardian"), ("EU_CASP_ADDRESS", "eu_casp"), ("GH_VASP_ADDRESS", "gh_vasp")]:
    print(f"export {env}={k[role].address}")
PY
)"

"$ANVIL" --port "$PORT" --silent &
ANVIL_PID=$!
trap 'kill "$ANVIL_PID" 2>/dev/null || true' EXIT

for _ in $(seq 1 50); do
  if "${FORGE%forge}cast" chain-id --rpc-url "$RPC_URL" >/dev/null 2>&1; then break; fi
  sleep 0.1
done

cd "$ROOT/contracts"
"$FORGE" script script/Deploy.s.sol --rpc-url "$RPC_URL" --broadcast

echo
echo "Deployed on local Anvil (chain id 31337). Addresses: contracts/deployments/31337.json"
