"use client";

import { AnimatePresence, motion } from "framer-motion";
import { buildQuote, cedis, etaShare, pct, type QuoteView } from "@/lib/routeQuote";
import type { ViewState } from "@/lib/store";
import { cx, ease, euros } from "./ui";

export function RouteQuote({ state }: { state: ViewState }) {
  const quote = buildQuote(state);
  const status = state.payment?.status;
  const notPaid = status === "stopped" ? "Stopped · not paid" : status === "held" || status === "frozen" || status === "awaiting_supplier" ? "On hold · not paid yet" : null;
  return (
    <AnimatePresence initial={false}>
      {quote ? (
        <motion.div
          key="quote"
          initial={{ opacity: 0, height: 0 }}
          animate={{ opacity: 1, height: "auto" }}
          exit={{ opacity: 0, height: 0 }}
          transition={{ duration: 0.45, ease }}
          className="overflow-hidden"
        >
          <div className="mt-2 rounded-[14px] border border-[var(--line)] bg-[var(--surface-2)] p-3" aria-label="Route quote">
            <div className="flex items-center justify-between">
              <span className="text-[10.5px] font-medium text-ink-2">Quote · {quote.routeId}</span>
              <span className={cx("rounded-full border px-2 py-0.5 text-[9px]", notPaid ? "border-[var(--danger)] text-[var(--danger)]" : "border-[var(--line)] bg-white text-ink-3")}>{notPaid ?? "Simulated rates"}</span>
            </div>

            <dl className="mt-2 space-y-1 text-[11.5px]">
              <QuoteLine label="You send" value={euros(quote.amountEur)} />
              {quote.recipientGetsGhs !== undefined ? (
                <QuoteLine label={notPaid ? "Supplier would get" : "Supplier gets"} value={cedis(quote.recipientGetsGhs)} detail={quote.midRateEurGhs ? `mid rate ${quote.midRateEurGhs}` : undefined} strong />
              ) : null}
              <QuoteLine
                label={quote.basis === "cash" ? "Fees + FX margin" : "All-in cost"}
                value={`${euros(quote.cost)} · ${pct(quote.costPct)}`}
                detail={quote.basis === "cash" && quote.fxMarginEur !== undefined ? `${euros(quote.feesEur)} fees + ${euros(quote.fxMarginEur)} FX` : undefined}
              />
              <QuoteLine label="Arrives" value={quote.etaLabel} detail="estimate" />
            </dl>

            {!notPaid && quote.swift && quote.savedEur !== undefined ? <Savings quote={quote} /> : null}

            <RouteRows quote={quote} />

            {quote.basis === "cash" && quote.totalCostEur !== undefined ? (
              <p className="mt-2 text-[9.5px] leading-snug text-ink-3">
                Ranked on all-in cost (fees, FX margin, cost of delay and failure risk): {euros(quote.totalCostEur)}
                {quote.swift?.totalCostEur !== undefined ? ` vs ${euros(quote.swift.totalCostEur)} via SWIFT` : ""}. Fraud risk never enters the score.
              </p>
            ) : null}
          </div>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}

function QuoteLine({ label, value, detail, strong }: { label: string; value: string; detail?: string; strong?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="text-ink-3">{label}</dt>
      <dd className={cx("text-right tabular-nums", strong ? "font-semibold text-ink" : "font-medium text-ink")}>
        {value}
        {detail ? <span className="ml-1.5 text-[9.5px] font-normal text-ink-3">{detail}</span> : null}
      </dd>
    </div>
  );
}

export function Savings({ quote, compact }: { quote: QuoteView; compact?: boolean }) {
  const swift = quote.swift!;
  const saved = quote.savedEur ?? 0;
  const slowest = Math.max(quote.etaMinutes ?? 0, swift.etaMinutes ?? 0);
  return (
    <div className={cx("rounded-[10px] bg-white", compact ? "mt-2 p-2" : "mt-2.5 p-2.5")}>
      <div className="flex items-baseline justify-between gap-2 text-[11px]">
        <span className="text-ink-3">
          vs SWIFT <span className="tabular-nums text-ink-2">{euros(swift.cost)}</span>
        </span>
        <span className="font-semibold tabular-nums" style={{ color: saved > 0 ? "var(--low)" : "var(--medium)" }}>
          {saved > 0 ? `Save ${euros(saved)}` : `+${euros(-saved)}`}
          {quote.savedPct !== undefined ? ` · ${pct(Math.abs(quote.savedPct))}` : ""}
        </span>
      </div>
      {quote.etaMinutes && swift.etaMinutes ? (
        <div className="mt-2 space-y-1">
          <EtaBar label="Sylo" eta={quote.etaLabel} share={etaShare(quote.etaMinutes, slowest)} color="var(--accent)" />
          <EtaBar label="SWIFT" eta={swift.etaLabel ?? ""} share={etaShare(swift.etaMinutes, slowest)} color="rgba(0,0,0,.28)" />
        </div>
      ) : null}
    </div>
  );
}

function EtaBar({ label, eta, share, color }: { label: string; eta: string; share: number; color: string }) {
  return (
    <div className="grid grid-cols-[38px_minmax(0,1fr)_58px] items-center gap-2 text-[9.5px]">
      <span className="text-ink-3">{label}</span>
      <span className="h-1.5 overflow-hidden rounded-full bg-[var(--surface-2)]">
        <motion.span className="block h-full rounded-full" style={{ background: color }} initial={{ width: 0 }} animate={{ width: `${share * 100}%` }} transition={{ duration: 0.9, ease }} />
      </span>
      <span className="text-right tabular-nums text-ink-2">{eta}</span>
    </div>
  );
}

function RouteRows({ quote }: { quote: QuoteView }) {
  return (
    <div className="mt-2.5 border-t border-[var(--line)] pt-2">
      <div className="mb-1 grid grid-cols-[22px_minmax(0,1fr)_56px_64px] gap-1.5 px-1 text-[9px] uppercase tracking-wide text-ink-3">
        <span />
        <span>Route</span>
        <span className="text-right">Arrives</span>
        <span className="text-right">{quote.basis === "cash" ? "Fees + FX" : "All-in"}</span>
      </div>
      {quote.rows.map((row) => (
        <div
          key={row.routeId}
          className={cx(
            "grid grid-cols-[22px_minmax(0,1fr)_56px_64px] items-baseline gap-1.5 rounded-md px-1 py-1 text-[10.5px]",
            row.chosen ? "bg-[var(--accent-soft)] text-accent" : "text-ink-2",
          )}
          title={row.excluded ? `Excluded by ${row.excludedBy ?? "policy"}` : undefined}
        >
          <span className={cx("font-mono text-[9.5px]", row.chosen ? "text-accent" : "text-ink-3")}>{row.routeId}</span>
          <span className="min-w-0">
            <span className={cx("block truncate", row.excluded ? "text-ink-3 line-through decoration-[rgba(0,0,0,.25)]" : row.chosen && "font-medium")}>{row.name}</span>
            {row.excluded ? <span className="block text-[9px] leading-snug text-[var(--danger)]">{exclusionLabel(row.excludedBy)}</span> : null}
          </span>
          <span className="text-right tabular-nums">{row.etaLabel ?? "—"}</span>
          <span className={cx("text-right tabular-nums", row.excluded && "text-ink-3")}>{row.cost !== undefined ? euros(Math.round(row.cost)) : "—"}</span>
        </div>
      ))}
    </div>
  );
}

export function exclusionLabel(ruleId?: string | null) {
  if (!ruleId) return "Excluded";
  const words = ruleId.split("_").filter(Boolean);
  const [country, ...rest] = words;
  const text = rest.join(" ").toLowerCase();
  return country && country.length === 2 ? `${country} rule: ${text}` : words.join(" ").toLowerCase();
}
