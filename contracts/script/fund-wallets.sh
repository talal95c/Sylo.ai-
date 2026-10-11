#!/usr/bin/env bash
# Tops up the role wallets from the deployer on Fuji, to the amounts of docs/setup.md section 5.
# Only the difference to each target is sent, so re-running is safe.
#   DRY_RUN=1 contracts/script/fund-wallets.sh   # show the plan and balances, send nothing
#   FUND_RELAYER=0.5 ...                         # override one target (AVAX)
#   DEPLOY_RESERVE=0.3                           # AVAX kept on the deployer for deployments
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="$ROOT/.env"
[[ -f "$ENV_FILE" ]] || { echo "No .env: run contracts/script/new-wallets.sh first" >&2; exit 1; }
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

: "${FUJI_RPC_URL:?missing in .env}" "${FUJI_RPC_URL_2:?missing in .env}" "${DEPLOYER_PK:?missing in .env}"
EXPLORER_BASE_URL="${EXPLORER_BASE_URL:-https://testnet.snowtrace.io}"

for rpc in "$FUJI_RPC_URL" "$FUJI_RPC_URL_2"; do
  id="$(cast chain-id --rpc-url "$rpc")"
  [[ "$id" == "43113" ]] || { echo "Refusing: $rpc returns chain ID $id, expected 43113 (Fuji)" >&2; exit 1; }
done
echo "Both RPC endpoints are Fuji (43113)."

deployer="${DEPLOYER_ADDRESS:-$(cast wallet address --private-key "$DEPLOYER_PK")}"
TARGETS=(
  "RELAYER:${FUND_RELAYER:-1.0}"
  "ANALYST_SIGNER:${FUND_ANALYST_SIGNER:-0.2}"
  "GUARDIAN:${FUND_GUARDIAN:-0.3}"
  "EU_CASP:${FUND_EU_CASP:-0.3}"
  "GH_VASP:${FUND_GH_VASP:-0.2}"
  "ATTACKER:${FUND_ATTACKER:-0.3}"
)

wei_sub() { python3 -c "import sys; print(max(0, int(sys.argv[1]) - int(sys.argv[2])))" "$1" "$2"; }
wei_add() { python3 -c "import sys; print(int(sys.argv[1]) + int(sys.argv[2]))" "$1" "$2"; }
wei_lt() { python3 -c "import sys; sys.exit(0 if int(sys.argv[1]) < int(sys.argv[2]) else 1)" "$1" "$2"; }
avax() { cast from-wei "$1"; }

deployer_balance="$(cast balance "$deployer" --rpc-url "$FUJI_RPC_URL")"
reserve="$(cast to-wei "${DEPLOY_RESERVE:-0.3}")"
total=0
declare -a SENDS=()

printf '%-16s %-44s %12s %12s %12s\n' ROLE ADDRESS BALANCE TARGET TO_SEND
printf '%-16s %-44s %12s\n' DEPLOYER "$deployer" "$(avax "$deployer_balance")"
for entry in "${TARGETS[@]}"; do
  role="${entry%%:*}"
  target_avax="${entry#*:}"
  address_var="${role}_ADDRESS"
  address="${!address_var:-}"
  [[ -n "$address" ]] || { echo "$address_var is empty in .env: run new-wallets.sh" >&2; exit 1; }
  balance="$(cast balance "$address" --rpc-url "$FUJI_RPC_URL")"
  need="$(wei_sub "$(cast to-wei "$target_avax")" "$balance")"
  total="$(wei_add "$total" "$need")"
  [[ "$need" == "0" ]] || SENDS+=("$role:$address:$need")
  printf '%-16s %-44s %12s %12s %12s\n' "$role" "$address" "$(avax "$balance")" "$target_avax" "$(avax "$need")"
done
echo "Total to send: $(avax "$total") AVAX; kept on the deployer for deployments: $(avax "$reserve") AVAX"

if [[ "${DRY_RUN:-0}" == "1" ]]; then
  echo "DRY_RUN=1: nothing sent."
  exit 0
fi
if [[ ${#SENDS[@]} -eq 0 ]]; then
  echo "Every role is already at its target."
  exit 0
fi
if wei_lt "$deployer_balance" "$(wei_add "$total" "$reserve")"; then
  missing="$(wei_sub "$(wei_add "$total" "$reserve")" "$deployer_balance")"
  echo "The deployer needs $(avax "$missing") more AVAX: request it from the faucet, or lower the targets (FUND_<ROLE>=...)." >&2
  exit 1
fi

for send in "${SENDS[@]}"; do
  IFS=: read -r role address need <<<"$send"
  tx="$(cast send "$address" --value "$need" --private-key "$DEPLOYER_PK" --rpc-url "$FUJI_RPC_URL" --json | jq -r '.transactionHash')"
  echo "$role <- $(avax "$need") AVAX  $EXPLORER_BASE_URL/tx/$tx"
done
echo "Deployer balance now: $(avax "$(cast balance "$deployer" --rpc-url "$FUJI_RPC_URL")") AVAX"
