import { DANGER_COLOR, SAFE_COLOR, SIGNAL_COLOR, tierColor, withAlpha } from "@/lib/colors";
import { formatAmount } from "@/lib/format";
import type { ViewState } from "@/lib/store";

interface AlertOverlayProps {
  state: ViewState;
  names: Record<string, string>;
  onClose(): void;
}

/** Signal families of the PRD (§10.1). */
const REF_LABELS: Record<string, string> = {
  B: "Beneficiary",
  V: "Provenance and channel",
  P: "Payer session",
  G: "Geography",
  H: "Behaviour",
  N: "Network",
  S: "Structure",
  R: "Norms",
};

type Tone = "info" | "danger" | "safe";

const TONE_COLORS: Record<Tone, string> = { info: SIGNAL_COLOR, danger: DANGER_COLOR, safe: SAFE_COLOR };

function updates(state: ViewState, names: Record<string, string>): { key: string; tone: Tone; text: string }[] {
  const n = (id: string) => names[id] ?? id;
  const list: { key: string; tone: Tone; text: string }[] = [];
  const { requested, recorded } = state.verification;
  if (requested) {
    const swap = requested.simSwapRecent ? "Recent SIM swap: the answer cannot be trusted." : "No recent SIM swap.";
    list.push({
      key: "requested",
      tone: "info",
      text: `SMS sent to ${requested.contactName} on ${requested.contactMasked}, on file since ${requested.contactSince}. ${swap}`,
    });
  }
  if (recorded) {
    list.push({ key: "recorded", tone: recorded.result === "DENIED" ? "danger" : "safe", text: `Supplier answer: ${recorded.answerText}` });
  }
  if (state.chain.revocation) {
    list.push({ key: "revoked", tone: "danger", text: "Revoked on Avalanche: the signed payment can no longer be released." });
  }
  if (state.chain.refund) {
    list.push({ key: "refund", tone: "info", text: `${formatAmount(state.chain.refund.amount, "EUR")} refunded from escrow to ${n(state.chain.refund.to)}.` });
  }
  if (state.chain.release) {
    list.push({ key: "release", tone: "safe", text: `Released from escrow to ${n(state.chain.release.to)}.` });
  }
  if (state.stopped) list.push({ key: "stopped", tone: "safe", text: state.stopped.headline });
  if (state.credited) list.push({ key: "credited", tone: "safe", text: `Credited at ${n(state.credited.at)}.` });
  if (state.attack?.attempted && state.attack.description) {
    list.push({ key: "attack", tone: "danger", text: `Attack: ${state.attack.description}` });
  }
  if (state.attack?.reverted) {
    list.push({ key: "reverted", tone: "safe", text: `Rejected by the smart contract: ${state.attack.fn ?? "call"}() reverted with ${state.attack.reason}.` });
  }
  return list;
}

export default function AlertOverlay({ state, names, onClose }: AlertOverlayProps) {
  const held = state.held;
  if (!held) return null;
  const color = tierColor(held.tier);
  const live = updates(state, names);

  return (
    <section
      className="panel alert"
      role="alert"
      aria-labelledby="alert-headline"
      style={{ borderColor: withAlpha(color, 0.75), boxShadow: `0 0 0 1px ${withAlpha(color, 0.25)}, 0 24px 60px -24px ${withAlpha(color, 0.45)}` }}
    >
      <header className="alert__header">
        <span className="tier-chip" style={{ color, borderColor: withAlpha(color, 0.5), background: withAlpha(color, 0.12) }}>
          {held.tier}
          {state.payment.score !== null && ` · ${state.payment.score}`}
        </span>
        <h2 id="alert-headline" className="alert__headline">
          {held.headline}
        </h2>
        <button type="button" className="icon-button" onClick={onClose} aria-label="Close the alert">
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true">
            <path d="M6 6l12 12M18 6L6 18" />
          </svg>
        </button>
      </header>

      <ul className="alert__reasons">
        {held.reasons.map((reason, index) => (
          <li key={`${reason.ref}-${index}`}>
            <abbr className="ref" title={REF_LABELS[reason.ref] ?? reason.ref}>
              {reason.ref}
            </abbr>
            <span>{reason.text}</span>
          </li>
        ))}
      </ul>

      <dl className="alert__plan">
        <dt>What protects the money</dt>
        <dd>{held.protection}</dd>
        <dt>What happens next</dt>
        <dd>{held.nextStep}</dd>
      </dl>

      {live.length > 0 && (
        <ol className="alert__updates" aria-live="polite">
          {live.map((update) => (
            <li key={update.key} className={update.key === "stopped" ? "alert__update--final" : undefined}>
              <span className="dot" style={{ background: TONE_COLORS[update.tone] }} aria-hidden="true" />
              <span style={update.tone === "safe" ? { color: SAFE_COLOR } : undefined}>{update.text}</span>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
