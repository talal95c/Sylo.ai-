import type {
  ApprovalGrantedData,
  BreakerOffData,
  BreakerOnData,
  ClusterDetectedData,
  NormsRoute,
  RouteSelectedData,
  PaymentCreditedData,
  PaymentHeldData,
  CaseReadyData,
  GuardianIncidentData,
  KillSwitchData,
  LegRejectedData,
  PaymentStoppedData,
  RailDownData,
  SyloEvent,
  Tier,
  VerificationRecordedData,
  VerificationRequestedData,
  SystemModeData,
  TrafficSampleData,
} from "./events";
import { describe, distinctReasons } from "./feed";

export type PaymentStatus =
  | "idle"
  | "deciding"
  | "in_transit"
  | "held"
  | "awaiting_supplier"
  | "awaiting_analyst"
  | "frozen"
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
  outcome?: string;
  functionName?: string;
  reasonCode?: string;
  incidentId?: string;
  /** Title for this event when the type alone is not specific enough (alerts, attacks). */
  title?: string;
}

export interface RailView extends RailDownData {
  simulated: boolean;
}

export interface IncidentView extends GuardianIncidentData {
  simulated: boolean;
}

export interface KillSwitchView extends KillSwitchData {
  simulated: boolean;
}

export interface WaveSample {
  paymentId: string;
  from: string;
  to: string;
  payerName: string;
  amountLabel: string;
}

export interface WaveView {
  samples: WaveSample[];
  cluster: ClusterDetectedData | null;
  breaker: BreakerOnData | null;
}

export interface ViewState {
  mode: SystemModeData | null;
  lastSeq: number;
  scenario: "legit" | "diverted" | "mule_wave" | null;
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
    actionTier?: Tier;
    score?: number;
    routeId?: string;
    routeName?: string;
    feesEur?: number;
    etaLabel?: string;
    routeReason?: string;
    routeCostEur?: number;
    settlement?: string;
    intentHash?: string;
    intentTxHash?: string;
    intentSimulated?: boolean;
  };
  risk: null | {
    score: number;
    tier: Tier;
    model: string;
    reasons: { ref: string; text: string }[];
    rulesFired: string[];
    oobResolvable: boolean;
  };
  routes: NormsRoute[];
  selectedRouteId: string | null;
  routeScores: RouteSelectedData["scores"];
  approval: ApprovalGrantedData | null;
  hops: HopView[];
  held: PaymentHeldData | null;
  caseFile: CaseReadyData | null;
  incident: IncidentView | null;
  rails: Record<string, RailView>;
  killSwitch: KillSwitchView | null;
  rejectedLeg: (LegRejectedData & { simulated: boolean }) | null;
  alertOpen: boolean;
  verification: {
    requested?: VerificationRequestedData;
    recorded?: VerificationRecordedData;
  };
  revoked: boolean;
  refunded: boolean;
  released: boolean;
  attack: {
    attempted: boolean;
    reverted: boolean;
    reason: string | null;
    name: string | null;
    functionName: string | null;
  };
  credited: PaymentCreditedData | null;
  stopped: PaymentStoppedData | null;
  quote: RouteSelectedData | null;
  timing: { createdTs?: string; committedTs?: string; creditedTs?: string };
  feed: FeedItem[];
  wave: WaveView | null;
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
  caseFile: null,
  incident: null,
  rails: {},
  killSwitch: null,
  rejectedLeg: null,
  alertOpen: false,
  verification: {},
  revoked: false,
  refunded: false,
  released: false,
  attack: { attempted: false, reverted: false, reason: null, name: null, functionName: null },
  credited: null,
  stopped: null,
  quote: null,
  timing: {},
  feed: [],
  wave: null,
};

export function resetForSourceChange(state: ViewState): ViewState {
  return { ...initialState, mode: state.mode };
}

