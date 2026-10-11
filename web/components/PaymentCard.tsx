"use client";

import type { ReactNode } from "react";
import { AnimatePresence, motion } from "framer-motion";
import type { PaymentStatus, ViewState } from "@/lib/store";
import { RouteQuote } from "./RouteQuote";
import { Dot, ease, shortHash, Spinner, Tag } from "./ui";

const STATUS: Record<PaymentStatus, { label: string; color: string; busy?: boolean }> = {
  idle: { label: "Ready", color: "rgba(0,0,0,.38)" },
  deciding: { label: "Decision in progress", color: "var(--accent)", busy: true },
  in_transit: { label: "In transit", color: "var(--accent)", busy: true },
  held: { label: "Held in escrow", color: "var(--medium)" },
  awaiting_supplier: { label: "Awaiting supplier", color: "var(--medium)", busy: true },
  frozen: { label: "Frozen by the guardian", color: "var(--danger)" },
  stopped: { label: "Stopped", color: "var(--danger)" },
  credited: { label: "Supplier credited", color: "var(--low)" },
};

function statusMeta(status: PaymentStatus, refunded: boolean) {
  const meta = STATUS[status];
  return status === "stopped" && refunded ? { ...meta, label: "Stopped and refunded" } : meta;
}

export function StatusPill({ status, refunded = false }: { status: PaymentStatus; refunded?: boolean }) {
  const meta = statusMeta(status, refunded);
  return (
    <AnimatePresence mode="wait" initial={false}>
      <motion.span
        key={meta.label}
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
  const status = statusMeta(payment?.status ?? "idle", state.refunded);

  return (
    <motion.section layout initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.7, ease, delay: 0.1 }} className="card shrink-0 overflow-clip rounded-[18px]" aria-label="Payment">
      <div className="sticky top-0 z-10 flex items-center justify-between rounded-t-[18px] bg-white px-4 pb-2 pt-4">
        <Tag index="01">Payment</Tag>
        <StatusPill status={payment?.status ?? "idle"} refunded={state.refunded} />
      </div>

      <AnimatePresence mode="wait" initial={false}>
        {payment ? (
          <motion.div key={payment.paymentId} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.35, ease }} className="px-4 pb-3.5 pt-1">
            <div className="flex flex-wrap items-center gap-2">
              <div className="text-[31px] font-semibold leading-none tabular-nums">
                {formatAmount(payment.amount.value, payment.amount.currency)}
              </div>
              <span className="rounded-full border border-[var(--line)] bg-[var(--surface-2)] px-2.5 py-1 text-[10px] font-medium text-ink-2">
                {payment.amount.currency}
              </span>
            </div>

            <div className="mt-2 truncate text-[13px] font-medium text-ink">Payment to {payment.payeeName}</div>
            <div className="mt-0.5 font-mono text-[10px] text-ink-3">{payment.paymentId}</div>

            <div className="mt-3 border-t border-[var(--line)]">
              <PaymentRow icon="bank" label="From" value={payment.payerName} />
              <PaymentRow
                icon="bank"
                label="To"
                value={payment.payeeName}
                detail={payment.accountHolder !== payment.payeeName ? payment.accountHolder : undefined}
                trailing={<AccountBadge known={payment.knownAccount} />}
              />
              <PaymentRow
                icon="route"
                label="Route"
                value={
                  payment.status === "stopped" && !payment.routeName
                    ? "No route allowed"
                    : payment.routeName ?? "Awaiting route selection"
                }
                detail={
                  payment.status === "stopped" && !payment.routeName
                    ? state.stopped?.detail
                    : routeDetail(payment)
                }
              />
              <PaymentRow
                icon="status"
                label="Status"
                value={status.label}
                valueColor={status.color}
                detail={payment.intentHash ? `Signed intent ${shortHash(payment.intentHash, 8, 5)}` : riskDetail(payment)}
                badge={payment.intentHash ? (payment.intentSimulated ? "Simulated" : "On-chain") : undefined}
                trailing={payment.tier && payment.score !== undefined ? <RiskBadge tier={payment.tier} score={payment.score} /> : undefined}
                last
              />
            </div>
            <RouteQuote state={state} />
          </motion.div>
        ) : (
          <motion.div key="empty" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="px-4 pb-4 pt-2">
            <h1 className="text-[24px] font-medium leading-[1.12]">
              Stop the diverted payment <span className="text-ink-3">before the money is gone.</span>
            </h1>
            <p className="mt-2.5 text-[12.5px] leading-relaxed text-ink-2">
              Run a scenario. The engine checks the law, scores fraud, picks the cheapest compliant route and seals the payment on Avalanche before any money moves.
            </p>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.section>
  );
}

