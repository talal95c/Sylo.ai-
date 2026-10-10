/**
 * View state: a pure reducer from engine events to what the page draws.
 *
 * The web draws, the engine decides: nothing here computes a decision. Every sentence about the
 * payment (headline, reasons, protection, next step, answers) is carried by the events.
 *
 * Sequence rule (reconnects replay the session buffer, replay files restart at 1):
 * - `system.mode` is always applied and never changes `lastSeq`;
 * - `session.reset` and `scenario.started` are always applied: they reset the view and set
 *   `lastSeq` to their own `seq`;
 * - any other event whose `seq` is not greater than `lastSeq` is ignored.
 */

import {
  isKnownEvent,
  type EventOf,
  type HopKind,
  type InstitutionId,
  type KnownEvent,
  type NormSignal,
  type Reason,
  type RouteScore,
  type Settlement,
  type SyloEvent,
  type SystemModeData,
  type TaxNotice,
  type Tier,
} from "./events";
import { institutionName } from "./geo";

export type PaymentStatus = "idle" | "deciding" | "in_transit" | "held" | "awaiting_supplier" | "stopped" | "credited";
export type HopState = "pending" | "active" | "settled" | "refunded";
export type FeedFamily = "decision" | "leg" | "chain" | "alert" | "attack" | "system";

export interface TxView {
  txHash: string | null;
  explorerUrl: string | null;
  simulated: boolean;
}

export interface PaymentView {
  id: string | null;
  status: PaymentStatus;
  uetr: string | null;
  payer: { id: string; name: string; institutionId: InstitutionId } | null;
  beneficiary: {
    payeeName: string;
    accountHolder: string;
    accountMasked: string;
    institutionId: InstitutionId;
    knownPayee: boolean;
    knownAccount: boolean;
  } | null;
  amount: { value: string; currency: string } | null;
  purpose: string | null;
  invoiceRef: string | null;
  provenance: string | null;
  senderDomain: string | null;
  tier: Tier | null;
  score: number | null;
  riskModel: string | null;
  rulesFired: string[];
  reasons: Reason[];
  /** From `intent.committed`. */
  sealed: (TxView & { intentHash: string }) | null;
  executed: boolean;
  /** From `payment.stopped`. */
  stopped: { headline: string; detail: string } | null;
  /** From `payment.credited`. `n` is the ordinal of the event (see ViewState.applied). */
  credited: { n: number; at: InstitutionId; feesEur: number; routeCostEur: number; swiftRouteCostEur: number; elapsedLabel: string } | null;
}

export interface RouteView {
  routeId: string;
  name: string;
  settlement: Settlement | string;
  hops: { from: InstitutionId; to: InstitutionId; kind: HopKind }[];
  status: "PASS" | "EXCLUDED";
  excludedBy: string | null;
  reason: string | null;
  legalRef: string | null;
}

export interface SelectedRouteView {
  routeId: string;
  name: string;
  settlement: string;
  reason: string;
  feesEur: number | null;
  etaLabel: string;
  priceOfSafetyEur: number | null;
  scores: RouteScore[];
}

export interface HopView {
  index: number;
  from: InstitutionId;
  to: InstitutionId;
  kind: HopKind;
  state: HopState;
  rail: string | null;
  label: string | null;
  durationMs: number | null;
  sentN: number | null;
  settledN: number | null;
}

export interface HeldView {
  n: number;
  hop: number;
  at: string;
  tier: Tier;
  headline: string;
  reasons: Reason[];
  protection: string;
  nextStep: string;
  expiresAt: string;
}

export interface EscrowView {
  status: "locked" | "released" | "refunded";
  /** Index of the hop on which the money stopped. */
  hop: number | null;
  amount: string;
  token: string;
  expiresAt: string;
  depositedN: number;
  releasedN: number | null;
  refundedN: number | null;
  to: InstitutionId | null;
}

export interface VerificationView {
  contactName: string;
  contactMasked: string;
  contactSince: string;
  channel: string;
  simSwapChecked: boolean;
  simSwapRecent: boolean;
  result: "CONFIRMED" | "DENIED" | null;
  answerText: string | null;
}

export interface RevocationView {
  n: number;
  reasonCode: string;
  by: string;
}

export interface AttackView {
  n: number;
  attack: string;
  description: string;
  by: string;
  reverted: boolean;
  function: string | null;
  reason: string | null;
  text: string | null;
}

export interface RevertView {
  n: number;
  function: string;
  reason: string;
  text: string;
}

