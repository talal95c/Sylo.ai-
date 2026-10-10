"use client";

import { AnimatePresence, motion } from "framer-motion";
import type { ViewState } from "@/lib/store";
import { TIER_COLORS } from "@/lib/colors";
import { Check, cx, ease, euros, shortHash, Spinner, Tag } from "./ui";

type StepState = "pending" | "running" | "done" | "warn" | "fail";

interface Step {
  key: string;
  label: string;
  detail?: string;
  state: StepState;
  extra?: React.ReactNode;
}

function buildSteps(state: ViewState): Step[] {
  const p = state.payment;
  const final = p?.status === "credited" || p?.status === "stopped";
  const excluded = state.routes.filter((route) => route.status === "EXCLUDED");
  const settledCount = state.hops.filter((hop) => hop.state === "settled").length;

  const steps: (Omit<Step, "state"> & { done: boolean; warn?: boolean; fail?: boolean })[] = [
    {
      key: "norms",
      label: "Legal routes checked",
      done: state.routes.length > 0,
      detail: state.routes.length
        ? `${state.routes.length - excluded.length} of ${state.routes.length} routes allowed${excluded.length ? ` · ${excluded.map((r) => r.routeId).join(", ")} excluded` : ""}`
        : "France → Ghana norms pack",
    },
    {
      key: "risk",
      label: "Fraud risk scored",
      done: Boolean(state.risk),
      warn: state.risk ? state.risk.tier !== "LOW" : false,
      detail: state.risk
        ? `${state.risk.score} · ${state.risk.tier} · ${state.risk.rulesFired.length} rules fired`
        : "Deterministic rules",
    },
    {
      key: "route",
      label: "Cheapest compliant route",
      done: Boolean(state.selectedRouteId),
      detail: p?.routeName ? `${p.routeId} · ${p.routeName}` : "Fraud risk never enters the route score",
      extra: state.routeScores.length ? <RouteTable state={state} /> : null,
    },
    {
      key: "approval",
      label: state.approval?.conditional ? "Conditional dual approval" : "Dual approval",
      done: Boolean(state.approval),
      detail: state.approval ? state.approval.by.map((who) => who.name).join(" + ") : "CFO + second approver",
    },
    {
      key: "intent",
      label: "Intent sealed before money moves",
      done: Boolean(p?.intentHash),
      detail: p?.intentHash ? `${shortHash(p.intentHash, 8, 4)} · EIP-712` : "EIP-712 signature · registry",
    },
    {
      key: "settle",
      label: state.held ? "Held in on-chain escrow" : "Settlement",
      done: p?.status === "credited" || state.refunded || (state.hops.length > 0 && settledCount === state.hops.length),
      warn: Boolean(state.held) && !state.released,
      fail: state.refunded,
      detail: state.refunded
        ? "Revoked on-chain · refunded to payer"
        : state.released
          ? "Supplier confirmed · escrow released"
          : state.verification.requested
            ? `Asking ${state.verification.requested.contactName} on known number`
            : state.hops.length
              ? `${settledCount} of ${state.hops.length} legs settled`
              : "Legs follow the signed intent",
    },
    {
      key: "outcome",
      label: p?.status === "stopped" ? "Payment stopped" : p?.status === "credited" ? "Supplier credited" : "Outcome",
      done: final,
      fail: p?.status === "stopped",
      detail: state.attack.reverted
        ? "Attack on release() rejected by the contract"
        : p?.status === "stopped"
          ? "EUR returned · case opened for the analyst"
          : state.credited
            ? `${euros(state.credited.routeCostEur)} all-in vs ${euros(state.credited.swiftRouteCostEur)} via SWIFT`
            : "Credited or stopped",
    },
  ];

  let runningAssigned = false;
  const waiting = p?.status === "held" || p?.status === "awaiting_supplier";
  return steps.map((step) => {
    let value: StepState = "pending";
    if (step.done) value = step.fail ? "fail" : step.warn ? "warn" : "done";
    else if (p && !final && !runningAssigned) {
      runningAssigned = true;
      value = step.warn && waiting ? "warn" : "running";
    }
    return { key: step.key, label: step.label, detail: step.detail, extra: step.extra, state: value };
  });
}

