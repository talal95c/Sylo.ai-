import { describe, expect, it } from "vitest";
import type { SyloEvent } from "../events";
import { buildQuote, secondsBetween } from "../quote";
import { initialState, reduce } from "../store";

function event(seq: number, type: string, data: Record<string, unknown>, ts = "2026-10-11T09:00:00.000Z"): SyloEvent {
  return { v: 1, seq, id: `evt-${seq}`, ts, type, paymentId: "pay-1", simulated: true, data } as SyloEvent;
}

const created = event(1, "payment.created", {
  payer: { name: "Atelier" },
  beneficiary: { payeeName: "Kente", accountHolder: "Kente", knownAccount: true },
  amount: { value: "85000.00", currency: "EUR" },
});

const legacyScores = [
  { routeId: "R1", s: 216.0, excludedBy: null },
  { routeId: "R2", s: 941.73, excludedBy: null },
  { routeId: "R3", s: 179.21, excludedBy: null },
  { routeId: "R4", s: null, excludedBy: "GH_FX_EXPORT_PROCEEDS_NOMINATED_BANK" },
];

function selected(extra: Record<string, unknown>, scores: unknown[]) {
  return event(2, "route.selected", {
    routeId: "R3",
    name: "Euro stablecoin on Avalanche",
    settlement: "ONCHAIN_ESCROW",
    tier: "LOW",
    reason: "",
    feesEur: 170,
    etaLabel: "≈ 2 h",
    priceOfSafetyEur: 0,
    scores,
    ...extra,
  });
}

describe("buildQuote", () => {
  it("compares fees + FX against SWIFT when the engine sends a cost breakdown", () => {
    const scores = [
      { routeId: "R1", s: 1834.4, excludedBy: null, name: "SWIFT correspondent", etaLabel: "1–3 days", etaMinutes: 2880, feesEur: 80, fxMarginEur: 1700, cashCostEur: 1780 },
      { routeId: "R3", s: 855.81, excludedBy: null, name: "Euro stablecoin on Avalanche", etaLabel: "≈ 2 h", etaMinutes: 120, feesEur: 170, fxMarginEur: 680, cashCostEur: 850 },
      { routeId: "R4", s: null, excludedBy: "GH_FX_EXPORT_PROCEEDS_NOMINATED_BANK", name: "Mobile wallet", cashCostEur: 2975 },
    ];
    const cost = { feesEur: 170, fxMarginEur: 680, timeCostEur: 1.56, failureCostEur: 4.25, cashCostEur: 850, totalCostEur: 855.81 };
    const state = [created, selected({ cost, etaMinutes: 120, recipientGetsGhs: 1391280, midRateEurGhs: 16.5 }, scores)].reduce(reduce, initialState);
    const quote = buildQuote(state)!;

    expect(quote.basis).toBe("cash");
    expect(quote.cost).toBe(850);
    expect(quote.costPct).toBe(1);
    expect(quote.swift?.cost).toBe(1780);
    expect(quote.savedEur).toBe(930);
    expect(quote.savedPct).toBeCloseTo(52.25, 2);
    expect(quote.recipientGetsGhs).toBe(1391280);
    expect(quote.rows.map((row) => row.routeId)).toEqual(["R3", "R1", "R4"]);
    expect(quote.rows[2].excluded).toBe(true);
  });

  it("falls back to the all-in score with older events", () => {
    const state = [created, selected({}, legacyScores)].reduce(reduce, initialState);
    const quote = buildQuote(state)!;

    expect(quote.basis).toBe("all-in");
    expect(quote.cost).toBe(179.21);
    expect(quote.savedEur).toBe(36.79);
  });

  it("has no SWIFT comparison when SWIFT itself is selected", () => {
    const state = [created, selected({ routeId: "R1", name: "SWIFT correspondent" }, legacyScores)].reduce(reduce, initialState);
    expect(buildQuote(state)?.swift).toBeUndefined();
  });

  it("measures the decision time from the event log", () => {
    expect(secondsBetween("2026-10-11T09:00:00.000Z", "2026-10-11T09:00:06.400Z")).toBe(6.4);
    expect(secondsBetween(undefined, "2026-10-11T09:00:06.400Z")).toBeUndefined();
  });
});
