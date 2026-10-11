import type { FeedItem } from "./store";
import type { SyloEvent } from "./events";

const institutionNames: Record<string, string> = {
  payer_rhone: "Rhône Cosmétiques",
  bank_fr: "Banque Hexagone",
  casp_eu: "EuroLedger CASP",
  corr_uk: "Thames Correspondent Bank",
  payout_nl: "Meridian Payouts",
  remit_fr: "QuickRemit",
  vasp_gh: "Kente Digital Assets",
  bank_gh: "Gold Coast Commercial Bank",
  momo_gh: "AccraPay Wallets",
  supplier_ssx: "Savanna Shea Exports",
  mule_bank: "Volta Rural Bank",
};

function text(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function number(value: unknown, fallback = 0): number {
  return typeof value === "number" ? value : fallback;
}

function nameFor(id: unknown): string {
  const key = text(id);
  return institutionNames[key] ?? key.replaceAll("_", " ");
}

export type OutcomeTone = "success" | "warning" | "danger" | "neutral";

const VERIFICATION_BADGES: Record<string, { label: string; tone: OutcomeTone }> = {
  CONFIRMED: { label: "Confirmed", tone: "success" },
  DENIED: { label: "Denied", tone: "danger" },
};

const TIER_BADGES: Record<string, { label: string; tone: OutcomeTone }> = {
  LOW: { label: "Low risk", tone: "success" },
  MEDIUM: { label: "Medium risk", tone: "warning" },
  HIGH: { label: "High risk", tone: "warning" },
  CRITICAL: { label: "Critical", tone: "danger" },
};

/** Badge for events whose status comes from a structured outcome field; null for other event types. */
export function outcomeBadge(
  item: Pick<FeedItem, "type" | "outcome">,
): { label: string; tone: OutcomeTone } | null {
  if (item.type === "verification.recorded") {
    return (item.outcome && VERIFICATION_BADGES[item.outcome]) || { label: "Recorded", tone: "neutral" };
  }
  if (item.type === "risk.scored") {
    return (item.outcome && TIER_BADGES[item.outcome]) || { label: "Scored", tone: "neutral" };
  }
  return null;
}

export function describe(
  event: SyloEvent,
): Omit<FeedItem, "seq" | "ts" | "simulated"> {
  const data = event.data as Record<string, unknown>;
  const txHash = typeof data.txHash === "string" ? data.txHash : undefined;
  const explorerUrl =
    typeof data.explorerUrl === "string" || data.explorerUrl === null
      ? data.explorerUrl
      : undefined;
  let family: FeedItem["family"] = "system";
  let label = `Event received: ${event.type}`;
  let outcome: string | undefined;

  switch (event.type) {
    case "session.reset":
      label = "Session reset";
      break;
    case "system.mode":
      label = `Mode: risk ${text(data.risk)}, chain ${text(data.chain)}, rails ${text(data.rails)}`;
      break;
    case "scenario.started":
      family = "decision";
      label = `Scenario started: ${text(data.scenario)}`;
      break;
    case "payment.created": {
      family = "decision";
      const beneficiary = data.beneficiary as Record<string, unknown> | undefined;
      const amount = data.amount as Record<string, unknown> | undefined;
      label = `Payment received: ${text(amount?.currency)} ${text(amount?.value)} for ${text(beneficiary?.payeeName)}`;
      break;
    }
    case "norms.checked": {
      family = "decision";
      const routes = Array.isArray(data.routes) ? data.routes : [];
      const excluded = routes.find((route) => {
        const candidate = route as Record<string, unknown>;
        return candidate.status === "EXCLUDED";
      }) as Record<string, unknown> | undefined;
      label = excluded
        ? `Norms checked: ${text(excluded.routeId)} excluded by ${text(excluded.excludedBy, "policy")}`
        : `Norms checked: ${routes.length} routes evaluated`;
      break;
    }
    case "risk.scored":
      family = "decision";
      label = `Risk ${number(data.score)} · ${text(data.tier)}`;
      outcome = text(data.tier) || undefined;
      break;
    case "route.selected":
      family = "decision";
      label = `Route selected: ${text(data.name)} · ${text(data.etaLabel)}`;
      break;
    case "approval.granted": {
      family = "decision";
      const approvers = Array.isArray(data.by)
        ? data.by
            .map((entry) => text((entry as Record<string, unknown>).name))
            .filter(Boolean)
            .join(" and ")
        : "";
      label = `Approval granted${approvers ? ` by ${approvers}` : ""}`;
      break;
    }
    case "intent.committed":
      family = "chain";
      label = "Payment intent committed on Avalanche";
      break;
    case "leg.sent":
      family = "leg";
      label = `Leg ${number(data.hop) + 1} sent: ${nameFor(data.from)} → ${nameFor(data.to)}${data.kind === "chain" ? " on Avalanche" : ""}`;
      break;
    case "leg.settled":
      family = "leg";
      label = `Leg ${number(data.hop) + 1} settled at ${nameFor(data.at)}`;
      break;
    case "escrow.deposited":
      family = "chain";
      label = `EUR ${text(data.amount)} locked in tEURC escrow`;
      break;
    case "payment.held":
      family = "alert";
      label = text(data.headline, "Payment held for review");
      break;
    case "case.ready":
      family = "alert";
      label = `Analyst case file ready · ${text(data.typology, "case")}`;
      break;
    case "verification.requested":
      family = "alert";
      label = `Known-contact check requested for ${text(data.contactName)}`;
      break;
    case "verification.recorded":
      family = "alert";
      label = text(data.answerText, `Supplier response: ${text(data.result)}`);
      outcome = text(data.result) || undefined;
      break;
    case "intent.revoked":
      family = "chain";
      label = "Payment intent revoked on-chain";
      break;
    case "escrow.refunded":
      family = "chain";
      label = `Escrow refunded to ${nameFor(data.to)}`;
      break;
    case "escrow.released":
      family = "chain";
      label = `Escrow released to ${nameFor(data.to)}`;
      break;
    case "intent.executed":
      family = "chain";
      label = "Payment intent marked executed on-chain";
      break;
    case "payment.credited":
      family = "decision";
      label = `Payment credited at ${nameFor(data.at)} · fees €${number(data.feesEur)}`;
      break;
    case "payment.stopped":
      family = "alert";
      label = text(data.headline, "Payment stopped");
      break;
    case "attack.attempted":
      family = "attack";
      label = text(data.description, "Attack attempt started");
      break;
    case "leg.rejected":
      family = "attack";
      label = `Leg ${number(data.hop) + 1} rejected on ${text(data.rail)}: ${text(data.reason)}`;
      break;
    case "tx.reverted":
      family = "attack";
      label = `${text(data.function, "Transaction")}() reverted: ${text(data.reason)}`;
      break;
    case "rail.down":
      family = "alert";
      label = `${text(data.name, text(data.routeId))} unavailable: ${text(data.reason)}`;
      break;
    case "rail.up":
      family = "system";
      label = `${text(data.name, text(data.routeId))} restored`;
      break;
    case "killswitch.on":
      family = "attack";
      label = `Kill switch on ${text(data.name, text(data.adapter))}: ${text(data.reason)}`;
      break;
    case "guardian.incident":
      family = "attack";
      label = `${text(data.headline, "Guardian incident")} · ${text(data.incidentId)}`;
      break;
    case "traffic.sample":
      family = "system";
      label = text(data.text, "Network traffic sample received");
      break;
    case "cluster.detected":
      family = "alert";
      label = `Sample cluster ${text(data.clusterId)} · ${number(data.accounts)} accounts · ${number(data.agents)} agents`;
      break;
    case "breaker.on":
      family = "alert";
      label = text(data.text, `Circuit breaker ${text(data.breakerId)} enabled`);
      break;
    case "breaker.off":
      family = "system";
      label = `Circuit breaker ${text(data.breakerId)} ${text(data.reason).toLowerCase()}`;
      break;
    case "alert.raised":
      family = "alert";
      label = `${text(data.channel)} alert to ${text(data.to)}: ${text(data.text)}`;
      break;
  }

  return {
    type: event.type,
    family,
    text: label,
    ...(txHash ? { txHash } : {}),
    ...(explorerUrl !== undefined ? { explorerUrl } : {}),
    ...(outcome ? { outcome } : {}),
    ...(typeof data.function === "string" ? { functionName: data.function } : {}),
    ...(typeof data.reason === "string" ? { reasonCode: data.reason } : {}),
    ...(typeof data.incidentId === "string" ? { incidentId: data.incidentId } : {}),
  };
}