function RouteTable({ state }: { state: ViewState }) {
  return (
    <div className="mt-2 space-y-1">
      {[...state.routeScores]
        .sort((a, b) => (a.s ?? 1e9) - (b.s ?? 1e9))
        .map((score) => {
          const route = state.routes.find((candidate) => candidate.routeId === score.routeId);
          const chosen = score.routeId === state.selectedRouteId;
          return (
            <div
              key={score.routeId}
              className={cx(
                "flex items-center justify-between rounded-[10px] px-2.5 py-1.5 text-[11.5px]",
                chosen ? "bg-[var(--accent-soft)] text-accent" : "text-ink-2",
              )}
            >
              <span className="flex items-center gap-2">
                <span className={cx("font-mono text-[10.5px]", chosen ? "text-accent" : "text-ink-3")}>{score.routeId}</span>
                <span className={score.s === null ? "text-ink-3 line-through decoration-[rgba(0,0,0,.25)]" : ""}>
                  {route?.name ?? score.routeId}
                </span>
              </span>
              <span className="tabular-nums">{score.s === null ? "excluded" : euros(score.s)}</span>
            </div>
          );
        })}
    </div>
  );
}

function StepIcon({ state, index }: { state: StepState; index: number }) {
  if (state === "running") return <Spinner size={18} />;
  if (state === "done") return <Check size={18} />;
  if (state === "warn")
    return (
      <span className="grid size-[18px] place-items-center rounded-full text-[11px] font-semibold text-white" style={{ background: TIER_COLORS.MEDIUM }}>
        !
      </span>
    );
  if (state === "fail")
    return (
      <span className="grid size-[18px] place-items-center rounded-full bg-[var(--danger)] text-white">
        <svg width="10" height="10" viewBox="0 0 10 10"><path d="M2 2l6 6M8 2 2 8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" /></svg>
      </span>
    );
  return <span className="grid size-[18px] place-items-center font-mono text-[10px] text-ink-3">{String(index + 1).padStart(2, "0")}</span>;
}

export function DecisionSteps({ state }: { state: ViewState }) {
  const steps = buildSteps(state);
  return (
    <motion.section
      layout
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.7, ease, delay: 0.2 }}
      className="card rounded-[24px] p-5"
      aria-label="Engine decisions"
    >
      <div className="flex items-center justify-between">
        <Tag index="02">Engine decisions</Tag>
        <span className="text-[11px] text-ink-3">drawn from events</span>
      </div>
      <ol className="mt-4 space-y-0.5">
        {steps.map((step, index) => (
          <motion.li
            key={step.key}
            layout="position"
            className={cx(
              "rounded-[14px] px-2.5 py-2 transition-colors duration-300",
              step.state === "running" && "bg-[var(--accent-soft)]",
            )}
          >
            <div className="flex items-start gap-3">
              <span className="mt-[1px] grid size-[18px] place-items-center">
                <AnimatePresence mode="wait" initial={false}>
                  <motion.span
                    key={step.state}
                    initial={{ scale: 0.5, opacity: 0 }}
                    animate={{ scale: 1, opacity: 1 }}
                    exit={{ scale: 0.5, opacity: 0 }}
                    transition={{ duration: 0.2 }}
                    className="grid place-items-center"
                  >
                    <StepIcon state={step.state} index={index} />
                  </motion.span>
                </AnimatePresence>
              </span>
              <div className="min-w-0 flex-1">
                <div
                  className={cx(
                    "text-[13px] font-medium tracking-[-0.02em]",
                    step.state === "pending" ? "text-ink-3" : "text-ink",
                    step.state === "running" && "text-accent",
                  )}
                >
                  {step.label}
                </div>
                <div className="truncate text-[11.5px] text-ink-3">{step.detail}</div>
                {step.extra && step.state !== "pending" ? step.extra : null}
              </div>
            </div>
          </motion.li>
        ))}
      </ol>
    </motion.section>
  );
}
