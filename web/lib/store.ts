// Pure view state: events in, state out. The web app draws what the engine decided; nothing here
// approves, blocks or scores a payment.
import {
  isKnown,
  type ApprovalGranted,
  type Beneficiary,
  type EscrowDeposited,
  type EscrowMoved,
  type Hop,
  type IntentCommitted,
  type IntentRevoked,
  type NormsChecked,
  type NormsRoute,
  type PaymentCreated,
  type PaymentCredited,
  type PaymentHeld,
  type PaymentStopped,
  type RiskScored,
  type RouteSelected,
  type ScenarioStarted,
  type SyloEvent,
  type SystemMode,
  type Tier,
  type VerificationRecorded,
  type VerificationRequested,
} from "./events";
import { formatAmount, formatEur } from "./format";

export type PaymentStatus = "idle" | "deciding" | "in_transit" | "held" | "awaiting_supplier" | "stopped" | "credited";
export type HopState = "pending" | "active" | "settled" | "refunded";
export type LockState = "none" | "locked" | "revoked" | "open";
export type FeedFamily = "system" | "decision" | "leg" | "chain" | "alert" | "attack";

export interface HopView extends Hop {
  index: number;
  state: HopState;
  durationMs: number | null;
  /** seq of the event that gave the hop its current state. */
  since: number;
}

export interface PaymentView {
  id: string | null;
  scenario: ScenarioStarted["scenario"] | null;
  uetr: string | null;
  payer: PaymentCreated["payer"] | null;
  beneficiary: Beneficiary | null;
  amount: PaymentCreated["amount"] | null;
  invoiceRef: string | null;
  provenance: string | null;
  senderDomain: string | null;
  tier: Tier | null;
  score: number | null;
  status: PaymentStatus;
}

export interface FeedItem {
  seq: number;
  ts: string;
  type: string;
  family: FeedFamily;
  simulated: boolean;
  txHash: string | null;
  explorerUrl: string | null;
  event: SyloEvent;
}

export interface ChainView {
  intent: (IntentCommitted & { simulated: boolean }) | null;
  escrow: EscrowDeposited | null;
  lock: LockState;
  revocation: IntentRevoked | null;
  refund: EscrowMoved | null;
  release: EscrowMoved | null;
  executed: boolean;
}

export interface AttackView {
  attempted: boolean;
  description: string | null;
  reverted: boolean;
  reason: string | null;
  fn: string | null;
}

export interface ViewState {
  /** Increases whenever the view is reset, so the globe can drop its one-shot effects. */
  run: number;
  lastSeq: number;
  mode: SystemMode | null;
  scenario: ScenarioStarted | null;
  payment: PaymentView;
  routes: NormsRoute[];
  norms: Omit<NormsChecked, "routes"> | null;
  risk: RiskScored | null;
  selectedRouteId: string | null;
  selection: RouteSelected | null;
  approval: ApprovalGranted | null;
  hops: HopView[];
  held: (PaymentHeld & { seq: number }) | null;
  verification: { requested: VerificationRequested | null; recorded: VerificationRecorded | null };
  chain: ChainView;
  chainEvents: FeedItem[];
  attack: AttackView | null;
  stopped: PaymentStopped | null;
  credited: PaymentCredited | null;
  feed: FeedItem[];
}

const IDLE_PAYMENT: PaymentView = {
  id: null,
  scenario: null,
  uetr: null,
  payer: null,
  beneficiary: null,
  amount: null,
  invoiceRef: null,
  provenance: null,
  senderDomain: null,
  tier: null,
  score: null,
  status: "idle",
};

export function initialState(): ViewState {
  return {
    run: 0,
    lastSeq: 0,
    mode: null,
    scenario: null,
    payment: IDLE_PAYMENT,
    routes: [],
    norms: null,
    risk: null,
    selectedRouteId: null,
    selection: null,
    approval: null,
    hops: [],
    held: null,
    verification: { requested: null, recorded: null },
    chain: { intent: null, escrow: null, lock: "none", revocation: null, refund: null, release: null, executed: false },
    chainEvents: [],
    attack: null,
    stopped: null,
    credited: null,
    feed: [],
  };
}

