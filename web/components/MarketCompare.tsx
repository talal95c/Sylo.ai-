"use client";

import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { MARKET_CAPTURED_ON, marketRows } from "@/lib/market";
import { pct, type QuoteView } from "@/lib/routeQuote";
import { cx, ease, euros } from "./ui";

export function MarketCompare({ quote }: { quote: QuoteView }) {
  const [open, setOpen] = useState(false);
  const rows = marketRows(quote.amountEur);
  return (
    <div className="mt-2">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="inline-flex items-center gap-1 text-[11px] font-medium text-accent hover:opacity-80"
      >
        What would today&apos;s market have cost?
        <motion.svg animate={{ rotate: open ? 180 : 0 }} transition={{ duration: 0.25, ease }} width="10" height="10" viewBox="0 0 10 10" aria-hidden>
          <path d="m2 3.5 3 3 3-3" stroke="currentColor" strokeWidth="1.4" fill="none" strokeLinecap="round" strokeLinejoin="round" />
        </motion.svg>
      </button>
      <AnimatePresence initial={false}>
        {open ? (
          <motion.div
            key="market"
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.35, ease }}
            className="overflow-hidden"
          >
            <div className="mt-2 rounded-[10px] border border-[var(--line)] bg-white p-2" aria-label="Market comparison">
              <MarketRow name="Sylo" kind={`${quote.routeId} · simulated`} cost={quote.cost} costPct={quote.costPct} eta={quote.etaLabel} highlight />
              {rows.map((row) => {
                const delta = row.costEur - quote.cost;
                return (
                  <MarketRow
                    key={row.quote.id}
                    name={row.quote.name}
                    kind={row.quote.kind}
                    cost={row.costEur}
                    costPct={row.costPct}
                    eta={row.quote.eta}
                    delta={delta}
                    note={row.transfers > 1 ? `max GH₵${row.quote.maxRecipientGhs!.toLocaleString("en-US")} per transfer → ${row.transfers} transfers` : row.quote.note}
                    title={`${row.quote.source} · captured ${row.quote.capturedAt}`}
                  />
                );
              })}
              <p className="mt-1.5 px-1 text-[9px] leading-snug text-ink-3">
                Real public quotes for the same amount, EUR→GHS, captured up to {MARKET_CAPTURED_ON} (Wise price API and comparison data). Fees + FX margin vs mid-market. Sylo figures are simulated.
              </p>
            </div>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </div>
  );
}

function MarketRow({ name, kind, cost, costPct, eta, delta, note, title, highlight }: { name: string; kind: string; cost: number; costPct: number; eta: string; delta?: number; note?: string; title?: string; highlight?: boolean }) {
  return (
    <div className={cx("grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 rounded-md px-1.5 py-1.5", highlight ? "bg-[var(--accent-soft)]" : "border-t border-[var(--line)]")} title={title}>
      <div className="min-w-0">
        <div className={cx("truncate text-[11px] font-medium", highlight ? "text-accent" : "text-ink")}>
          {name} <span className="font-normal text-ink-3">· {kind}</span>
        </div>
        <div className="truncate text-[9.5px] text-ink-3">{eta}{note ? ` · ${note}` : ""}</div>
      </div>
      <div className="text-right">
        <div className="text-[11px] font-medium tabular-nums text-ink">{euros(Math.round(cost))} <span className="font-normal text-ink-3">{pct(costPct)}</span></div>
        {delta !== undefined ? (
          <div className="text-[9.5px] tabular-nums" style={{ color: delta > 0 ? "var(--low)" : "var(--medium)" }}>
            {delta > 0 ? `Sylo saves ${euros(Math.round(delta))}` : `${euros(Math.round(-delta))} cheaper than Sylo`}
          </div>
        ) : null}
      </div>
    </div>
  );
}
