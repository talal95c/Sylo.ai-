"use client";

import type { ReactNode } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { ruleLabel } from "@/lib/feed";
import { formatEventTime } from "@/lib/eventTime";
import { paymentStatusView } from "@/lib/paymentStatus";
import { buildQuote } from "@/lib/routeQuote";
import type { ViewState } from "@/lib/store";
import { GlowingShadow } from "./glowing-shadow";
import { Check, cx, ease, euros, PanelHeaderButton, shortHash, Spinner } from "./ui";

type StepState = "pending" | "running" | "done" | "warn" | "fail" | "skipped";

interface Step {
  key: string;
  label: string;
  detail: string;
  state: StepState;
  time: string;
  badge: string;
  extra?: ReactNode;
}

const STEP_EVENTS: Record<string, string[]> = {
  norms: ["norms.checked"],
  risk: ["risk.scored"],
  route: ["route.selected"],
  approval: ["approval.granted"],
  intent: ["intent.committed"],
  settle: ["leg.settled", "escrow.deposited", "payment.held", "verification.requested", "escrow.released", "escrow.refunded"],
  outcome: ["payment.credited", "payment.stopped", "tx.reverted"],
};

function eventTime(state: ViewState, key: string, sourceKind: "live" | "replay") {
  const start = [...state.feed].reverse().find((item) => item.type === "scenario.started")?.ts ?? state.feed[0]?.ts;
  if (!start) return "--";
  const event = [...state.feed].reverse().find((item) => STEP_EVENTS[key]?.includes(item.type));
  if (!event) return "--";
  return formatEventTime(event.ts, sourceKind, start);
}

function buildSteps(state: ViewState, sourceKind: "live" | "replay"): Step[] {
  const p = state.payment;
  const final = p?.status === "credited" || p?.status === "stopped";
  const excluded = state.routes.filter((route) => route.status === "EXCLUDED");
  const settledCount = state.hops.filter((hop) => hop.state === "settled").length;
  const definitions: (Omit<Step, "state" | "time" | "badge"> & { done: boolean; warn?: boolean; fail?: boolean; badge?: string })[] = [
    {
      key: "norms",
      label: "Legal routes checked",
      done: state.routes.length > 0,
      detail: state.routes.length ? `${state.routes.length - excluded.length} of ${state.routes.length} routes allowed${excluded.length ? ` / ${excluded.map((route) => route.routeId).join(", ")} excluded` : ""}` : "France to Ghana norms pack",
      badge: state.routes.length ? "Compliant" : undefined,
    },
    {
      key: "risk",
      label: "Fraud risk scored",
      done: Boolean(state.risk),
      warn: state.risk ? state.risk.tier !== "LOW" : false,
      detail: state.risk ? `${state.risk.score} / ${state.risk.tier} / ${state.risk.reasons.length} ${state.risk.reasons.length === 1 ? "reason" : "reasons"}` : "Deterministic fraud controls",
      badge: state.risk ? (state.risk.tier === "LOW" ? "Low risk" : "Review") : undefined,
    },
    {
      key: "route",
      label: "Compliant route selected",
      done: Boolean(state.selectedRouteId),
      detail: p?.routeName ? `${p.routeId} / ${p.routeName}` : "Fraud risk never enters the route score",
      badge: state.selectedRouteId ? "Selected" : undefined,
      extra: state.routeScores.length || state.routes.length ? <RouteTable state={state} /> : undefined,
    },
    {
      key: "approval",
      label: state.approval?.conditional ? "Conditional dual approval" : "Dual approval",
      done: Boolean(state.approval),
      detail: state.approval ? state.approval.by.map((person) => person.name).join(" + ") : "CFO and second approver",
      badge: state.approval ? (state.approval.conditional ? "Conditional" : "Approved") : undefined,
    },
    {
      key: "intent",
      label: "Payment intent sealed",
      done: Boolean(p?.intentHash),
      detail: p?.intentHash ? `${shortHash(p.intentHash, 8, 4)} / EIP-712` : "Signed before funds move",
      badge: p?.intentHash ? "Sealed" : undefined,
    },
    {
      key: "settle",
      label: state.held ? "Funds protected in escrow" : "Settlement controls",
      done: p?.status === "credited" || state.refunded || (state.hops.length > 0 && settledCount === state.hops.length),
      warn: Boolean(state.held) && !state.released,
      fail: state.refunded,
      detail: state.refunded ? "Intent revoked / funds returned" : state.released ? "Supplier confirmed / escrow released" : state.verification.requested ? `Known-contact check with ${state.verification.requested.contactName}` : state.hops.length ? `${settledCount} of ${state.hops.length} legs settled` : "Follows the signed payment intent",
      badge: state.refunded ? "Refunded" : state.released ? "Released" : state.held ? "Protected" : undefined,
    },
    {
      key: "outcome",
      label: p?.status === "stopped" ? "Payment stopped" : p?.status === "credited" ? "Supplier credited" : "Final outcome",
      done: final,
      fail: p?.status === "stopped",
      detail: state.attack.reverted ? "Unauthorized release rejected" : p?.status === "stopped" ? "Refunded to payer / analyst case opened" : state.credited ? creditedSummary(state) : "Credited or stopped",
      badge: p?.status === "stopped" ? "Stopped" : p?.status === "credited" ? "Credited" : undefined,
    },
  ];

  let runningAssigned = false;
  const waiting = p?.status === "held" || p?.status === "awaiting_supplier" || p?.status === "awaiting_analyst";
  return definitions.map((step) => {
    let value: StepState = "pending";
    if (step.done) value = step.fail ? "fail" : step.warn ? "warn" : "done";
    else if (final) value = "skipped";
    else if (p && !final && !runningAssigned) {
      runningAssigned = true;
      value = step.warn && waiting ? "warn" : "running";
    }
    const defaultBadge = value === "running" ? "Processing" : value === "pending" ? "Pending" : value === "skipped" ? "Skipped" : value === "warn" ? "Review" : value === "fail" ? "Blocked" : "Complete";
    return { key: step.key, label: step.label, detail: step.detail, state: value, time: eventTime(state, step.key, sourceKind), badge: step.badge ?? defaultBadge, extra: step.extra };
  });
}