/** A fresh view that keeps the engine mode (it describes the engine, not the payment). */
export function resetView(state: ViewState): ViewState {
  return { ...initialState(), mode: state.mode, run: state.run + 1 };
}

export function reduce(state: ViewState, event: SyloEvent): ViewState {
  switch (event.type) {
    case "system.mode": {
      const mode = event.data as SystemMode;
      // A new bootId means the engine restarted: the session the view shows no longer exists.
      const restarted = Boolean(state.mode?.bootId && mode.bootId && mode.bootId !== state.mode.bootId);
      return restarted ? { ...resetView(state), mode } : { ...state, mode };
    }
    case "session.reset":
      return { ...resetView(state), lastSeq: event.seq };
    case "scenario.started":
      return apply(resetView(state), event);
  }
  if (event.seq <= state.lastSeq) return state;
  return apply(state, event);
}

const FAMILIES: Record<string, FeedFamily> = {
  "scenario.started": "decision",
  "payment.created": "decision",
  "norms.checked": "decision",
  "risk.scored": "decision",
  "route.selected": "decision",
  "approval.granted": "decision",
  "leg.sent": "leg",
  "leg.settled": "leg",
  "payment.credited": "leg",
  "intent.committed": "chain",
  "escrow.deposited": "chain",
  "verification.recorded": "chain",
  "intent.revoked": "chain",
  "escrow.refunded": "chain",
  "escrow.released": "chain",
  "intent.executed": "chain",
  "payment.held": "alert",
  "verification.requested": "alert",
  "payment.stopped": "alert",
  "attack.attempted": "attack",
  "tx.reverted": "attack",
};

function toFeedItem(event: SyloEvent): FeedItem {
  const data = (event.data ?? {}) as Record<string, unknown>;
  return {
    seq: event.seq,
    ts: event.ts,
    type: event.type,
    family: FAMILIES[event.type] ?? "system",
    simulated: event.simulated,
    txHash: typeof data.txHash === "string" ? data.txHash : null,
    explorerUrl: typeof data.explorerUrl === "string" ? data.explorerUrl : null,
    event,
  };
}

function patchHop(hops: HopView[], index: number, patch: Partial<HopView> & { since: number }, hop?: Hop): HopView[] {
  if (hops.some((h) => h.index === index)) {
    return hops.map((h) => (h.index === index ? { ...h, ...patch } : h));
  }
  if (!hop) return hops;
  const created: HopView = { ...hop, index, state: "pending", durationMs: null, ...patch };
  return [...hops, created].sort((a, b) => a.index - b.index);
}

