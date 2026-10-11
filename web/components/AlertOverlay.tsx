"use client";

import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { AnimatePresence, motion } from "framer-motion";
import type { ViewState } from "@/lib/store";
import { paymentStatusView } from "@/lib/paymentStatus";
import { CSS_REFUND_COLOR, CSS_TIER_COLORS } from "@/lib/colors";
import { revertMessage } from "@/lib/revert";
import { buildQuote, secondsBetween } from "@/lib/routeQuote";
import { MarketCompare } from "./MarketCompare";
import { Savings } from "./RouteQuote";
import { ease, euros, LockIcon, Spinner } from "./ui";

const REF_LABEL: Record<string, string> = {
  V: "Provenance",
  B: "Beneficiary",
  R: "Regulation",
  N: "Network",
  G: "Geography",
  H: "History",
  P: "Payer session",
  S: "Structuring",
};

const ACTION_LABEL: Record<string, string> = {
  CONFIRM_REVOCATION: "Confirm revocation",
  RELEASE_AFTER_CONFIRMATION: "Release only after confirmation",
  ESCALATE_AML: "Escalate to AML",
  NO_ACTION: "No action",
};

const LLM_LABEL: Record<string, string> = {
  off: "template",
  cached: "Mistral · cached",
  live: "Mistral · live",
};

function AlertChip({ children, color = "var(--ink-2)" }: { children: React.ReactNode; color?: string }) {
  return (
    <span
      className="inline-flex h-6 items-center rounded-full border px-2.5 text-[11px] font-medium"
      style={{ color, borderColor: `color-mix(in srgb, ${color} 16%, white)`, background: `color-mix(in srgb, ${color} 7%, white)` }}
    >
      {children}
    </span>
  );
}

function verificationChip(state: ViewState) {
  if (state.incident) return { label: "Guardian incident", color: "var(--danger)" };
  const recorded = state.verification.recorded;
  if (recorded?.result === "DENIED") return { label: "Supplier denied", color: "var(--danger)" };
  if (recorded?.result === "CONFIRMED") return { label: "Supplier confirmed", color: "var(--low)" };
  const requested = state.verification.requested;
  if (requested) return { label: `Asking ${requested.contactName} by ${requested.channel}`, color: "var(--medium)" };
  return { label: "Verification pending", color: "var(--ink-3)" };
}

