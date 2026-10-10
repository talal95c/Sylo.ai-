"use client";

import { motion } from "framer-motion";
import Link from "next/link";
import type { SystemModeData } from "@/lib/events";
import type { SourceKind } from "@/lib/source";
import { cx, Dot, ease } from "./ui";

type IconName = "risk" | "chain" | "rails";

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
    </svg>
  );
}

export function ModeBanner({ mode }: { mode: SystemModeData | null }) {
  const value = mode ?? { risk: "rules", chain: "mock", llm: "off", rails: "simulated", degraded: [] };
  const degraded = value.degraded.map((item) => item.toLowerCase());
  const items: { icon: IconName; label: string; color: string }[] = [
    {
      icon: "risk",
      label: `Risk · ${String(value.risk).toLowerCase()}`,
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
  ];
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

export function TopBar({
  mode,
  sourceKind,
  notice,
  onSource,
}: {
  mode: SystemModeData | null;
  sourceKind: SourceKind;
  notice?: string;
  onSource: (kind: SourceKind) => void;
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
        <span className="hidden whitespace-nowrap text-[12px] text-ink-2 sm:block">Lyon → Ghana</span>
      </div>

      <div className="hidden whitespace-nowrap xl:block">
        <ModeBanner mode={mode} />
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
                {kind === "live" ? <Dot color={sourceKind === "live" ? "var(--low)" : "rgba(0,0,0,.25)"} pulse={sourceKind === "live"} /> : null}
                {kind}
              </span>
            </button>
          ))}
        </div>
      </div>
    </motion.header>
  );
}
