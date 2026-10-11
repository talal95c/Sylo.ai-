export type InstitutionId =
  | "payer_rhone"
  | "bank_fr"
  | "casp_eu"
  | "corr_uk"
  | "payout_nl"
  | "remit_fr"
  | "vasp_gh"
  | "bank_gh"
  | "momo_gh"
  | "supplier_ssx"
  | "mule_bank";

export type Tier = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
export type HopKind = "bank" | "chain" | "wallet";
export type RouteStatus = "PASS" | "EXCLUDED";
export type Settlement = "FIAT_HOLD" | "NONE" | "ONCHAIN_ESCROW";

export interface Hop {
  from: InstitutionId;
  to: InstitutionId;
  kind: HopKind;
}

export interface SystemModeData {
  risk: "rules" | "model";
  chain: "mock" | "fuji";
  llm: "off" | "cached" | "live";
  rails: "simulated";
  degraded: string[];
  confidential?: "off" | "simulated" | "eerc";
}

export interface PaymentParty {
  id: string;
  name: string;
  institutionId: InstitutionId;
}

export interface PaymentBeneficiary {
  payeeName: string;
  accountHolder: string;
  accountMasked: string;
  institutionId: InstitutionId;
  knownPayee: boolean;
  knownAccount: boolean;
}

export interface PaymentCreatedData {
  uetr: string;
  payer: PaymentParty;
  beneficiary: PaymentBeneficiary;
  amount: { value: string; currency: string };
  purpose: string;
  invoiceRef: string;
  provenance: string;
  senderDomain?: string;
}

export interface NormsRoute {
  routeId: string;
  name: string;
  settlement: Settlement;
  hops: Hop[];
  status: RouteStatus;
  excludedBy?: string;
  reason?: string;
  legalRef?: string;
}

export interface NormsCheckedData {
  packVersion: string;
  routes: NormsRoute[];
  signals: { code: string; text: string; ruleId: string }[];
  taxNotices: { text: string; reference: string }[];
}

export interface RiskScoredData {
  score: number;
  tier: Tier;
  rulesFired: string[];
  reasons: { ref: string; text: string; ruleId?: string | null }[];
  model: string;
  oobResolvable?: boolean;
}

export type RecommendedAction =
  | "CONFIRM_REVOCATION"
  | "RELEASE_AFTER_CONFIRMATION"
  | "ESCALATE_AML"
  | "NO_ACTION";

export interface CaseReadyData {
  summary: string;
  sentences?: { text: string; refs: string[] }[];
  timeline?: { at: string; eventId: string; text: string }[];
  typology: string;
  recommendedAction: RecommendedAction;
  explanation: string;
  citations: { ref: string; source: string }[];
  reportDraft?: string | null;
  llm: "off" | "cached" | "live";
  promptVersion: string;
  model: string;
}

export interface RouteSelectedData {
  routeId: string;
  name: string;
  settlement: Settlement;
  tier: Tier;
  scores: { routeId: string; s: number | null; excludedBy: string | null }[];
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

export interface IntentCommittedData {
  intentHash: string;
  tier: Tier;
  txHash: string;
  explorerUrl: string | null;
}

export interface LegSentData extends Hop {
  hop: number;
  rail: string;
  durationMs: number;
}

export interface LegSettledData {
  hop: number;
  at: InstitutionId;
}

export interface ChainTransactionData {
  txHash: string;
  explorerUrl: string | null;
}

export interface EscrowDepositedData extends ChainTransactionData {
  amount: string;
  token: "tEURC";
  expiresAt: string;
}

export interface PaymentHeldData {
  hop: number;
  at: "escrow" | "bank";
  tier: Tier;
  headline: string;
  reasons: { ref: string; text: string; ruleId?: string | null }[];
  protection: string;
  nextStep: string;
  expiresAt: string;
}

export interface VerificationRequestedData {
  contactName: string;
  contactMasked: string;
  contactSince: string;
  channel: "SMS";
  simSwapChecked: true;
  simSwapRecent: boolean;
}

export interface VerificationRecordedData extends ChainTransactionData {
  result: "CONFIRMED" | "DENIED";
  answerText: string;
}

export interface IntentRevokedData extends ChainTransactionData {
  reasonCode: "SUPPLIER_DENIED";
  by: string;
}

export interface EscrowSettledData extends ChainTransactionData {
  to: InstitutionId;
  amount: string;
}

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
  attack: "release_revoked" | "swap_beneficiary" | "replay";
  description: string;
  by: "attacker";
}

