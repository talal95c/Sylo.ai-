import { engineUrl } from "./engine";

export interface IntakeField {
  value: string | null;
  provenance: string;
  confidence: number;
  conflict: boolean;
}

export interface IntakeDecision {
  routes: { routeId: string; name: string; status: "PASS" | "EXCLUDED" }[];
  normChecks: { routeId: string; ruleId: string; result: string }[];
  risk: {
    score: number;
    tier: string;
    topReasons: { text: string }[];
  };
  route: {
    chosen: string | null;
    feesEur: number;
    etaLabel: string | null;
    settlement: string | null;
    blockedBy: string | null;
  };
  approval?: { conditional: boolean };
}

export interface IntakeResponse {
  intake: {
    fields: Record<string, IntakeField>;
    senderDomain: IntakeField;
    changedDetails: boolean;
    lookalikeDomain: string | null;
    urgencyCues: string[];
    instructionLikeLines: number;
    needsHuman: boolean;
    truncated: boolean;
  };
  matchedOrder: string | null;
  decision: IntakeDecision | null;
}

export type QuoteOrder = "legit" | "diverted";

export interface IntakePipelineStep {
  title: string;
  detail: string;
  state: "done" | "idle";
}

export function orderForMatchedPayment(paymentId: string | null): QuoteOrder | null {
  if (paymentId === "PAY-2026-0001") return "legit";
  if (paymentId === "PAY-2026-0002") return "diverted";
  return null;
}

export function mapIntakePipeline(response: IntakeResponse): IntakePipelineStep[] {
  const decision = response.decision;
  const commit = {
    title: "Commit",
    detail: "Not yet: nothing is committed until you execute.",
    state: "idle" as const,
  };
  if (!response.matchedOrder || !decision) {
    return [
      { title: "Norms", detail: "No recorded order to check against the rule pack.", state: "done" },
      { title: "Risk", detail: "No risk score was computed for this document.", state: "idle" },
      { title: "Route & cost", detail: "No payment route was selected.", state: "idle" },
      commit,
    ];
  }

  const passed = decision.routes.filter((route) => route.status === "PASS").length;
  const excluded = decision.routes.filter((route) => route.status === "EXCLUDED").length;
  const riskReasons = decision.risk.topReasons
    .slice(0, 3)
    .map((reason) => reason.text)
    .join(" · ");
  const selectedRoute = decision.routes.find(
    (route) => route.routeId === decision.route.chosen,
  );
  const settlement = [
    decision.approval?.conditional ? "conditional" : undefined,
    decision.route.settlement === "ONCHAIN_ESCROW" ? "escrow" : undefined,
  ]
    .filter(Boolean)
    .join(" · ");
  const routeDetails = [
    selectedRoute
      ? `${selectedRoute.routeId} · ${selectedRoute.name}`
      : decision.route.chosen,
    `€${decision.route.feesEur} fees`,
    decision.route.etaLabel,
    settlement || undefined,
  ]
    .filter(Boolean)
    .join(" · ");

  return [
    {
      title: "Norms",
      detail: `${passed} routes passed · ${excluded} excluded across ${decision.normChecks.length} rule checks.`,
      state: "done",
    },
    {
      title: "Risk",
      detail: `${decision.risk.tier} · ${decision.risk.score}/100${riskReasons ? ` · ${riskReasons}` : ""}`,
      state: "done",
    },
    { title: "Route & cost", detail: routeDetails, state: "done" },
    commit,
  ];
}

function responseDetail(payload: unknown): string | undefined {
  if (typeof payload !== "object" || payload === null || !("detail" in payload)) {
    return undefined;
  }
  const detail = payload.detail;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const first = detail[0];
    if (
      typeof first === "object" &&
      first !== null &&
      "msg" in first &&
      typeof first.msg === "string" &&
      first.msg.trim()
    ) {
      return first.msg;
    }
  }
  return undefined;
}

async function request<T>(pathname: string, body: Record<string, unknown>): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${engineUrl.replace(/\/$/, "")}${pathname}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch (error) {
    if (error instanceof TypeError) {
      throw new Error(
        "Engine unreachable: check the connection or switch to Replay",
      );
    }
    throw error;
  }
  if (!response.ok) {
    let detail: string | undefined;
    try {
      detail = responseDetail(await response.json());
    } catch {
      detail = undefined;
    }
    throw new Error(
      detail ? `Engine refused: ${detail}` : `Engine refused (${response.status})`,
    );
  }
  return (await response.json()) as T;
}

export function submitIntake(text: string): Promise<IntakeResponse> {
  return request("/v1/intake", { text });
}

export function requestQuote(order: QuoteOrder): Promise<{ quoteId: string }> {
  return request("/v1/quotes", { order });
}

export function executeQuote(quoteId: string): Promise<{ paymentId: string }> {
  return request("/v1/payments", { quoteId });
}
