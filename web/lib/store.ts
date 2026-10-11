import type {
  ApprovalGrantedData,
  NormsRoute,
  RouteSelectedData,
  PaymentCreditedData,
  PaymentHeldData,
  PaymentStoppedData,
  SyloEvent,
  Tier,
  VerificationRecordedData,
  VerificationRequestedData,
  SystemModeData,
} from "./events";
import { describe } from "./feed";

export type PaymentStatus =
  | "idle"
  | "deciding"
  | "in_transit"
  | "held"
  | "awaiting_supplier"
  | "stopped"
  | "credited";
export type HopState = "pending" | "active" | "settled" | "refunded";

export interface HopView {
  index: number;
  from: string;
  to: string;
  kind: "bank" | "chain" | "wallet";
  state: HopState;
  durationMs?: number;
}

export interface FeedItem {
  seq: number;
  ts: string;
  type: string;
  family: "decision" | "leg" | "chain" | "alert" | "attack" | "system";
  text: string;
  simulated: boolean;
  txHash?: string;
  explorerUrl?: string | null;
}

export interface ViewState {
  mode: SystemModeData | null;
  lastSeq: number;
  scenario: "legit" | "diverted" | null;
  lastEvent: SyloEvent | null;
  payment: null | {
    paymentId: string;
    payerName: string;
    payeeName: string;
    accountHolder: string;
    knownAccount: boolean;
    amount: { value: string; currency: string };
    status: PaymentStatus;
    tier?: Tier;
    score?: number;
    routeId?: string;
    routeName?: string;
    feesEur?: number;
    etaLabel?: string;
    routeReason?: string;
    routeCostEur?: number;
    intentHash?: string;
    intentTxHash?: string;
    intentSimulated?: boolean;
  };
  risk: null | {
    score: number;
    tier: Tier;
    reasons: { ref: string; text: string }[];
    rulesFired: string[];
  };
  routes: NormsRoute[];
  selectedRouteId: string | null;
  routeScores: RouteSelectedData["scores"];
  approval: ApprovalGrantedData | null;
  hops: HopView[];
  held: PaymentHeldData | null;
  alertOpen: boolean;
  verification: {
    requested?: VerificationRequestedData;
    recorded?: VerificationRecordedData;
  };
  revoked: boolean;
  refunded: boolean;
  released: boolean;
  attack: { attempted: boolean; reverted: boolean; reason: string | null };
  credited: PaymentCreditedData | null;
  stopped: PaymentStoppedData | null;
  feed: FeedItem[];
}

export const initialState: ViewState = {
  mode: null,
  lastSeq: 0,
  scenario: null,
  lastEvent: null,
  payment: null,
  risk: null,
  routes: [],
  selectedRouteId: null,
  routeScores: [],
  approval: null,
  hops: [],
  held: null,
  alertOpen: false,
  verification: {},
  revoked: false,
  refunded: false,
  released: false,
  attack: { attempted: false, reverted: false, reason: null },
  credited: null,
  stopped: null,
  feed: [],
};

function eventData(event: SyloEvent): Record<string, unknown> {
  return event.data as Record<string, unknown>;
}

function feedItem(event: SyloEvent): FeedItem {
  return {
    seq: event.seq,
    ts: event.ts,
    simulated: event.simulated,
    ...describe(event),
  };
}

function paymentWithStatus(
  payment: ViewState["payment"],
  status: PaymentStatus,
): ViewState["payment"] {
  return payment ? { ...payment, status } : null;
}

function selectedHops(routes: NormsRoute[], routeId: string): HopView[] {
  const route = routes.find((candidate) => candidate.routeId === routeId);
  return (
    route?.hops.map((hop, index) => ({
      index,
      from: hop.from,
      to: hop.to,
      kind: hop.kind,
      state: "pending",
    })) ?? []
  );
}

