/**
 * TypeScript mirror of spec/events.schema.json (envelope v1, catalogue of build spec section 4.2).
 *
 * The engine decides and the web draws: these types describe what the engine says, nothing more.
 * Every `data` object allows additional properties, so unknown fields are ignored everywhere.
 */

export const SCHEMA_VERSION = 1;

export type InstitutionId = string;
export type Tier = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
export type Settlement = "NONE" | "FIAT_HOLD" | "ONCHAIN_ESCROW";
export type HopKind = "bank" | "chain" | "wallet";

export interface Hop {
  from: InstitutionId;
  to: InstitutionId;
  kind: HopKind;
}

export interface Reason {
  ref: string;
  text: string;
}

export interface TxFields {
  txHash: string;
  explorerUrl: string | null;
}

// ---------------------------------------------------------------- data per event type

export type SessionResetData = Record<string, unknown>;

export interface SystemModeData {
  risk: "rules" | "model";
  chain: "mock" | "fuji";
  llm: "off" | "cached" | "live";
  rails: "simulated";
  degraded: string[];
}

export interface ScenarioStartedData {
  scenario: string;
  speed: number;
  auto: boolean;
}

export interface PaymentCreatedData {
  uetr: string;
  payer: { id: string; name: string; institutionId: InstitutionId };
  beneficiary: {
    payeeName: string;
    accountHolder: string;
    accountMasked: string;
    institutionId: InstitutionId;
    knownPayee: boolean;
    knownAccount: boolean;
  };
  amount: { value: string; currency: string };
  purpose: string;
  invoiceRef: string;
  provenance: string;
  senderDomain?: string;
}

export interface NormRoute {
  routeId: string;
  name: string;
  settlement: Settlement;
  hops: Hop[];
  status: "PASS" | "EXCLUDED";
  excludedBy?: string;
  reason?: string;
  legalRef?: string;
}

export interface NormSignal {
  code: string;
  text: string;
  ruleId: string;
}

export interface TaxNotice {
  text: string;
  reference: string;
}

export interface NormsCheckedData {
  packVersion: string;
  routes: NormRoute[];
  signals: NormSignal[];
  taxNotices: TaxNotice[];
}

export interface RiskScoredData {
  score: number;
  tier: Tier;
  rulesFired: string[];
  reasons: Reason[];
  model: string;
}

export interface RouteScore {
  routeId: string;
  s: number | null;
  excludedBy: string | null;
}

export interface RouteSelectedData {
  routeId: string;
  name: string;
  settlement: Settlement;
  tier: Tier;
  scores: RouteScore[];
  reason: string;
  feesEur: number;
  etaLabel: string;
  priceOfSafetyEur: number;
}

export interface ApprovalGrantedData {
  by: { name: string; role: string }[];
  method: "SCA" | "DUAL_CONTROL";
  conditional: boolean;
  approvalHash: string;
}

export interface IntentCommittedData extends TxFields {
  intentHash: string;
  tier: Tier;
}

export interface LegSentData extends Hop {
  hop: number;
  rail: string;
  durationMs: number;
  /** Extra field sent by the engine: what this leg is, in words. */
  label?: string;
}

export interface LegSettledData {
  hop: number;
  at: InstitutionId;
}

export interface EscrowDepositedData extends TxFields {
  amount: string;
  token: string;
  expiresAt: string;
}

export interface PaymentHeldData {
  hop: number;
  at: "escrow" | "bank";
  tier: Tier;
  headline: string;
  reasons: Reason[];
  protection: string;
  nextStep: string;
  expiresAt: string;
}

export interface VerificationRequestedData {
  contactName: string;
  contactMasked: string;
  contactSince: string;
  channel: string;
  simSwapChecked: boolean;
  simSwapRecent: boolean;
}

export interface VerificationRecordedData extends TxFields {
  result: "CONFIRMED" | "DENIED";
  answerText: string;
}

export interface IntentRevokedData extends TxFields {
  reasonCode: string;
  by: string;
}

export interface EscrowMovedData extends TxFields {
  to: InstitutionId;
  amount: string;
}

export type IntentExecutedData = TxFields;

export interface PaymentCreditedData {
  at: InstitutionId;
  feesEur: number;
  routeCostEur: number;
  swiftRouteCostEur: number;
  elapsedLabel: string;
}

export interface PaymentStoppedData {
  headline: string;
  detail: string;
}

export interface AttackAttemptedData {
  attack: string;
  description: string;
  by: string;
}

export interface TxRevertedData {
  function: string;
  reason: string;
  txHash: string | null;
  explorerUrl: string | null;
  /** Extra field sent by the engine: the sentence to show. */
  text?: string;
}