export interface ChainEventView extends TxView {
  n: number;
  seq: number;
  type: string;
}

export interface FeedItem extends TxView {
  /** Ordinal of the event in this page session: unique and increasing, also across view resets. */
  n: number;
  seq: number;
  id: string;
  ts: string;
  type: string;
  family: FeedFamily;
  /** One line that tells what happened. */
  text: string;
  /** Optional second-level lines (reasons, texts carried by the event). */
  details: string[];
  paymentId: string | null;
}

export interface ViewState {
  /** Highest `seq` applied in the current session. */
  lastSeq: number;
  /** Number of events applied since the page loaded. Never reset: the ordinals `n` come from it. */
  applied: number;
  /** Ordinal of the event that last reset the view (0 when none did). */
  runN: number;
  mode: SystemModeData | null;
  scenario: { name: string; speed: number; auto: boolean } | null;
  payment: PaymentView;
  packVersion: string | null;
  routes: RouteView[];
  /** Ordinal of the last `norms.checked`. */
  routesN: number | null;
  signals: NormSignal[];
  taxNotices: TaxNotice[];
  selectedRouteId: string | null;
  route: SelectedRouteView | null;
  hops: HopView[];
  approval: { by: { name: string; role: string }[]; method: string; conditional: boolean } | null;
  held: HeldView | null;
  escrow: EscrowView | null;
  verification: VerificationView | null;
  revocation: RevocationView | null;
  chainEvents: ChainEventView[];
  attack: AttackView | null;
  lastRevert: RevertView | null;
  feed: FeedItem[];
  /**
   * Raw envelopes for the globe, in order: the reset event (`session.reset` or `scenario.started`)
   * and every event applied since. `system.mode` and ignored duplicates are never in it.
   *
   * The globe consumes it by position (it handles the items after the ones it has seen, and starts
   * over when the list gets shorter). So every change is either an append or a strict shrink: a
   * reset that arrives while the list holds a single item is appended to it instead of replacing it.
   */
  events: SyloEvent[];
}

const MAX_FEED_ITEMS = 400;

const EMPTY_PAYMENT: PaymentView = {
  id: null,
  status: "idle",
  uetr: null,
  payer: null,
  beneficiary: null,
  amount: null,
  purpose: null,
  invoiceRef: null,
  provenance: null,
  senderDomain: null,
  tier: null,
  score: null,
  riskModel: null,
  rulesFired: [],
  reasons: [],
  sealed: null,
  executed: false,
  stopped: null,
  credited: null,
};

export const initialState: ViewState = {
  lastSeq: 0,
  applied: 0,
  runN: 0,
  mode: null,
  scenario: null,
  payment: EMPTY_PAYMENT,
  packVersion: null,
  routes: [],
  routesN: null,
  signals: [],
  taxNotices: [],
  selectedRouteId: null,
  route: null,
  hops: [],
  approval: null,
  held: null,
  escrow: null,
  verification: null,
  revocation: null,
  chainEvents: [],
  attack: null,
  lastRevert: null,
  feed: [],
  events: [],
};

// ---------------------------------------------------------------- formatting helpers (display only)

const NUMBER = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 });

/** "85000.00" -> "85,000" */
export function formatAmount(value: string | number | null | undefined): string {
  const amount = typeof value === "number" ? value : Number(value);
  return Number.isFinite(amount) ? NUMBER.format(amount) : String(value ?? "");
}

/** ("85000.00", "EUR") -> "EUR 85,000" */
export function formatMoney(value: string | number | null | undefined, currency: string | null | undefined): string {
  return `${currency ?? ""} ${formatAmount(value)}`.trim();
}

/** 179.21 -> "€179.21" */
export function formatEur(value: number | string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "";
  return `€${formatAmount(value)}`;
}

/** "0x79b993cd…9d28" */
export function shortHash(hash: string | null | undefined): string {
  if (!hash) return "";
  return hash.length > 12 ? `${hash.slice(0, 6)}…${hash.slice(-4)}` : hash;
}

function list<T>(value: T[] | null | undefined): T[] {
  return Array.isArray(value) ? value : [];
}

function chainLabel(chain: string): string {
  return chain === "mock" ? "simulated" : chain;
}

// ---------------------------------------------------------------- selectors

export function activeHop(state: ViewState): HopView | null {
  for (let i = state.hops.length - 1; i >= 0; i -= 1) {
    if (state.hops[i].state === "active") return state.hops[i];
  }
  return null;
}

