#!/usr/bin/env bash
# Replaces a registry signer key: new wallet -> grant the role -> update .env -> revoke the old address.
# Usage: contracts/script/rotate-signer.sh ROUTER_SIGNER|VERIFIER_SIGNER|ANALYST_SIGNER
# Needs DEPLOYER_PK (role admin) and FUJI_RPC_URL in .env. Prints addresses and tx hashes only.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="$ROOT/.env"
PREFIX="${1:-}"
case "$PREFIX" in
  ROUTER_SIGNER | VERIFIER_SIGNER | ANALYST_SIGNER) ;;
  *) echo "usage: $0 ROUTER_SIGNER|VERIFIER_SIGNER|ANALYST_SIGNER" >&2; exit 2 ;;
esac
ROLE_NAME="${PREFIX}_ROLE"

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

RPC="${FUJI_RPC_URL:?FUJI_RPC_URL is not set}"
[ "$(cast chain-id --rpc-url "$RPC")" = "${CHAIN_ID:-43113}" ] || { echo "RPC is not on chain ${CHAIN_ID:-43113}" >&2; exit 1; }
REGISTRY="$(jq -r .registry "$ROOT/contracts/deployments/$(cast chain-id --rpc-url "$RPC").json")"
ROLE="$(cast keccak "$ROLE_NAME")"
OLD_VAR="${PREFIX}_ADDRESS"
OLD="${!OLD_VAR:?$OLD_VAR is not set}"

wallet="$(cast wallet new --json)"
NEW="$(jq -r '.data[0].address' <<<"$wallet")"
NEW_PK="$(jq -r '.data[0].private_key' <<<"$wallet")"
unset wallet

has_role() { cast call "$REGISTRY" "hasRole(bytes32,address)(bool)" "$ROLE" "$1" --rpc-url "$RPC"; }
send() { cast send "$REGISTRY" "$@" --private-key "$DEPLOYER_PK" --rpc-url "$RPC" --json | jq -r .transactionHash; }

echo "$ROLE_NAME: $OLD -> $NEW"
echo "grant  tx $(send "grantRole(bytes32,address)" "$ROLE" "$NEW")"
[ "$(has_role "$NEW")" = "true" ] || { echo "grant did not take effect; .env unchanged" >&2; exit 1; }

tmp="$(mktemp "$ENV_FILE.XXXXXX")"
awk -v pk="${PREFIX}_PK" -v addr="$OLD_VAR" -v npk="$NEW_PK" -v naddr="$NEW" -F= '
  $1 == pk { print pk "=" npk; next }
  $1 == addr { print addr "=" naddr; next }
  { print }
' "$ENV_FILE" > "$tmp"
chmod "$(stat -f %Lp "$ENV_FILE" 2>/dev/null || stat -c %a "$ENV_FILE")" "$tmp"
mv "$tmp" "$ENV_FILE"
unset NEW_PK
echo ".env updated (${PREFIX}_PK, $OLD_VAR)"

echo "revoke tx $(send "revokeRole(bytes32,address)" "$ROLE" "$OLD")"
[ "$(has_role "$OLD")" = "false" ] || { echo "old address still holds $ROLE_NAME" >&2; exit 1; }
echo "done: $NEW holds $ROLE_NAME, $OLD no longer does"
