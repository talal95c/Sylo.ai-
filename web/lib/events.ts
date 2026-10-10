// TypeScript mirror of spec/events.schema.json (v1). The spec only grows: unknown fields and
// unknown event types must be tolerated, never rejected.

export type InstitutionId = string;
export type HopKind = "bank" | "chain" | "wallet";
export type Tier = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";

export interface Hop {
  from: InstitutionId;
  to: InstitutionId;
  kind: HopKind;
}

export interface Reason {
  ref: string;
  text: string;
  ruleId?: string | null;
}

export interface TxRef {
  txHash: string;
  explorerUrl: string | null;
}

export interface SystemMode {
  risk: "rules" | "model";
  chain: "mock" | "fuji";
  llm: "off" | "cached" | "live";
  rails: "simulated";
  degraded: string[];
  bootId?: string;
}

export interface ScenarioStarted {
  scenario: "legit" | "diverted";
  speed: number;
  auto: boolean;
}

export interface Beneficiary {
  payeeName: string;
  accountHolder: string;
  accountMasked: string;
  institutionId: InstitutionId;
  knownPayee: boolean;
  knownAccount: boolean;
}

export interface PaymentCreated {
  uetr: string;
  payer: { id: string; name: string; institutionId: InstitutionId };
  beneficiary: Beneficiary;
  amount: { value: string; currency: string };
  purpose: string;
  invoiceRef: string;
  provenance: string;
  senderDomain?: string;
}

export interface NormsRoute {
  routeId: string;
  name: string;
  settlement: string;
  hops: Hop[];
  status: "PASS" | "EXCLUDED";
  excludedBy?: string;
  reason?: string;
  legalRef?: string;
}

export interface NormsChecked {
  packVersion: string;
  routes: NormsRoute[];
  signals: { code: string; text: string; ruleId: string }[];
  taxNotices: { text: string; reference: string }[];
}

export interface RiskScored {
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

export interface RouteSelected {
  routeId: string;
  name: string;
  settlement: string;
  tier: Tier;
  scores: RouteScore[];
  reason: string;
  feesEur: number;
  etaLabel: string;
  priceOfSafetyEur: number;
  hops?: Hop[];
}

export interface ApprovalGranted {
  by: { name: string; role: string }[];
  method: "SCA" | "DUAL_CONTROL";
  conditional: boolean;
  approvalHash: string;
}

export interface IntentCommitted extends TxRef {
  intentHash: string;
  tier: Tier;
}

export interface LegSent {
  hop: number;
  from: InstitutionId;
  to: InstitutionId;
  kind: HopKind;
  rail: string;
  durationMs: number;
}

export interface LegSettled {
  hop: number;
  at: InstitutionId;
}

export interface EscrowDeposited extends TxRef {
  amount: string;
  token: string;
  expiresAt: string;
}

export interface PaymentHeld {
  hop: number;
  at: "escrow" | "bank";
  tier: Tier;
  headline: string;
  reasons: Reason[];
  protection: string;
  nextStep: string;
  expiresAt: string;
}

export interface VerificationRequested {
  contactName: string;
  contactMasked: string;
  contactSince: string;
  channel: "SMS";
  simSwapChecked: boolean;
  simSwapRecent: boolean;
}

export interface VerificationRecorded extends TxRef {
  result: "CONFIRMED" | "DENIED";
  answerText: string;
}

export interface IntentRevoked extends TxRef {
  reasonCode: string;
  by: string;
}

export interface EscrowMoved extends TxRef {
  to: InstitutionId;
  amount: string;
}

export interface PaymentCredited {
  at: InstitutionId;
  feesEur: number;
  routeCostEur: number;
  swiftRouteCostEur: number;
  elapsedLabel: string;
}

export interface PaymentStopped {
  headline: string;
  detail: string;
}

export interface AttackAttempted {
  attack: string;
  description: string;
  by: string;
}

export interface TxReverted {
  function: string;
  reason: string;
  txHash: string | null;
  explorerUrl: string | null;
}

interface EventData {
  "session.reset": Record<string, never>;
  "system.mode": SystemMode;
  "scenario.started": ScenarioStarted;
  "payment.created": PaymentCreated;
  "norms.checked": NormsChecked;
  "risk.scored": RiskScored;
  "route.selected": RouteSelected;
  "approval.granted": ApprovalGranted;
  "intent.committed": IntentCommitted;
  "leg.sent": LegSent;
  "leg.settled": LegSettled;
  "escrow.deposited": EscrowDeposited;
  "payment.held": PaymentHeld;
  "verification.requested": VerificationRequested;
  "verification.recorded": VerificationRecorded;
  "intent.revoked": IntentRevoked;
  "escrow.refunded": EscrowMoved;
  "escrow.released": EscrowMoved;
  "intent.executed": TxRef;
  "payment.credited": PaymentCredited;
  "payment.stopped": PaymentStopped;
  "attack.attempted": AttackAttempted;
  "tx.reverted": TxReverted;
}

export type KnownType = keyof EventData;

export interface Envelope<T extends string = string, D = unknown> {
  v: 1;
  seq: number;
  id: string;
  ts: string;
  type: T;
  paymentId: string | null;
  simulated: boolean;
  data: D;
}

/** Any message from the stream or a fixture, including types this client does not know yet. */
export type SyloEvent = Envelope;

export type KnownEvent = { [K in KnownType]: Envelope<K, EventData[K]> }[KnownType];

const KNOWN_TYPES: ReadonlySet<string> = new Set<KnownType>([
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
]);

export function isKnown(event: SyloEvent): event is KnownEvent {
  return KNOWN_TYPES.has(event.type);
}

export function parseJsonl(text: string): SyloEvent[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0)
    .map((line) => JSON.parse(line) as SyloEvent);
}