export function AlertOverlay({ state, onClose }: { state: ViewState; onClose: () => void }) {
  const [detailsFor, setDetailsFor] = useState<string | null>(null);
  const alertRef = useRef<HTMLElement>(null);
  const detailsButtonRef = useRef<HTMLButtonElement>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const held = state.held;
  const status = state.payment?.status;
  const terminal = status === "credited" || status === "stopped";
  const showHeld = Boolean(held && state.alertOpen && !terminal);
  const showOutcome = terminal && state.alertOpen;
  const receipt = buildQuote(state);
  const paymentId = state.payment?.paymentId;
  const detailsKey = `${state.feed[0]?.seq ?? 0}:${paymentId ?? "none"}:${held?.headline ?? "none"}`;
  const detailsOpen = detailsFor === detailsKey;

  const check = verificationChip(state);

  useEffect(() => {
    if (!showHeld) return;
    returnFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const frame = requestAnimationFrame(() => alertRef.current?.focus());
    return () => cancelAnimationFrame(frame);
  }, [showHeld]);

  const handleAlertKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key !== "Escape") return;
    event.preventDefault();
    if (detailsOpen) {
      setDetailsFor(null);
      detailsButtonRef.current?.focus();
      return;
    }
    onClose();
    requestAnimationFrame(() => returnFocusRef.current?.focus());
  };

  return (
    <div className="pointer-events-none absolute inset-x-0 bottom-[92px] z-20 flex justify-center px-4">
      <AnimatePresence mode="wait" initial={false}>
        {showHeld && held ? (
          <motion.section
            key="held"
            role="alertdialog"
            aria-label={held.headline}
            ref={alertRef}
            tabIndex={-1}
            onKeyDown={handleAlertKeyDown}
            initial={{ opacity: 0, y: 24, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 16, scale: 0.98 }}
            transition={{ duration: 0.45, ease }}
            data-globe-occluder="bottom"
            className="card pointer-events-auto max-h-[calc(100dvh-196px)] w-[min(560px,100%)] overflow-y-auto overscroll-contain rounded-[20px]"
          >
            <div className="h-1 w-full" style={{ background: state.incident ? "var(--danger)" : state.revoked ? "var(--danger)" : state.released ? "var(--low)" : CSS_TIER_COLORS[held.tier] }} />
            <div className="px-4 pb-4 pt-3.5">
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <h2 className="truncate text-[17px] font-semibold leading-tight">{held.headline}</h2>
                  <p className="mt-1 truncate text-[11.5px] text-ink-2" title={held.reasons[0]?.text}>{held.reasons[0]?.text}</p>
                </div>
                <button
                  ref={detailsButtonRef}
                  type="button"
                  onClick={onClose}
                  aria-label="Close alert"
                  className="grid size-7 shrink-0 place-items-center rounded-full bg-[var(--surface-2)] text-ink-2 transition hover:bg-[#ebecee] hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                >
                  <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden><path d="M2 2l6 6M8 2 2 8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" /></svg>
                </button>
              </div>

              <div className="mt-3 flex flex-wrap items-center gap-1.5">
                <AlertChip color={CSS_TIER_COLORS[held.tier]}>{held.tier} · {state.risk?.score ?? "--"}</AlertChip>
                <AlertChip color="var(--accent)">{held.at === "escrow" ? "In escrow" : "At the bank"}</AlertChip>
                <AlertChip color={check.color}>{check.label}</AlertChip>
                <button
                  type="button"
                  aria-expanded={detailsOpen}
                  aria-controls="held-alert-details"
                  onClick={() => setDetailsFor(detailsOpen ? null : detailsKey)}
                  className="ml-auto inline-flex h-7 items-center gap-1.5 rounded-md px-2 text-[11px] font-medium text-accent transition-colors hover:bg-[var(--accent-soft)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                >
                  Details
                  <svg className={`transition-transform duration-200 motion-reduce:transition-none ${detailsOpen ? "rotate-180" : ""}`} width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden>
                    <path d="m3 4.5 3 3 3-3" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </button>
              </div>

              <AnimatePresence initial={false}>
                {detailsOpen ? (
                  <motion.div
                    id="held-alert-details"
                    key="details"
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: "auto", opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    transition={{ duration: 0.22, ease }}
                    className="overflow-hidden"
                  >
                    <div className="thin-scrollbar mt-4 max-h-[30vh] overflow-x-hidden overflow-y-auto border-t border-[var(--line)] pt-4 pr-1">
                      <ul className="space-y-2">
                        {held.reasons.map((reason) => (
                          <li key={`${reason.ref}-${reason.text}`} className="flex gap-3 text-[12px] leading-snug text-ink-2">
                            <span className="h-5 shrink-0 rounded-full bg-[var(--surface-2)] px-2 text-[11px] font-medium leading-5 text-ink">{REF_LABEL[reason.ref] ?? reason.ref}</span>
                            <span>{reason.text}</span>
                          </li>
                        ))}
                      </ul>
                      <div className="mt-4 rounded-lg bg-[var(--surface-2)] p-3 text-[11.5px]">
                        <div className="text-ink-2">{held.protection}</div>
                        <div className="mt-3 border-t border-[var(--line)] pt-3"><Verification state={state} nextStep={held.nextStep} /></div>
                      </div>
                      <CaseFile state={state} />
                    </div>
                  </motion.div>
                ) : null}
              </AnimatePresence>
            </div>
          </motion.section>
        ) : showOutcome ? (
          <motion.section
            key={`outcome-${status}`}
            role="status"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 12 }}
            transition={{ duration: 0.55, ease }}
            data-globe-occluder="bottom"
            className="card pointer-events-auto flex w-[min(560px,100%)] items-center gap-4 rounded-[20px] p-4 pr-5"
          >
            <span className="grid size-10 shrink-0 place-items-center rounded-full text-white" style={{ background: status === "credited" ? "var(--low)" : state.refunded && !state.attack.reverted ? CSS_REFUND_COLOR : "var(--danger)" }}>
              {status === "credited" ? (
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden><path d="M3 8.4 6.4 11.6 13 4.6" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>
              ) : <LockIcon size={16} />}
            </span>
            <div className="min-w-0 flex-1">
              <div className="text-[14.5px] font-medium">
                {paymentStatusView(state).label}
              </div>
              <div className="mt-0.5 text-[12px] leading-snug text-ink-2">
                {status === "credited"
                  ? creditedHeadline(state) ?? creditedDetail(state)
                  : state.attack.reverted
                    ? revertMessage(state.attack.reason)
                    : state.stopped?.detail}
              </div>
              {status !== "credited" && state.attack.reverted && state.attack.reason ? (
                <span className="mt-1 block font-mono text-[11px] text-ink-3" title={state.attack.reason}>
                  {state.attack.reason}
                </span>
              ) : null}
              {status === "credited" && receipt?.swift && receipt.savedEur !== undefined ? <Savings quote={receipt} compact /> : null}
              {status === "credited" && receipt ? <MarketCompare quote={receipt} /> : null}
            </div>
          </motion.section>
        ) : null}
      </AnimatePresence>
    </div>
  );
}