export function reduce(state: ViewState, event: SyloEvent): ViewState {
  if (event.type !== "system.mode" && event.seq <= state.lastSeq) {
    return state;
  }

  const isReset = event.type === "session.reset" || event.type === "scenario.started";
  const base = isReset ? { ...initialState, mode: state.mode } : state;
  const next: ViewState = {
    ...base,
    lastSeq: event.type === "system.mode" ? state.lastSeq : event.seq,
    lastEvent: event,
    feed: [...base.feed, feedItem(event)],
  };
  const data = eventData(event);

  switch (event.type) {
    case "system.mode":
      return { ...next, mode: data as unknown as SystemModeData };
    case "session.reset":
      return { ...next, feed: [] };
    case "scenario.started":
      return {
        ...next,
        scenario: data.scenario === "diverted" ? "diverted" : "legit",
      };
    case "payment.created": {
      const payer = data.payer as Record<string, unknown>;
      const beneficiary = data.beneficiary as Record<string, unknown>;
      const amount = data.amount as Record<string, unknown>;
      return {
        ...next,
        payment: {
          paymentId: event.paymentId ?? "",
          payerName: String(payer.name ?? ""),
          payeeName: String(beneficiary.payeeName ?? ""),
          accountHolder: String(beneficiary.accountHolder ?? ""),
          knownAccount: Boolean(beneficiary.knownAccount),
          amount: {
            value: String(amount.value ?? ""),
            currency: String(amount.currency ?? ""),
          },
          status: "deciding",
        },
      };
    }
    case "norms.checked":
      return { ...next, routes: data.routes as NormsRoute[] };
    case "risk.scored":
      return {
        ...next,
        risk: {
          score: Number(data.score),
          tier: data.tier as Tier,
          reasons: data.reasons as { ref: string; text: string }[],
          rulesFired: data.rulesFired as string[],
        },
        payment: next.payment
          ? {
              ...next.payment,
              score: Number(data.score),
              tier: data.tier as Tier,
            }
          : null,
      };
    case "route.selected": {
      const scores = (data.scores ?? []) as RouteSelectedData["scores"];
      const ownScore = scores.find((score) => score.routeId === data.routeId)?.s;
      return {
        ...next,
        selectedRouteId: String(data.routeId),
        routeScores: scores,
        hops: selectedHops(next.routes, String(data.routeId)),
        payment: next.payment
          ? {
              ...next.payment,
              routeId: String(data.routeId),
              routeName: String(data.name),
              feesEur: Number(data.feesEur),
              etaLabel: String(data.etaLabel),
              routeReason: String(data.reason),
              routeCostEur: ownScore ?? undefined,
              tier: data.tier as Tier,
            }
          : null,
      };
    }
    case "approval.granted":
      return { ...next, approval: data as unknown as ApprovalGrantedData };
    case "intent.committed":
      return {
        ...next,
        payment: next.payment
          ? {
              ...next.payment,
              status: "in_transit",
              tier: data.tier as Tier,
              intentHash: String(data.intentHash),
              intentTxHash: String(data.txHash),
              intentSimulated: event.simulated,
            }
          : null,
      };
    case "leg.sent": {
      const hop = Number(data.hop);
      return {
        ...next,
        payment: paymentWithStatus(next.payment, "in_transit"),
        hops: next.hops.map((item) =>
          item.index === hop
            ? {
                ...item,
                from: String(data.from),
                to: String(data.to),
                kind: data.kind as HopView["kind"],
                state: "active",
                durationMs: Number(data.durationMs),
              }
            : item,
        ),
      };
    }
    case "leg.settled": {
      const hop = Number(data.hop);
      return {
        ...next,
        hops: next.hops.map((item) =>
          item.index === hop ? { ...item, state: "settled" } : item,
        ),
      };
    }
    case "payment.held":
      return {
        ...next,
        payment: paymentWithStatus(next.payment, "held"),
        held: data as unknown as PaymentHeldData,
        alertOpen: true,
      };
    case "verification.requested":
      return {
        ...next,
        payment: paymentWithStatus(next.payment, "awaiting_supplier"),
        verification: {
          ...next.verification,
          requested: data as unknown as VerificationRequestedData,
        },
      };
    case "verification.recorded":
      return {
        ...next,
        verification: {
          ...next.verification,
          recorded: data as unknown as VerificationRecordedData,
        },
      };
    case "intent.revoked":
      return { ...next, revoked: true };
    case "escrow.refunded": {
      const heldHop = next.held?.hop ?? Number.MAX_SAFE_INTEGER;
      return {
        ...next,
        refunded: true,
        hops: next.hops.map((hop) =>
          hop.index <= heldHop && (hop.state === "settled" || hop.state === "active")
            ? { ...hop, state: "refunded" }
            : hop,
        ),
      };
    }
    case "escrow.released":
      return {
        ...next,
        released: true,
        payment: paymentWithStatus(next.payment, "in_transit"),
      };
    case "payment.credited":
      return {
        ...next,
        payment: paymentWithStatus(next.payment, "credited"),
        credited: data as unknown as PaymentCreditedData,
      };
    case "payment.stopped":
      return {
        ...next,
        payment: paymentWithStatus(next.payment, "stopped"),
        stopped: data as unknown as PaymentStoppedData,
      };
    case "attack.attempted":
      return {
        ...next,
        attack: { ...next.attack, attempted: true },
      };
    case "tx.reverted":
      return {
        ...next,
        attack: {
          ...next.attack,
          reverted: true,
          reason: String(data.reason ?? ""),
        },
      };
    default:
      return next;
  }
}

export function closeAlert(state: ViewState): ViewState {
  return { ...state, alertOpen: false };
}

export function availableActions(state: ViewState): {
  runLegit: boolean;
  runDiverted: boolean;
  confirm: boolean;
  deny: boolean;
  attack: boolean;
  reset: boolean;
} {
  const canRun =
    state.payment === null ||
    state.payment.status === "credited" ||
    state.payment.status === "stopped";
  const awaitingSupplier = state.payment?.status === "awaiting_supplier";

  return {
    runLegit: canRun,
    runDiverted: canRun,
    confirm: awaitingSupplier,
    deny: awaitingSupplier,
    attack: state.revoked && !state.attack.attempted,
    reset: true,
  };
}