export interface EventDataMap {
  "session.reset": SessionResetData;
  "system.mode": SystemModeData;
  "scenario.started": ScenarioStartedData;
  "payment.created": PaymentCreatedData;
  "norms.checked": NormsCheckedData;
  "risk.scored": RiskScoredData;
  "route.selected": RouteSelectedData;
  "approval.granted": ApprovalGrantedData;
  "intent.committed": IntentCommittedData;
  "leg.sent": LegSentData;
  "leg.settled": LegSettledData;
  "escrow.deposited": EscrowDepositedData;
  "payment.held": PaymentHeldData;
  "verification.requested": VerificationRequestedData;
  "verification.recorded": VerificationRecordedData;
  "intent.revoked": IntentRevokedData;
  "escrow.refunded": EscrowMovedData;
  "escrow.released": EscrowMovedData;
  "intent.executed": IntentExecutedData;
  "payment.credited": PaymentCreditedData;
  "payment.stopped": PaymentStoppedData;
  "attack.attempted": AttackAttemptedData;
  "tx.reverted": TxRevertedData;
}

export type KnownEventType = keyof EventDataMap;

export const KNOWN_EVENT_TYPES: readonly KnownEventType[] = [
  "session.reset",
  "system.mode",
  "scenario.started",
  "payment.created",
  "norms.checked",
  "risk.scored",
  "route.selected",
  "approval.granted",
  "intent.committed",
  "leg.sent",
  "leg.settled",
  "escrow.deposited",
  "payment.held",
  "verification.requested",
  "verification.recorded",
  "intent.revoked",
  "escrow.refunded",
  "escrow.released",
  "intent.executed",
  "payment.credited",
  "payment.stopped",
  "attack.attempted",
  "tx.reverted",
];

/** Declared in the schema for later versions, never emitted in v0. The web keeps them in the feed only. */
export const RESERVED_EVENT_TYPES: readonly string[] = [
  "approval.required",
  "leg.rejected",
  "case.ready",
  "case.action",
  "alert.raised",
  "cluster.detected",
  "breaker.on",
  "breaker.off",
  "rail.down",
  "rail.up",
  "killswitch.on",
  "guardian.incident",
  "confidential.transfer",
  "root.anchored",
  "traffic.sample",
];

// ---------------------------------------------------------------- envelope

export interface Envelope<T extends string = string, D = Record<string, unknown>> {
  v: number;
  seq: number;
  id: string;
  ts: string;
  type: T;
  paymentId: string | null;
  simulated: boolean;
  data: D;
}

export type EventOf<K extends KnownEventType> = Envelope<K, EventDataMap[K]>;
export type KnownEvent = { [K in KnownEventType]: EventOf<K> }[KnownEventType];
/** Any other event type (reserved names, or types added by a later engine). */
export type UnknownEvent = Envelope<string, Record<string, unknown>>;
export type SyloEvent = KnownEvent | UnknownEvent;

const KNOWN = new Set<string>(KNOWN_EVENT_TYPES);

export function isKnownEvent(event: SyloEvent): event is KnownEvent {
  return KNOWN.has(event.type);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Checks the envelope only (the engine validates `data` against the schema). Returns null when it is not an event. */
export function parseEvent(raw: unknown): SyloEvent | null {
  if (!isRecord(raw)) return null;
  const { seq, type } = raw;
  if (typeof type !== "string" || type === "") return null;
  if (typeof seq !== "number" || !Number.isFinite(seq) || seq < 0) return null;
  return {
    v: typeof raw.v === "number" ? raw.v : SCHEMA_VERSION,
    seq,
    id: typeof raw.id === "string" ? raw.id : `evt-${String(seq).padStart(6, "0")}`,
    ts: typeof raw.ts === "string" ? raw.ts : "",
    type,
    paymentId: typeof raw.paymentId === "string" ? raw.paymentId : null,
    simulated: raw.simulated === true,
    data: isRecord(raw.data) ? raw.data : {},
  } as SyloEvent;
}

export function parseEventJson(text: string): SyloEvent | null {
  try {
    return parseEvent(JSON.parse(text));
  } catch {
    return null;
  }
}

/** One event per line (spec/fixtures/*.jsonl). Lines that are not events are skipped. */
export function parseJsonl(text: string): SyloEvent[] {
  const events: SyloEvent[] = [];
  for (const line of text.split(/\r?\n/)) {
    if (line.trim() === "") continue;
    const event = parseEventJson(line);
    if (event) events.push(event);
  }
  return events;
}
