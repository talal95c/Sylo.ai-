export type OrderId = "legit" | "diverted" | "lagos-accra";

export interface OrderDetails {
  id: OrderId;
  title: string;
  badge?: string;
  globe: boolean;
  executable: boolean;
  payer: { name: string; city: string; country: string };
  beneficiary: {
    name: string;
    city: string;
    country: string;
    accountHolder: string;
    account: string;
  };
  amount: { value: string; currency: string };
  invoiceRef: string;
  corridor: string;
}

// The three recorded orders. Values come from spec/fixtures/scene1-legit.jsonl,
// spec/fixtures/scene2-diverted.jsonl (payment.created) and
// engine/packs/NG-GH.yaml (demo block), with cities from
// spec/geo/institutions.json.
export const ORDERS: OrderDetails[] = [
  {
    id: "legit",
    title: "France → Ghana · verified details",
    globe: true,
    executable: true,
    payer: { name: "Rhône Cosmétiques SAS", city: "Lyon", country: "FR" },
    beneficiary: {
      name: "Savanna Shea Exports Ltd",
      city: "Tamale",
      country: "GH",
      accountHolder: "SAVANNA SHEA EXPORTS LTD",
      account: "GH•• •••• 2207",
    },
    amount: { value: "85000.00", currency: "EUR" },
    invoiceRef: "SSE-2026-118",
    corridor: "FR → GH",
  },
  {
    id: "diverted",
    title: "France → Ghana · bank details changed by email",
    globe: true,
    executable: true,
    payer: { name: "Rhône Cosmétiques SAS", city: "Lyon", country: "FR" },
    beneficiary: {
      name: "Savanna Shea Exports Ltd",
      city: "Tamale",
      country: "GH",
      accountHolder: "K. MENSAH VENTURES",
      account: "GH•• •••• 9083",
    },
    amount: { value: "85000.00", currency: "EUR" },
    invoiceRef: "SSE-2026-118",
    corridor: "FR → GH",
  },
  {
    id: "lagos-accra",
    title: "Nigeria → Ghana · quote only",
    badge: "Not drawn on the globe yet",
    globe: false,
    executable: false,
    payer: { name: "Lekki Foods Ltd", city: "Lagos", country: "NG" },
    beneficiary: {
      name: "Savanna Shea Exports Ltd",
      city: "Tamale",
      country: "GH",
      accountHolder: "SAVANNA SHEA EXPORTS LTD",
      account: "acc-ssx-nominated",
    },
    amount: { value: "25000.00", currency: "USD" },
    invoiceRef: "SSE-2026-131",
    corridor: "NG → GH",
  },
];

export interface QuoteDecision {
  paymentId?: string;
  corridor?: string;
  currency?: string;
  packVersion?: string;
  normChecks?: { routeId: string; ruleId: string; result: string; legalRef?: string }[];
  risk?: {
    score: number;
    tier: string;
    rulesFired?: unknown[];
    topReasons?: ({ text?: string } | string)[];
    oobResolvable?: boolean;
  };
  route?: {
    chosen?: string | null;
    candidates?: { routeId: string; s: number | null; excludedBy?: string | null }[];
    feesEur?: number;
    etaLabel?: string;
    priceOfSafetyEur?: number;
    blockedBy?: string | null;
    reason?: string;
  };
  quoteId?: string;
  validUntil?: string;
  executable?: boolean;
}

export interface StepSummary {
  title: string;
  detail: string;
}

function firstReason(reasons?: ({ text?: string } | string)[]) {
  const first = reasons?.[0];
  return typeof first === "string" ? first : first?.text;
}

// The four check summaries the /test pipeline shows, built from the decision
// the engine returned. Pure: never invents content the engine did not send.
export function summarizeQuote(decision: QuoteDecision): StepSummary[] {
  const checks = decision.normChecks ?? [];
  const passed = checks.filter((check) => check.result === "PASS").length;
  const failed = checks.length - passed;
  const pack = decision.corridor ?? decision.packVersion ?? "norms pack";

  const risk = decision.risk;
  const riskDetail = risk
    ? `${risk.tier} · score ${risk.score}${firstReason(risk.topReasons) ? ` · ${firstReason(risk.topReasons)}` : ""}`
    : "No risk data in the decision";

  const route = decision.route;
  const excludedCount = (route?.candidates ?? []).filter(
    (candidate) => candidate.excludedBy || candidate.s === null,
  ).length;
  const routeDetail = route?.chosen
    ? `${route.chosen}${typeof route.feesEur === "number" ? ` · €${route.feesEur.toFixed(2)} fees` : ""}${route.etaLabel ? ` · ${route.etaLabel}` : ""}${excludedCount ? ` · ${excludedCount} excluded` : ""}`
    : route?.blockedBy
      ? `No compliant route · ${route.blockedBy}`
      : "No route in the decision";

  const commitDetail = decision.executable
    ? "Sealed on run"
    : "Quote only";

  return [
    { title: "Norms", detail: checks.length ? `${passed} pass · ${failed} fail · ${pack}` : `No checks returned · ${pack}` },
    { title: "Risk", detail: riskDetail },
    { title: "Route & cost", detail: routeDetail },
    { title: "Commit", detail: commitDetail },
  ];
}
