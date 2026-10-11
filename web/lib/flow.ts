import type { ViewState } from "./store";

export type FlowNodeId =
  | "payment"
  | "norms"
  | "risk"
  | "sealDirect"
  | "settle"
  | "credited"
  | "sealEscrow"
  | "hold"
  | "supplier"
  | "stopped";

export type FlowStatus = "idle" | "running" | "waiting" | "done" | "warn" | "fail" | "skipped";
export type EdgeStatus = "idle" | "active" | "done" | "skipped";
export type EdgeTone = "ink" | "low" | "medium" | "danger";
export type Lane = "direct" | "escrow";

export interface FlowEdge {
  id: string;
  from: FlowNodeId;
  fromHandle: string;
  to: FlowNodeId;
  toHandle: string;
  tone: EdgeTone;
}

export const FLOW_EDGES: FlowEdge[] = [
  { id: "payment-norms", from: "payment", fromHandle: "bottom", to: "norms", toHandle: "top", tone: "ink" },
  { id: "norms-risk", from: "norms", fromHandle: "bottom", to: "risk", toHandle: "top", tone: "ink" },
  { id: "risk-direct", from: "risk", fromHandle: "low", to: "sealDirect", toHandle: "in", tone: "low" },
  { id: "risk-escrow", from: "risk", fromHandle: "high", to: "sealEscrow", toHandle: "in", tone: "medium" },
  { id: "direct-settle", from: "sealDirect", fromHandle: "out", to: "settle", toHandle: "in", tone: "ink" },
  { id: "settle-credited", from: "settle", fromHandle: "out", to: "credited", toHandle: "in", tone: "ink" },
  { id: "escrow-hold", from: "sealEscrow", fromHandle: "out", to: "hold", toHandle: "in", tone: "ink" },
  { id: "hold-supplier", from: "hold", fromHandle: "out", to: "supplier", toHandle: "in", tone: "ink" },
  { id: "supplier-credited", from: "supplier", fromHandle: "yes", to: "credited", toHandle: "in", tone: "low" },
  { id: "supplier-stopped", from: "supplier", fromHandle: "no", to: "stopped", toHandle: "in", tone: "danger" },
];

export function flowLane(state: ViewState): Lane | null {
  if (!state.risk) return null;
  return state.risk.tier === "LOW" ? "direct" : "escrow";
}

const REACHED: FlowStatus[] = ["done", "warn", "fail"];

export function flowStatuses(state: ViewState): Record<FlowNodeId, FlowStatus> {
  const lane = flowLane(state);
  const answer = state.verification.recorded?.result;
  const statuses: Record<FlowNodeId, FlowStatus> = {
    payment: "idle",
    norms: "idle",
    risk: "idle",
    sealDirect: "idle",
    settle: "idle",
    credited: "idle",
    sealEscrow: "idle",
    hold: "idle",
    supplier: "idle",
    stopped: "idle",
  };

  if (state.payment) statuses.payment = "done";
  if (state.routes.length) statuses.norms = "done";
  if (state.risk) statuses.risk = state.risk.tier === "LOW" ? "done" : "warn";
  if (state.payment?.intentHash) statuses[lane === "escrow" ? "sealEscrow" : "sealDirect"] = "done";
  const allSettled = state.hops.length > 0 && state.hops.every((hop) => hop.state === "settled");
  if (lane === "direct" && (allSettled || state.credited)) statuses.settle = "done";
  if (state.held) statuses.hold = "warn";
  if (answer) statuses.supplier = answer === "CONFIRMED" ? "done" : "fail";
  if (state.credited) statuses.credited = "done";
  if (state.stopped) statuses.stopped = "fail";

  const path: FlowNodeId[] = ["payment", "norms", "risk"];
  if (lane === "direct") path.push("sealDirect", "settle", "credited");
  if (lane === "escrow") {
    path.push("sealEscrow", "hold", "supplier");
    if (answer === "CONFIRMED") path.push("credited");
    if (answer === "DENIED") path.push("stopped");
  }

  const final = Boolean(state.credited || state.stopped);
  if (state.scenario && !final) {
    const next = path.find((id) => !REACHED.includes(statuses[id]));
    if (next) statuses[next] = next === "supplier" && state.payment?.status === "awaiting_supplier" ? "waiting" : "running";
  }

  const skip = (ids: FlowNodeId[]) => ids.forEach((id) => (statuses[id] = "skipped"));
  if (lane === "direct") skip(["sealEscrow", "hold", "supplier", "stopped"]);
  if (lane === "escrow") skip(["sealDirect", "settle"]);
  if (answer === "CONFIRMED") skip(["stopped"]);
  if (answer === "DENIED") skip(["credited"]);

  return statuses;
}