function formatAmount(value: string, currency: string) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    currencyDisplay: "narrowSymbol",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(Number(value));
}

function routeDetail(payment: NonNullable<ViewState["payment"]>) {
  const details = [payment.routeId, payment.etaLabel];
  return details.filter(Boolean).join(" · ") || "The engine is evaluating compliant routes";
}

function riskDetail(payment: NonNullable<ViewState["payment"]>) {
  if (!payment.tier || payment.score === undefined) return "Fraud controls in progress";
  return `${payment.tier} risk · score ${payment.score}`;
}

function AccountBadge({ known }: { known: boolean }) {
  return (
    <span
      className="rounded-full px-2 py-1 text-[9.5px] font-medium"
      style={
        known
          ? { color: "var(--low)", background: "color-mix(in srgb, var(--low) 9%, white)" }
          : { color: "var(--medium)", background: "color-mix(in srgb, var(--medium) 10%, white)" }
      }
    >
      {known ? "Nominated" : "New account"}
    </span>
  );
}

function RiskBadge({ tier, score }: { tier: NonNullable<ViewState["payment"]>["tier"]; score: number }) {
  return (
    <span className="rounded-full bg-[var(--surface-2)] px-2 py-1 text-[9.5px] font-medium text-ink-2">
      {tier} · {score}
    </span>
  );
}

function PaymentRow({
  icon,
  label,
  value,
  detail,
  badge,
  trailing,
  valueColor,
  last,
}: {
  icon: "bank" | "route" | "status";
  label: string;
  value: ReactNode;
  detail?: string;
  badge?: string;
  trailing?: ReactNode;
  valueColor?: string;
  last?: boolean;
}) {
  return (
    <div className={`grid grid-cols-[26px_42px_minmax(0,1fr)_auto] items-center gap-2 py-2.5 ${last ? "" : "border-b border-[var(--line)]"}`}>
      <span className="grid size-6 place-items-center rounded-full bg-[var(--surface-2)] text-ink-2">
        <PaymentIcon name={icon} />
      </span>
      <span className="text-[10.5px] text-ink-3">{label}</span>
      <span className="min-w-0">
        <span className="block truncate text-[12px] font-medium" style={valueColor ? { color: valueColor } : undefined}>{value}</span>
        {detail || badge ? (
          <span className="mt-0.5 flex min-w-0 items-center gap-1.5">
            {detail ? <span className="block min-w-0 truncate text-[9.5px] text-ink-3" title={detail}>{detail}</span> : null}
            {badge ? <span className="shrink-0 rounded-full border border-[var(--line-strong)] bg-[var(--surface-2)] px-1.5 py-0.5 text-[8px] font-medium leading-none text-ink-2">{badge}</span> : null}
          </span>
        ) : null}
      </span>
      {trailing ? <span className="ml-1 shrink-0">{trailing}</span> : null}
    </div>
  );
}

function PaymentIcon({ name }: { name: "bank" | "route" | "status" }) {
  if (name === "route") {
    return <svg width="13" height="13" viewBox="0 0 16 16" fill="none" aria-hidden><circle cx="3" cy="4" r="1.5" stroke="currentColor" strokeWidth="1.4" /><circle cx="13" cy="12" r="1.5" stroke="currentColor" strokeWidth="1.4" /><path d="M4.5 4h2A2.5 2.5 0 0 1 9 6.5v3A2.5 2.5 0 0 0 11.5 12" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" /></svg>;
  }
  if (name === "status") {
    return <svg width="13" height="13" viewBox="0 0 16 16" fill="none" aria-hidden><circle cx="8" cy="8" r="6" stroke="currentColor" strokeWidth="1.4" /><path d="m5 8 2 2 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" /></svg>;
  }
  return <svg width="13" height="13" viewBox="0 0 16 16" fill="none" aria-hidden><path d="M2.5 6h11M3.5 6v6.5m3-6.5v6.5m3-6.5v6.5m3-6.5v6.5M2 13h12M8 2l6 3H2l6-3Z" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" /></svg>;
}
