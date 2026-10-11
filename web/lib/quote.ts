import type { HopKind, Tier } from "./events";
import { engineUrl } from "./engine";
import diverted from "../samples/quotes/diverted.json";
import legit from "../samples/quotes/legit.json";

export type OrderName = "legit" | "diverted";

export interface QuoteRoute {
  routeId: string;
  name: string;
  settlement: string;
  hops: { from: string; to: string; kind: HopKind }[];
  status: string;
  excludedBy?: string | null;
  reason?: string;
}

export interface Quote {
  quoteId?: string;
  executable: boolean;
  paymentId: string;
  currency: string;
  routes: QuoteRoute[];
  route: {
    chosen: string | null;
    settlement: string;
    reason: string;
    feesEur: number | null;
    etaLabel: string | null;
    priceOfSafetyEur: number | null;
    blockedBy: string | null;
    candidates: { routeId: string; s: number | null; excludedBy: string | null }[];
  };
  risk: { score: number; tier: Tier; topReasons: { ref: string; text: string }[] };
  rails: { routeId: string; feesEur: number; etaLabel: string; available: boolean; simulated: boolean }[];
  approval: { required: { id: string; name: string; role: string }[]; method: string; conditional: boolean };
  /** True when the engine was unreachable and this is the quote recorded from it. */
  recorded?: boolean;
}

const RECORDED: Record<OrderName, Quote> = {
  legit: legit as Quote,
  diverted: diverted as Quote,
};

export const INVOICE_AMOUNT = 85000;

export function liveEngineEnabled() {
  return process.env.NEXT_PUBLIC_SOURCE !== "replay";
}

async function call<T>(pathname: string, body: unknown, headers: Record<string, string> = {}): Promise<T> {
  const response = await fetch(`${engineUrl.replace(/\/$/, "")}${pathname}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...headers },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new EngineError(response.status, typeof detail?.detail === "string" ? detail.detail : null);
  }
  return (await response.json()) as T;
}

export class EngineError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string | null,
  ) {
    super(detail ?? `Engine request failed (${status})`);
  }
}

/** The engine's decision for one of the recorded orders; falls back to the recorded quote offline. */
export async function fetchQuote(order: OrderName, amount: number, signal?: AbortSignal): Promise<Quote> {
  const custom = amount !== INVOICE_AMOUNT;
  if (!liveEngineEnabled()) {
    if (custom) throw new EngineError(0, null);
    return { ...RECORDED[order], recorded: true };
  }
  try {
    const body = custom ? { order, amount: amount.toFixed(2) } : { order };
    return await Promise.race([
      call<Quote>("/v1/quotes", body),
      new Promise<never>((_, reject) => {
        const timer = setTimeout(() => reject(new EngineError(0, null)), 4000);
        signal?.addEventListener("abort", () => clearTimeout(timer));
      }),
    ]);
  } catch (error) {
    if (error instanceof EngineError && error.status !== 0) throw error;
    if (custom) throw new EngineError(0, null);
    return { ...RECORDED[order], recorded: true };
  }
}

export function submitPayment(quoteId: string) {
  return call<{ paymentId: string }>("/v1/payments", { quoteId }, { "Idempotency-Key": `web-${quoteId}` });
}
