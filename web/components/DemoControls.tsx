"use client";

import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { useState } from "react";
import type { SourceKind } from "@/lib/source";
import type { ViewState } from "@/lib/store";
import { cx, ease, Spinner } from "./ui";

interface Actions {
  runLegit: () => void;
  runDiverted: () => void;
  runMuleWave: () => void;
  runGuardian: () => void;
  runOutage: () => void;
  confirm: () => void;
  deny: () => void;
  attack: () => void;
  swapAttack: () => void;
  replayAttack: () => void;
  reset: () => void;
}

type Available = Record<keyof Actions, boolean>;

function Button({
  children,
  onClick,
  tone = "secondary",
  disabled = false,
}: {
  children: React.ReactNode;
  onClick: () => void;
  tone?: "primary" | "secondary" | "danger" | "dark";
  disabled?: boolean;
}) {
  return (
    <motion.button
      whileHover={{ y: -1 }}
      whileTap={{ scale: 0.97 }}
      onClick={onClick}
      disabled={disabled}
      className={cx(
        "h-10 whitespace-nowrap rounded-full px-4 text-[13px] font-medium tracking-[-0.02em] transition-colors",
        tone === "primary" && "bg-accent text-white shadow-[inset_0_0_12px_rgba(255,255,255,0.35),0_6px_16px_-8px_rgba(1,43,255,0.7)] hover:bg-[#0022d6]",
        tone === "dark" && "iridescent-ring bg-ink text-white shadow-[inset_0_0_14px_rgba(255,255,255,0.35)]",
        tone === "secondary" && "border border-[var(--line-strong)] bg-white text-ink hover:bg-[var(--surface-2)]",
        tone === "danger" && "border border-[color-mix(in_srgb,var(--danger)_40%,white)] bg-white text-[var(--danger)] hover:bg-[color-mix(in_srgb,var(--danger)_6%,white)]",
        disabled && "cursor-not-allowed opacity-40",
      )}
    >
      {children}
    </motion.button>
  );
}

function MoreScenes({ actions, available, sourceKind }: { actions: Actions; available: Available; sourceKind: SourceKind }) {
  const [open, setOpen] = useState(false);
  const run = (action: () => void) => {
    setOpen(false);
    action();
  };
  const entries = [
    { label: "Mule wave", action: actions.runMuleWave, enabled: available.runMuleWave },
    { label: "Guardian incident", action: actions.runGuardian, enabled: available.runGuardian && sourceKind === "replay", suffix: sourceKind === "live" ? "Replay" : undefined },
    { label: "Rail outage", action: actions.runOutage, enabled: available.runOutage },
    { label: "Swap beneficiary", action: actions.swapAttack, enabled: available.swapAttack },
    { label: "Replay intent", action: actions.replayAttack, enabled: available.replayAttack },
  ];

  return (
    <div className="relative">
      <button
        type="button"
        aria-expanded={open}
        aria-haspopup="menu"
        onClick={() => setOpen((value) => !value)}
        className="flex h-10 items-center gap-2 whitespace-nowrap rounded-full border border-[var(--line-strong)] bg-white px-4 text-[13px] font-medium text-ink transition-colors hover:bg-[var(--surface-2)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      >
        More scenes
        <svg className={`transition-transform ${open ? "rotate-180" : ""}`} width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden>
          <path d="m3 4.5 3 3 3-3" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      <AnimatePresence>
        {open ? (
          <motion.div
            role="menu"
            aria-label="Additional demo scenes"
            initial={{ opacity: 0, y: 6, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 4, scale: 0.98 }}
            transition={{ duration: 0.18, ease }}
            onKeyDown={(event) => {
              if (event.key === "Escape") setOpen(false);
            }}
            className="card absolute bottom-[48px] right-0 w-52 overflow-hidden rounded-xl p-1.5 shadow-[var(--shadow-float)]"
          >
            {entries.map((entry) => (
              <button
                key={entry.label}
                type="button"
                role="menuitem"
                disabled={!entry.enabled}
                onClick={() => run(entry.action)}
                className="flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-[12.5px] text-ink transition-colors hover:bg-[var(--surface-2)] focus-visible:bg-[var(--surface-2)] focus-visible:outline-none disabled:cursor-not-allowed disabled:text-ink-3"
              >
                <span>{entry.label}</span>
                {entry.suffix ? <span className="font-mono text-[9px] uppercase text-ink-3">{entry.suffix}</span> : null}
              </button>
            ))}
          </motion.div>
        ) : null}
      </AnimatePresence>
    </div>
  );
}

