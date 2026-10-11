"use client";

import { AnimatePresence, motion } from "framer-motion";
import type { ViewState } from "@/lib/store";
import { REFUND_COLOR, TIER_COLORS } from "@/lib/colors";
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

const LLM_LABEL: Record<string, string> = { off: "template", cached: "Mistral · cached", live: "Mistral · live" };

export function AlertOverlay({ state, onClose }: { state: ViewState; onClose: () => void }) {
  const held = state.held;
  const status = state.payment?.status;
  const terminal = status === "credited" || status === "stopped";
  const showHeld = Boolean(held && state.alertOpen && !terminal);
  const showOutcome = terminal;

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
            transition={{ duration: 0.55, ease }}
            className="card pointer-events-auto w-[min(560px,100%)] overflow-hidden rounded-[28px]"
          >
            <div className="h-1 w-full" style={{ background: state.revoked ? "var(--danger)" : state.released ? "var(--low)" : TIER_COLORS[held.tier] }} />
            <div className="p-6">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <div className="flex items-center gap-2 text-[12px] font-medium" style={{ color: TIER_COLORS[held.tier] }}>
                    <LockIcon size={14} /> {held.tier} risk · {state.risk?.score ?? ""} · money held {held.at === "escrow" ? "in escrow" : "at the bank"}
                  </div>
                  <h2 className="mt-2 text-[22px] font-medium leading-tight tracking-[-0.04em]">{held.headline}</h2>
                </div>
                <button
                  onClick={onClose}
                  aria-label="Close alert"
                  className="grid size-8 shrink-0 place-items-center rounded-full bg-[var(--surface-2)] text-ink-2 transition hover:bg-[#ebecee] hover:text-ink"
                >
                  <svg width="10" height="10" viewBox="0 0 10 10"><path d="M2 2l6 6M8 2 2 8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" /></svg>
                </button>
              </div>

              <ul className="mt-4 space-y-2">
                {held.reasons.map((reason, index) => (
                  <motion.li
                    key={reason.text}
                    initial={{ opacity: 0, x: -8, filter: "blur(4px)" }}
                    animate={{ opacity: 1, x: 0, filter: "blur(0px)" }}
                    transition={{ duration: 0.45, ease, delay: 0.25 + index * 0.18 }}
                    className="flex gap-3 text-[13px] leading-snug text-ink-2"
                  >
                    <span className="mt-[1px] h-5 shrink-0 rounded-full bg-[var(--surface-2)] px-2 text-[10.5px] font-medium leading-5 text-ink">
                      {REF_LABEL[reason.ref] ?? reason.ref}
                    </span>
                    <span>{reason.text}</span>
                  </motion.li>
                ))}
              </ul>

              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: 0.25 + held.reasons.length * 0.18 }}
                className="mt-5 rounded-[18px] bg-[var(--surface-2)] p-4 text-[12.5px]"
              >
                <div className="text-ink-2">{held.protection}</div>
                <div className="mt-3 border-t border-[var(--line)] pt-3">
                  <Verification state={state} nextStep={held.nextStep} />
                </div>
              </motion.div>
              <CaseFile state={state} />
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
            className="card pointer-events-auto flex w-[min(560px,100%)] items-center gap-4 rounded-[24px] p-4 pr-5"
          >
            <span
              className="grid size-10 shrink-0 place-items-center rounded-full text-white"
              style={{
                background: status === "credited"
                  ? "var(--low)"
                  : state.refunded && !state.attack.reverted
                    ? REFUND_COLOR
                    : "var(--danger)",
              }}
            >
              {status === "credited" ? (
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M3 8.4 6.4 11.6 13 4.6" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>
              ) : (
                <LockIcon size={16} />
              )}
            </span>
            <div className="min-w-0">
              <div className="text-[14.5px] font-medium tracking-[-0.03em]">
                {status === "credited"
                  ? `Credited · ${euros(state.credited?.routeCostEur ?? 0)} all-in vs ${euros(state.credited?.swiftRouteCostEur ?? 0)} via SWIFT`
                  : state.stopped?.headline}
              </div>
              <div className="mt-0.5 text-[12px] leading-snug text-ink-2">
                {status === "credited"
                  ? `Saved ${euros((state.credited?.swiftRouteCostEur ?? 0) - (state.credited?.routeCostEur ?? 0))} · ${state.credited?.elapsedLabel ?? ""}`
                  : state.attack.reverted
                    ? `An attacker called release() after revocation. Rejected by the smart contract: ${state.attack.reason}.`
                    : state.stopped?.detail}
              </div>
            </div>
          </motion.section>
        ) : null}
      </AnimatePresence>
    </div>
  );
}

function Verification({ state, nextStep }: { state: ViewState; nextStep: string }) {
  const requested = state.verification.requested;
  const recorded = state.verification.recorded;
  if (recorded) {
    const ok = recorded.result === "CONFIRMED";
    return (
      <div>
        <div className="flex items-center gap-2 font-medium" style={{ color: ok ? "var(--low)" : "var(--danger)" }}>
          {ok ? "Supplier confirmed" : "Supplier denied"}
        </div>
        <div className="mt-1 text-ink">{recorded.answerText}</div>
        <div className="mt-2 text-ink-3">
          {state.refunded
            ? "Intent revoked on-chain · EUR 85,000 refunded from escrow"
            : state.revoked
              ? "Revoking the intent on-chain…"
              : state.released
                ? "Escrow released · payment continues"
                : "Recording the answer on-chain…"}
        </div>
      </div>
    );
  }
  if (requested) {
    return (
      <div className="flex items-start gap-3">
        <Spinner size={16} color="var(--medium)" />
        <div>
          <div className="font-medium text-ink">
            Asking {requested.contactName} on {requested.contactMasked}
          </div>
          <div className="mt-0.5 text-ink-3">
            Known contact since {requested.contactSince} · {requested.channel} · SIM swap{" "}
            {requested.simSwapRecent ? "recent" : "not recent"}
          </div>
        </div>
      </div>
    );
  }
  return <div className="text-ink-3">{nextStep}</div>;
}

function CaseFile({ state }: { state: ViewState }) {
  const file = state.caseFile;
  return (
    <AnimatePresence>
      {file ? (
        <motion.details
          key="case"
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.45, ease }}
          className="group mt-3 rounded-[18px] border border-[var(--line)] p-4 text-[12.5px]"
        >
          <summary className="flex cursor-pointer list-none items-center justify-between gap-3">
            <span className="font-medium text-ink">Analyst case file</span>
            <span className="flex items-center gap-2 text-[11px] text-ink-2">
              <span className="rounded-full bg-[var(--surface-2)] px-2 py-0.5">{ACTION_LABEL[file.recommendedAction] ?? file.recommendedAction}</span>
              <span>{LLM_LABEL[file.llm] ?? file.llm} · advisory only</span>
            </span>
          </summary>
          <div className="mt-3 max-h-[150px] overflow-y-auto pr-1">
            {file.sentences?.length ? (
              <ul className="space-y-1.5">
                {file.sentences.map((sentence) => (
                  <li key={sentence.text} className="leading-snug text-ink-2">
                    {sentence.text}{" "}
                    <span className="font-mono text-[10.5px] text-ink-3">{sentence.refs.join(" · ")}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="leading-snug text-ink-2">{file.explanation}</p>
            )}
          </div>
          <div className="mt-3 text-[11px] text-ink-3">{file.typology} · {file.model} · every sentence cites a system event or rule</div>
        </motion.details>
      ) : null}
    </AnimatePresence>
  );
}
