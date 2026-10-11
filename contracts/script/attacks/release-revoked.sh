#!/usr/bin/env bash
# Scene 2b: an attacker calls release() on a revoked payment to push the money to the mule.
# Without PAYMENT_ID: commits, escrows and revokes a fresh 85,000 tEURC payment, attacks it, then refunds it.
# With PAYMENT_ID=0x...: attacks that payment (it must already be REVOKED, e.g. the engine's scene 2 run).
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

if [ -n "${PAYMENT_ID:-}" ]; then
  I_PID="$PAYMENT_ID"
  [ "$(status_of "$I_PID")" = REVOKED ] || { echo "attack: $I_PID is $(status_of "$I_PID"), not REVOKED" >&2; exit 1; }
else
  new_intent release-revoked
  say "Commit a MEDIUM payment of 85,000 tEURC (payment $I_PID)"
  send "$RELAYER_PK" "$REGISTRY" "commit($INTENT_T,bytes)" "$(intent_tuple)" "$(sign_intent)"
  say "Escrow it"
  send "$RELAYER_PK" "$ESCROW" "deposit($INTENT_T,address)" "$(intent_tuple)" "$EU_CASP_ADDRESS"
  say "The supplier denies; the analyst revokes"
  case_hash="$(cast keccak "case-$I_PID")"
  nonce="$(nonce63)"
  send "$RELAYER_PK" "$REGISTRY" "revoke($REVOCATION_T,bytes)" \
    "($I_PID,1,$case_hash,$nonce)" "$(sign_revocation "$I_PID" "$case_hash" "$nonce")"
fi

say "ATTACK: the attacker calls release() on revoked payment $I_PID"
attack PaymentNotReleasable "$ATTACKER_PK" "$ESCROW" "release(bytes32)" "$I_PID"
echo "   status is still $(status_of "$I_PID")"

if [ -z "${PAYMENT_ID:-}" ]; then
  say "Refund the payer"
  send "$RELAYER_PK" "$ESCROW" "refund(bytes32)" "$I_PID"
fi