function apply(state: ViewState, event: SyloEvent): ViewState {
  const item = toFeedItem(event);
  const next: ViewState = { ...state, lastSeq: event.seq, feed: [...state.feed, item] };
  if (item.family === "chain" || event.type === "tx.reverted") next.chainEvents = [...state.chainEvents, item];
  if (!isKnown(event)) return next;

  switch (event.type) {
    case "scenario.started":
      return {
        ...next,
        scenario: event.data,
        payment: { ...next.payment, id: event.paymentId, scenario: event.data.scenario, status: "deciding" },
      };
    case "payment.created": {
      const d = event.data;
      return {
        ...next,
        payment: {
          ...next.payment,
          id: event.paymentId ?? next.payment.id,
          uetr: d.uetr,
          payer: d.payer,
          beneficiary: d.beneficiary,
          amount: d.amount,
          invoiceRef: d.invoiceRef,
          provenance: d.provenance,
          senderDomain: d.senderDomain ?? null,
          status: "deciding",
        },
      };
    }
    case "norms.checked": {
      const { routes, ...rest } = event.data;
      return { ...next, routes, norms: rest };
    }
    case "risk.scored":
      return { ...next, risk: event.data, payment: { ...next.payment, tier: event.data.tier, score: event.data.score } };
    case "route.selected": {
      const d = event.data;
      const hops = d.hops ?? next.routes.find((r) => r.routeId === d.routeId)?.hops ?? [];
      return {
        ...next,
        selectedRouteId: d.routeId,
        selection: d,
        hops: hops.map((h, index) => ({ ...h, index, state: "pending", durationMs: null, since: event.seq })),
        payment: { ...next.payment, tier: d.tier },
      };
    }
    case "approval.granted":
      return { ...next, approval: event.data };
    case "intent.committed":
      return { ...next, chain: { ...next.chain, intent: { ...event.data, simulated: event.simulated } } };
    case "leg.sent": {
      const d = event.data;
      return {
        ...next,
        hops: patchHop(
          next.hops,
          d.hop,
          { state: "active", durationMs: d.durationMs, since: event.seq },
          { from: d.from, to: d.to, kind: d.kind },
        ),
        payment: { ...next.payment, status: "in_transit" },
      };
    }
    case "leg.settled":
      return { ...next, hops: patchHop(next.hops, event.data.hop, { state: "settled", since: event.seq }) };
    case "escrow.deposited":
      return { ...next, chain: { ...next.chain, escrow: event.data, lock: "locked" } };
    case "payment.held":
      return {
        ...next,
        held: { ...event.data, seq: event.seq },
        payment: { ...next.payment, tier: event.data.tier, status: "held" },
      };
    case "verification.requested":
      return {
        ...next,
        verification: { ...next.verification, requested: event.data },
        payment: { ...next.payment, status: "awaiting_supplier" },
      };
    case "verification.recorded":
      return {
        ...next,
        verification: { ...next.verification, recorded: event.data },
        payment: { ...next.payment, status: "held" },
      };
    case "intent.revoked":
      return { ...next, chain: { ...next.chain, lock: "revoked", revocation: event.data } };
    case "escrow.refunded": {
      const heldHop = next.held?.hop ?? Math.max(-1, ...next.hops.filter((h) => h.state !== "pending").map((h) => h.index));
      return {
        ...next,
        chain: { ...next.chain, refund: event.data },
        hops: next.hops.map((h) => (h.index <= heldHop ? { ...h, state: "refunded", since: event.seq } : h)),
      };
    }
    case "escrow.released":
      return {
        ...next,
        chain: { ...next.chain, lock: "open", release: event.data },
        hops: next.held ? patchHop(next.hops, next.held.hop, { state: "active", since: event.seq }) : next.hops,
        payment: { ...next.payment, status: "in_transit" },
      };
    case "intent.executed":
      return { ...next, chain: { ...next.chain, executed: true } };
    case "payment.credited":
      return {
        ...next,
        credited: event.data,
        hops: next.hops.map((h) =>
          h.state === "refunded" || h.state === "settled" ? h : { ...h, state: "settled", since: event.seq },
        ),
        payment: { ...next.payment, status: "credited" },
      };
    case "payment.stopped":
      return { ...next, stopped: event.data, payment: { ...next.payment, status: "stopped" } };
    case "attack.attempted":
      return {
        ...next,
        attack: { attempted: true, description: event.data.description, reverted: false, reason: null, fn: null },
      };
    case "tx.reverted":
      return {
        ...next,
        attack: {
          ...(next.attack ?? { attempted: false, description: null }),
          reverted: true,
          reason: event.data.reason,
          fn: event.data.function,
        },
      };
    default:
      return next;
  }
}

