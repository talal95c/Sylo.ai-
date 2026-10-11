import { describe, expect, it } from "vitest";
import {
  mapIntakePipeline,
  orderForMatchedPayment,
  type IntakeResponse,
} from "../intake";

function response(matched = true): IntakeResponse {
  return {
    intake: {
      fields: {},
      senderDomain: {
        value: "savannashea-exports.com",
        provenance: "invoice_pdf_email",
        confidence: 0.8,
        conflict: false,
      },
      changedDetails: true,
      lookalikeDomain: "savanna-shea.com",
      urgencyCues: [],
      instructionLikeLines: 0,
      needsHuman: true,
      truncated: false,
    },
    matchedOrder: matched ? "PAY-2026-0002" : null,
    decision: matched
      ? {
          routes: [
            { routeId: "R1", name: "SWIFT correspondent", status: "PASS" },
            { routeId: "R2", name: "Payout provider", status: "PASS" },
            { routeId: "R3", name: "Euro stablecoin on Avalanche", status: "PASS" },
            { routeId: "R4", name: "Mobile wallet remittance", status: "EXCLUDED" },
          ],
          normChecks: [
            { routeId: "R1", ruleId: "SANCTIONS_SCREEN", result: "PASS" },
            { routeId: "R4", ruleId: "GH_FX_EXPORT_PROCEEDS_NOMINATED_BANK", result: "FAIL" },
          ],
          risk: {
            score: 77,
            tier: "HIGH",
            topReasons: [
              { text: "The bank details came from an emailed invoice." },
              { text: "This is the first payment to this account." },
            ],
          },
          route: {
            chosen: "R3",
            feesEur: 170,
            etaLabel: "≈ 2 h",
            settlement: "ONCHAIN_ESCROW",
            blockedBy: null,
          },
          approval: { conditional: true },
        }
      : null,
  };
}

describe("intake pipeline mapping", () => {
  it("maps the engine's norms, risk and route decision into the four steps", () => {
    expect(mapIntakePipeline(response())).toEqual([
      {
        title: "Norms",
        detail: "3 routes passed · 1 excluded across 2 rule checks.",
        state: "done",
      },
      {
        title: "Risk",
        detail:
          "HIGH · 77/100 · The bank details came from an emailed invoice. · This is the first payment to this account.",
        state: "done",
      },
      {
        title: "Route & cost",
        detail:
          "R3 · Euro stablecoin on Avalanche · €170 fees · ≈ 2 h · conditional · escrow",
        state: "done",
      },
      {
        title: "Commit",
        detail: "Not yet: nothing is committed until you execute.",
        state: "idle",
      },
    ]);
  });

  it("leaves decision steps unfilled when no order matches", () => {
    expect(mapIntakePipeline(response(false))).toMatchObject([
      { title: "Norms", state: "done" },
      { title: "Risk", state: "idle" },
      { title: "Route & cost", state: "idle" },
      { title: "Commit", state: "idle" },
    ]);
  });

  it("maps only the two executable recorded orders", () => {
    expect(orderForMatchedPayment("PAY-2026-0001")).toBe("legit");
    expect(orderForMatchedPayment("PAY-2026-0002")).toBe("diverted");
    expect(orderForMatchedPayment("unknown")).toBeNull();
  });
});