export function riskModeForSource(
  state: ViewState,
  sourceKind: "live" | "replay",
): "rules" | "model" {
  const model = state.risk?.model.toLowerCase();
  if (model) return model.startsWith("rules") ? "rules" : "model";
  return sourceKind === "replay" ? "model" : (state.mode?.risk ?? "rules");
}

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
  if (
    event.type !== "system.mode" &&
    event.type !== "session.reset" &&
    event.seq === state.lastSeq
  ) {
    return state;
  }

  const sequenceRestart =
    event.type !== "system.mode" &&
    event.type !== "session.reset" &&
    event.seq < state.lastSeq;
  const current = sequenceRestart
    ? { ...initialState, mode: state.mode }
    : state;
  const isSessionReset = event.type === "session.reset";
  const isScenarioStart = event.type === "scenario.started";
  const isWaveFollowUp =
    isScenarioStart &&
    current.scenario === "mule_wave" &&
    current.payment === null;
  const base = isSessionReset
    ? { ...initialState, mode: current.mode }
    : isScenarioStart && isWaveFollowUp
      ? {
          ...initialState,
          mode: current.mode,
          rails: current.rails,
          killSwitch: current.killSwitch,
          feed: current.feed,
          wave: current.wave,
          scenario: "mule_wave" as const,
        }
      : isScenarioStart
      ? {
          ...initialState,
          mode: current.mode,
          rails: current.rails,
          killSwitch: current.killSwitch,
        }
      : current;
  const next: ViewState = {
    ...base,
    lastSeq: event.type === "system.mode" ? current.lastSeq : event.seq,
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
      if (data.scenario === "mule_wave" || isWaveFollowUp) {
        return { ...next, scenario: "mule_wave" };
      }
      return {
        ...next,
        scenario: String(data.scenario ?? "").startsWith("diverted") ? "diverted" : "legit",
      };
    case "traffic.sample": {
      const sample = data as unknown as TrafficSampleData;
      const amount = `${sample.amount.currency} ${Number(sample.amount.value).toLocaleString("en-US", {
        minimumFractionDigits: 0,
        maximumFractionDigits: 2,
      })}`;
      const samples = sample.arcs.map((arc) => ({
        paymentId: event.paymentId ?? "",
        from: arc.from,
        to: arc.to,
        payerName: sample.payer.name,
        amountLabel: amount,
      }));
      return {
        ...next,
        wave: {
          ...(next.wave ?? { samples: [], cluster: null, breaker: null }),
          samples: [...(next.wave?.samples ?? []), ...samples],
        },
      };
    }
    case "cluster.detected":
      return {
        ...next,
        wave: {
          ...(next.wave ?? { samples: [], cluster: null, breaker: null }),
          cluster: data as unknown as ClusterDetectedData,
        },
      };
    case "breaker.on":
      return {
        ...next,
        wave: {
          ...(next.wave ?? { samples: [], cluster: null, breaker: null }),
          breaker: data as unknown as BreakerOnData,
        },
      };
    case "breaker.off": {
      const breaker = data as unknown as BreakerOffData;
      if (next.wave?.breaker?.breakerId !== breaker.breakerId) return next;
      return {
        ...next,
        wave: { ...next.wave, breaker: null },
      };
    }
    case "payment.created": {
      const payer = data.payer as Record<string, unknown>;
      const beneficiary = data.beneficiary as Record<string, unknown>;
      const amount = data.amount as Record<string, unknown>;
      return {
        ...next,
        timing: { createdTs: event.ts },
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
          model: String(data.model ?? ""),
          reasons: distinctReasons(data.reasons as { ref: string; text: string; ruleId?: string | null }[]),
          rulesFired: data.rulesFired as string[],
          oobResolvable: data.oobResolvable === true,
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
        quote: data as unknown as RouteSelectedData,
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
              settlement: typeof data.settlement === "string" ? data.settlement : undefined,
              actionTier: data.tier as Tier,
            }
          : null,
      };
    }
    case "approval.granted":
      return { ...next, approval: data as unknown as ApprovalGrantedData };
    case "intent.committed":
      return {
        ...next,
        timing: { ...next.timing, committedTs: event.ts },
        payment: next.payment
          ? {
              ...next.payment,
              status: "in_transit",
              actionTier: data.tier as Tier,
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
        held: {
          ...(data as unknown as PaymentHeldData),
          reasons: distinctReasons((data as unknown as PaymentHeldData).reasons),
        },
        alertOpen: true,
      };
    case "case.ready":
      return { ...next, caseFile: data as unknown as CaseReadyData };
    case "guardian.incident": {
      const incident = data as unknown as GuardianIncidentData;
      return {
        ...next,
        incident: { ...incident, simulated: event.simulated },
        payment: incident.action.includes("FREEZE")
          ? paymentWithStatus(next.payment, "frozen")
          : next.payment,
        alertOpen: true,
      };
    }
    case "verification.requested":
      return {
        ...next,
        payment: paymentWithStatus(next.payment, data.channel === "ANALYST" ? "awaiting_analyst" : "awaiting_supplier"),
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
        timing: { ...next.timing, creditedTs: event.ts },
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
        attack: {
          ...next.attack,
          attempted: true,
          name: typeof data.attack === "string" ? data.attack : null,
        },
      };
    case "leg.rejected":
      return {
        ...next,
        rejectedLeg: {
          ...(data as unknown as LegRejectedData),
          simulated: event.simulated,
        },
      };
    case "tx.reverted":
      // Only a revert that follows an attack is the attack's outcome (a chain may revert for other reasons).
      if (!next.attack.attempted) return next;
      return {
        ...next,
        attack: {
          ...next.attack,
          reverted: true,
          reason: String(data.reason ?? ""),
          functionName: typeof data.function === "string" ? data.function : null,
        },
      };
    case "rail.down": {
      const rail = data as unknown as RailDownData;
      return {
        ...next,
        rails: {
          ...next.rails,
          [rail.routeId]: { ...rail, simulated: event.simulated },
        },
      };
    }
    case "rail.up": {
      const routeId = String(data.routeId ?? "");
      const rails = { ...next.rails };
      delete rails[routeId];
      return {
        ...next,
        rails,
        killSwitch: next.killSwitch?.adapter === routeId ? null : next.killSwitch,
      };
    }
    case "killswitch.on":
      return {
        ...next,
        killSwitch: {
          ...(data as unknown as KillSwitchData),
          simulated: event.simulated,
        },
      };
    default:
      return next;
  }
}

