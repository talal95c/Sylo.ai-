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
      label =
        excluded?.routeId === "R4"
          ? "Norms checked: R4 excluded (Ghana export-proceeds rule)"
          : `Norms checked: ${routes.length} routes evaluated`;
      break;
    }
    case "risk.scored":
      family = "decision";
      label = `Risk ${number(data.score)} · ${text(data.tier)}`;
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
    case "verification.requested":
      family = "alert";
      label = `Known-contact check requested for ${text(data.contactName)}`;
      break;
    case "verification.recorded":
      family = "alert";
      label = text(data.answerText, `Supplier response: ${text(data.result)}`);
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
    case "tx.reverted":
      family = "attack";
      label = `Rejected by the smart contract: ${text(data.reason)}.`;
      break;
  }

  return {
    type: event.type,
    family,
    text: label,
    ...(txHash ? { txHash } : {}),
    ...(explorerUrl !== undefined ? { explorerUrl } : {}),
  };
}
