const REVERT_MESSAGES: Record<string, string> = {
  PaymentNotReleasable: "The escrow refused to release a revoked payment.",
  CommitmentMismatch:
    "The contract refused a leg that differs from the signed intent.",
  InvalidTransition:
    "The contract refused a step this payment's state does not allow.",
  INTENT_HASH_MISMATCH:
    "The rail refused a leg that does not match the signed intent.",
};

export function revertMessage(reason: string | null | undefined): string {
  return (reason && REVERT_MESSAGES[reason]) ||
    "The smart contract refused the transaction.";
}
