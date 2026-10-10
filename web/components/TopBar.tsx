"use client";

import { motion } from "framer-motion";
import type { SystemModeData } from "@/lib/events";
import type { SourceKind } from "@/lib/source";
import { cx, Dot, ease } from "./ui";

export function ModeBanner({ mode, sourceKind }: { mode: SystemModeData | null; sourceKind: SourceKind }) {
  const value = mode ?? { risk: "rules", chain: "mock", llm: "off", rails: "simulated", degraded: [] };
  const chips = [
    ["Risk", value.risk === "rules" ? "Rules" : "Model"],
    ["Chain", value.chain === "mock" ? "Simulated" : "Fuji"],
    ["Rails", "Simulated"],
  ];
  return (
    <div className="flex items-center gap-1.5" role="status" aria-label="System mode">
      {chips.map(([key, label], index) => (
        <span
          key={key}
          className="inline-flex h-7 items-center gap-1.5 rounded-full bg-[var(--surface-2)] px-2.5 text-[11.5px] text-ink-2"
        >
          <span className="font-mono text-[10px] text-ink-3">{String(index + 1).padStart(3, "0")}</span>
          <span className="text-ink-3">{key}</span>
          <span className="font-medium text-ink">{label}</span>
        </span>
      ))}
      {value.degraded.length ? (
        <span className="inline-flex h-7 items-center gap-1.5 rounded-full bg-amber-50 px-2.5 text-[11.5px] font-medium text-amber-700">
          <Dot color="var(--medium)" pulse /> Degraded: {value.degraded.join(", ")} · stricter mode
        </span>
      ) : null}
      {sourceKind === "replay" ? (
        <span className="inline-flex h-7 items-center rounded-full bg-[var(--surface-2)] px-2.5 text-[11.5px] text-ink-2">
          Recorded events
        </span>
      ) : null}
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
      className="glass absolute left-4 right-4 top-4 z-30 flex h-14 items-center justify-between rounded-full py-2 pl-5 pr-2"
    >
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2.5">
          <span className="relative grid size-6 place-items-center">
            <span className="absolute inset-0 rounded-full" style={{ background: "var(--iridescent)" }} />
            <span className="absolute inset-[5px] rounded-full bg-white" />
            <span className="relative size-1.5 rounded-full bg-ink" />
          </span>
          <span className="text-[17px] font-semibold tracking-[-0.04em]">Sylo.ai</span>
        </div>
        <span className="hidden h-5 w-px bg-[var(--line-strong)] lg:block" />
        <span className="hidden text-[13px] text-ink-2 lg:block">Lyon → Ghana · cross-border payment control</span>
      </div>

      <div className="hidden xl:block">
        <ModeBanner mode={mode} sourceKind={sourceKind} />
      </div>

      <div className="flex items-center gap-3">
        {notice ? (
          <motion.span
            initial={{ opacity: 0, x: 8 }}
            animate={{ opacity: 1, x: 0 }}
            className="hidden items-center gap-2 text-[12px] text-amber-700 md:flex"
          >
            <Dot color="var(--medium)" pulse /> {notice}
          </motion.span>
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
