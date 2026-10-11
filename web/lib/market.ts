/**
 * Real public quotes for EUR -> GHS, captured once and frozen for the demo (not live, not simulated).
 * Cost = fixedFeeEur + variablePct * amount, where variablePct includes the FX margin over mid-market.
 */
export interface MarketQuote {
  id: string;
  name: string;
  kind: string;
  fixedFeeEur: number;
  variablePct: number;
  eta: string;
  note?: string;
  maxRecipientGhs?: number;
  source: string;
  capturedAt: string;
}

export const MARKET_MID_RATE_EUR_GHS = 13.1886;
export const MARKET_CAPTURED_ON = "2026-10-11";

export const MARKET_QUOTES: MarketQuote[] = [
  {
    id: "wise",
    name: "Wise",
    kind: "Main competitor",
    fixedFeeEur: 0,
    variablePct: 915.67 / 85000,
    eta: "seconds to 1 business day (Wise claim)",
    maxRecipientGhs: 140000,
    source: "wise.com public price API, bank transfer to bank account",
    capturedAt: "2026-10-11T07:37Z",
  },
  {
    id: "bank",
    name: "BNP Paribas",
    kind: "Bank · SWIFT",
    fixedFeeEur: 0,
    variablePct: 0.0287132169,
    eta: "1–3 days (estimate, not in the quote)",
    source: "Wise comparison data (api.wise.com/v4/comparisons)",
    capturedAt: "2026-10-09T18:10Z",
  },
  {
    id: "wu",
    name: "Western Union",
    kind: "Money transfer",
    fixedFeeEur: 2.99,
    variablePct: 0.0095317885,
    eta: "not in the quote",
    note: "limit for €85k not verified",
    source: "Wise comparison data (api.wise.com/v4/comparisons)",
    capturedAt: "2026-10-05T10:34Z",
  },
];

export interface MarketRow {
  quote: MarketQuote;
  costEur: number;
  costPct: number;
  transfers: number;
}

export function marketRows(amountEur: number): MarketRow[] {
  return MARKET_QUOTES.map((quote) => {
    const costEur = Math.round((quote.fixedFeeEur + quote.variablePct * amountEur) * 100) / 100;
    const receivedGhs = (amountEur - costEur) * MARKET_MID_RATE_EUR_GHS;
    return {
      quote,
      costEur,
      costPct: amountEur ? (costEur / amountEur) * 100 : 0,
      transfers: quote.maxRecipientGhs ? Math.max(1, Math.ceil(receivedGhs / quote.maxRecipientGhs)) : 1,
    };
  });
}