function creditedSummary(state: ViewState) {
  const quote = buildQuote(state);
  if (!quote) return "Supplier credited";
  const label = quote.basis === "cash" ? "fees + FX" : "all-in";
  return quote.swift ? `${euros(quote.cost)} ${label} vs ${euros(quote.swift.cost)} via SWIFT` : `${euros(quote.cost)} ${label}`;
}

function RouteTable({ state }: { state: ViewState }) {
  const rows: { routeId: string; s: number | null | undefined; excludedBy?: string | null }[] = state.routeScores.length
    ? state.routeScores
    : state.routes.map((route) => ({ routeId: route.routeId, s: route.status === "EXCLUDED" ? null : undefined, excludedBy: route.excludedBy }));
  const rank = (row: (typeof rows)[number]) => row.excludedBy || row.s === null ? 2e9 : typeof row.s === "number" ? row.s : 1e9;
  return (
    <div className="mt-2 space-y-0.5">
      {[...rows]
        .sort((a, b) => rank(a) - rank(b))
        .map((score) => {
          const route = state.routes.find((candidate) => candidate.routeId === score.routeId);
          const chosen = score.routeId === state.selectedRouteId;
          const excluded = score.s === null || Boolean(score.excludedBy);
          const exclusion = ruleLabel(score.excludedBy ?? route?.excludedBy ?? "Excluded");
          return (
            <div key={score.routeId} className={cx("grid grid-cols-[18px_minmax(0,1fr)_auto] items-baseline gap-1.5 rounded-md px-2 py-1 text-[11px] leading-snug", chosen ? "bg-[var(--accent-soft)] text-accent" : "text-ink-2")}>
              <span className={cx("font-mono text-[10px]", chosen ? "text-accent" : "text-ink-3")}>{score.routeId}</span>
              <span className={excluded ? "text-ink-3 line-through decoration-[rgba(0,0,0,.25)]" : chosen ? "font-medium" : ""}>{route?.name ?? score.routeId}</span>
              <span className={cx("max-w-24 truncate tabular-nums", excluded && "text-[var(--danger)]")} title={excluded ? exclusion : undefined}>{excluded ? exclusion : typeof score.s === "number" ? euros(score.s) : "—"}</span>
            </div>
          );
        })}
    </div>
  );
}

const STEP_COLOR: Record<StepState, string> = {
  pending: "rgba(0,0,0,.28)",
  running: "var(--accent)",
  done: "var(--low)",
  warn: "var(--medium)",
  fail: "var(--danger)",
  skipped: "rgba(0,0,0,.2)",
};

function StepIcon({ state, index }: { state: StepState; index: number }) {
  if (state === "running") return <Spinner size={14} />;
  if (state === "done") return <Check size={14} />;
  if (state === "warn") return <span className="text-[11px] font-bold">!</span>;
  if (state === "fail") return <svg width="9" height="9" viewBox="0 0 10 10" aria-hidden><path d="M2 2l6 6M8 2 2 8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" /></svg>;
  if (state === "skipped") return <span className="font-mono text-[10px]">−</span>;
  return <span className="font-mono text-[8.5px]">{String(index + 1).padStart(2, "0")}</span>;
}

function decisionSummary(state: ViewState) {
  const status = state.payment?.status;
  if (!status) return { title: "Ready for a scenario", detail: "No payment decision has been requested.", color: "var(--ink-3)" };
  if (status === "deciding") return { title: "Decision in progress", detail: "The engine is evaluating legal routes and fraud controls.", color: "var(--accent)" };
  if (status === "in_transit") return { title: "Payment released", detail: "The approved payment is following its signed route.", color: "var(--accent)" };
  if (status === "held" || status === "awaiting_supplier" || status === "awaiting_analyst") return { title: "Conditional hold active", detail: "Funds remain protected while the known-contact check is completed.", color: "var(--medium)" };
  if (status === "frozen") return { title: "Guardian freeze active", detail: state.incident?.headline ?? "The payment is frozen and the corridor is paused.", color: "var(--danger)" };
  if (status === "stopped") return { title: "Payment stopped", detail: state.refunded ? "The intent was revoked and the funds were returned to the payer." : "Blocked before any money moved. A case was opened for the analyst.", color: "var(--danger)" };
  if (status === "credited") return { title: "Payment cleared", detail: "The supplier was credited through the approved route.", color: "var(--low)" };
  return { title: "Awaiting events", detail: "The panel updates as the engine reports each step.", color: "var(--ink-3)" };
}