export function closeAlert(state: ViewState): ViewState {
  return { ...state, alertOpen: false };
}

export function availableActions(
  state: ViewState,
  sourceKind: "live" | "replay" = "replay",
): {
  runLegit: boolean;
  runDiverted: boolean;
  runMuleWave: boolean;
  runGuardian: boolean;
  runOutage: boolean;
  runSimSwap: boolean;
  runHoldExpiry: boolean;
  runTimeLock: boolean;
  runConfidential: boolean;
  confirm: boolean;
  deny: boolean;
  attack: boolean;
  swapAttack: boolean;
  replayAttack: boolean;
  reset: boolean;
} {
  const canRun =
    state.payment === null ||
    state.payment.status === "credited" ||
    state.payment.status === "stopped";
  const awaitingSupplier = state.payment?.status === "awaiting_supplier";
  // Live, Scene 4 is an attack on the payment held in escrow; in replay it is a recorded scene.
  const heldInEscrow = awaitingSupplier && state.held?.at === "escrow" && !state.attack.attempted;

  return {
    runLegit: canRun,
    runDiverted: canRun,
    runMuleWave: canRun,
    runGuardian: sourceKind === "live" ? heldInEscrow : canRun,
    runOutage: canRun,
    runSimSwap: canRun,
    runHoldExpiry: canRun,
    runTimeLock: canRun,
    runConfidential: canRun,
    confirm: awaitingSupplier,
    deny: awaitingSupplier,
    attack: state.revoked && !state.attack.attempted,
    swapAttack: Boolean(state.payment?.intentHash) && !state.attack.attempted,
    replayAttack: Boolean(state.payment?.intentHash) && !state.attack.attempted,
    reset: true,
  };
}
