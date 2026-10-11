#!/usr/bin/env bash
# A compromised rail adapter tries to escrow the committed payment with the attacker as beneficiary.
# The escrow recomputes the EIP-712 hash of what it is given; it differs from the committed one.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

new_intent swap-beneficiary
say "Commit a MEDIUM payment of 85,000 tEURC to the GH VASP (payment $I_PID)"
send "$RELAYER_PK" "$REGISTRY" "commit($INTENT_T,bytes)" "$(intent_tuple)" "$(sign_intent)"

say "ATTACK: escrow the same payment with beneficiary $ATTACKER_ADDRESS"
attack CommitmentMismatch "$RELAYER_PK" "$ESCROW" "deposit($INTENT_T,address)" \
  "$(intent_tuple "$ATTACKER_ADDRESS")" "$EU_CASP_ADDRESS"
echo "   status is still $(status_of "$I_PID"); no money moved"
