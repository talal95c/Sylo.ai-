#!/usr/bin/env bash
# The attacker captured a signed intent and submits it again, hoping to pay the same invoice twice.
# A payment id commits once; the registry refuses the second commit.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

new_intent replay-intent 0
signature="$(sign_intent)"
say "Commit a LOW payment of 85,000 tEURC (payment $I_PID)"
send "$RELAYER_PK" "$REGISTRY" "commit($INTENT_T,bytes)" "$(intent_tuple)" "$signature"

say "ATTACK: the attacker resubmits the same signed intent"
attack InvalidTransition "$ATTACKER_PK" "$REGISTRY" "commit($INTENT_T,bytes)" "$(intent_tuple)" "$signature"
echo "   status is still $(status_of "$I_PID")"
