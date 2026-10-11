#!/usr/bin/env bash
# Shared helpers for the attack scripts (sourced, not run): .env, network check, EIP-712 signing
# with cast, transactions and revert decoding. Prints addresses and tx hashes, never keys.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT/.env}"
if [ "$ENV_FILE" != none ] && [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

for tool in cast jq; do
  command -v "$tool" >/dev/null || { echo "attack: '$tool' not found (docs/setup.md)" >&2; exit 1; }
done

RPC="${RPC_URL:-${FUJI_RPC_URL:?set FUJI_RPC_URL in .env or RPC_URL}}"
CHAIN_ID="$(cast chain-id --rpc-url "$RPC")"
DEPLOYMENT="$ROOT/contracts/deployments/$CHAIN_ID.json"
[ -f "$DEPLOYMENT" ] || { echo "attack: no deployment for chain $CHAIN_ID ($DEPLOYMENT)" >&2; exit 1; }
REGISTRY="$(jq -r .registry "$DEPLOYMENT")"
ESCROW="$(jq -r .escrow "$DEPLOYMENT")"
TOKEN="$(jq -r .token "$DEPLOYMENT")"
EXPLORER=""
[ "$CHAIN_ID" = 43113 ] && EXPLORER="${EXPLORER_BASE_URL:-https://testnet.snowtrace.io}"
FAILED_TX_GAS=300000

INTENT_T="(bytes32,bytes32,address,address,uint256,bytes32,bytes32,bytes32,uint8,uint64,uint256)"
REVOCATION_T="(bytes32,uint8,bytes32,uint256)"
STATUS_NAMES=(NONE COMMITTED CONFIRMED DENIED REVOKED EXECUTED)

say() { printf '\n== %s\n' "$*"; }
link() { if [ -n "$EXPLORER" ]; then echo "$EXPLORER/tx/$1"; else echo "$1"; fi; }
nonce63() { echo $(((RANDOM << 45) ^ (RANDOM << 30) ^ (RANDOM << 15) ^ RANDOM)); }

status_of() {
  local s
  s="$(cast call "$REGISTRY" "statusOf(bytes32)(uint8)" "$1" --rpc-url "$RPC")"
  echo "${STATUS_NAMES[$s]}"
}

# new_intent <label> [tier]: a fresh intent from the EU CASP treasury to the GH VASP, in globals I_*.
new_intent() {
  I_PID="$(cast keccak "ATTACK-$1-$(date +%s)-$RANDOM$RANDOM")"
  I_CORRIDOR="$(cast keccak "FR-GH")"
  I_BENEFICIARY="${GH_VASP_ADDRESS:?GH_VASP_ADDRESS is not set}"
  I_AMOUNT=85000000000
  I_OFFCHAIN="$(cast keccak "offchain-$I_PID")"
  I_DECISION="$(cast keccak "decision-$I_PID")"
  I_APPROVAL="$(cast keccak "approval-$I_PID")"
  I_TIER="${2:-1}"
  I_VALID_UNTIL=$(($(date +%s) + 600))
  I_NONCE="$(nonce63)"
}

# intent_tuple [beneficiary]: the I_* intent as a cast tuple, optionally with another beneficiary.
intent_tuple() {
  echo "($I_PID,$I_CORRIDOR,${1:-$I_BENEFICIARY},$TOKEN,$I_AMOUNT,$I_OFFCHAIN,$I_DECISION,$I_APPROVAL,$I_TIER,$I_VALID_UNTIL,$I_NONCE)"
}

# sign_typed <private key> <primary type> <fields json> <message json>: EIP-712 signature (spec/eip712.json).
sign_typed() {
  local file sig
  file="$(mktemp)"
  jq -n --arg primary "$2" --argjson fields "$3" --argjson message "$4" \
    --arg registry "$REGISTRY" --argjson chainId "$CHAIN_ID" '{
      types: {
        EIP712Domain: [
          {name: "name", type: "string"}, {name: "version", type: "string"},
          {name: "chainId", type: "uint256"}, {name: "verifyingContract", type: "address"}
        ],
        ($primary): $fields
      },
      primaryType: $primary,
      domain: {name: "SyloPaymentRegistry", version: "1", chainId: $chainId, verifyingContract: $registry},
      message: $message
    }' >"$file"
  sig="$(cast wallet sign --data --from-file "$file" --private-key "$1")"
  rm -f "$file"
  echo "$sig"
}

