"use client";

import { AnimatePresence, motion } from "framer-motion";
import type { PaymentStatus, ViewState } from "@/lib/store";
import { GlowingShadow } from "./glowing-shadow";
import { Dot, ease, shortHash, Spinner, Tag } from "./ui";

const STATUS: Record<PaymentStatus, { label: string; color: string; busy?: boolean }> = {
  idle: { label: "Ready", color: "rgba(0,0,0,.38)" },
  deciding: { label: "Decision in progress", color: "var(--accent)", busy: true },
  in_transit: { label: "In transit", color: "var(--accent)", busy: true },
  held: { label: "Held in escrow", color: "var(--medium)" },
  awaiting_supplier: { label: "Awaiting supplier", color: "var(--medium)", busy: true },
  stopped: { label: "Stopped and refunded", color: "var(--danger)" },
  credited: { label: "Supplier credited", color: "var(--low)" },
};

type DetailIcon = "from" | "to" | "route" | "status";

function DetailGlyph({ name }: { name: DetailIcon }) {
  const common = { stroke: "currentColor", strokeWidth: 1.5, strokeLinecap: "round" as const, strokeLinejoin: "round" as const, fill: "none" };
  return (
    <svg width="15" height="15" viewBox="0 0 16 16" aria-hidden>
      {name === "from" ? <><circle cx="8" cy="5" r="2.5" {...common} /><path d="M3.5 13c.5-2.4 2-3.6 4.5-3.6s4 1.2 4.5 3.6" {...common} /></> : null}
      {name === "to" ? <><path d="M8 14s4-3.7 4-7.5a4 4 0 1 0-8 0C4 10.3 8 14 8 14Z" {...common} /><circle cx="8" cy="6.4" r="1.25" {...common} /></> : null}
      {name === "route" ? <><circle cx="3" cy="12.5" r="1.25" {...common} /><circle cx="13" cy="3.5" r="1.25" {...common} /><path d="M4.2 12c4-.8 2.4-5.5 6.3-7.2" {...common} /></> : null}
      {name === "status" ? <><circle cx="8" cy="8" r="5.5" {...common} /><path d="m5.2 8 1.8 1.8 3.8-4" {...common} /></> : null}
    </svg>
  );
}

export function StatusPill({ status }: { status: PaymentStatus }) {
  const meta = STATUS[status];
  return (
    <AnimatePresence mode="wait" initial={false}>
      <motion.span
        key={status}
        initial={{ opacity: 0, y: 3 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -3 }}
        transition={{ duration: 0.2, ease }}
        className="inline-flex h-7 items-center gap-1.5 rounded-full border px-2.5 text-[11.5px] font-medium"
        style={{ color: meta.color, borderColor: `color-mix(in srgb, ${meta.color} 20%, white)`, background: `color-mix(in srgb, ${meta.color} 5%, white)` }}
      >
        {meta.busy ? <Spinner size={11} color={meta.color} /> : <Dot color={meta.color} />}
        {meta.label}
      </motion.span>
    </AnimatePresence>
  );
}

function amountOnly(value: string) {
  return Number(value).toLocaleString("en-US", { maximumFractionDigits: 2 });
}