export function DecisionSteps({ state, expanded, onExpandedChange, sourceKind = "replay" }: { state: ViewState; expanded: boolean; onExpandedChange: (expanded: boolean) => void; sourceKind?: "live" | "replay" }) {
  const steps = buildSteps(state, sourceKind);
  const completed = steps.filter((step) => step.state === "done" || step.state === "warn" || step.state === "fail").length;
  const summary = decisionSummary(state);
  const final =
    state.payment?.status === "credited" || state.payment?.status === "stopped";
  const summaryCard = (
    <div className="mx-4 mb-4 rounded-lg bg-[var(--accent-soft)] px-3 py-3">
      <div className="flex items-center gap-2 text-[11.5px] font-semibold text-accent"><span className="grid size-5 place-items-center rounded-md border border-[color-mix(in_srgb,var(--accent)_16%,white)] bg-white text-[11px]">✣</span>Decision: {final ? paymentStatusView(state).label : summary.title}</div>
      <p className="mt-1 text-[11px] leading-relaxed text-ink-2">{summary.detail}</p>
    </div>
  );
  return (
    <GlowingShadow layout initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25, ease }} className={cx("flex min-h-0 w-full", expanded ? "flex-1" : "shrink-0")} panelClassName="flex min-h-0 flex-col overflow-clip" aria-label="Engine decisions">
      <PanelHeaderButton
        index="02"
        title="Engine decisions"
        meta={`${completed} · ${steps.length} steps`}
        expanded={expanded}
        controls="engine-decisions-content"
        onToggle={() => onExpandedChange(!expanded)}
        sticky
      />

      <AnimatePresence initial={false}>
        {expanded ? (
          <motion.div
            id="engine-decisions-content"
            key="engine-decisions-content"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.22, ease }}
            className="thin-scrollbar min-h-0 shrink basis-auto overflow-y-auto overscroll-contain"
          >
      {final ? <div className="sticky top-0 z-[2] bg-white pt-1">{summaryCard}</div> : null}
      <ol className="px-4 py-1">
        {steps.map((step, index) => (
          <motion.li key={step.key} layout="position" transition={{ duration: 0.25, ease }} className="relative grid grid-cols-[54px_22px_minmax(0,1fr)_auto] items-start gap-2 py-2">
            <time className="pt-0.5 font-mono text-[10px] text-ink-3">{step.time}</time>
            <span data-timeline-column className="grid w-[22px] self-stretch grid-rows-[18px_minmax(0,1fr)] justify-items-center">
              <span data-timeline-marker className="relative z-[1] col-start-1 row-start-1 grid size-[18px] place-items-center rounded-full border bg-white" style={{ color: STEP_COLOR[step.state], borderColor: `color-mix(in srgb, ${STEP_COLOR[step.state]} 42%, white)` }}>
                <AnimatePresence mode="wait" initial={false}><motion.span key={step.state} initial={{ scale: 0.6, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.6, opacity: 0 }} transition={{ duration: 0.18 }} className="grid place-items-center"><StepIcon state={step.state} index={index} /></motion.span></AnimatePresence>
              </span>
              {index < steps.length - 1 ? <span data-timeline-line className="col-start-1 row-start-2 h-[calc(100%+16px)] w-px justify-self-center bg-[var(--line-strong)]" aria-hidden /> : null}
            </span>
            <div className="min-w-0">
              <div className={cx("text-[12.5px] font-medium", (step.state === "pending" || step.state === "skipped") && "text-ink-3")} style={step.state === "running" ? { color: "var(--accent)" } : undefined}>{step.label}</div>
              <div className="mt-0.5 truncate text-[11px] leading-snug text-ink-3" title={step.detail}>{step.detail}</div>
            </div>
            <span className="mt-0.5 rounded-full border px-2 py-1 text-[11px] font-medium" style={{ color: STEP_COLOR[step.state], borderColor: `color-mix(in srgb, ${STEP_COLOR[step.state]} 14%, white)`, background: `color-mix(in srgb, ${STEP_COLOR[step.state]} 8%, white)` }}>{step.badge}</span>
            {step.extra && step.state !== "pending" ? <div className="col-span-2 col-start-3 min-w-0">{step.extra}</div> : null}
          </motion.li>
        ))}
      </ol>

      {!final ? summaryCard : null}
          </motion.div>
        ) : null}
      </AnimatePresence>
    </GlowingShadow>
  );
}
