import type { RouteScore } from "./events";
import type { ViewState } from "./store";

export interface QuoteRow extends RouteScore {
  chosen: boolean;
  excluded: boolean;
  cost?: number;
}

export interface QuoteView {
  amountEur: number;
  routeId: string;
  routeName: string;
  etaLabel: string;
  etaMinutes?: number;
  feesEur: number;
  fxMarginEur?: number;
  cost: number;
  costPct: number;
  basis: "cash" | "all-in";
  totalCostEur?: number;
  recipientGetsGhs?: number;
  midRateEurGhs?: number;
  priceOfSafetyEur: number;
  swift?: { cost: number; etaLabel?: string; etaMinutes?: number; totalCostEur?: number; recipientGetsGhs?: number };
  savedEur?: number;
  savedPct?: number;
  rows: QuoteRow[];
}

export function buildQuote(state: ViewState): QuoteView | null {
  const quote = state.quote;
  const payment = state.payment;
  if (!quote || !payment) return null;
  const amountEur = Number(payment.amount.value) || 0;
  const scores = quote.scores ?? [];
  const own = scores.find((score) => score.routeId === quote.routeId);
  const swiftScore = scores.find((score) => score.routeId === "R1");
  const basis = quote.cost?.cashCostEur !== undefined ? "cash" : "all-in";
  const costOf = (score?: RouteScore) => (basis === "cash" ? score?.cashCostEur : score?.s ?? undefined);
  const cost = basis === "cash" ? quote.cost!.cashCostEur : own?.s ?? quote.feesEur;
  const swiftCost = quote.routeId === "R1" ? undefined : costOf(swiftScore);
  const savedEur = swiftCost !== undefined ? round2(swiftCost - cost) : undefined;

  const rows: QuoteRow[] = scores.map((score) => ({
    ...score,
    name: score.name ?? state.routes.find((route) => route.routeId === score.routeId)?.name ?? score.routeId,
    chosen: score.routeId === quote.routeId,
    excluded: score.s === null || Boolean(score.excludedBy),
    cost: costOf(score),
  }));
  const rank = (row: QuoteRow) => (row.chosen ? -1 : row.excluded ? 1e12 + (row.cost ?? 0) : row.cost ?? 1e11);
  rows.sort((a, b) => rank(a) - rank(b));

  return {
    amountEur,
    routeId: quote.routeId,
    routeName: quote.name,
    etaLabel: quote.etaLabel,
    etaMinutes: quote.etaMinutes,
    feesEur: quote.feesEur,
    fxMarginEur: quote.cost?.fxMarginEur,
    cost,
    costPct: amountEur ? (cost / amountEur) * 100 : 0,
    basis,
    totalCostEur: quote.cost?.totalCostEur ?? own?.s ?? undefined,
    recipientGetsGhs: quote.recipientGetsGhs,
    midRateEurGhs: quote.midRateEurGhs,
    priceOfSafetyEur: quote.priceOfSafetyEur ?? 0,
    swift:
      swiftCost !== undefined
        ? {
            cost: swiftCost,
            etaLabel: swiftScore?.etaLabel,
            etaMinutes: swiftScore?.etaMinutes,
            totalCostEur: swiftScore?.s ?? undefined,
            recipientGetsGhs: swiftScore?.recipientGetsGhs,
          }
        : undefined,
    savedEur,
    savedPct: savedEur !== undefined && swiftCost ? (savedEur / swiftCost) * 100 : undefined,
    rows,
  };
}

/** Seconds between two event timestamps of the log (demo pacing included). */
export function secondsBetween(from?: string, to?: string) {
  if (!from || !to) return undefined;
  const ms = Date.parse(to) - Date.parse(from);
  return Number.isFinite(ms) && ms >= 0 ? ms / 1000 : undefined;
}

export function cedis(value: number) {
  return `GH₵${value.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
}

export function pct(value: number) {
  return `${value.toLocaleString("en-US", { maximumFractionDigits: value < 10 ? 2 : 0 })} %`;
}

export function etaShare(minutes: number | undefined, slowest: number | undefined) {
  if (!minutes || !slowest) return 0;
  return Math.max(0.04, Math.log10(1 + minutes) / Math.log10(1 + slowest));
}

function round2(value: number) {
  return Math.round(value * 100) / 100;
}
