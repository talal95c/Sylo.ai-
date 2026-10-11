"use client";

import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useRef, type KeyboardEvent } from "react";
import { actionLabel } from "@/lib/feed";
import type { IncidentView } from "@/lib/store";
import { ease, euros, shortHash } from "./ui";

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="border-b border-[var(--line)] py-3 last:border-0">
      <dt className="text-[11px] font-medium uppercase text-ink-3">{label}</dt>
      <dd className="mt-1 text-[12.5px] leading-relaxed text-ink">{value}</dd>
    </div>
  );
}

export function IncidentDrawer({ incident, open, onClose }: { incident: IncidentView | null; open: boolean; onClose: () => void }) {
  const drawerRef = useRef<HTMLElement>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const safeExplorer = incident?.explorerUrl && /^https:\/\//.test(incident.explorerUrl) ? incident.explorerUrl : null;
  useEffect(() => {
    if (!open || !incident) return;
    returnFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const frame = requestAnimationFrame(() => {
      drawerRef.current?.querySelector<HTMLElement>("button, a, input, select, textarea, [tabindex]:not([tabindex='-1'])")?.focus();
    });
    return () => {
      cancelAnimationFrame(frame);
      requestAnimationFrame(() => returnFocusRef.current?.focus());
    };
  }, [open, incident]);

  const trapFocus = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      onClose();
      return;
    }
    if (event.key !== "Tab" || !drawerRef.current) return;
    const items = Array.from(drawerRef.current.querySelectorAll<HTMLElement>("button, a, input, select, textarea, [tabindex]:not([tabindex='-1'])"));
    const first = items[0];
    const last = items.at(-1);
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last?.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first?.focus();
    }
  };
  return (
    <AnimatePresence>
      {open && incident ? (
        <motion.aside
          role="dialog"
          aria-modal="true"
          aria-labelledby="incident-drawer-title"
          ref={drawerRef}
          tabIndex={-1}
          onKeyDown={trapFocus}
          initial={{ opacity: 0, x: 24 }}
          animate={{ opacity: 1, x: 0 }}
          exit={{ opacity: 0, x: 20 }}
          transition={{ duration: 0.25, ease }}
          className="card absolute bottom-[88px] right-4 top-[76px] z-40 flex w-[min(400px,calc(100vw-2rem))] flex-col overflow-hidden rounded-[18px]"
        >
          <header className="flex shrink-0 items-start justify-between gap-4 border-b border-[var(--line)] px-5 py-4">
            <div>
              <div className="flex items-center gap-2">
                <span className="size-2 rounded-full bg-[var(--danger)]" />
                <span className="font-mono text-[9px] uppercase text-[var(--danger)]">Draft, not filed</span>
                {incident.simulated ? <span className="rounded border border-[var(--line-strong)] px-1.5 py-0.5 font-mono text-[8px] uppercase text-ink-3">Simulated</span> : null}
              </div>
              <h2 id="incident-drawer-title" className="mt-2 text-[18px] font-semibold">DORA incident draft</h2>
              <p className="mt-1 font-mono text-[10px] text-ink-3">{incident.incidentId} · {incident.rule}</p>
            </div>
            <button type="button" onClick={onClose} aria-label="Close incident drawer" className="grid size-8 shrink-0 place-items-center rounded-full bg-[var(--surface-2)] text-ink-2 hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent">
              <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden><path d="M2 2l6 6M8 2 2 8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" /></svg>
            </button>
          </header>
          <div className="thin-scrollbar min-h-0 flex-1 overflow-x-hidden overflow-y-auto px-5 py-2">
            <dl>
              <Field label="Clients affected" value={incident.dora.clientsAffected.toLocaleString("en-US")} />
              <Field label="Amount" value={euros(incident.dora.amountEur)} />
              <Field label="Duration" value={`${incident.dora.durationMinutes} min`} />
              <Field label="Geographic spread" value={incident.dora.geographicSpread.join(" · ")} />
              <Field label="Criticality" value={incident.dora.criticality} />
              <Field label="Third parties" value={incident.dora.thirdParties.join(" · ")} />
            </dl>
            <div className="mt-2 rounded-lg bg-[color-mix(in_srgb,var(--danger)_6%,white)] p-3 text-[11.5px] text-ink-2">
              <span className="font-medium text-[var(--danger)]">Action</span> · {actionLabel(incident.action)}
            </div>
            <div className="mt-3 pb-4 text-[11px]">
              {safeExplorer && incident.txHash ? (
                <a href={safeExplorer} target="_blank" rel="noopener noreferrer" className="font-mono text-accent underline-offset-2 hover:underline">
                  Snowtrace · {shortHash(incident.txHash)}
                </a>
              ) : (
                <span className="font-mono uppercase text-ink-3">Simulated · no explorer transaction</span>
              )}
            </div>
          </div>
        </motion.aside>
      ) : null}
    </AnimatePresence>
  );
}