export interface TransactionRevertedData {
  function: string;
  reason: string;
  txHash: string | null;
  explorerUrl: string | null;
}

export interface LegRejectedData {
  hop: number;
  rail: string;
  reason:
    | "INTENT_HASH_MISMATCH"
    | "NONCE_USED"
    | "REVOKED"
    | "EXPIRED"
    | "NOT_CONFIRMED"
    | "RAIL_DOWN"
    | "KILL_SWITCH";
  from?: InstitutionId;
  to?: InstitutionId;
  text?: string;
}

export interface RailDownData {
  routeId: string;
  name?: string;
  reason: string;
}

export interface RailUpData {
  routeId: string;
  name?: string;
}

export interface KillSwitchData {
  adapter: string;
  name?: string;
  reason: string;
  refusals: number;
  windowSeconds?: number;
  revoked?: string[];
}

export interface DoraIncidentDraft {
  clientsAffected: number;
  amountEur: number;
  durationMinutes: number;
  geographicSpread: string[];
  criticality: string;
  thirdParties: string[];
  major?: boolean;
  draft?: true;
}

export interface GuardianIncidentData extends ChainTransactionData {
  incidentId: string;
  rule: string;
  action: string;
  headline?: string;
  dora: DoraIncidentDraft;
}

export interface EventEnvelope<T extends string, D> {
  v: 1;
  seq: number;
  id: string;
  ts: string;
  type: T;
  paymentId: string | null;
  simulated: boolean;
  data: D;
}

export type SyloEvent =
  | EventEnvelope<"session.reset", Record<string, never>>
  | EventEnvelope<"system.mode", SystemModeData>
  | EventEnvelope<
      "scenario.started",
      { scenario: "legit" | "diverted" | "mule_wave" | "outage"; speed: number; auto: boolean }
    >
  | EventEnvelope<"payment.created", PaymentCreatedData>
  | EventEnvelope<"norms.checked", NormsCheckedData>
  | EventEnvelope<"risk.scored", RiskScoredData>
  | EventEnvelope<"route.selected", RouteSelectedData>
  | EventEnvelope<"approval.granted", ApprovalGrantedData>
  | EventEnvelope<"intent.committed", IntentCommittedData>
  | EventEnvelope<"leg.sent", LegSentData>
  | EventEnvelope<"leg.settled", LegSettledData>
  | EventEnvelope<"escrow.deposited", EscrowDepositedData>
  | EventEnvelope<"payment.held", PaymentHeldData>
  | EventEnvelope<"case.ready", CaseReadyData>
  | EventEnvelope<"verification.requested", VerificationRequestedData>
  | EventEnvelope<"verification.recorded", VerificationRecordedData>
  | EventEnvelope<"intent.revoked", IntentRevokedData>
  | EventEnvelope<"escrow.refunded", EscrowSettledData>
  | EventEnvelope<"escrow.released", EscrowSettledData>
  | EventEnvelope<"intent.executed", ChainTransactionData>
  | EventEnvelope<"payment.credited", PaymentCreditedData>
  | EventEnvelope<"payment.stopped", PaymentStoppedData>
  | EventEnvelope<"attack.attempted", AttackAttemptedData>
  | EventEnvelope<"leg.rejected", LegRejectedData>
  | EventEnvelope<"tx.reverted", TransactionRevertedData>
  | EventEnvelope<"rail.down", RailDownData>
  | EventEnvelope<"rail.up", RailUpData>
  | EventEnvelope<"killswitch.on", KillSwitchData>
  | EventEnvelope<"guardian.incident", GuardianIncidentData>
  | EventEnvelope<string, Record<string, unknown>>;
