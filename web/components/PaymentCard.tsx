import { HOP_COLORS, REFUND_COLOR, SAFE_COLOR, SIGNAL_COLOR, tierColor, withAlpha } from "@/lib/colors";
import { displayName, formatAmount, formatEur, shortHash } from "@/lib/format";
import type { Institution } from "@/lib/geo";
import type { HopView, PaymentStatus, ViewState } from "@/lib/store";

interface PaymentCardProps {
  state: ViewState;
  institutions: Record<string, Institution>;
}

const FLAP_TEXT: Record<PaymentStatus, string> = {
  idle: "Ready",
  deciding: "Checking",
  in_transit: "In transit",
  held: "Held",
  awaiting_supplier: "Held",
  stopped: "Stopped",
  credited: "Credited",
};

function flapColor(state: ViewState): string {
  switch (state.payment.status) {
    case "idle":
      return "#8b9bb4";
    case "deciding":
      return SIGNAL_COLOR;
    case "in_transit":
      return HOP_COLORS.bank;
    case "held":
    case "awaiting_supplier":
      return tierColor(state.payment.tier);
    case "stopped":
    case "credited":
      return SAFE_COLOR;
  }
}

function statusLine(state: ViewState, name: (id: string) => string): string {
  const { payment, hops } = state;
  switch (payment.status) {
    case "idle":
      return "Choose a scenario in the demo controls to send a payment.";
    case "deciding":
      return "Checking the corridor rules, the fraud risk and the cheapest safe route…";
    case "in_transit": {
      const active = hops.find((h) => h.state === "active");
      return active
        ? `In transit · leg ${active.index + 1} of ${hops.length}: ${name(active.from)} → ${name(active.to)}`
        : "In transit";
    }
    case "awaiting_supplier": {
      const contact = state.verification.requested?.contactName;
      return contact
        ? `Held in escrow on Avalanche · asking ${contact} on the number on file`
        : "Held in escrow on Avalanche · asking the supplier";
    }
    case "held":
      if (state.chain.refund) return `Refunding the escrow to ${name(state.chain.refund.to)}…`;
      if (state.chain.lock === "revoked") return "Revoked on Avalanche · the escrow is refunding the payer";
      if (state.verification.recorded?.result === "CONFIRMED") return "Supplier confirmed · releasing the escrow";
      return state.held?.at === "bank" ? "Held at the bank" : "Held in escrow on Avalanche";
    case "stopped":
      return state.stopped?.headline ?? "Payment stopped.";
    case "credited": {
      const credited = state.credited;
      if (!credited) return "Credited";
      return `Credited at ${name(credited.at)} · ${formatEur(credited.routeCostEur)} all-in against ${formatEur(credited.swiftRouteCostEur)} via SWIFT · ${credited.elapsedLabel}`;
    }
  }
}

function segmentColor(hop: HopView, state: ViewState): string {
  switch (hop.state) {
    case "pending":
      return hop.kind === "chain" ? withAlpha(HOP_COLORS.chain, 0.35) : "rgba(148, 163, 184, 0.2)";
    case "active":
      return state.held?.hop === hop.index && state.chain.lock !== "open" ? tierColor("MEDIUM") : HOP_COLORS[hop.kind];
    case "settled":
      return tierColor(state.payment.tier);
    case "refunded":
      return REFUND_COLOR;
  }
}

export default function PaymentCard({ state, institutions }: PaymentCardProps) {
  const { payment, selection, hops, chain } = state;
  const name = (id: string) => institutions[id]?.short ?? id;
  const city = (id: string | undefined) => (id ? (institutions[id]?.city ?? id) : "");
  const color = flapColor(state);
  const idle = payment.status === "idle";
  const destination = hops.at(-1)?.to ?? payment.beneficiary?.institutionId;
  const stops = hops.length ? [hops[0].from, ...hops.map((h) => h.to)] : [];

  return (
    <section className="panel payment-card" aria-label="Payment" aria-live="polite">
      <header className="payment-card__header">
        <p className="eyebrow">
          {idle ? "Sylo.ai · France → Ghana corridor" : `${payment.id ?? "Payment"} · invoice ${payment.invoiceRef ?? "…"}`}
        </p>
        <span key={`${state.run}-${payment.status}`} className="flap" style={{ color, borderColor: withAlpha(color, 0.45) }}>
          {FLAP_TEXT[payment.status]}
        </span>
      </header>

      <h1 className="payment-card__title">
        {payment.payer && payment.beneficiary
          ? `${displayName(payment.payer.name)} → ${displayName(payment.beneficiary.payeeName)}`
          : idle
            ? "Ready for the next payment"
            : "New payment order…"}
      </h1>
      {payment.beneficiary && !payment.beneficiary.knownAccount && (
        <p className="payment-card__warning">new account: {payment.beneficiary.accountHolder}</p>
      )}

      {payment.amount && (
        <div className="payment-card__facts">
          <span className="payment-card__amount">{formatAmount(payment.amount.value, payment.amount.currency)}</span>
          {payment.payer && destination && (
            <span className="payment-card__cities">
              {city(payment.payer.institutionId)} → {city(destination)}
            </span>
          )}
        </div>
      )}

      {(payment.tier || selection) && (
        <div className="payment-card__route">
          {payment.tier && payment.score !== null && (
            <span className="tier-chip" style={{ color: tierColor(payment.tier), borderColor: withAlpha(tierColor(payment.tier), 0.5), background: withAlpha(tierColor(payment.tier), 0.12) }}>
              {payment.tier} · {payment.score}
            </span>
          )}
          {selection && (
            <span>
              <strong>{selection.routeId}</strong> {selection.name} · fees {formatEur(selection.feesEur)} · ETA {selection.etaLabel}
              {selection.tier !== "LOW" && ` · price of safety ${formatEur(selection.priceOfSafetyEur)}`}
            </span>
          )}
        </div>
      )}

      {hops.length > 0 && (
        <div className="itinerary" aria-label={`Route with ${hops.length} legs`}>
          <ol className="itinerary__legs">
            {hops.map((hop) => (
              <li
                key={hop.index}
                className={`itinerary__leg itinerary__leg--${hop.state}`}
                style={{ background: segmentColor(hop, state) }}
                aria-label={`Leg ${hop.index + 1}: ${name(hop.from)} to ${name(hop.to)}${hop.kind === "chain" ? " on Avalanche" : ""}, ${hop.state}`}
                title={`${name(hop.from)} → ${name(hop.to)}${hop.kind === "chain" ? " · Avalanche C-Chain" : ""}`}
              />
            ))}
          </ol>
          <ol className="itinerary__stops" aria-hidden="true">
            {stops.map((stop, index) => (
              <li key={`${stop}-${index}`}>{city(stop)}</li>
            ))}
          </ol>
        </div>
      )}

      <p className="payment-card__status" style={{ color: payment.status === "stopped" || payment.status === "credited" ? SAFE_COLOR : undefined }}>
        {statusLine(state, name)}
      </p>

      {chain.intent && (
        <p className="payment-card__seal">
          Sealed on Avalanche ·{" "}
          {chain.intent.explorerUrl ? (
            <a href={chain.intent.explorerUrl} target="_blank" rel="noreferrer">
              {shortHash(chain.intent.intentHash)}
            </a>
          ) : (
            <span>{shortHash(chain.intent.intentHash)}</span>
          )}
          {chain.intent.simulated && " · simulated"}
        </p>
      )}
    </section>
  );
}
