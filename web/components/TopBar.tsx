"use client";

import { motion } from "framer-motion";
import type { SystemModeData } from "@/lib/events";
import type { SourceKind } from "@/lib/source";
import { cx, Dot, ease } from "./ui";

export function ModeBanner({ mode }: { mode: SystemModeData | null }) {
  const value = mode ?? { risk: "rules", chain: "mock", llm: "off", rails: "simulated", degraded: [] };
  const degraded = value.degraded.map((item) => item.toLowerCase());
  const items = [
    {
      label: `Risk · ${String(value.risk).toLowerCase()}`,
      color: degraded.some((item) => item.includes("risk")) ? "var(--medium)" : "var(--low)",
    },
    {
      label: `Chain · ${value.chain === "mock" ? "simulated" : String(value.chain).toLowerCase()}`,
      color: value.chain === "mock" || degraded.some((item) => item.includes("chain")) ? "var(--medium)" : "var(--low)",
    },
    {
      label: `Rails · ${String(value.rails).toLowerCase()}`,
      color: value.rails === "simulated" || degraded.some((item) => item.includes("rail")) ? "var(--medium)" : "var(--low)",
    },
  ];
  return (
    <div
      className="flex h-8 items-center divide-x divide-[var(--line-strong)] rounded-full border border-[var(--line)] bg-white/70"
      role="status"
      aria-label="System mode"
      title={value.degraded.length ? `Degraded: ${value.degraded.join(", ")}` : undefined}
    >
      {items.map(({ label, color }) => (
        <span key={label} className="inline-flex h-full items-center gap-2 whitespace-nowrap px-3 text-[12px] text-ink-2">
          <span className="size-1.5 shrink-0 rounded-full" style={{ background: color }} />
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
      className="glass absolute left-4 right-4 top-4 z-30 grid h-14 select-none grid-cols-[1fr_auto_1fr] items-center gap-4 rounded-2xl px-4 sm:px-5"
    >
      <div className="flex min-w-0 items-center gap-3">
        <div className="flex shrink-0 items-center gap-2.5">
          <span className="relative grid size-6 place-items-center">
            <span className="absolute inset-0 rounded-full" style={{ background: "var(--iridescent)" }} />
            <span className="absolute inset-[5px] rounded-full bg-white" />
            <span className="relative size-1.5 rounded-full bg-ink" />
          </span>
          <span className="text-[17px] font-semibold tracking-[-0.04em]">Sylo.ai</span>
        </div>
        <span className="hidden h-5 w-px shrink-0 bg-[var(--line-strong)] sm:block" />
        <span className="hidden whitespace-nowrap text-[13px] text-ink-2 sm:block">Lyon → Ghana</span>
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
        <div className="flex h-10 items-center rounded-full bg-[var(--surface-2)] p-1" role="radiogroup" aria-label="Event source">
          {(["live", "replay"] as const).map((kind) => (
            <button
              key={kind}
              role="radio"
              aria-checked={sourceKind === kind}
              onClick={() => onSource(kind)}
              className={cx(
                "relative h-8 rounded-full px-3.5 text-[12.5px] font-medium capitalize transition-colors",
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
