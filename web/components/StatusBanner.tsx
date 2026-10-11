"use client";

import { AnimatePresence, motion } from "framer-motion";
import type { ViewState } from "@/lib/store";
import { cx, ease } from "./ui";

export function StatusBanner({ state, onOpenIncident }: { state: ViewState; onOpenIncident: () => void }) {
  const rail = Object.values(state.rails)[0];
  const item = state.killSwitch
    ? {
        key: `kill-${state.killSwitch.adapter}`,
        tone: "danger" as const,
        title: `Kill switch · ${state.killSwitch.name ?? state.killSwitch.adapter}`,
        detail: state.killSwitch.reason,
        simulated: state.killSwitch.simulated,
        action: undefined,
      }
    : state.incident
      ? {
          key: `incident-${state.incident.incidentId}`,
          tone: "danger" as const,
          title: state.incident.headline ?? `Guardian incident · ${state.incident.incidentId}`,
          detail: state.incident.action,
          simulated: state.incident.simulated,
          action: onOpenIncident,
        }
      : rail
        ? {
            key: `rail-${rail.routeId}`,
            tone: "warning" as const,
            title: `${rail.name ?? rail.routeId} unavailable`,
            detail: rail.reason,
            simulated: rail.simulated,
            action: undefined,
          }
        : state.mode?.degraded.length
          ? {
              key: `degraded-${state.mode.degraded.join("-")}`,
              tone: "warning" as const,
              title: "Degraded mode",
              detail: state.mode.degraded.join(" · "),
              simulated: false,
              action: undefined,
            }
          : null;

  return (
    <AnimatePresence mode="wait">
      {item ? (
        <motion.div
          key={item.key}
          role="status"
          initial={{ opacity: 0, y: -8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -6 }}
          transition={{ duration: 0.25, ease }}
          className="card absolute left-1/2 top-[76px] z-30 flex max-w-[min(680px,calc(100vw-2rem))] -translate-x-1/2 items-center gap-3 rounded-lg px-3 py-2"
        >
          <span className={cx("size-2 shrink-0 rounded-full", item.tone === "danger" ? "bg-[var(--danger)]" : "bg-[var(--medium)]")} />
          <div className="min-w-0 text-[11.5px]">
            <span className="font-semibold text-ink">{item.title}</span>
            <span className="ml-2 text-ink-2">{item.detail}</span>
          </div>
          {item.simulated ? <span className="shrink-0 rounded border border-[var(--line-strong)] bg-[var(--surface-2)] px-1.5 py-0.5 font-mono text-[8.5px] uppercase text-ink-3">Simulated</span> : null}
          {item.action ? (
            <button type="button" onClick={item.action} className="shrink-0 rounded-md px-2 py-1 text-[10.5px] font-medium text-[var(--danger)] hover:bg-[color-mix(in_srgb,var(--danger)_6%,white)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--danger)]">
              Open draft
            </button>
          ) : null}
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}