/**
 * Which demo buttons apply to the current view. This only mirrors what the engine accepts
 * (it answers 409 otherwise): the engine stays the authority.
 */
export function availableActions(state: ViewState): { run: boolean; supplierAnswer: boolean; attack: boolean } {
  const status = state.payment.status;
  const running = status === "deciding" || status === "in_transit" || status === "held" || status === "awaiting_supplier";
  const attackInFlight = state.attack !== null && !state.attack.reverted;
  return {
    run: !running,
    supplierAnswer: status === "awaiting_supplier",
    attack: status === "stopped" && state.revocation !== null && !attackInFlight,
  };
}

// ---------------------------------------------------------------- reducer

export function reduce(state: ViewState, event: SyloEvent): ViewState {
  if (event.type === "system.mode") return applyMode(state, event as EventOf<"system.mode">);

  const resets = event.type === "session.reset" || event.type === "scenario.started";
  if (!resets && event.seq <= state.lastSeq) return state;

  const n = state.applied + 1;
  const base: ViewState = resets ? { ...initialState, mode: state.mode, runN: n } : state;
  const next = isKnownEvent(event) ? applyKnown(base, event, n) : base;
  const tx = txOf(event);
  return {
    ...next,
    lastSeq: event.seq,
    applied: n,
    chainEvents: tx.txHash ? [...next.chainEvents, { n, seq: event.seq, type: event.type, ...tx }] : next.chainEvents,
    feed: appendFeed(next.feed, feedItem(event, next, n, tx)),
    events: resets ? (state.events.length === 1 ? [...state.events, event] : [event]) : [...next.events, event],
  };
}

function applyMode(state: ViewState, event: EventOf<"system.mode">): ViewState {
  const data = event.data;
  const mode: SystemModeData = {
    risk: data.risk,
    chain: data.chain,
    llm: data.llm,
    rails: data.rails,
    degraded: list(data.degraded),
  };
  if (state.mode && JSON.stringify(state.mode) === JSON.stringify(mode)) return state;
  const n = state.applied + 1;
  return { ...state, mode, applied: n, feed: appendFeed(state.feed, feedItem(event, state, n, txOf(event))) };
}

function txOf(event: SyloEvent): TxView {
  const data = event.data as { txHash?: unknown; explorerUrl?: unknown };
  return {
    txHash: typeof data.txHash === "string" ? data.txHash : null,
    explorerUrl: typeof data.explorerUrl === "string" ? data.explorerUrl : null,
    simulated: event.simulated,
  };
}

function appendFeed(feed: FeedItem[], item: FeedItem): FeedItem[] {
  const next = [...feed, item];
  return next.length > MAX_FEED_ITEMS ? next.slice(next.length - MAX_FEED_ITEMS) : next;
}

function withPayment(state: ViewState, patch: Partial<PaymentView>): ViewState {
  return { ...state, payment: { ...state.payment, ...patch } };
}

