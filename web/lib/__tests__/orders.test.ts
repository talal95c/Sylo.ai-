import { describe, expect, it } from "vitest";
import { summarizeQuote, type QuoteDecision } from "../orders";

const decision: QuoteDecision = {
  paymentId: "PAY-2026-0002",
  corridor: "FR-GH",
  currency: "EUR",
  packVersion: "fr-gh-2026.1",
  normChecks: [
    { routeId: "R1", ruleId: "EU_PSD2", result: "PASS" },
    { routeId: "R2", ruleId: "EU_PSD2", result: "PASS" },
    { routeId: "R3", ruleId: "GH_FOREX", result: "FAIL" },
  ],
  risk: {
    score: 62,
    tier: "MEDIUM",
    rulesFired: ["R-PV-01"],
    topReasons: [{ text: "Account details came from an e-mail" }],
  },
  route: {
    chosen: "R2",
    candidates: [
      { routeId: "R1", s: 812.4 },
      { routeId: "R2", s: 640.1 },
      { routeId: "R3", s: null, excludedBy: "GH_FOREX" },
    ],
    feesEur: 640.1,
    etaLabel: "T+0",
    priceOfSafetyEur: 28,
  },
  quoteId: "Q-0001",
  executable: true,
};

describe("summarizeQuote", () => {
  it("summarizes the four checks from the decision", () => {
    const steps = summarizeQuote(decision);
    expect(steps).toHaveLength(4);
    expect(steps[0].title).toBe("Norms");
    expect(steps[0].detail).toContain("2 pass");
    expect(steps[0].detail).toContain("1 fail");
    expect(steps[1].detail).toContain("MEDIUM");
    expect(steps[1].detail).toContain("62");
    expect(steps[1].detail).toContain("Account details came from an e-mail");
    expect(steps[2].detail).toContain("R2");
    expect(steps[2].detail).toContain("640.10");
    expect(steps[2].detail).toContain("T+0");
    expect(steps[2].detail).toContain("1 excluded");
    expect(steps[3].detail).toBe("Sealed on run");
  });

  it("marks non-executable quotes as quote only", () => {
    const steps = summarizeQuote({ ...decision, executable: false });
    expect(steps[3].detail).toBe("Quote only");
  });

  it("handles a decision with no route", () => {
    const steps = summarizeQuote({ ...decision, route: { chosen: null, blockedBy: "RISK_TIER", candidates: [] } });
    expect(steps[2].detail).toContain("RISK_TIER");
  });
});
