"use client";

import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import type { ViewState } from "@/lib/store";
import { REFUND_COLOR, TIER_COLORS } from "@/lib/colors";
import { revertMessage } from "@/lib/revert";
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
      className="inline-flex h-6 items-center rounded-full border px-2.5 text-[10.5px] font-medium"
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
  const held = state.held;
  const status = state.payment?.status;
  const terminal = status === "credited" || status === "stopped";
  const showHeld = Boolean(held && state.alertOpen && !terminal);
  const showOutcome = terminal;
  const paymentId = state.payment?.paymentId;
  const detailsKey = `${state.feed[0]?.seq ?? 0}:${paymentId ?? "none"}:${held?.headline ?? "none"}`;
  const detailsOpen = detailsFor === detailsKey;

  const check = verificationChip(state);

  return (
    <div className="pointer-events-none absolute inset-x-0 bottom-[92px] z-20 flex justify-center px-4">
      <AnimatePresence mode="wait">
        {showHeld && held ? (
          <motion.section
            key="held"
            role="alertdialog"
            aria-label={held.headline}
            initial={{ opacity: 0, y: 24, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 16, scale: 0.98 }}
            transition={{ duration: 0.45, ease }}
            className="card pointer-events-auto w-[min(560px,100%)] overflow-hidden rounded-[20px]"
          >
            <div className="h-1 w-full" style={{ background: state.incident ? "var(--danger)" : state.revoked ? "var(--danger)" : state.released ? "var(--low)" : TIER_COLORS[held.tier] }} />
            <div className="px-4 pb-4 pt-3.5">
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <h2 className="truncate text-[17px] font-semibold leading-tight">{held.headline}</h2>
                  <p className="mt-1 truncate text-[11.5px] text-ink-2" title={held.reasons[0]?.text}>{held.reasons[0]?.text}</p>
                </div>
                <button
                  type="button"
                  onClick={onClose}
                  aria-label="Close alert"
                  className="grid size-7 shrink-0 place-items-center rounded-full bg-[var(--surface-2)] text-ink-2 transition hover:bg-[#ebecee] hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                >
                  <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden><path d="M2 2l6 6M8 2 2 8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" /></svg>
                </button>
              </div>

              <div className="mt-3 flex flex-wrap items-center gap-1.5">
                <AlertChip color={TIER_COLORS[held.tier]}>{held.tier} · {state.risk?.score ?? "--"}</AlertChip>
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
                    <div className="thin-scrollbar mt-4 max-h-[min(52vh,460px)] overflow-x-hidden overflow-y-auto border-t border-[var(--line)] pt-4 pr-1">
                      <ul className="space-y-2">
                        {held.reasons.map((reason) => (
                          <li key={`${reason.ref}-${reason.text}`} className="flex gap-3 text-[12px] leading-snug text-ink-2">
                            <span className="h-5 shrink-0 rounded-full bg-[var(--surface-2)] px-2 text-[10px] font-medium leading-5 text-ink">{REF_LABEL[reason.ref] ?? reason.ref}</span>
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
        ) : null}
      </AnimatePresence>

      <AnimatePresence mode="wait">
        {showOutcome ? (
          <motion.section
            key={`outcome-${status}`}
            role="status"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 12 }}
            transition={{ duration: 0.55, ease }}
            className="card pointer-events-auto flex w-[min(560px,100%)] items-center gap-4 rounded-[20px] p-4 pr-5"
          >
            <span className="grid size-10 shrink-0 place-items-center rounded-full text-white" style={{ background: status === "credited" ? "var(--low)" : state.refunded && !state.attack.reverted ? REFUND_COLOR : "var(--danger)" }}>
              {status === "credited" ? (
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden><path d="M3 8.4 6.4 11.6 13 4.6" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>
              ) : <LockIcon size={16} />}
            </span>
            <div className="min-w-0">
              <div className="text-[14.5px] font-medium">
                {status === "credited" ? `Credited · ${euros(state.credited?.routeCostEur ?? 0)} all-in vs ${euros(state.credited?.swiftRouteCostEur ?? 0)} via SWIFT` : state.stopped?.headline}
              </div>
              <div className="mt-0.5 text-[12px] leading-snug text-ink-2">
                {status === "credited"
                  ? `Saved ${euros((state.credited?.swiftRouteCostEur ?? 0) - (state.credited?.routeCostEur ?? 0))} · ${state.credited?.elapsedLabel ?? ""}`
                  : state.attack.reverted
                    ? revertMessage(state.attack.reason)
                    : state.stopped?.detail}
              </div>
              {status !== "credited" && state.attack.reverted && state.attack.reason ? (
                <span className="mt-1 block font-mono text-[9px] text-ink-3" title={state.attack.reason}>
                  {state.attack.reason}
                </span>
              ) : null}
            </div>
          </motion.section>
        ) : null}
      </AnimatePresence>
    </div>
  );
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

function CaseFile({ state }: { state: ViewState }) {
  const file = state.caseFile;
  if (!file) return null;
  return (
    <section className="mt-3 rounded-lg border border-[var(--line)] p-3 text-[11.5px]" aria-label="Analyst case file">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-medium text-ink">Analyst case file</span>
        <span className="text-[10px] text-ink-3">{LLM_LABEL[file.llm] ?? file.llm} · advisory only</span>
      </div>
      <div className="mt-2 inline-flex rounded-full bg-[var(--surface-2)] px-2 py-1 text-[10px] text-ink-2">{ACTION_LABEL[file.recommendedAction] ?? file.recommendedAction}</div>
      {file.sentences?.length ? (
        <ul className="mt-3 space-y-1.5">
          {file.sentences.map((sentence) => (
            <li key={`${sentence.text}-${sentence.refs.join("-")}`} className="leading-snug text-ink-2">
              {sentence.text} <span className="font-mono text-[10px] text-ink-3">{sentence.refs.join(" · ")}</span>
            </li>
          ))}
        </ul>
      ) : <p className="mt-3 leading-snug text-ink-2">{file.explanation}</p>}
      {file.citations.length ? (
        <div className="mt-3 border-t border-[var(--line)] pt-2 text-[10px] text-ink-3">
          Citations: {file.citations.map((citation) => `${citation.ref} (${citation.source})`).join(" · ")}
        </div>
      ) : null}
    </section>
  );
}