function applyKnown(state: ViewState, event: KnownEvent, n: number): ViewState {
  switch (event.type) {
    case "session.reset":
    case "system.mode":
      return state;

    case "scenario.started":
      return {
        ...state,
        scenario: { name: event.data.scenario, speed: event.data.speed > 0 ? event.data.speed : 1, auto: event.data.auto === true },
        payment: { ...state.payment, id: event.paymentId, status: "deciding" },
      };

    case "payment.created": {
      const d = event.data;
      return withPayment(state, {
        id: event.paymentId ?? state.payment.id,
        status: "deciding",
        uetr: d.uetr,
        payer: d.payer ?? null,
        beneficiary: d.beneficiary ?? null,
        amount: d.amount ?? null,
        purpose: d.purpose,
        invoiceRef: d.invoiceRef,
        provenance: d.provenance,
        senderDomain: d.senderDomain ?? null,
      });
    }

    case "norms.checked": {
      const d = event.data;
      const routes: RouteView[] = list(d.routes).map((route) => ({
        routeId: route.routeId,
        name: route.name,
        settlement: route.settlement,
        hops: list(route.hops).map((hop) => ({ from: hop.from, to: hop.to, kind: hop.kind })),
        status: route.status === "EXCLUDED" ? "EXCLUDED" : "PASS",
        excludedBy: route.excludedBy ?? null,
        reason: route.reason ?? null,
        legalRef: route.legalRef ?? null,
      }));
      return { ...state, packVersion: d.packVersion, routes, routesN: n, signals: list(d.signals), taxNotices: list(d.taxNotices) };
    }

    case "risk.scored": {
      const d = event.data;
      return withPayment(state, { score: d.score, tier: d.tier, riskModel: d.model, rulesFired: list(d.rulesFired), reasons: list(d.reasons) });
    }

    case "route.selected": {
      const d = event.data;
      const selected = state.routes.find((route) => route.routeId === d.routeId);
      const hops: HopView[] = (selected?.hops ?? []).map((hop, index) => ({
        index,
        from: hop.from,
        to: hop.to,
        kind: hop.kind,
        state: "pending",
        rail: null,
        label: null,
        durationMs: null,
        sentN: null,
        settledN: null,
      }));
      return {
        ...withPayment(state, { tier: d.tier ?? state.payment.tier }),
        selectedRouteId: d.routeId,
        route: {
          routeId: d.routeId,
          name: d.name,
          settlement: d.settlement,
          reason: d.reason,
          feesEur: typeof d.feesEur === "number" ? d.feesEur : null,
          etaLabel: d.etaLabel,
          priceOfSafetyEur: typeof d.priceOfSafetyEur === "number" ? d.priceOfSafetyEur : null,
          scores: list(d.scores),
        },
        hops,
      };
    }

    case "approval.granted":
      return { ...state, approval: { by: list(event.data.by), method: event.data.method, conditional: event.data.conditional === true } };

    case "intent.committed":
      return withPayment(state, {
        tier: event.data.tier ?? state.payment.tier,
        sealed: { intentHash: event.data.intentHash, ...txOf(event) },
      });

    case "leg.sent": {
      const d = event.data;
      const hops = state.hops.slice();
      // The route normally comes from norms.checked; a leg outside of it is drawn from the event alone.
      while (hops.length <= d.hop) {
        hops.push({ index: hops.length, from: d.from, to: d.from, kind: d.kind, state: "pending", rail: null, label: null, durationMs: null, sentN: null, settledN: null });
      }
      hops[d.hop] = {
        ...hops[d.hop],
        from: d.from,
        to: d.to,
        kind: d.kind,
        state: "active",
        rail: d.rail ?? null,
        label: d.label ?? null,
        durationMs: typeof d.durationMs === "number" ? d.durationMs : null,
        sentN: n,
        settledN: null,
      };
      return { ...withPayment(state, { status: "in_transit" }), hops };
    }

    case "leg.settled": {
      const d = event.data;
      if (!state.hops[d.hop]) return state;
      const hops = state.hops.slice();
      hops[d.hop] = { ...hops[d.hop], state: "settled", settledN: n };
      return { ...state, hops };
    }

    case "escrow.deposited": {
      const d = event.data;
      const active = activeHop(state);
      return {
        ...state,
        escrow: {
          status: "locked",
          hop: active ? active.index : null,
          amount: d.amount,
          token: d.token,
          expiresAt: d.expiresAt,
          depositedN: n,
          releasedN: null,
          refundedN: null,
          to: null,
        },
      };
    }

    case "payment.held": {
      const d = event.data;
      const escrow = state.escrow && d.at === "escrow" ? { ...state.escrow, hop: d.hop } : state.escrow;
      return {
        ...withPayment(state, { status: "held", tier: d.tier ?? state.payment.tier }),
        escrow,
        held: {
          n,
          hop: d.hop,
          at: d.at,
          tier: d.tier,
          headline: d.headline,
          reasons: list(d.reasons),
          protection: d.protection,
          nextStep: d.nextStep,
          expiresAt: d.expiresAt,
        },
      };
    }

    case "verification.requested": {
      const d = event.data;
      return {
        ...withPayment(state, { status: "awaiting_supplier" }),
        verification: {
          contactName: d.contactName,
          contactMasked: d.contactMasked,
          contactSince: d.contactSince,
          channel: d.channel,
          simSwapChecked: d.simSwapChecked === true,
          simSwapRecent: d.simSwapRecent === true,
          result: null,
          answerText: null,
        },
      };
    }

    case "verification.recorded": {
      const d = event.data;
      const previous: VerificationView = state.verification ?? {
        contactName: "",
        contactMasked: "",
        contactSince: "",
        channel: "",
        simSwapChecked: false,
        simSwapRecent: false,
        result: null,
        answerText: null,
      };
      return {
        ...withPayment(state, { status: "held" }),
        verification: { ...previous, result: d.result, answerText: d.answerText },
      };
    }

    case "intent.revoked":
      return { ...state, revocation: { n, reasonCode: event.data.reasonCode, by: event.data.by } };

    case "escrow.refunded": {
      const d = event.data;
      const escrow: EscrowView = state.escrow
        ? { ...state.escrow, status: "refunded", refundedN: n, to: d.to }
        : { status: "refunded", hop: null, amount: d.amount, token: "", expiresAt: "", depositedN: n, releasedN: null, refundedN: n, to: d.to };
      const hops = state.hops.map((hop) => (hop.state === "settled" || hop.state === "active" ? { ...hop, state: "refunded" as const } : hop));
      return { ...state, escrow, hops };
    }

    case "escrow.released": {
      const d = event.data;
      const escrow: EscrowView = state.escrow
        ? { ...state.escrow, status: "released", releasedN: n, to: d.to }
        : { status: "released", hop: null, amount: d.amount, token: "", expiresAt: "", depositedN: n, releasedN: n, refundedN: null, to: d.to };
      return { ...withPayment(state, { status: "in_transit" }), escrow };
    }

    case "intent.executed":
      return withPayment(state, { executed: true });

    case "payment.credited": {
      const d = event.data;
      return withPayment(state, {
        status: "credited",
        credited: { n, at: d.at, feesEur: d.feesEur, routeCostEur: d.routeCostEur, swiftRouteCostEur: d.swiftRouteCostEur, elapsedLabel: d.elapsedLabel },
      });
    }

    case "payment.stopped":
      return withPayment(state, { status: "stopped", stopped: { headline: event.data.headline, detail: event.data.detail } });

    case "attack.attempted":
      return {
        ...state,
        attack: { n, attack: event.data.attack, description: event.data.description, by: event.data.by, reverted: false, function: null, reason: null, text: null },
      };

    case "tx.reverted": {
      const d = event.data;
      const text = revertText(d.text, d.reason);
      const attack = state.attack && !state.attack.reverted ? { ...state.attack, reverted: true, function: d.function, reason: d.reason, text } : state.attack;
      return { ...state, attack, lastRevert: { n, function: d.function, reason: d.reason, text } };
    }
  }
}

