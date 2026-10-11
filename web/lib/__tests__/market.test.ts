import { describe, expect, it } from "vitest";
import { marketRows } from "../market";

describe("marketRows", () => {
  it("reproduces the captured €85,000 quotes", () => {
    const rows = Object.fromEntries(marketRows(85000).map((row) => [row.quote.id, row]));
    expect(rows.wise.costEur).toBe(915.67);
    expect(rows.wise.transfers).toBe(8);
    expect(rows.bank.costEur).toBe(2440.62);
    expect(rows.wu.costEur).toBe(813.19);
  });

  it("needs a single Wise transfer under the GHS cap", () => {
    expect(marketRows(5000).find((row) => row.quote.id === "wise")?.transfers).toBe(1);
  });
});
