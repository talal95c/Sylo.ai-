"use client";

import { AnimatePresence, motion } from "framer-motion";
import type { ViewState } from "@/lib/store";
import { GlowingShadow } from "./glowing-shadow";
import { Check, cx, ease, euros, shortHash, Spinner, Tag } from "./ui";

type StepState = "pending" | "running" | "done" | "warn" | "fail";

interface Step {
  key: string;
  label: string;
  detail: string;
  state: StepState;
  time: string;
  badge: string;
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

function eventTime(state: ViewState, key: string) {
  const start = state.feed[0]?.ts;
  if (!start) return "--";
  const event = [...state.feed].reverse().find((item) => STEP_EVENTS[key]?.includes(item.type));
  if (!event) return "--";
  return event.ts.slice(11, 19);
}

function buildSteps(state: ViewState): Step[] {
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
      detail: state.risk ? `${state.risk.score} / ${state.risk.tier} / ${state.risk.rulesFired.length} rules fired` : "Deterministic fraud controls",
      badge: state.risk ? (state.risk.tier === "LOW" ? "Low risk" : "Review") : undefined,
    },
    {
      key: "route",
      label: "Compliant route selected",
      done: Boolean(state.selectedRouteId),
      detail: p?.routeName ? `${p.routeId} / ${p.routeName}` : "Cheapest eligible payment rail",
      badge: state.selectedRouteId ? "Selected" : undefined,
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
      detail: state.attack.reverted ? "Unauthorized release rejected" : p?.status === "stopped" ? "Refunded to payer / analyst case opened" : state.credited ? `${euros(state.credited.routeCostEur)} all-in vs ${euros(state.credited.swiftRouteCostEur)} via SWIFT` : "Credited or stopped",
      badge: p?.status === "stopped" ? "Stopped" : p?.status === "credited" ? "Credited" : undefined,
    },
  ];

  let runningAssigned = false;
  const waiting = p?.status === "held" || p?.status === "awaiting_supplier";
  return definitions.map((step) => {
    let value: StepState = "pending";
    if (step.done) value = step.fail ? "fail" : step.warn ? "warn" : "done";
    else if (p && !final && !runningAssigned) {
      runningAssigned = true;
      value = step.warn && waiting ? "warn" : "running";
    }
    const defaultBadge = value === "running" ? "Processing" : value === "pending" ? "Pending" : value === "warn" ? "Review" : value === "fail" ? "Blocked" : "Complete";
    return { key: step.key, label: step.label, detail: step.detail, state: value, time: eventTime(state, step.key), badge: step.badge ?? defaultBadge };
  });
}

const STEP_COLOR: Record<StepState, string> = {
  pending: "rgba(0,0,0,.28)",
  running: "var(--accent)",
  done: "var(--low)",
  warn: "var(--medium)",
  fail: "var(--danger)",
};

function StepIcon({ state, index }: { state: StepState; index: number }) {
  if (state === "running") return <Spinner size={14} />;
  if (state === "done") return <Check size={14} />;
  if (state === "warn") return <span className="text-[10px] font-bold">!</span>;
  if (state === "fail") return <svg width="9" height="9" viewBox="0 0 10 10" aria-hidden><path d="M2 2l6 6M8 2 2 8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" /></svg>;
  return <span className="font-mono text-[8.5px]">{String(index + 1).padStart(2, "0")}</span>;
}

function decisionSummary(state: ViewState) {
  const status = state.payment?.status;
  if (!status) return { title: "Ready for a scenario", detail: "No payment decision has been requested.", color: "var(--ink-3)" };
  if (status === "deciding") return { title: "Decision in progress", detail: "The engine is evaluating legal routes and fraud controls.", color: "var(--accent)" };
  if (status === "in_transit") return { title: "Payment released", detail: "The approved payment is following its signed route.", color: "var(--accent)" };
  if (status === "held" || status === "awaiting_supplier") return { title: "Conditional hold active", detail: "Funds remain protected while the known-contact check is completed.", color: "var(--medium)" };
  if (status === "stopped") return { title: "Payment stopped", detail: "The intent was revoked and the funds were returned to the payer.", color: "var(--danger)" };
  return { title: "Payment cleared", detail: "The supplier was credited through the approved route.", color: "var(--low)" };
}

export function DecisionSteps({ state }: { state: ViewState }) {
  const steps = buildSteps(state);
  const completed = steps.filter((step) => step.state === "done" || step.state === "warn" || step.state === "fail").length;
  const summary = decisionSummary(state);
  return (
    <GlowingShadow layout initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.7, ease, delay: 0.2 }} className="shrink-0" panelClassName="overflow-hidden" aria-label="Engine decisions">
      <div className="flex items-center justify-between px-4 pb-2 pt-4">
        <Tag index="02">Engine decisions</Tag>
        <span className="font-mono text-[10px] text-ink-3">{completed}/{steps.length} complete</span>
      </div>

      <ol className="px-4 py-1">
        {steps.map((step, index) => (
          <motion.li key={step.key} layout="position" className="relative grid grid-cols-[54px_22px_minmax(0,1fr)_auto] items-start gap-2 py-2">
            {index < steps.length - 1 ? <span className="absolute bottom-[-8px] left-[64px] top-[27px] w-px bg-[var(--line-strong)]" aria-hidden /> : null}
            <time className="pt-0.5 font-mono text-[9.5px] text-ink-3">{step.time}</time>
            <span className="relative z-[1] grid size-[18px] place-items-center rounded-full border bg-white" style={{ color: STEP_COLOR[step.state], borderColor: `color-mix(in srgb, ${STEP_COLOR[step.state]} 42%, white)` }}>
              <AnimatePresence mode="wait" initial={false}><motion.span key={step.state} initial={{ scale: 0.6, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.6, opacity: 0 }} transition={{ duration: 0.18 }} className="grid place-items-center"><StepIcon state={step.state} index={index} /></motion.span></AnimatePresence>
            </span>
            <div className="min-w-0">
              <div className={cx("text-[12.5px] font-medium", step.state === "pending" && "text-ink-3")} style={step.state === "running" ? { color: "var(--accent)" } : undefined}>{step.label}</div>
              <div className="mt-0.5 truncate text-[10.5px] leading-snug text-ink-3">{step.detail}</div>
            </div>
            <span className="mt-0.5 rounded-full border px-2 py-1 text-[9px] font-medium" style={{ color: STEP_COLOR[step.state], borderColor: `color-mix(in srgb, ${STEP_COLOR[step.state]} 14%, white)`, background: `color-mix(in srgb, ${STEP_COLOR[step.state]} 8%, white)` }}>{step.badge}</span>
          </motion.li>
        ))}
      </ol>

      <div className="mx-4 mb-4 rounded-lg bg-[var(--accent-soft)] px-3 py-3">
        <div className="flex items-center gap-2 text-[11.5px] font-semibold text-accent"><span className="grid size-5 place-items-center rounded-md border border-[color-mix(in_srgb,var(--accent)_16%,white)] bg-white text-[11px]">✣</span>Decision: {summary.title.toLowerCase()}</div>
        <p className="mt-1 text-[10.5px] leading-relaxed text-ink-2">{summary.detail}</p>
      </div>
    </GlowingShadow>
  );
}