function revertText(text: string | undefined, reason: string): string {
  return typeof text === "string" && text !== "" ? text : `Rejected by the smart contract: ${reason}.`;
}

// ---------------------------------------------------------------- feed (one line per event)

const FAMILY: Record<string, FeedFamily> = {
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
  "intent.revoked": "chain",
  "escrow.refunded": "chain",
  "escrow.released": "chain",
  "intent.executed": "chain",
  "payment.held": "alert",
  "verification.requested": "alert",
  "verification.recorded": "alert",
  "payment.stopped": "alert",
  "attack.attempted": "attack",
  "tx.reverted": "attack",
};

function feedItem(event: SyloEvent, state: ViewState, n: number, tx: TxView): FeedItem {
  const { text, details } = isKnownEvent(event) ? describe(event, state) : { text: `${event.type} (not drawn in this version)`, details: [] };
  return {
    n,
    seq: event.seq,
    id: event.id,
    ts: event.ts,
    type: event.type,
    family: FAMILY[event.type] ?? "system",
    text,
    details: details.filter((line) => line !== ""),
    paymentId: event.paymentId,
    ...tx,
  };
}

function describe(event: KnownEvent, state: ViewState): { text: string; details: string[] } {
  const currency = state.payment.amount?.currency ?? "";
  switch (event.type) {
    case "session.reset":
      return { text: "Session reset", details: [] };

    case "system.mode": {
      const d = event.data;
      const parts = [`risk ${d.risk}`, `chain ${chainLabel(d.chain)}`, `rails ${d.rails}`];
      if (d.llm && d.llm !== "off") parts.push(`LLM ${d.llm}`);
      const degraded = list(d.degraded);
      if (degraded.length > 0) parts.push(`degraded: ${degraded.join(", ")}`);
      return { text: `Mode: ${parts.join(" · ")}`, details: [] };
    }

    case "scenario.started": {
      const d = event.data;
      return { text: `Scenario started: ${d.scenario}${d.speed && d.speed !== 1 ? ` (${d.speed}× speed)` : ""}`, details: [] };
    }

    case "payment.created": {
      const d = event.data;
      const b = d.beneficiary;
      const details = [`Invoice ${d.invoiceRef} · ${d.purpose} · bank details from: ${String(d.provenance).replaceAll("_", " ")}`];
      if (b) {
        const at = institutionName(b.institutionId);
        details.push(b.knownAccount ? `Known account ${b.accountMasked} at ${at}` : `New account: ${b.accountHolder} (${b.accountMasked}) at ${at}`);
      }
      if (d.senderDomain) details.push(`Sender domain: ${d.senderDomain}`);
      return {
        text: `Payment order: ${formatMoney(d.amount?.value, d.amount?.currency)} from ${d.payer?.name ?? "payer"} to ${b?.payeeName ?? "beneficiary"}`,
        details,
      };
    }

    case "norms.checked": {
      const routes = list(event.data.routes);
      const allowed = routes.filter((route) => route.status !== "EXCLUDED");
      const details = routes
        .filter((route) => route.status === "EXCLUDED")
        .map((route) => `${route.routeId} ${route.name}: ${route.reason ?? route.excludedBy ?? "excluded"}`);
      for (const signal of list(event.data.signals)) details.push(`Signal: ${signal.text}`);
      return {
        text: `Norms checked: ${allowed.length} of ${routes.length} routes allowed (${allowed.map((route) => route.routeId).join(", ")})`,
        details,
      };
    }

    case "risk.scored":
      return {
        text: `Risk score ${event.data.score}/100: ${event.data.tier}`,
        details: list(event.data.reasons).map((reason) => `${reason.ref} · ${reason.text}`),
      };

    case "route.selected": {
      const d = event.data;
      return { text: `Route selected: ${d.routeId} ${d.name} · fees ${formatEur(d.feesEur)} · ${d.etaLabel}`, details: [d.reason] };
    }

    case "approval.granted": {
      const d = event.data;
      const names = list(d.by).map((person) => `${person.name} (${person.role})`).join(" and ");
      return { text: `Approval recorded: ${names} · ${String(d.method).replaceAll("_", " ")}${d.conditional ? " · conditional" : ""}`, details: [] };
    }

    case "intent.committed":
      return { text: `Payment intent sealed on Avalanche · tier ${event.data.tier}`, details: [] };

    case "leg.sent": {
      const d = event.data;
      return { text: `Leg ${d.hop + 1} sent: ${institutionName(d.from)} → ${institutionName(d.to)}`, details: d.label ? [d.label] : [] };
    }

    case "leg.settled":
      return { text: `Leg ${event.data.hop + 1} settled at ${institutionName(event.data.at)}`, details: [] };

    case "escrow.deposited":
      return { text: `${formatAmount(event.data.amount)} ${event.data.token} locked in the escrow contract`, details: [] };

    case "payment.held":
      return { text: event.data.headline, details: [event.data.protection, event.data.nextStep] };

    case "verification.requested": {
      const d = event.data;
      const sim = d.simSwapChecked ? (d.simSwapRecent ? "SIM-swap check: recent swap detected" : "SIM-swap check: no recent swap") : "SIM-swap check: not done";
      return {
        text: `Asked ${d.contactName} by ${d.channel} on ${d.contactMasked}`,
        details: [`Number on file since ${d.contactSince} · ${sim}`],
      };
    }

    case "verification.recorded":
      return { text: `Supplier answer recorded: ${event.data.result}`, details: [event.data.answerText] };

    case "intent.revoked":
      return { text: `Payment revoked on-chain (${event.data.reasonCode}) by ${event.data.by}`, details: [] };

    case "escrow.refunded":
      return { text: `Escrow refunded: ${formatMoney(event.data.amount, currency)} back to ${institutionName(event.data.to)}`, details: [] };

    case "escrow.released":
      return { text: `Escrow released: ${formatMoney(event.data.amount, currency)} to ${institutionName(event.data.to)}`, details: [] };

    case "intent.executed":
      return { text: "Intent marked executed on-chain", details: [] };

    case "payment.credited": {
      const d = event.data;
      return {
        text: `Payment credited at ${institutionName(d.at)}`,
        details: [`Fees ${formatEur(d.feesEur)} · route cost ${formatEur(d.routeCostEur)} · SWIFT route ${formatEur(d.swiftRouteCostEur)} · ${d.elapsedLabel}`],
      };
    }

    case "payment.stopped":
      return { text: event.data.headline, details: [event.data.detail] };

    case "attack.attempted":
      return { text: `Attack attempt: ${event.data.description}`, details: [] };

    case "tx.reverted":
      return { text: revertText(event.data.text, event.data.reason), details: [`${event.data.function}() reverted: ${event.data.reason}`] };
  }
}