export function edgeStatus(edge: FlowEdge, statuses: Record<FlowNodeId, FlowStatus>): EdgeStatus {
  const from = statuses[edge.from];
  const to = statuses[edge.to];
  if (from === "skipped" || to === "skipped") return "skipped";
  if (REACHED.includes(to)) return "done";
  if ((to === "running" || to === "waiting") && REACHED.includes(from)) return "active";
  return "idle";
}

export type NarrationTone = "neutral" | "accent" | "low" | "medium" | "danger";

const formatEur = (value: string | number) =>
  `EUR ${Number(value).toLocaleString("en-US", { maximumFractionDigits: 2 })}`;

export function narrate(state: ViewState): { tone: NarrationTone; text: string } {
  const p = state.payment;
  const event = state.lastEvent;
  if (state.attack.reverted)
    return { tone: "low", text: `The attacker called release() on the revoked payment. The contract rejected it (${state.attack.reason}).` };
  if (state.attack.attempted) return { tone: "danger", text: "An attacker calls release() to push the revoked money to the mule account…" };
  if (state.stopped) return { tone: "danger", text: state.stopped.headline };
  if (state.credited)
    return {
      tone: "low",
      text: `Credited. €${state.credited.routeCostEur.toLocaleString("en-US")} all-in instead of €${state.credited.swiftRouteCostEur.toLocaleString("en-US")} via SWIFT.`,
    };
  if (!p || !event) return { tone: "neutral", text: "Pick a scenario below. Each node lights up as the engine emits its events." };

  switch (event.type) {
    case "scenario.started":
      return { tone: "accent", text: "A new payment request arrives…" };
    case "payment.created":
      return { tone: "accent", text: `${p.payerName} asks to pay ${formatEur(p.amount.value)} to ${p.payeeName}.` };
    case "norms.checked": {
      const allowed = state.routes.filter((route) => route.status === "PASS").length;
      return { tone: "accent", text: `Legal check: ${allowed} of ${state.routes.length} routes are allowed from France to Ghana.` };
    }
    case "risk.scored": {
      const risk = state.risk;
      if (!risk) break;
      return risk.tier === "LOW"
        ? { tone: "low", text: `Risk ${risk.score} · LOW. ${risk.reasons[0]?.text ?? ""} The payment can go directly.` }
        : { tone: "medium", text: `Risk ${risk.score} · ${risk.tier}. ${risk.reasons[0]?.text ?? ""} The money will wait in escrow.` };
    }
    case "route.selected":
      return { tone: "accent", text: `Cheapest legal route: ${p.routeId} · ${p.routeName}. Fraud risk never changes the price.` };
    case "approval.granted":
      return {
        tone: "accent",
        text: `${state.approval?.conditional ? "Conditional approval" : "Approved"} by ${state.approval?.by.map((who) => who.name).join(" and ")}.`,
      };
    case "intent.committed":
      return { tone: "accent", text: "Intent sealed on-chain (EIP-712) before any money moves." };
    case "leg.sent":
    case "leg.settled": {
      const settled = state.hops.filter((hop) => hop.state === "settled").length;
      return { tone: "accent", text: `Money moving along the signed route: ${settled} of ${state.hops.length} legs settled.` };
    }
    case "escrow.deposited":
      return { tone: "medium", text: "The funds enter the on-chain escrow instead of going to the new account." };
    case "payment.held":
      return { tone: "medium", text: `${state.held?.headline ?? "Payment held"}. Nobody can take the money out yet.` };
    case "verification.requested":
      return {
        tone: "medium",
        text: `Sylo asks ${state.verification.requested?.contactName} on the number known since ${state.verification.requested?.contactSince.slice(0, 4)}, not the one in the email.`,
      };
    case "verification.recorded":
      return {
        tone: state.verification.recorded?.result === "CONFIRMED" ? "low" : "danger",
        text: state.verification.recorded?.answerText ?? "",
      };
    case "intent.revoked":
      return { tone: "danger", text: "The intent is revoked on-chain. This payment can never be released." };
    case "escrow.refunded":
      return { tone: "danger", text: `The escrow refunds ${formatEur(p.amount.value)} to ${p.payerName}.` };
    case "escrow.released":
      return { tone: "low", text: "Supplier confirmed: the escrow releases the funds." };
    case "intent.executed":
      return { tone: "accent", text: "The sealed intent is executed on-chain." };
  }
  return { tone: "accent", text: "Engine working…" };
}