function creditedHeadline(state: ViewState): string | undefined {
  const quote = buildQuote(state);
  const reroutedFromAvalanche = quote?.rows.some(
    (row) => row.routeId === "R3" && row.excludedBy === "RAIL_DOWN",
  );
  if (quote?.routeId === "R1" && reroutedFromAvalanche) {
    const cost = state.credited?.routeCostEur ?? quote.cost;
    return `Rerouted to SWIFT: Avalanche rail was down${cost !== undefined ? ` · ${euros(cost)} all-in` : ""}`;
  }
  return undefined;
}

function creditedDetail(state: ViewState) {
  const quote = buildQuote(state);
  const credited = state.credited;
  const parts: string[] = [];
  if (quote) parts.push(`${euros(quote.cost)} ${quote.basis === "cash" ? "fees + FX" : "all-in"}${quote.swift ? ` vs ${euros(quote.swift.cost)} via SWIFT` : ""}`);
  if (credited?.elapsedLabel) parts.push(`arrives ${credited.elapsedLabel}${credited.swiftEtaLabel ? ` vs ${credited.swiftEtaLabel}` : ""}`);
  const decided = secondsBetween(state.timing.createdTs, state.timing.committedTs);
  if (decided !== undefined) parts.push(`decided in ${decided.toFixed(1)} s`);
  if (quote && quote.priceOfSafetyEur > 0) parts.push(`price of safety ${euros(quote.priceOfSafetyEur)}`);
  return parts.join(" · ");
}

function Verification({ state, nextStep }: { state: ViewState; nextStep: string }) {
  if (state.incident) {
    return <div className="font-medium text-[var(--danger)]">{state.incident.headline ?? state.incident.rule}</div>;
  }
  const requested = state.verification.requested;
  const recorded = state.verification.recorded;
  if (recorded) {
    const confirmed = recorded.result === "CONFIRMED";
    return (
      <div>
        <div className="font-medium" style={{ color: confirmed ? "var(--low)" : "var(--danger)" }}>{confirmed ? "Supplier confirmed" : "Supplier denied"}</div>
        <div className="mt-1 text-ink">{recorded.answerText}</div>
        <div className="mt-2 text-ink-3">{state.refunded ? "Funds refunded from escrow" : state.revoked ? "Revoking the intent on-chain" : state.released ? "Escrow released · payment continues" : "Recording the answer on-chain"}</div>
      </div>
    );
  }
  if (requested) {
    return (
      <div className="flex items-start gap-3">
        <Spinner size={16} color="var(--medium)" />
        <div>
          <div className="font-medium text-ink">Asking {requested.contactName} on {requested.contactMasked}</div>
          <div className="mt-0.5 text-ink-3">Known contact since {requested.contactSince} · {requested.channel} · SIM swap {requested.simSwapRecent ? "recent" : "not recent"}</div>
        </div>
      </div>
    );
  }
  return <div className="text-ink-3">{nextStep}</div>;
}

const isInvoiceScreen = (refs: string[]) => refs.some((ref) => ref.startsWith("TX-"));

function CaseFile({ state }: { state: ViewState }) {
  const file = state.caseFile;
  if (!file) return null;
  return (
    <section className="mt-3 rounded-lg border border-[var(--line)] p-3 text-[11.5px]" aria-label="Analyst case file">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-medium text-ink">Analyst case file</span>
        <span className="text-[11px] text-ink-3">{LLM_LABEL[file.llm] ?? file.llm} · advisory only</span>
      </div>
      <div className="mt-2 inline-flex rounded-full bg-[var(--surface-2)] px-2 py-1 text-[11px] text-ink-2">{ACTION_LABEL[file.recommendedAction] ?? file.recommendedAction}</div>
      {file.sentences?.length ? (
        <ul className="mt-3 space-y-1.5">
          {[...file.sentences]
            .sort((a, b) => Number(isInvoiceScreen(b.refs)) - Number(isInvoiceScreen(a.refs)))
            .map((sentence) => (
            <li key={`${sentence.text}-${sentence.refs.join("-")}`} className="leading-snug text-ink-2">
              {isInvoiceScreen(sentence.refs) ? (
                <span className="mr-1.5 rounded-full bg-[var(--surface-2)] px-1.5 py-0.5 text-[11px] font-medium text-ink">Invoice screen</span>
              ) : null}
              {sentence.text} <span className="font-mono text-[10px] text-ink-3">{sentence.refs.join(" · ")}</span>
            </li>
            ))}
        </ul>
      ) : <p className="mt-3 leading-snug text-ink-2">{file.explanation}</p>}
      {file.citations.length ? (
        <div className="mt-3 border-t border-[var(--line)] pt-2 text-[11px] text-ink-3">
          Citations: {file.citations.map((citation) => `${citation.ref} (${citation.source})`).join(" · ")}
        </div>
      ) : null}
    </section>
  );
}
