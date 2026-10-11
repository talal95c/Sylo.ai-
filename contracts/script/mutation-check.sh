#!/usr/bin/env bash
# Plants known bugs in the contracts one at a time and checks that the test suites catch each one.
# src/ is restored from git after every mutant. Usage: script/mutation-check.sh  (RUNS=64 invariant runs)
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

git diff --quiet -- src || { echo "mutation-check: src/ has uncommitted changes; commit or stash them first" >&2; exit 1; }
trap 'git checkout -- src' EXIT

SUITES='EscrowInvariantsTest|EscrowFuzzTest|ReentrancyTest'
total=0
caught=0

# mutant <name> <file> <exact text> <replacement>
mutant() {
  total=$((total + 1))
  FROM="$3" TO="$4" perl -0pi -e 's/\Q$ENV{FROM}\E/$ENV{TO}/' "$2"
  if git diff --quiet -- "$2"; then
    echo "SKIP   $1 (text not found)"
    return
  fi
  if ! forge build >/dev/null 2>&1; then
    echo "BROKEN $1 (does not compile; not a valid mutant)"
  elif FOUNDRY_INVARIANT_RUNS="${RUNS:-64}" forge test --match-contract "$SUITES" >/dev/null 2>&1; then
    echo "MISSED $1"
  else
    echo "CAUGHT $1"
    caught=$((caught + 1))
  fi
  git checkout -- src
}

E=src/PaymentEscrow.sol
R=src/PaymentRegistry.sol
mutant "release ignores a freeze" $E '!h.frozen && block.timestamp' 'block.timestamp'
mutant "release ignores a paused corridor" $E '&& !corridorPaused[h.corridorId] ' ''
mutant "anyone refunds early" $E 'if (!expired && REGISTRY.statusOf(paymentId)' 'if (false && REGISTRY.statusOf(paymentId)'
mutant "deposit skips the digest check" $E ' || REGISTRY.digestOf(i) != intentHash' ''
mutant "deposit accepts any tier" $E 'if (i.tier != uint8(Tier.MEDIUM)) revert TierNotEscrowable();' ''
mutant "second deposit allowed" $E 'if (h.expiresAt != 0) revert AlreadyDeposited();' ''
mutant "refund forgets totalHeld" $E $'totalHeld[h.token] -= h.amount;\n        emit Refunded' 'emit Refunded'
mutant "refund pays the beneficiary" $E 'safeTransfer(h.payer, h.amount)' 'safeTransfer(h.beneficiary, h.amount)'
mutant "release without nonReentrant" $E 'function release(bytes32 paymentId) external nonReentrant' 'function release(bytes32 paymentId) external'
mutant "nonce not recorded" $R 'nonceUsed[signer][nonce] = true;' 'nonceUsed[signer][nonce] = false;'
mutant "revoke reopens executed payments" $R 's != Status.DENIED) revert' 's != Status.DENIED && s != Status.EXECUTED) revert'

echo "$caught/$total mutants caught"
[ "$caught" -eq "$total" ]