sign_intent() {
  sign_typed "${ROUTER_SIGNER_PK:?ROUTER_SIGNER_PK is not set}" PaymentIntent '[
    {"name": "paymentId", "type": "bytes32"}, {"name": "corridorId", "type": "bytes32"},
    {"name": "beneficiary", "type": "address"}, {"name": "token", "type": "address"},
    {"name": "amount", "type": "uint256"}, {"name": "offchainHash", "type": "bytes32"},
    {"name": "decisionHash", "type": "bytes32"}, {"name": "approvalHash", "type": "bytes32"},
    {"name": "tier", "type": "uint8"}, {"name": "validUntil", "type": "uint64"},
    {"name": "nonce", "type": "uint256"}
  ]' "$(jq -n --arg pid "$I_PID" --arg corridor "$I_CORRIDOR" --arg beneficiary "$I_BENEFICIARY" \
    --arg token "$TOKEN" --arg amount "$I_AMOUNT" --arg offchain "$I_OFFCHAIN" --arg decision "$I_DECISION" \
    --arg approval "$I_APPROVAL" --argjson tier "$I_TIER" --argjson validUntil "$I_VALID_UNTIL" \
    --arg nonce "$I_NONCE" '{paymentId: $pid, corridorId: $corridor, beneficiary: $beneficiary,
      token: $token, amount: $amount, offchainHash: $offchain, decisionHash: $decision,
      approvalHash: $approval, tier: $tier, validUntil: $validUntil, nonce: $nonce}')"
}

# sign_revocation <payment id> <case hash> <nonce>: the analyst revokes with reason SUPPLIER_DENIED (1).
sign_revocation() {
  sign_typed "${ANALYST_SIGNER_PK:?ANALYST_SIGNER_PK is not set}" Revocation '[
    {"name": "paymentId", "type": "bytes32"}, {"name": "reasonCode", "type": "uint8"},
    {"name": "caseHash", "type": "bytes32"}, {"name": "nonce", "type": "uint256"}
  ]' "$(jq -n --arg pid "$1" --arg case "$2" --arg nonce "$3" \
    '{paymentId: $pid, reasonCode: 1, caseHash: $case, nonce: $nonce}')"
}

# send <private key> <contract> <signature> [args...]: a transaction that must succeed.
send() {
  local pk="$1" to="$2" receipt
  shift 2
  receipt="$(cast send "$to" "$@" --private-key "$pk" --rpc-url "$RPC" --json)"
  [ "$(jq -r .status <<<"$receipt")" = 0x1 ] || { echo "attack: setup transaction failed: $1" >&2; exit 1; }
  echo "   ok  $(link "$(jq -r .transactionHash <<<"$receipt")")"
}

# reason_of <cast output>: the custom error name in a revert, matched against the contracts' ABIs.
reason_of() {
  local data selector name
  data="$(grep -oE '0x[0-9a-fA-F]{8,}' <<<"$1" | head -n 1 || true)"
  [ -n "$data" ] || { echo "unknown"; return; }
  selector="$(echo "${data:0:10}" | tr 'A-F' 'a-f')"
  for name in $(jq -r '.[] | select(.type == "error") | "\(.name)(\([.inputs[].type] | join(",")))"' \
    "$ROOT"/chain/sylo_chain/abi/*.json | sort -u); do
    if [ "$(cast sig "$name")" = "$selector" ]; then
      echo "${name%%(*}"
      return
    fi
  done
  echo "unknown ($selector)"
}

# attack <expected reason> <private key> <contract> <signature> [args...]: sends the attack with a
# fixed gas limit (no estimation, so it is mined even though it reverts), then prints the reason.
attack() {
  local expected="$1" pk="$2" to="$3" from receipt tx block out reason
  shift 3
  from="$(cast wallet address --private-key "$pk")"
  receipt="$(cast send "$to" "$@" --private-key "$pk" --rpc-url "$RPC" --gas-limit "$FAILED_TX_GAS" --json 2>&1 || true)"
  tx="$(grep -oE '"transactionHash":"0x[0-9a-f]{64}"' <<<"$receipt" | grep -oE '0x[0-9a-f]{64}' || true)"
  [ -n "$tx" ] || { echo "attack: the transaction was not mined:" >&2; echo "$receipt" >&2; exit 1; }
  [ "$(jq -r .status <<<"$receipt")" = 0x0 ] || { echo "attack: the attack SUCCEEDED ($(link "$tx"))" >&2; exit 1; }
  block="$(jq -r .blockNumber <<<"$receipt")"
  reason="unknown"
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    out="$(cast call "$to" "$@" --from "$from" --block "$((block - 1))" --rpc-url "$RPC" 2>&1 || true)"
    reason="$(reason_of "$out")"
    [ "$reason" != unknown ] && break
    sleep 1
  done
  echo "   REFUSED by the contract: $reason"
  echo "   failed tx: $(link "$tx")"
  [ "$reason" = "$expected" ] || { echo "attack: expected $expected, got $reason" >&2; exit 1; }
}
