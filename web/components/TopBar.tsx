"use client";

import { motion } from "framer-motion";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import type { SystemModeData } from "@/lib/events";
import type { SourceKind } from "@/lib/source";
import { CORRIDOR_LABEL } from "@/lib/corridor";
import { cx, Dot, ease } from "./ui";

export type DemoView = "globe" | "nodes";

type IconName = "risk" | "chain" | "rails" | "llm";

function ModeIcon({ name, color }: { name: IconName; color: string }) {
  const common = { stroke: color, strokeWidth: 1.4, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  return (
    <svg width="12" height="12" viewBox="0 0 16 16" fill="none" aria-hidden className="shrink-0">
      {name === "risk" ? (
        <>
          <path d="M8 1.75 13 3.6v4.1c0 3.05-2.1 5.4-5 6.55-2.9-1.15-5-3.5-5-6.55V3.6L8 1.75Z" {...common} />
          <path d="m5.8 8 1.5 1.5 2.9-3" {...common} />
        </>
      ) : null}
      {name === "chain" ? (
        <>
          <path d="M6.6 9.4a2.6 2.6 0 0 0 3.7 0l2.2-2.2a2.6 2.6 0 0 0-3.7-3.7l-.6.6" {...common} />
          <path d="M9.4 6.6a2.6 2.6 0 0 0-3.7 0L3.5 8.8a2.6 2.6 0 0 0 3.7 3.7l.6-.6" {...common} />
        </>
      ) : null}
      {name === "rails" ? (
        <>
          <path d="M2.5 5.5h10m0 0-2.5-2.5m2.5 2.5L10 8" {...common} />
          <path d="M13.5 10.5h-10m0 0L6 8m-2.5 2.5L6 13" {...common} />
        </>
      ) : null}
      {name === "llm" ? (
        <>
          <path d="M3 3.5h10v7H8l-3.5 2v-2H3z" {...common} />
          <circle cx="5.5" cy="7" r=".5" fill={color} />
          <circle cx="8" cy="7" r=".5" fill={color} />
          <circle cx="10.5" cy="7" r=".5" fill={color} />
        </>
      ) : null}
    </svg>
  );
}

function modeItems(mode: SystemModeData | null, riskMode?: "rules" | "model") {
  const value = mode ?? { risk: "rules", chain: "mock", llm: "off", rails: "simulated", degraded: [] };
  const degraded = value.degraded.map((item) => item.toLowerCase());
  const items: { icon: IconName; label: string; color: string }[] = [
    {
      icon: "risk",
      label: `Risk · ${String(riskMode ?? value.risk).toLowerCase()}`,
      color: degraded.some((item) => item.includes("risk")) ? "var(--medium)" : "var(--low)",
    },
    {
      icon: "chain",
      label: `Chain · ${value.chain === "mock" ? "simulated" : String(value.chain).toLowerCase()}`,
      color: value.chain === "mock" || degraded.some((item) => item.includes("chain")) ? "var(--medium)" : "var(--low)",
    },
    {
      icon: "rails",
      label: `Rails · ${String(value.rails).toLowerCase()}`,
      color: value.rails === "simulated" || degraded.some((item) => item.includes("rail")) ? "var(--medium)" : "var(--low)",
    },
    {
      icon: "llm",
      label: `LLM · ${String(value.llm).toLowerCase()}`,
      color: value.llm === "off" || degraded.some((item) => item.includes("llm")) ? "var(--medium)" : "var(--low)",
    },
  ];
  if (value.confidential) {
    items.push({
      icon: "llm",
      label: `Confidential · ${value.confidential.toLowerCase()}`,
      color: value.confidential === "off" ? "var(--medium)" : "var(--low)",
    });
  }
  return { value, items };
}

export function ModeBanner({
  mode,
  riskMode,
}: {
  mode: SystemModeData | null;
  riskMode?: "rules" | "model";
}) {
  const { value, items } = modeItems(mode, riskMode);
  return (
    <div
      className="flex h-7 items-center divide-x divide-[var(--line-strong)] rounded-full border border-[var(--line)] bg-white/70"
      role="status"
      aria-label="System mode"
      title={value.degraded.length ? `Degraded: ${value.degraded.join(", ")}` : undefined}
    >
      {items.map(({ icon, label, color }) => (
        <span key={label} className="inline-flex h-full items-center gap-1.5 whitespace-nowrap px-2.5 text-[11.5px] text-ink-2">
          <ModeIcon name={icon} color={color} />
          {label}
        </span>
      ))}
    </div>
  );
}

function ModePopover({ mode, riskMode }: { mode: SystemModeData | null; riskMode: "rules" | "model" }) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const { items, value } = modeItems(mode, riskMode);

  useEffect(() => {
    if (!open) return;
    const closeOnOutsideClick = (event: PointerEvent) => {
      if (event.target instanceof Node && !rootRef.current?.contains(event.target)) setOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setOpen(false);
      triggerRef.current?.focus();
    };
    document.addEventListener("pointerdown", closeOnOutsideClick);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutsideClick);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  return (
    <div ref={rootRef} className="relative">
      <button
        ref={triggerRef}
        type="button"
        aria-expanded={open}
        aria-controls="system-modes-popover"
        onClick={() => setOpen((current) => !current)}
        className="flex h-8 items-center gap-1.5 rounded-full border border-[var(--line)] bg-white/80 px-3 text-[11px] font-medium text-ink-2"
      >
        Modes
        <svg className={`transition-transform ${open ? "rotate-180" : ""}`} width="10" height="10" viewBox="0 0 12 12" fill="none" aria-hidden>
          <path d="m3 4.5 3 3 3-3" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      {open ? (
        <div
          id="system-modes-popover"
          role="dialog"
          aria-label="System modes"
          className="card absolute left-1/2 top-[calc(100%+10px)] z-50 w-64 -translate-x-1/2 rounded-xl p-3 shadow-[var(--shadow-float)]"
        >
          <div className="mb-2 text-[11px] font-semibold text-ink">System modes</div>
          <div className="grid gap-2">
            {items.map(({ icon, label, color }) => (
              <div key={label} className="flex items-center gap-2 text-[11px] text-ink-2">
                <ModeIcon name={icon} color={color} />
                <span>{label}</span>
              </div>
            ))}
          </div>
          {value.degraded.length ? (
            <p className="mt-3 border-t border-[var(--line)] pt-2 text-[11px] leading-snug text-amber-800">
              Degraded mode: {value.degraded.join(", ")}.
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function ViewIcon({ name }: { name: DemoView }) {
  const p = { stroke: "currentColor", strokeWidth: 1.4, strokeLinecap: "round" as const, strokeLinejoin: "round" as const, fill: "none" };
  return (
    <svg width="12" height="12" viewBox="0 0 16 16" aria-hidden className="shrink-0">
      {name === "globe" ? (
        <>
          <circle cx="8" cy="8" r="6.25" {...p} />
          <path d="M1.75 8h12.5M8 1.75c1.7 1.75 2.5 3.8 2.5 6.25S9.7 12.5 8 14.25C6.3 12.5 5.5 10.45 5.5 8S6.3 3.5 8 1.75Z" {...p} />
        </>
      ) : (
        <>
          <rect x="1.75" y="2.25" width="5" height="4" rx="1.2" {...p} />
          <rect x="9.25" y="9.75" width="5" height="4" rx="1.2" {...p} />
          <path d="M6.75 4.25h1.5a1.5 1.5 0 0 1 1.5 1.5v4" {...p} />
        </>
      )}
    </svg>
  );
}

export function TopBar({
  mode,
  riskMode,
  sourceKind,
  connectionStatus,
  notice,
  onSource,
  view,
  onView,
  onHelp,
}: {
  mode: SystemModeData | null;
  riskMode: "rules" | "model";
  sourceKind: SourceKind;
  connectionStatus: "connecting" | "live" | "offline";
  notice?: string;
  onSource: (kind: SourceKind) => void;
  view: DemoView;
  onView: (view: DemoView) => void;
  onHelp?: () => void;
}) {
  return (
    <motion.header
      initial={{ opacity: 0, y: -12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.7, ease }}
      className="glass absolute left-4 right-4 top-4 z-30 grid h-12 select-none grid-cols-[1fr_auto_1fr] items-center gap-4 rounded-2xl pl-4 pr-1.5 sm:pl-4"
    >
      <div className="flex min-w-0 items-center gap-3">
        <Link href="/" className="flex shrink-0 items-center gap-2" title="Home">
          <span className="relative grid size-5 place-items-center">
            <span className="absolute inset-0 rounded-full" style={{ background: "var(--iridescent)" }} />
            <span className="absolute inset-[4px] rounded-full bg-white" />
            <span className="relative size-1.5 rounded-full bg-ink" />
          </span>
          <span className="text-[15px] font-semibold tracking-[-0.04em]">Sylo.ai</span>
        </Link>
        <span className="hidden h-4 w-px shrink-0 bg-[var(--line-strong)] sm:block" />
        <span className="hidden whitespace-nowrap text-[12px] text-ink-2 sm:block">{CORRIDOR_LABEL}</span>
        <div className="flex h-8 items-center rounded-full bg-[var(--surface-2)] p-1" role="tablist" aria-label="Demo view">
          {(["globe", "nodes"] as const).map((tab) => (
            <button
              key={tab}
              role="tab"
              aria-selected={view === tab}
              onClick={() => onView(tab)}
              className={cx(
                "relative h-6 rounded-full px-2.5 text-[12px] font-medium capitalize transition-colors",
                view === tab ? "text-ink" : "text-ink-3 hover:text-ink-2",
              )}
            >
              {view === tab ? (
                <motion.span
                  layoutId="view-pill"
                  className="absolute inset-0 rounded-full bg-white shadow-[0_1px_3px_rgba(0,0,0,0.1)]"
                  transition={{ duration: 0.35, ease }}
                />
              ) : null}
              <span className="relative flex items-center gap-1.5">
                <ViewIcon name={tab} />
                {tab}
              </span>
            </button>
          ))}
        </div>
      </div>

      <div className="justify-self-center">
        <div className="hidden whitespace-nowrap xl:block">
          <ModeBanner mode={mode} riskMode={riskMode} />
        </div>
        <div className="xl:hidden">
          <ModePopover mode={mode} riskMode={riskMode} />
        </div>
      </div>

      <div className="flex min-w-0 items-center justify-end gap-2.5">
        {notice && sourceKind === "replay" ? (
          <motion.span
            initial={{ opacity: 0, x: 8 }}
            animate={{ opacity: 1, x: 0 }}
            title={notice}
            className="hidden items-center gap-1.5 whitespace-nowrap text-[11px] text-amber-700 md:flex"
          >
            <Dot color="var(--medium)" pulse /> Engine offline · replay
          </motion.span>
        ) : sourceKind === "replay" ? (
          <span className="hidden whitespace-nowrap text-[10.5px] text-ink-3 sm:block" title="Recorded events">
            Recorded events
          </span>
        ) : null}
        {sourceKind === "live" ? (
          <span
            className="hidden items-center gap-1.5 whitespace-nowrap text-[11px] text-ink-2 md:flex"
            role="status"
            aria-live="polite"
            aria-label={`Live stream ${connectionStatus}`}
          >
            <Dot
              color={connectionStatus === "live" ? "var(--low)" : connectionStatus === "offline" ? "var(--danger)" : "var(--medium)"}
              pulse={connectionStatus === "connecting"}
            />
            {connectionStatus === "live" ? "Live" : connectionStatus === "offline" ? "Offline" : "Connecting…"}
          </span>
        ) : null}
        {onHelp ? (
          <button
            type="button"
            onClick={onHelp}
            aria-label="Show the guided tour"
            title="Guided tour"
            className="grid size-8 shrink-0 place-items-center rounded-full text-[12.5px] font-medium text-ink-3 transition-colors hover:bg-[var(--surface-2)] hover:text-ink"
          >
            ?
          </button>
        ) : null}
        <div className="flex h-9 items-center rounded-full bg-[var(--surface-2)] p-1" role="radiogroup" aria-label="Event source">
          {(["live", "replay"] as const).map((kind) => (
            <button
              key={kind}
              role="radio"
              aria-checked={sourceKind === kind}
              onClick={() => onSource(kind)}
              className={cx(
                "relative h-7 rounded-full px-3 text-[12px] font-medium capitalize transition-colors",
                sourceKind === kind ? "text-ink" : "text-ink-3 hover:text-ink-2",
              )}
            >
              {sourceKind === kind ? (
                <motion.span
                  layoutId="source-pill"
                  className="absolute inset-0 rounded-full bg-white shadow-[0_1px_3px_rgba(0,0,0,0.1)]"
                  transition={{ duration: 0.35, ease }}
                />
              ) : null}
              <span className="relative flex items-center gap-1.5">
                {kind === "live" ? <Dot color={sourceKind === "live" ? (connectionStatus === "live" ? "var(--low)" : connectionStatus === "offline" ? "var(--danger)" : "var(--medium)") : "rgba(0,0,0,.25)"} pulse={sourceKind === "live" && connectionStatus === "connecting"} /> : null}
                {kind}
              </span>
            </button>
          ))}
        </div>
      </div>
    </motion.header>
  );
}