/** One line of plain English per event: the feed must tell the story without the globe. */
export function describeEvent(event: SyloEvent, names: Record<string, string> = {}): string {
  const n = (id: string) => names[id] ?? id;
  if (!isKnown(event)) return `Event ${event.type} (not displayed by this version)`;
  switch (event.type) {
    case "session.reset":
      return "Session reset";
    case "system.mode": {
      const d = event.data;
      return `Engine mode: risk ${d.risk}, chain ${d.chain === "fuji" ? "Avalanche Fuji" : "simulated"}`;
    }
    case "scenario.started":
      return `Scenario started: ${event.data.scenario === "legit" ? "legit payment" : "diverted invoice"} at ${event.data.speed}×`;
    case "payment.created": {
      const d = event.data;
      const line = `${event.paymentId}: ${formatAmount(d.amount.value, d.amount.currency)} from ${d.payer.name} to ${d.beneficiary.payeeName}`;
      return d.beneficiary.knownAccount ? line : `${line}, new account ${d.beneficiary.accountHolder}`;
    }
    case "norms.checked": {
      const d = event.data;
      const allowed = d.routes.filter((r) => r.status === "PASS").length;
      const excluded = d.routes.filter((r) => r.status === "EXCLUDED");
      const tail = excluded.length
        ? `; ${excluded.map((r) => r.routeId).join(", ")} excluded by ${excluded[0].excludedBy}`
        : "";
      return `Corridor rules ${d.packVersion}: ${allowed} routes allowed${tail}`;
    }
    case "risk.scored": {
      const d = event.data;
      const fired = d.rulesFired.length ? `rules ${d.rulesFired.join(", ")}` : "no rule fired";
      return `Fraud risk ${d.score}/100, ${d.tier}: ${fired}`;
    }
    case "route.selected": {
      const d = event.data;
      const escrow = d.settlement === "ONCHAIN_ESCROW" ? ", escrow on Avalanche" : "";
      return `Route ${d.routeId} selected: ${d.name}, fees ${formatEur(d.feesEur)}, ETA ${d.etaLabel}${escrow}`;
    }
    case "approval.granted": {
      const d = event.data;
      return `Approved by ${d.by.map((p) => p.name).join(" and ")}${d.conditional ? ", conditional on the escrow" : ""}`;
    }
    case "intent.committed":
      return `Signed payment sealed on Avalanche, tier ${event.data.tier}`;
    case "leg.sent": {
      const d = event.data;
      return `Leg ${d.hop + 1} sent: ${n(d.from)} → ${n(d.to)}${d.kind === "chain" ? " on Avalanche C-Chain" : ""}`;
    }
    case "leg.settled":
      return `Leg ${event.data.hop + 1} settled at ${n(event.data.at)}`;
    case "escrow.deposited":
      return `${formatAmount(event.data.amount, event.data.token)} locked in the escrow contract`;
    case "payment.held":
      return event.data.headline;
    case "verification.requested": {
      const d = event.data;
      return `SMS check sent to ${d.contactName} (${d.contactMasked}), ${d.simSwapRecent ? "recent SIM swap detected" : "no recent SIM swap"}`;
    }
    case "verification.recorded":
      return `Supplier ${event.data.result === "DENIED" ? "denied" : "confirmed"}: ${event.data.answerText}`;
    case "intent.revoked":
      return `Signed payment revoked on-chain (${event.data.reasonCode})`;
    case "escrow.refunded":
      return `${formatAmount(event.data.amount, "EUR")} refunded from escrow to ${n(event.data.to)}`;
    case "escrow.released":
      return `${formatAmount(event.data.amount, "EUR")} released from escrow to ${n(event.data.to)}`;
    case "intent.executed":
      return "Signed payment executed on-chain";
    case "payment.credited": {
      const d = event.data;
      return `Credited at ${n(d.at)}: ${formatEur(d.routeCostEur)} all-in against ${formatEur(d.swiftRouteCostEur)} via SWIFT`;
    }
    case "payment.stopped":
      return event.data.headline;
    case "attack.attempted":
      return event.data.description;
    case "tx.reverted":
      return `${event.data.function}() rejected by the smart contract: ${event.data.reason}`;
  }
}

const IN_FLIGHT: readonly PaymentStatus[] = ["deciding", "in_transit", "held", "awaiting_supplier"];

export const canRunScenario = (state: ViewState) => !IN_FLIGHT.includes(state.payment.status);
export const canAnswerSupplier = (state: ViewState) => state.payment.status === "awaiting_supplier";
export const canAttack = (state: ViewState) =>
  state.payment.status === "stopped" && state.chain.lock === "revoked" && !state.attack?.attempted;