export function DemoControls({
  state,
  actions,
  available,
  speed,
  setSpeed,
  sourceKind,
}: {
  state: ViewState;
  actions: Actions;
  available: Available;
  speed: 1 | 2;
  setSpeed: (speed: 1 | 2) => void;
  sourceKind: SourceKind;
}) {
  const status = state.payment?.status;
  const busy = status === "deciding" || status === "in_transit" || status === "held" || status === "frozen";
  const phase = available.confirm ? "supplier" : busy ? "busy" : "start";
  const reducedMotion = useReducedMotion();
  const caption = state.attack.reverted
    ? "Rejected by the smart contract"
    : status === "deciding"
      ? "Engine deciding…"
      : status === "in_transit"
        ? "Payment moving…"
        : status === "held" || status === "awaiting_supplier"
          ? `Waiting for ${state.verification.requested?.contactName ?? "the supplier"}`
          : status === "frozen"
            ? "Frozen by the guardian"
          : status === "stopped"
            ? "Stopped · refunded"
            : status === "credited"
              ? "Credited"
              : "Ready";
  const captionIsError = status === "stopped" || state.attack.attempted || state.attack.reverted;
  const showFloatingCaption = !busy && phase !== "supplier" && status !== "stopped" && status !== "credited" && !state.attack.reverted;

  return (
    <>
      {showFloatingCaption ? (
        <div className="pointer-events-none absolute bottom-[74px] left-1/2 z-30 -translate-x-1/2 whitespace-nowrap text-[14px] text-ink-2" aria-live="polite">
          <AnimatePresence mode="wait" initial={false}>
            <motion.span
              key={caption}
              initial={{ opacity: 0, y: reducedMotion ? 0 : 6, filter: reducedMotion ? "blur(0px)" : "blur(4px)" }}
              animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
              exit={{ opacity: 0, y: reducedMotion ? 0 : -6, filter: reducedMotion ? "blur(0px)" : "blur(4px)" }}
              transition={{ duration: reducedMotion ? 0 : 0.28, ease }}
              style={captionIsError ? { color: "#FF3B30" } : undefined}
            >
              {caption}
            </motion.span>
          </AnimatePresence>
        </div>
      ) : null}
      <motion.nav
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.7, ease, delay: 0.3 }}
        aria-label="Demo controls"
        data-globe-occluder="bottom"
        className="glass absolute bottom-4 left-1/2 z-30 flex h-14 -translate-x-1/2 items-center gap-1.5 rounded-full p-2"
      >
      <AnimatePresence mode="popLayout" initial={false}>
        <motion.div
          key={phase + String(available.attack)}
          initial={{ opacity: 0, y: 8, filter: "blur(4px)" }}
          animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
          exit={{ opacity: 0, y: -8, filter: "blur(4px)" }}
          transition={{ duration: 0.3, ease }}
          className="flex items-center gap-1.5"
        >
          {phase === "start" ? (
            <>
              <Button tone="primary" onClick={actions.runLegit}>Legitimate payment</Button>
              <Button tone="dark" onClick={actions.runDiverted}>Diverted invoice</Button>
              {available.attack ? <Button tone="danger" onClick={actions.attack}>Try release() attack</Button> : null}
            </>
          ) : null}
          {phase === "supplier" ? (
            <>
              <span className="whitespace-nowrap px-3 text-[12.5px] text-ink-2">{state.verification.requested?.contactName ?? "Supplier"} replies</span>
              <Button tone="secondary" onClick={actions.confirm}>“Yes, it’s our account”</Button>
              <Button tone="dark" onClick={actions.deny}>“We never changed it”</Button>
            </>
          ) : null}
          {phase === "busy" ? (
            <span className="flex h-10 items-center gap-2.5 px-4 text-[13px] text-ink-2">
              <Spinner size={14} />
              {status === "deciding" ? "Engine deciding…" : status === "held" ? "Holding in escrow…" : status === "frozen" ? "Guardian freeze active" : "Payment moving…"}
            </span>
          ) : null}
        </motion.div>
      </AnimatePresence>

      <MoreScenes actions={actions} available={available} sourceKind={sourceKind} />

      <span className="mx-1 h-6 w-px bg-[var(--line-strong)]" />
      <div className="flex h-10 items-center rounded-full bg-[var(--surface-2)] p-1" role="radiogroup" aria-label="Speed">
        {([1, 2] as const).map((value) => (
          <button
            key={value}
            role="radio"
            aria-checked={speed === value}
            onClick={() => setSpeed(value)}
            className={cx(
              "relative h-8 w-9 rounded-full font-mono text-[11.5px] transition-colors",
              speed === value ? "text-ink" : "text-ink-3",
            )}
          >
            {speed === value ? (
              <motion.span layoutId="speed-pill" className="absolute inset-0 rounded-full bg-white shadow-[0_1px_3px_rgba(0,0,0,0.1)]" />
            ) : null}
            <span className="relative">{value}×</span>
          </button>
        ))}
      </div>
      <button
        onClick={actions.reset}
        aria-label="Reset"
        title="Reset"
        className="grid size-10 place-items-center rounded-full text-ink-2 transition hover:bg-[var(--surface-2)] hover:text-ink"
      >
        <svg width="15" height="15" viewBox="0 0 16 16" fill="none"><path d="M2.5 8a5.5 5.5 0 1 0 1.7-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" /><path d="M2.5 2.5V5.5H5.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" /></svg>
      </button>
      </motion.nav>
    </>
  );
}
