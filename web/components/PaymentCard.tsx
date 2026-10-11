"use client";

import type { ReactNode } from "react";
import { AnimatePresence, motion } from "framer-motion";
import type { PaymentStatus, ViewState } from "@/lib/store";
import { TIER_COLORS } from "@/lib/colors";
import { GlowingShadow } from "./glowing-shadow";
import { Dot, ease, euros, formatMoney, Metric, shortHash, Spinner, Tag } from "./ui";

const STATUS: Record<PaymentStatus, { label: string; color: string; busy?: boolean }> = {
  idle: { label: "Ready", color: "rgba(0,0,0,.38)" },
  deciding: { label: "Decision in progress", color: "var(--accent)", busy: true },
  in_transit: { label: "In transit", color: "var(--accent)", busy: true },
  held: { label: "Held in escrow", color: "var(--medium)" },
  awaiting_supplier: { label: "Awaiting supplier", color: "var(--medium)", busy: true },
  stopped: { label: "Stopped and refunded", color: "var(--danger)" },
  credited: { label: "Supplier credited", color: "var(--low)" },
};

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

export function PaymentCard({ state }: { state: ViewState }) {
  const payment = state.payment;

  return (
    <GlowingShadow layout initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.7, ease, delay: 0.1 }} className="shrink-0" panelClassName="overflow-hidden" aria-label="Payment">
      <div className="flex items-center justify-between px-4 pb-2 pt-4">
        <Tag index="01">Payment</Tag>
        <StatusPill status={payment?.status ?? "idle"} />
      </div>

      <AnimatePresence mode="wait" initial={false}>
        {payment ? (
          <motion.div key={payment.paymentId} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.35, ease }} className="px-4 pb-4 pt-2">
            <div className="flex items-baseline justify-between gap-3">
              <div className="text-[30px] font-medium leading-none tracking-[-0.045em] tabular-nums">
                {formatMoney(payment.amount.value, payment.amount.currency)}
              </div>
              <span className="font-mono text-[10px] text-ink-3">{payment.paymentId}</span>
            </div>

            <div className="mt-4 space-y-2 text-[12.5px]">
              <Row label="From" value={payment.payerName} />
              <Row label="To" value={payment.payeeName} />
              <Row
                label="Account"
                value={
                  <span className="flex min-w-0 items-center justify-end gap-2">
                    <span className={payment.knownAccount ? "truncate" : "truncate font-medium"}>{payment.accountHolder}</span>
                    <span
                      className="shrink-0 rounded-full px-2 py-0.5 text-[10.5px] font-medium"
                      style={
                        payment.knownAccount
                          ? { color: "var(--low)", background: "color-mix(in srgb, var(--low) 10%, white)" }
                          : { color: "var(--medium)", background: "color-mix(in srgb, var(--medium) 12%, white)" }
                      }
                    >
                      {payment.knownAccount ? "Nominated" : "New account"}
                    </span>
                  </span>
                }
              />
            </div>

            <div className="mt-4 grid grid-cols-3 gap-3 border-t border-[var(--line)] pt-3.5">
              <Metric
                label="Fraud risk"
                value={payment.score !== undefined ? payment.score : "—"}
                sub={payment.tier ?? "scoring…"}
                color={payment.tier ? TIER_COLORS[payment.tier] : "rgba(0,0,0,.12)"}
              />
              <Metric
                label="Route cost"
                value={payment.routeCostEur !== undefined ? euros(payment.routeCostEur) : "—"}
                sub={payment.routeId ? `${payment.routeId} · all-in` : "routing…"}
                color={payment.routeId ? "var(--accent)" : "rgba(0,0,0,.12)"}
              />
              <Metric
                label="Arrival"
                value={payment.etaLabel ?? "—"}
                sub={payment.feesEur !== undefined ? `fees ${euros(payment.feesEur)}` : undefined}
                color={payment.etaLabel ? "#8b5cf6" : "rgba(0,0,0,.12)"}
              />
            </div>

            <AnimatePresence>
              {payment.intentHash ? (
                <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} transition={{ duration: 0.4, ease }} className="overflow-hidden">
                  <div className="mt-4 flex items-center justify-between gap-3 rounded-lg bg-[var(--surface-2)] px-3 py-2.5 text-[11.5px]">
                    <span className="text-ink-2">Signed intent</span>
                    <span className="ml-auto font-mono text-ink">{shortHash(payment.intentHash, 10, 6)}</span>
                    <span className="rounded border border-[var(--line-strong)] bg-white px-1.5 py-0.5 text-[9.5px] font-medium uppercase text-ink-3">{payment.intentSimulated ? "simulated" : "on-chain"}</span>
                  </div>
                </motion.div>
              ) : null}
            </AnimatePresence>
          </motion.div>
        ) : (
          <motion.div key="empty" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="px-4 pb-4 pt-2">
            <h1 className="text-[24px] font-medium leading-[1.12] tracking-[-0.045em]">
              Stop the diverted payment <span className="text-ink-3">before the money is gone.</span>
            </h1>
            <p className="mt-2.5 text-[12.5px] leading-relaxed text-ink-2">
              Run a scenario. The engine checks the law, scores fraud, picks the cheapest compliant route and seals the payment on Avalanche before any money moves.
            </p>
          </motion.div>
        )}
      </AnimatePresence>
    </GlowingShadow>
  );
}

function Row({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4">
      <span className="shrink-0 text-ink-3">{label}</span>
      <span className="min-w-0 truncate text-right text-ink">{value}</span>
    </div>
  );
}
