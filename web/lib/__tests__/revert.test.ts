import { describe, expect, it } from "vitest";
import { revertMessage } from "../revert";

describe("revert messages", () => {
  it.each([
    [
      "PaymentNotReleasable",
      "The escrow refused to release a revoked payment.",
    ],
    [
      "CommitmentMismatch",
      "The contract refused a leg that differs from the signed intent.",
    ],
    [
      "InvalidTransition",
      "The contract refused a step this payment's state does not allow.",
    ],
    [
      "INTENT_HASH_MISMATCH",
      "The rail refused a leg that does not match the signed intent.",
    ],
  ])("explains %s", (reason, expected) => {
    expect(revertMessage(reason)).toBe(expected);
  });

  it.each([undefined, null, "", "UnknownError"])(
    "uses a safe fallback for %s",
    (reason) => {
      expect(revertMessage(reason)).toBe(
        "The smart contract refused the transaction.",
      );
    },
  );
});
