import { CREDITED_COLOR, NEUTRAL_COLOR, tierColor, withAlpha } from "@/lib/colors";
import { institutionName } from "@/lib/geo";
import { activeHop, formatEur, formatMoney, shortHash, type ViewState } from "@/lib/store";

/** "Rhône Cosmétiques SAS" -> "Rhône Cosmétiques" (display only). */
function shortName(name: string): string {
  return name.replace(/[\s,]+(SAS|SA|SARL|Ltd\.?|Limited|LLC|Inc\.?|GmbH)$/i, "");
}

/** What the payment is doing now, in words taken from the view state and the events. */
function statusLine(state: ViewState): { label: string; detail: string; color: string } {
  const { payment, hops, held, verification, revocation, escrow } = state;
  const amber = tierColor(held?.tier ?? payment.tier);
  switch (payment.status) {
    case "idle":
      return { label: "Idle", detail: "No payment in progress", color: NEUTRAL_COLOR };
    case "deciding": {
      const step = payment.sealed
        ? "Intent sealed on-chain"
        : state.approval
          ? "Approved"
          : state.selectedRouteId
            ? "Route selected"
            : payment.score !== null
              ? "Risk scored"
              : state.routes.length > 0
                ? "Norms checked"
                : payment.payer
                  ? "Order received"
                  : "Scenario started";
      return { label: "Deciding", detail: step, color: "#38bdf8" };
    }
    case "in_transit": {
      const hop = activeHop(state);
      const settled = hops.filter((item) => item.state === "settled").length;
      const detail = hop
        ? `Leg ${hop.index + 1} of ${hops.length}: ${institutionName(hop.from)} → ${institutionName(hop.to)}`
        : `${settled} of ${hops.length} legs settled`;
      return { label: "In transit", detail, color: "#60a5fa" };
    }
    case "awaiting_supplier":
      return {
        label: "Held",
        detail: verification ? `Waiting for the answer of ${verification.contactName} (${verification.channel})` : "Waiting for the supplier",
        color: amber,
      };
    case "held": {
      const detail = revocation
        ? escrow?.status === "refunded"
          ? `Revoked on-chain · refund sent to ${institutionName(escrow.to)}`
          : "Revoked on-chain"
        : verification?.result
          ? `Supplier answer: ${verification.result}`
          : (held?.headline ?? "");
      return { label: "Held", detail, color: amber };
    }
    case "stopped":
      return { label: "Stopped", detail: payment.stopped?.headline ?? "", color: CREDITED_COLOR };
    case "credited": {
      const credited = payment.credited;
      return { label: "Credited", detail: credited ? `at ${institutionName(credited.at)} · ${credited.elapsedLabel}` : "", color: CREDITED_COLOR };
    }
  }
}

export default function PaymentCard({ state }: { state: ViewState }) {
  const { payment, route } = state;
  const status = statusLine(state);
  const chip = tierColor(payment.tier);
  const sealed = payment.sealed;

  if (payment.status === "idle") {
    return (
      <section aria-label="Payment" className="w-[560px] max-w-full rounded-xl border border-white/10 bg-slate-950/75 px-5 py-3 text-center shadow-xl shadow-black/40 backdrop-blur-md">
        <p className="text-sm font-semibold text-slate-100">No payment in progress</p>
        <p className="mt-0.5 text-xs text-slate-400">Run a scenario: the payment appears here and travels across the globe.</p>
      </section>
    );
  }

  return (
    <section aria-label="Payment" className="w-[560px] max-w-full rounded-xl border border-white/10 bg-slate-950/75 px-5 py-3 shadow-xl shadow-black/40 backdrop-blur-md">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="truncate text-base font-semibold text-slate-50">
            {payment.payer && payment.beneficiary ? `${shortName(payment.payer.name)} → ${shortName(payment.beneficiary.payeeName)}` : "Payment order incoming…"}
          </h1>
          {payment.beneficiary && !payment.beneficiary.knownAccount && (
            <p className="text-xs font-semibold text-amber-400">new account: {payment.beneficiary.accountHolder}</p>
          )}
          <p className="mt-0.5 text-xs text-slate-400">
            {[payment.id, payment.invoiceRef ? `invoice ${payment.invoiceRef}` : null, payment.purpose].filter(Boolean).join(" · ")}
          </p>
        </div>
        <p className="shrink-0 text-xl font-semibold tabular-nums text-slate-50">{payment.amount ? formatMoney(payment.amount.value, payment.amount.currency) : ""}</p>
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px] text-slate-200">
        {payment.tier && (
          <span className="rounded-full border px-2 py-0.5 text-xs font-semibold" style={{ borderColor: chip, color: chip, backgroundColor: withAlpha(chip, 0.12) }}>
            {payment.tier}
            {payment.score !== null ? ` · ${payment.score}/100` : ""}
          </span>
        )}
        {route && (
          <span>
            {route.routeId} · {route.name}
          </span>
        )}
        {route && (
          <span className="text-slate-400">
            Fees {formatEur(route.feesEur)} · ETA {route.etaLabel}
          </span>
        )}
      </div>

      <p className="mt-2 flex items-baseline gap-2 text-sm">
        <span className="shrink-0 rounded px-1.5 py-0.5 text-xs font-semibold uppercase tracking-wide" style={{ color: status.color, backgroundColor: withAlpha(status.color, 0.14) }}>
          {status.label}
        </span>
        <span className="text-slate-100">{status.detail}</span>
      </p>

      {sealed && (
        <p className="mt-1.5 text-xs text-slate-400">
          Sealed on Avalanche ·{" "}
          {sealed.explorerUrl ? (
            <a href={sealed.explorerUrl} target="_blank" rel="noopener noreferrer" className="font-mono text-violet-300 underline decoration-dotted">
              {shortHash(sealed.txHash)}
            </a>
          ) : (
            <span className="font-mono text-violet-300" title={sealed.txHash ?? undefined}>
              {shortHash(sealed.txHash)}
            </span>
          )}
          {sealed.simulated ? " · simulated" : ""}
        </p>
      )}

      {state.held === null && payment.reasons.length > 0 && (
        <ul className="mt-2 space-y-0.5 border-t border-white/10 pt-2 text-xs text-slate-300">
          {payment.reasons.map((reason, index) => (
            <li key={index} className="flex gap-2">
              <span className="mt-px h-4 w-4 shrink-0 rounded bg-white/10 text-center text-[10px] font-semibold leading-4 text-slate-200">{reason.ref}</span>
              <span>{reason.text}</span>
            </li>
          ))}
        </ul>
      )}
      {state.held === null && route?.reason && <p className="mt-1.5 text-xs text-slate-400">{route.reason}</p>}
    </section>
  );
}
