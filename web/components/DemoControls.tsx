"use client";

import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import type { ViewState } from "@/lib/store";
import { cx, ease, Spinner } from "./ui";

interface Actions {
  runLegit: () => void;
  runDiverted: () => void;
  confirm: () => void;
  deny: () => void;
  attack: () => void;
  reset: () => void;
}

type Available = Record<keyof Actions, boolean>;

function Button({
  children,
  onClick,
  tone = "secondary",
}: {
  children: React.ReactNode;
  onClick: () => void;
  tone?: "primary" | "secondary" | "danger" | "dark";
}) {
  return (
    <motion.button
      whileHover={{ y: -1 }}
      whileTap={{ scale: 0.97 }}
      onClick={onClick}
      className={cx(
        "h-10 whitespace-nowrap rounded-full px-4 text-[13px] font-medium tracking-[-0.02em] transition-colors",
        tone === "primary" && "bg-accent text-white shadow-[inset_0_0_12px_rgba(255,255,255,0.35),0_6px_16px_-8px_rgba(1,43,255,0.7)] hover:bg-[#0022d6]",
        tone === "dark" && "iridescent-ring bg-ink text-white shadow-[inset_0_0_14px_rgba(255,255,255,0.35)]",
        tone === "secondary" && "border border-[var(--line-strong)] bg-white text-ink hover:bg-[var(--surface-2)]",
        tone === "danger" && "border border-[color-mix(in_srgb,var(--danger)_40%,white)] bg-white text-[var(--danger)] hover:bg-[color-mix(in_srgb,var(--danger)_6%,white)]",
      )}
    >
      {children}
    </motion.button>
  );
}

export function DemoControls({
  state,
  actions,
  available,
  speed,
  setSpeed,
}: {
  state: ViewState;
  actions: Actions;
  available: Available;
  speed: 1 | 2;
  setSpeed: (speed: 1 | 2) => void;
}) {
  const status = state.payment?.status;
  const busy = status === "deciding" || status === "in_transit" || status === "held";
  const phase = available.confirm ? "supplier" : busy ? "busy" : "start";
  const reducedMotion = useReducedMotion();
  const caption = state.attack.reverted
    ? "Rejected by the smart contract"
    : status === "deciding"
      ? "Engine deciding…"
      : status === "in_transit"
        ? "Payment moving…"
        : status === "held" || status === "awaiting_supplier"
          ? "Waiting for Kwame"
          : status === "stopped"
            ? "Stopped · refunded"
            : status === "credited"
              ? "Credited"
              : "Ready";
  const captionIsError = status === "stopped" || state.attack.attempted || state.attack.reverted;

  return (
    <>
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
      <motion.nav
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.7, ease, delay: 0.3 }}
        aria-label="Demo controls"
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
              <span className="px-3 text-[12.5px] text-ink-2">Kwame Asante replies</span>
              <Button tone="secondary" onClick={actions.confirm}>“Yes, it’s our account”</Button>
              <Button tone="dark" onClick={actions.deny}>“We never changed it”</Button>
            </>
          ) : null}
          {phase === "busy" ? (
            <span className="flex h-10 items-center gap-2.5 px-4 text-[13px] text-ink-2">
              <Spinner size={14} />
              {status === "deciding" ? "Engine deciding…" : status === "held" ? "Holding in escrow…" : "Payment moving…"}
            </span>
          ) : null}
        </motion.div>
      </AnimatePresence>

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
