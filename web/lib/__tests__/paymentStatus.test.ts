import { describe, expect, it } from "vitest";
import { initialState, type ViewState } from "../store";
import { paymentStatusView } from "../paymentStatus";

function stateWith(
  status: NonNullable<ViewState["payment"]>["status"],
  options: Partial<Pick<ViewState, "refunded" | "attack">> = {},
): ViewState {
  return {
    ...initialState,
    payment: {
      paymentId: "PAY-1",
      payerName: "Payer",
      payeeName: "Supplier",
      accountHolder: "Supplier",
      knownAccount: true,
      amount: { value: "100.00", currency: "EUR" },
      status,
    },
    ...options,
  };
}

describe("paymentStatusView", () => {
  it.each([
    ["credited", "Supplier credited"],
    ["held", "Held in escrow"],
    ["stopped", "Stopped"],
  ] as const)("derives the %s status from the payment", (status, label) => {
    expect(paymentStatusView(stateWith(status)).label).toBe(label);
  });

  it("shows stopped and refunded as one outcome", () => {
    expect(paymentStatusView(stateWith("stopped", { refunded: true })).label).toBe(
      "Stopped and refunded",
    );
  });

  it("shows a reverted attack as the shared card status", () => {
    expect(
      paymentStatusView(
        stateWith("stopped", {
          refunded: true,
          attack: { ...initialState.attack, attempted: true, reverted: true },
        }),
      ),
    ).toEqual({ label: "Attack reverted", color: "var(--low)" });
  });
});