export function PaymentCard({ state }: { state: ViewState }) {
  const payment = state.payment;
  const status = payment?.status ?? "idle";
  const statusMeta = STATUS[status];

  return (
    <GlowingShadow layout initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.7, ease, delay: 0.1 }} className="shrink-0" panelClassName="overflow-hidden" aria-label="Payment">
      <div className="flex items-center justify-between px-4 pb-2 pt-4">
        <Tag index="01">Payment</Tag>
        <StatusPill status={status} />
      </div>

      <AnimatePresence mode="wait" initial={false}>
        {payment ? (
          <motion.div key={payment.paymentId} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.35, ease }} className="px-4 pb-4 pt-2">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-[33px] font-semibold leading-none tabular-nums">{amountOnly(payment.amount.value)}</span>
                  <span className="rounded-full border border-[var(--line)] bg-[var(--surface-2)] px-2 py-1 font-mono text-[10px] font-medium text-ink-2">{payment.amount.currency}</span>
                </div>
                <p className="mt-2 text-[12.5px] font-medium text-ink-2">Business payment</p>
                <p className="mt-0.5 text-[11px] leading-relaxed text-ink-3">Cross-border supplier payment to {payment.payeeName}.</p>
              </div>
              <span className="pt-1 font-mono text-[10px] text-ink-3">{payment.paymentId}</span>
            </div>

            <div className="mt-4 border-y border-[var(--line)]">
              <DetailRow icon="from" label="From" primary={payment.payerName} secondary="Payer account" suffix="FRA" />
              <DetailRow icon="to" label="To" primary={payment.payeeName} secondary={payment.accountHolder} suffix="GHA" tone={payment.knownAccount ? "success" : "warning"} />
              <DetailRow icon="route" label="Route" primary="France to Ghana" secondary={payment.routeName ?? "Evaluating compliant routes"} suffix={payment.routeId ?? "--"} />
              <DetailRow icon="status" label="Status" primary={statusMeta.label} secondary={payment.tier ? `Fraud risk ${payment.score ?? "-"} / ${payment.tier}` : "Checks not completed"} color={statusMeta.color} last />
            </div>

            {payment.intentHash ? (
              <div className="mt-4 flex items-center justify-between gap-3 rounded-lg bg-[var(--surface-2)] px-3 py-2.5 text-[11.5px]">
                <span className="text-ink-2">Signed intent</span>
                <span className="ml-auto font-mono text-ink">{shortHash(payment.intentHash, 10, 6)}</span>
                <span className="rounded border border-[var(--line-strong)] bg-white px-1.5 py-0.5 text-[9.5px] font-medium uppercase text-ink-3">{payment.intentSimulated ? "simulated" : "on-chain"}</span>
              </div>
            ) : null}
          </motion.div>
        ) : (
          <motion.div key="empty" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="px-5 py-5">
            <div className="text-[12px] font-medium text-ink">No active payment</div>
            <p className="mt-1.5 text-[12.5px] leading-relaxed text-ink-2">Select a scenario to inspect its payment details, route and fraud decision.</p>
            <div className="mt-4 grid grid-cols-3 gap-px overflow-hidden rounded-lg border border-[var(--line)] bg-[var(--line)]">
              {[["01", "Legal routes"], ["02", "Fraud risk"], ["03", "Protected route"]].map(([index, label]) => (
                <div key={index} className="bg-white px-2.5 py-3"><div className="font-mono text-[9.5px] text-ink-3">{index}</div><div className="mt-1 text-[11px] text-ink-2">{label}</div></div>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </GlowingShadow>
  );
}

function DetailRow({ icon, label, primary, secondary, suffix, tone, color, last }: { icon: DetailIcon; label: string; primary: string; secondary: string; suffix?: string; tone?: "success" | "warning"; color?: string; last?: boolean }) {
  const toneColor = tone === "success" ? "var(--low)" : tone === "warning" ? "var(--medium)" : "var(--ink-3)";
  return (
    <div className={`grid grid-cols-[26px_44px_minmax(0,1fr)_auto] items-center gap-2 py-2.5 ${last ? "" : "border-b border-[var(--line)]"}`}>
      <span className="grid size-6 place-items-center rounded-md bg-[var(--surface-2)] text-ink-2"><DetailGlyph name={icon} /></span>
      <span className="text-[11px] text-ink-3">{label}</span>
      <span className="min-w-0 text-right">
        <span className="block truncate text-[12px] font-medium" style={color ? { color } : undefined}>{primary}</span>
        <span className="mt-0.5 block truncate text-[10.5px]" style={{ color: tone ? toneColor : "var(--ink-3)" }}>{secondary}</span>
      </span>
      {suffix ? <span className="min-w-7 text-right font-mono text-[9.5px] font-medium text-ink-3">{suffix}</span> : null}
    </div>
  );
}
