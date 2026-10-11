"use client";

import { AnimatePresence, motion } from "framer-motion";
import { actionLabel } from "@/lib/feed";
import { selectVisibleBanners } from "@/lib/statusBanners";
import type { ViewState } from "@/lib/store";
import { cx, ease } from "./ui";

type Banner = {
  key: string;
  severity: number;
  degraded?: boolean;
  tone: "danger" | "warning";
  message: string;
  simulated: boolean;
  action?: () => void;
};

export function StatusBanner({
  state,
  view,
  onOpenIncident,
}: {
  state: ViewState;
  view: "globe" | "nodes";
  onOpenIncident: () => void;
}) {
  const banners: Banner[] = [];
  const rail = Object.values(state.rails)[0];

  if (state.incident) {
    banners.push({
      key: `incident-${state.incident.incidentId}`,
      severity: 4,
      tone: "danger",
      message: `Guardian incident: ${state.incident.headline ?? state.incident.incidentId}. ${actionLabel(state.incident.action)} is recommended.`,
      simulated: state.incident.simulated,
      action: onOpenIncident,
    });
  }
  if (state.killSwitch) {
    banners.push({
      key: `kill-${state.killSwitch.adapter}`,
      severity: 3,
      tone: "danger",
      message: `Kill switch active for ${state.killSwitch.name ?? state.killSwitch.adapter}: ${state.killSwitch.reason}.`,
      simulated: state.killSwitch.simulated,
    });
  }
  if (rail) {
    banners.push({
      key: `rail-${rail.routeId}`,
      severity: 2,
      tone: "warning",
      message: `${rail.name ?? rail.routeId} is unavailable: ${rail.reason}.`,
      simulated: rail.simulated,
    });
  }
  if (state.mode?.degraded.length) {
    const features = state.mode.degraded
      .map((item) => item.replace(/[._-]+/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase()))
      .join(", ");
    banners.push({
      key: `degraded-${state.mode.degraded.join("-")}`,
      severity: 1,
      degraded: true,
      tone: "warning",
      message: `Degraded mode is active for ${features}.`,
      simulated: false,
    });
  }

  const visible = selectVisibleBanners(banners);
  const hiddenCount = banners.length - visible.length;
  const placement =
    view === "nodes"
      ? "left-4 right-4 top-[124px]"
      : "left-[calc(340px+2rem)] right-[calc(320px+2rem)] top-[76px] 2xl:left-[calc(372px+2rem)] 2xl:right-[calc(360px+2rem)]";
  return (
    <div className={cx("absolute z-30 flex flex-col gap-2", placement)} aria-live="polite">
      <AnimatePresence initial={false}>
        {visible.map((item) => (
          <motion.div
            key={item.key}
            role="status"
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }}
            transition={{ duration: 0.25, ease }}
            className="card flex min-w-0 items-start gap-2.5 rounded-lg px-3 py-2"
          >
            <span className={cx("mt-1 size-2 shrink-0 rounded-full", item.tone === "danger" ? "bg-[var(--danger)]" : "bg-[var(--medium)]")} />
            <p className="min-w-0 flex-1 text-[11px] leading-snug text-ink-2">{item.message}</p>
            {item.simulated ? <span className="shrink-0 rounded border border-[var(--line-strong)] bg-[var(--surface-2)] px-1.5 py-0.5 font-mono text-[10px] uppercase text-ink-3">Simulated</span> : null}
            {item.action ? (
              <button type="button" onClick={item.action} className="shrink-0 rounded-md px-2 py-1 text-[11px] font-medium text-[var(--danger)] hover:bg-[color-mix(in_srgb,var(--danger)_6%,white)]">
                Open draft
              </button>
            ) : null}
          </motion.div>
        ))}
      </AnimatePresence>
      {hiddenCount > 0 ? <span className="self-end rounded-full border border-[var(--line)] bg-white/85 px-2 py-0.5 text-[11px] text-ink-2">+{hiddenCount} more notices</span> : null}
    </div>
  );
}
