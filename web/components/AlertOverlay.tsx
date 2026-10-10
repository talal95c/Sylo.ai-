"use client";

import { useState } from "react";

import { CREDITED_COLOR, DANGER_COLOR, tierColor, withAlpha } from "@/lib/colors";
import { institutionName } from "@/lib/geo";
import type { ViewState } from "@/lib/store";

/**
 * Shown from `payment.held` until dismissed. Every sentence about the payment comes from the
 * events: headline, reasons, protection, next step, then the live updates.
 */
export default function AlertOverlay({ state }: { state: ViewState }) {
  const [dismissed, setDismissed] = useState<number | null>(null);
  const { held, verification, revocation, escrow, attack, payment } = state;
  if (!held || dismissed === held.n) return null;

  const color = tierColor(held.tier);
  const updates: { key: string; text: string; color?: string; strong?: boolean }[] = [];
  if (verification) {
    const sim = verification.simSwapChecked ? (verification.simSwapRecent ? "recent SIM swap detected" : "no recent SIM swap") : "SIM-swap check not done";
    updates.push({
      key: "requested",
      text: `Asked ${verification.contactName} by ${verification.channel} on ${verification.contactMasked}, on file since ${verification.contactSince} (${sim}).`,
    });
    if (verification.answerText) updates.push({ key: "answer", text: verification.answerText, strong: true });
  }
  if (revocation) updates.push({ key: "revoked", text: `Revoked on-chain by ${revocation.by} (${revocation.reasonCode}).`, color: DANGER_COLOR });
  if (escrow?.status === "refunded") updates.push({ key: "refunded", text: `Refunded from escrow to ${institutionName(escrow.to)}.` });
  if (escrow?.status === "released") updates.push({ key: "released", text: `Released from escrow to ${institutionName(escrow.to)}.` });
  if (payment.stopped) {
    updates.push({ key: "stopped", text: payment.stopped.headline, color: CREDITED_COLOR, strong: true });
    updates.push({ key: "stopped-detail", text: payment.stopped.detail });
  }
  if (payment.credited) updates.push({ key: "credited", text: `Credited at ${institutionName(payment.credited.at)}.`, color: CREDITED_COLOR, strong: true });
  if (attack) {
    updates.push({ key: "attack", text: attack.description, color: DANGER_COLOR });
    if (attack.text) updates.push({ key: "reverted", text: attack.text, color: DANGER_COLOR, strong: true });
  }

  return (
    <section
      role="region"
      aria-label="Payment alert"
      className="relative max-h-[42vh] w-[640px] max-w-full overflow-y-auto rounded-xl border-2 bg-slate-950/85 px-5 py-3 shadow-2xl shadow-black/60 backdrop-blur-md"
      style={{ borderColor: color, boxShadow: `0 0 32px ${withAlpha(color, 0.25)}` }}
    >
      <div className="flex items-start justify-between gap-3">
        <h2 className="text-base font-semibold" style={{ color }}>
          {held.headline}
        </h2>
        <button
          type="button"
          onClick={() => setDismissed(held.n)}
          aria-label="Close the alert"
          className="-mr-2 -mt-1 shrink-0 rounded-md px-2 py-1 text-lg leading-none text-slate-400 hover:bg-white/10 hover:text-slate-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-400"
        >
          ×
        </button>
      </div>

      <div className="mt-2 grid grid-cols-1 gap-x-5 gap-y-2 md:grid-cols-2">
        <ul className="space-y-1 text-[13px] leading-snug text-slate-100">
          {held.reasons.map((reason, index) => (
            <li key={index} className="flex gap-2">
              <span className="mt-px h-4 w-4 shrink-0 rounded text-center text-[10px] font-bold leading-4" style={{ color, backgroundColor: withAlpha(color, 0.18) }}>
                {reason.ref}
              </span>
              <span>{reason.text}</span>
            </li>
          ))}
        </ul>
        <div className="space-y-2 text-[13px] leading-snug text-slate-200">
          <div>
            <h3 className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">What protects the money</h3>
            <p>{held.protection}</p>
          </div>
          <div>
            <h3 className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">What happens next</h3>
            <p>{held.nextStep}</p>
          </div>
        </div>
      </div>

      {updates.length > 0 && (
        <ul className="mt-2 space-y-1 border-t border-white/10 pt-2 text-[13px] leading-snug text-slate-200">
          {updates.map((update) => (
            <li key={update.key} className={update.strong ? "font-semibold" : undefined} style={update.color ? { color: update.color } : undefined}>
              {update.text}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
