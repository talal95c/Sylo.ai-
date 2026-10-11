import { describe, expect, it } from "vitest";
import { initialState, type ViewState } from "../store";
import { readyAfterTerminalBacklog } from "../liveReady";

function stateWith(status: NonNullable<ViewState["payment"]>["status"]): ViewState {
  return {
    ...initialState,
    mode: { risk: "model" } as ViewState["mode"],
    lastSeq: 42,
    payment: {
      paymentId: "PAY-1",
      payerName: "Payer",
      payeeName: "Supplier",
      accountHolder: "Supplier",
      knownAccount: true,
      amount: { value: "100.00", currency: "EUR" },
      status,
    },
    feed: [{ seq: 42, ts: "", type: "payment", family: "decision", text: "", simulated: true }],
  };
}

describe("readyAfterTerminalBacklog", () => {
  it.each(["credited", "stopped"] as const)(
    "clears a terminal %s payment while preserving session-level state",
    (status) => {
      const state = {
        ...stateWith(status),
        refunded: status === "stopped",
        rails: { R3: { routeId: "R3", simulated: true } as ViewState["rails"][string] },
        killSwitch: { adapter: "R3", simulated: true } as ViewState["killSwitch"],
      };

      expect(readyAfterTerminalBacklog(state)).toMatchObject({
        mode: state.mode,
        lastSeq: 42,
        payment: null,
        feed: [],
        rails: state.rails,
        killSwitch: state.killSwitch,
      });
    },
  );

  it("keeps an in-progress payment visible", () => {
    const state = stateWith("awaiting_supplier");
    expect(readyAfterTerminalBacklog(state)).toBe(state);
  });

  it("clears a refunded payment even before its stopped event arrives", () => {
    const state = { ...stateWith("awaiting_supplier"), refunded: true };
    expect(readyAfterTerminalBacklog(state)).toMatchObject({
      lastSeq: 42,
      payment: null,
      feed: [],
    });
  });
});
