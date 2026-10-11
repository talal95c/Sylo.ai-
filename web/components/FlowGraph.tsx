"use client";

import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { TIER_COLORS } from "@/lib/colors";
import {
  edgeStatus,
  FLOW_EDGES,
  flowLane,
  flowStatuses,
  narrate,
  type EdgeTone,
  type FlowNodeId,
  type FlowStatus,
  type Lane,
  type NarrationTone,
} from "@/lib/flow";
import { buildQuote, pct } from "@/lib/routeQuote";
import type { ViewState } from "@/lib/store";
import { Check, cx, ease, euros, formatMoney, shortHash, Spinner } from "./ui";

const NODE_W = 224;
const CANVAS_W = 1360;
const CANVAS_H = 660;
const TOP = 34;
const UPPER = TOP + 128;
const LOWER = TOP + 404;

const POS: Record<FlowNodeId, { x: number; y: number }> = {
  payment: { x: 0, y: TOP },
  norms: { x: 0, y: TOP + 196 },
  risk: { x: 0, y: TOP + 350 },
  sealDirect: { x: 344, y: UPPER },
  settle: { x: 608, y: UPPER },
  credited: { x: 1136, y: UPPER },
  sealEscrow: { x: 344, y: LOWER },
  hold: { x: 608, y: LOWER },
  supplier: { x: 872, y: LOWER },
  stopped: { x: 1136, y: LOWER },
};

const TONE_COLOR: Record<EdgeTone | NarrationTone, string> = {
  ink: "var(--ink)",
  neutral: "rgba(0,0,0,0.3)",
  accent: "var(--accent)",
  low: "var(--low)",
  medium: "var(--medium)",
  danger: "var(--danger)",
};

type IconName = "doc" | "scale" | "shield" | "seal" | "legs" | "check" | "lock" | "phone" | "undo";

function NodeIcon({ name }: { name: IconName }) {
  const p = { stroke: "currentColor", strokeWidth: 1.4, strokeLinecap: "round" as const, strokeLinejoin: "round" as const, fill: "none" };
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden className="shrink-0">
      {name === "doc" ? (
        <>
          <path d="M4 1.75h5.5L12.5 4.75v9.5H4z" {...p} />
          <path d="M6.25 8h4M6.25 10.75h4M9.25 1.75v3h3" {...p} />
        </>
      ) : null}
      {name === "scale" ? (
        <>
          <path d="M8 2v12M4.5 14h7M3 4.5h10" {...p} />
          <path d="m3 4.5-1.75 4.25a1.9 1.9 0 0 0 3.5 0zM13 4.5l-1.75 4.25a1.9 1.9 0 0 0 3.5 0z" {...p} />
        </>
      ) : null}
      {name === "shield" ? (
        <>
          <path d="M8 1.75 13 3.6v4.1c0 3.05-2.1 5.4-5 6.55-2.9-1.15-5-3.5-5-6.55V3.6z" {...p} />
          <path d="M8 5.25v3.25M8 10.75v.01" {...p} />
        </>
      ) : null}
      {name === "seal" ? (
        <>
          <path d="M8 1.75 13.4 4.9v6.2L8 14.25 2.6 11.1V4.9z" {...p} />
          <path d="m5.75 8 1.5 1.5 3-3" {...p} />
        </>
      ) : null}
      {name === "legs" ? (
        <>
          <circle cx="3" cy="8" r="1.5" {...p} />
          <circle cx="13" cy="8" r="1.5" {...p} />
          <path d="M4.5 8h7" {...p} strokeDasharray="1.5 2" />
        </>
      ) : null}
      {name === "check" ? (
        <>
          <circle cx="8" cy="8" r="6.25" {...p} />
          <path d="m5.5 8.2 1.75 1.75L10.75 6.5" {...p} />
        </>
      ) : null}
      {name === "lock" ? (
        <>
          <rect x="3" y="7" width="10" height="7" rx="2" {...p} />
          <path d="M5.5 7V5a2.5 2.5 0 0 1 5 0v2" {...p} />
        </>
      ) : null}
      {name === "phone" ? (
        <path d="M5.6 2.25 3.4 2.5c-.6.1-1 .6-.95 1.2.5 5.3 4.6 9.4 9.85 9.85.6.05 1.1-.35 1.2-.95l.25-2.2-2.9-1.25-1.35 1.35a8.4 8.4 0 0 1-3.6-3.6L7.2 5.55z" {...p} />
      ) : null}
      {name === "undo" ? (
        <>
          <path d="M5.5 4 2.75 6.75 5.5 9.5" {...p} />
          <path d="M2.75 6.75h6.5a3.75 3.75 0 0 1 0 7.5H7" {...p} />
        </>
      ) : null}
    </svg>
  );
}

function StatusBadge({ status }: { status: FlowStatus }) {
  return (
    <span className="grid h-5 min-w-5 place-items-center">
      <AnimatePresence mode="wait" initial={false}>
        <motion.span
          key={status}
          initial={{ scale: 0.5, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          exit={{ scale: 0.5, opacity: 0 }}
          transition={{ duration: 0.2 }}
          className="grid place-items-center"
        >
          {status === "running" ? <Spinner size={14} /> : null}
          {status === "waiting" ? (
            <span className="flex items-center gap-1 text-[10.5px] font-medium text-[var(--medium)]">
              <span className="pulse-dot inline-block size-1.5 rounded-full bg-[var(--medium)] text-[var(--medium)]" />
              waiting
            </span>
          ) : null}
          {status === "done" ? <Check size={15} /> : null}
          {status === "warn" ? (
            <span className="grid size-4 place-items-center rounded-full text-[10px] font-semibold text-white" style={{ background: TIER_COLORS.MEDIUM }}>
              !
            </span>
          ) : null}
          {status === "fail" ? (
            <span className="grid size-4 place-items-center rounded-full bg-[var(--danger)] text-white">
              <svg width="8" height="8" viewBox="0 0 10 10"><path d="M2 2l6 6M8 2 2 8" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" /></svg>
            </span>
          ) : null}
          {status === "idle" || status === "skipped" ? <span className="text-[13px] leading-none tracking-[0.1em] text-ink-3">···</span> : null}
        </motion.span>
      </AnimatePresence>
    </span>
  );
}

function Handle({ id, side, tone }: { id: string; side: "left" | "right" | "top" | "bottom" | "row"; tone?: string }) {
  return (
    <span
      data-handle={id}
      aria-hidden
      className={cx(
        "absolute z-10 size-[10px] rounded-full border-2 bg-white transition-colors duration-500",
        side === "left" && "-left-[6px] top-[19px]",
        side === "right" && "-right-[6px] top-[19px]",
        side === "top" && "-top-[6px] left-[calc(50%-5px)]",
        side === "bottom" && "-bottom-[6px] left-[calc(50%-5px)]",
        side === "row" && "-right-[24px] top-[calc(50%-5px)]",
      )}
      style={{ borderColor: tone ?? "rgba(0,0,0,0.28)" }}
    />
  );
}

function Row({ label, value, tone, handle }: { label: ReactNode; value: ReactNode; tone?: string; handle?: ReactNode }) {
  const empty = value === null || value === undefined || value === "";
  return (
    <div className="relative flex items-center justify-between gap-3 text-[12px] leading-5">
      <span className="shrink-0 text-ink-3">{label}</span>
      <AnimatePresence mode="wait" initial={false}>
        <motion.span
          key={empty ? "empty" : String(value)}
          initial={{ opacity: 0, filter: "blur(3px)" }}
          animate={{ opacity: 1, filter: "blur(0px)" }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.3, ease }}
          className={cx("min-w-0 truncate text-right tabular-nums", empty ? "text-ink-3" : "text-ink")}
          style={!empty && tone ? { color: tone } : undefined}
        >
          {empty ? "—" : value}
        </motion.span>
      </AnimatePresence>
      {handle}
    </div>
  );
}

function Group({ children }: { children: ReactNode }) {
  return <div className="relative rounded-[12px] bg-[var(--surface-2)] px-3 py-1.5">{children}</div>;
}

function FlowNode({
  id,
  status,
  icon,
  title,
  subtitle,
  handles,
  children,
}: {
  id: FlowNodeId;
  status: FlowStatus;
  icon: IconName;
  title: string;
  subtitle: string;
  handles: ReactNode;
  children: ReactNode;
}) {
  const ring =
    status === "running"
      ? "0 0 0 1.5px var(--accent), 0 0 0 6px rgba(1,43,255,0.08)"
      : status === "waiting"
        ? "0 0 0 1.5px var(--medium), 0 0 0 6px rgba(217,119,6,0.1)"
        : "0 0 0 0px transparent, 0 0 0 0px transparent";
  return (
    <motion.div
      data-node={id}
      className="card absolute rounded-[18px] p-1.5"
      style={{ left: POS[id].x, top: POS[id].y, width: NODE_W }}
      initial={false}
      animate={{ opacity: status === "skipped" ? 0.36 : 1, boxShadow: `${ring}, var(--shadow-card)` }}
      transition={{ duration: 0.45, ease }}
    >
      {handles}
      <div className="flex h-8 items-center gap-2 px-2">
        <span className={cx("transition-colors", status === "idle" || status === "skipped" ? "text-ink-3" : "text-ink")}>
          <NodeIcon name={icon} />
        </span>
        <span className="min-w-0 flex-1 truncate text-[13.5px] font-medium tracking-[-0.02em]">{title}</span>
        <StatusBadge status={status} />
      </div>
      <div className="truncate px-2 pb-1.5 text-[11.5px] text-ink-3">{subtitle}</div>
      <div className="space-y-1">{children}</div>
    </motion.div>
  );
}

function measure(root: HTMLElement): Record<string, { x: number; y: number }> {
  const out: Record<string, { x: number; y: number }> = {};
  root.querySelectorAll<HTMLElement>("[data-handle]").forEach((el) => {
    let x = el.offsetWidth / 2;
    let y = el.offsetHeight / 2;
    let current: HTMLElement | null = el;
    while (current && current !== root) {
      x += current.offsetLeft;
      y += current.offsetTop;
      const parent = current.offsetParent as HTMLElement | null;
      if (parent && parent !== root) {
        x += parent.clientLeft;
        y += parent.clientTop;
      }
      current = parent;
    }
    out[el.dataset.handle as string] = { x: Math.round(x), y: Math.round(y) };
  });
  return out;
}

function edgePath(a: { x: number; y: number }, b: { x: number; y: number }, vertical: boolean) {
  if (vertical) {
    const dy = Math.max(20, Math.abs(b.y - a.y) * 0.5);
    return `M ${a.x} ${a.y} C ${a.x} ${a.y + dy}, ${b.x} ${b.y - dy}, ${b.x} ${b.y}`;
  }
  const dx = Math.max(36, Math.abs(b.x - a.x) * 0.5);
  return `M ${a.x} ${a.y} C ${a.x + dx} ${a.y}, ${b.x - dx} ${b.y}, ${b.x} ${b.y}`;
}

function laneValue<T>(lane: Lane | null, own: Lane, value: T): T | null {
  return lane === own ? value : null;
}

export function FlowGraph({
  state,
  speed = 1,
  unsupportedScene = false,
  onSwitchToGlobe,
}: {
  state: ViewState;
  speed?: number;
  unsupportedScene?: boolean;
  onSwitchToGlobe?: () => void;
}) {
  const statuses = flowStatuses(state);
  const lane = flowLane(state);
  const p = state.payment;
  const quote = buildQuote(state);
  const reduced = useReducedMotion();
  const frameRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(1);
  const [points, setPoints] = useState<Record<string, { x: number; y: number }>>({});

  const remeasure = useCallback(() => {
    if (!canvasRef.current) return;
    const next = measure(canvasRef.current);
    setPoints((prev) => (JSON.stringify(prev) === JSON.stringify(next) ? prev : next));
  }, []);

  useLayoutEffect(remeasure);

  useEffect(() => {
    const frame = frameRef.current;
    if (!frame) return;
    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      setScale(Math.min(1.15, width / CANVAS_W, height / CANVAS_H));
    });
    observer.observe(frame);
    document.fonts?.ready.then(remeasure).catch(() => undefined);
    return () => observer.disconnect();
  }, [remeasure]);

  const handleTone = (nodeId: FlowNodeId, handle: string) => {
    const edges = FLOW_EDGES.filter((edge) => (edge.from === nodeId && edge.fromHandle === handle) || (edge.to === nodeId && edge.toHandle === handle));
    const done = edges.find((edge) => edgeStatus(edge, statuses) === "done");
    if (done) return TONE_COLOR[done.tone];
    if (edges.some((edge) => edgeStatus(edge, statuses) === "active")) return "var(--accent)";
    return undefined;
  };

  const settled = state.hops.filter((hop) => hop.state === "settled").length;
  const swift = state.routeScores.find((score) => score.routeId === "R1")?.s ?? null;
  const allowed = state.routes.filter((route) => route.status === "PASS");
  const excluded = state.routes.filter((route) => route.status === "EXCLUDED");
  const requested = state.verification.requested;
  const answer = state.verification.recorded?.result;
  const narration = narrate(state);

  const seal = (own: Lane) => (
    <Group>
      <Row label="Route" value={laneValue(lane, own, p?.routeName ? `${p.routeId} · ${p.routeName}` : null)} />
      <Row
        label="Cost"
        value={laneValue(lane, own, p?.routeCostEur !== undefined ? `${euros(p.routeCostEur)}${swift ? ` vs ${euros(swift)} SWIFT` : ""}` : null)}
      />
      <Row label="Approval" value={laneValue(lane, own, state.approval ? (state.approval.conditional ? "Conditional · 2 people" : "Dual control") : null)} />
      <Row label="Intent" value={laneValue(lane, own, p?.intentHash ? shortHash(p.intentHash, 6, 4) : null)} />
    </Group>
  );

  return (
    <div className="absolute inset-0">
      <div className="pointer-events-none absolute inset-x-4 top-[76px] z-20 flex flex-col items-center gap-1.5">
        <div className="glass flex min-h-9 max-w-[min(820px,100%)] items-center gap-2.5 rounded-full px-4 py-1.5" aria-live="polite">
          <motion.span
            className="size-1.5 shrink-0 rounded-full"
            animate={{ background: TONE_COLOR[narration.tone] }}
            transition={{ duration: 0.4 }}
          />
          <AnimatePresence mode="wait" initial={false}>
            <motion.span
              key={narration.text}
              initial={{ opacity: 0, y: reduced ? 0 : 4, filter: "blur(4px)" }}
              animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
              exit={{ opacity: 0, y: reduced ? 0 : -4, filter: "blur(4px)" }}
              transition={{ duration: 0.28, ease }}
              className="text-[12.5px] leading-snug text-ink-2"
            >
              {narration.text}
            </motion.span>
          </AnimatePresence>
        </div>
        {unsupportedScene && onSwitchToGlobe ? (
          <div className="glass pointer-events-auto flex items-center gap-2 rounded-full px-3 py-1.5 text-[11px] text-ink-2">
            <span>This scene is shown on the globe</span>
            <button type="button" onClick={onSwitchToGlobe} className="rounded-full px-2 py-1 font-medium text-accent hover:bg-[var(--accent-soft)]">
              Switch to Globe
            </button>
          </div>
        ) : null}
      </div>

      <div ref={frameRef} className="absolute inset-x-6 bottom-[92px] top-[128px] flex items-center justify-center">
        <div
          ref={canvasRef}
          className="relative shrink-0"
          style={{ width: CANVAS_W, height: CANVAS_H, transform: `scale(${scale})`, transformOrigin: "center" }}
        >
          <svg className="pointer-events-none absolute inset-0 overflow-visible" width={CANVAS_W} height={CANVAS_H} aria-hidden>
            {FLOW_EDGES.map((edge) => {
              const a = points[`${edge.from}:${edge.fromHandle}`];
              const b = points[`${edge.to}:${edge.toHandle}`];
              if (!a || !b) return null;
              const d = edgePath(a, b, edge.fromHandle === "bottom");
              const status = edgeStatus(edge, statuses);
              return (
                <g key={edge.id}>
                  <path
                    d={d}
                    fill="none"
                    stroke={status === "skipped" ? "rgba(0,0,0,0.08)" : "rgba(0,0,0,0.16)"}
                    strokeWidth={1.5}
                    strokeDasharray="3 5"
                    strokeLinecap="round"
                  />
                  {status === "done" ? (
                    <motion.path
                      d={d}
                      fill="none"
                      stroke={TONE_COLOR[edge.tone]}
                      strokeWidth={2.25}
                      strokeLinecap="round"
                      initial={{ pathLength: reduced ? 1 : 0 }}
                      animate={{ pathLength: 1 }}
                      transition={{ duration: 0.6, ease }}
                    />
                  ) : null}
                  {status === "active" ? (
                    <>
                      <path d={d} fill="none" stroke="var(--accent)" strokeWidth={2} strokeLinecap="round" strokeDasharray="6 8" className="flow-dash" />
                      {reduced ? null : (
                        <circle key={`${edge.id}-${status}`} r={3.5} fill="var(--accent)">
                          <animateMotion
                            ref={(node: SVGAnimateMotionElement | null) => {
                              node?.beginElement();
                            }}
                            begin="indefinite"
                            dur={`${1.4 / speed}s`}
                            repeatCount="indefinite"
                            path={d}
                          />
                        </circle>
                      )}
                    </>
                  ) : null}
                </g>
              );
            })}
          </svg>

          <span className="absolute left-0 top-0 inline-flex h-6 items-center rounded-full bg-white px-2.5 text-[12px] font-medium shadow-[var(--shadow-card)]">
            Start
          </span>
          <LaneLabel x={POS.sealDirect.x} y={UPPER - 30} color="var(--low)" active={lane === "direct"} dimmed={lane === "escrow"}>
            Low risk · the payment goes straight through
          </LaneLabel>
          <LaneLabel x={POS.sealEscrow.x} y={LOWER - 30} color="var(--medium)" active={lane === "escrow"} dimmed={lane === "direct"}>
            Suspicious · the money waits in escrow until the real supplier answers
          </LaneLabel>

          <FlowNode
            id="payment"
            status={statuses.payment}
            icon="doc"
            title="Payment request"
            subtitle="What the payer asks to send"
            handles={<Handle id="payment:bottom" side="bottom" tone={handleTone("payment", "bottom")} />}
          >
            <Group>
              <Row label="Amount" value={p ? formatMoney(p.amount.value, p.amount.currency) : null} />
              <Row label="Payee" value={p?.payeeName} />
              <Row label="Account holder" value={p?.accountHolder} tone={p && !p.knownAccount ? "var(--danger)" : undefined} />
              <Row label="Bank details" value={p ? (p.knownAccount ? "Known account" : "New account") : null} tone={p && !p.knownAccount ? "var(--danger)" : undefined} />
            </Group>
          </FlowNode>

          <FlowNode
            id="norms"
            status={statuses.norms}
            icon="scale"
            title="Legal check"
            subtitle="France → Ghana rule pack"
            handles={
              <>
                <Handle id="norms:top" side="top" tone={handleTone("norms", "top")} />
                <Handle id="norms:bottom" side="bottom" tone={handleTone("norms", "bottom")} />
              </>
            }
          >
            <Group>
              <Row label="Routes allowed" value={state.routes.length ? `${allowed.length} of ${state.routes.length}` : null} />
              <Row label="Excluded" value={state.routes.length ? (excluded.length ? excluded.map((route) => route.routeId).join(", ") : "None") : null} />
            </Group>
          </FlowNode>

          <FlowNode
            id="risk"
            status={statuses.risk}
            icon="shield"
            title="Fraud risk"
            subtitle="Rules score every signal"
            handles={<Handle id="risk:top" side="top" tone={handleTone("risk", "top")} />}
          >
            <Group>
              <Row label="Score" value={state.risk ? `${state.risk.score} · ${state.risk.tier}` : null} tone={state.risk ? TIER_COLORS[state.risk.tier] : undefined} />
              <Row label="Rules fired" value={state.risk ? String(state.risk.rulesFired.length) : null} />
            </Group>
            <Group>
              <BranchRow label="If low" value="pay directly" chosen={lane === "direct"} other={lane === "escrow"} color="var(--low)">
                <Handle id="risk:low" side="row" tone={handleTone("risk", "low")} />
              </BranchRow>
              <BranchRow label="If medium+" value="hold in escrow" chosen={lane === "escrow"} other={lane === "direct"} color="var(--medium)">
                <Handle id="risk:high" side="row" tone={handleTone("risk", "high")} />
              </BranchRow>
            </Group>
          </FlowNode>

          <FlowNode
            id="sealDirect"
            status={statuses.sealDirect}
            icon="seal"
            title="Route & seal"
            subtitle="Cheapest legal route, signed first"
            handles={
              <>
                <Handle id="sealDirect:in" side="left" tone={handleTone("sealDirect", "in")} />
                <Handle id="sealDirect:out" side="right" tone={handleTone("sealDirect", "out")} />
              </>
            }
          >
            {seal("direct")}
          </FlowNode>

          <FlowNode
            id="settle"
            status={statuses.settle}
            icon="legs"
            title="Settle legs"
            subtitle="Money follows the signed route"
            handles={
              <>
                <Handle id="settle:in" side="left" tone={handleTone("settle", "in")} />
                <Handle id="settle:out" side="right" tone={handleTone("settle", "out")} />
              </>
            }
          >
            <Group>
              <div className="flex gap-1 py-1.5">
                {(lane === "direct" && state.hops.length ? state.hops : Array.from({ length: 5 }, (_, index) => ({ index, state: "pending" as const }))).map((hop) => (
                  <motion.span
                    key={hop.index}
                    className="h-1.5 flex-1 rounded-full"
                    initial={false}
                    animate={{
                      background:
                        hop.state === "settled" ? "var(--low)" : hop.state === "active" ? "var(--accent)" : "rgba(0,0,0,0.1)",
                    }}
                    transition={{ duration: 0.35 }}
                  />
                ))}
              </div>
              <Row label="Legs" value={lane === "direct" && state.hops.length ? `${settled} of ${state.hops.length} settled` : null} />
            </Group>
          </FlowNode>

          <FlowNode
            id="credited"
            status={statuses.credited}
            icon="check"
            title="Supplier credited"
            subtitle="Funds reach the beneficiary"
            handles={<Handle id="credited:in" side="left" tone={handleTone("credited", "in")} />}
          >
            <Group>
              <Row label="Paid to" value={state.credited && p ? (state.credited.at === "supplier_ssx" ? p.payeeName : p.accountHolder) : null} />
              <Row label={quote?.basis === "cash" ? "Fees + FX" : "All-in cost"} value={state.credited && quote ? euros(quote.cost) : null} tone="var(--low)" />
              <Row label="Via SWIFT" value={state.credited && quote?.swift ? euros(quote.swift.cost) : null} />
              <Row label="Saved" value={state.credited && quote?.savedEur !== undefined ? `${euros(quote.savedEur)}${quote.savedPct !== undefined ? ` · ${pct(quote.savedPct)}` : ""}` : null} tone="var(--low)" />
              <Row label="Arrives" value={state.credited?.elapsedLabel} />
            </Group>
          </FlowNode>

          <FlowNode
            id="sealEscrow"
            status={statuses.sealEscrow}
            icon="seal"
            title="Route & seal"
            subtitle="Same route, paid into escrow"
            handles={
              <>
                <Handle id="sealEscrow:in" side="left" tone={handleTone("sealEscrow", "in")} />
                <Handle id="sealEscrow:out" side="right" tone={handleTone("sealEscrow", "out")} />
              </>
            }
          >
            {seal("escrow")}
          </FlowNode>

          <FlowNode
            id="hold"
            status={statuses.hold}
            icon="lock"
            title="Escrow hold"
            subtitle="Locked in a smart contract"
            handles={
              <>
                <Handle id="hold:in" side="left" tone={handleTone("hold", "in")} />
                <Handle id="hold:out" side="right" tone={handleTone("hold", "out")} />
              </>
            }
          >
            <Group>
              <Row label="Locked" value={state.held && p ? formatMoney(p.amount.value, p.amount.currency) : null} tone="var(--medium)" />
              <Row label="Red flags" value={state.held ? String(state.held.reasons.length) : null} />
              <Row label="Released" value={state.held ? (state.released ? "Yes" : state.refunded ? "Never" : "Only if confirmed") : null} />
            </Group>
          </FlowNode>

          <FlowNode
            id="supplier"
            status={statuses.supplier}
            icon="phone"
            title="Ask the supplier"
            subtitle="Contact on file, not the email's"
            handles={<Handle id="supplier:in" side="left" tone={handleTone("supplier", "in")} />}
          >
            <Group>
              <Row label="Contact" value={requested?.contactName} />
              <Row label="Channel" value={requested ? `${requested.channel} · ${requested.contactMasked}` : null} />
              <Row label="SIM swap" value={requested ? (requested.simSwapRecent ? "Recent" : "None recent") : null} />
            </Group>
            <Group>
              <BranchRow label="Confirms" value="release escrow" chosen={answer === "CONFIRMED"} other={answer === "DENIED"} color="var(--low)">
                <Handle id="supplier:yes" side="row" tone={handleTone("supplier", "yes")} />
              </BranchRow>
              <BranchRow label="Denies" value="revoke & refund" chosen={answer === "DENIED"} other={answer === "CONFIRMED"} color="var(--danger)">
                <Handle id="supplier:no" side="row" tone={handleTone("supplier", "no")} />
              </BranchRow>
            </Group>
          </FlowNode>

          <FlowNode
            id="stopped"
            status={statuses.stopped}
            icon="undo"
            title="Revoked & refunded"
            subtitle="Money goes back to the payer"
            handles={<Handle id="stopped:in" side="left" tone={handleTone("stopped", "in")} />}
          >
            <Group>
              <Row label="Intent" value={state.revoked ? "Revoked on-chain" : null} tone="var(--danger)" />
              <Row label="Refund" value={state.refunded && p ? formatMoney(p.amount.value, p.amount.currency) : null} />
              <Row
                label="release() attack"
                value={state.attack.reverted ? "Rejected" : state.attack.attempted ? "Trying…" : state.stopped ? "Try it below" : null}
                tone={state.attack.reverted ? "var(--low)" : state.attack.attempted ? "var(--danger)" : undefined}
              />
            </Group>
          </FlowNode>
        </div>
      </div>
    </div>
  );
}

function BranchRow({
  label,
  value,
  chosen,
  other,
  color,
  children,
}: {
  label: string;
  value: string;
  chosen: boolean;
  other: boolean;
  color: string;
  children: ReactNode;
}) {
  return (
    <div className={cx("relative flex items-center justify-between gap-3 text-[12px] leading-5 transition-opacity duration-500", other && "opacity-40")}>
      <span className="flex items-center gap-1.5 text-ink-3">
        <span className="size-1.5 rounded-full" style={{ background: color }} />
        {label}
      </span>
      <span className={cx("transition-colors duration-500", chosen ? "font-medium" : "text-ink-2")} style={chosen ? { color } : undefined}>
        {value}
      </span>
      {children}
    </div>
  );
}

function LaneLabel({
  x,
  y,
  color,
  active,
  dimmed,
  children,
}: {
  x: number;
  y: number;
  color: string;
  active: boolean;
  dimmed: boolean;
  children: ReactNode;
}) {
  return (
    <motion.span
      className="absolute inline-flex h-6 items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 text-[11.5px] font-medium"
      style={{ left: x, top: y }}
      initial={false}
      animate={{
        opacity: dimmed ? 0.4 : 1,
        background: active ? "#ffffff" : "rgba(255,255,255,0)",
        boxShadow: active ? "var(--shadow-card)" : "0 0 0 rgba(0,0,0,0)",
        color: active ? "var(--ink)" : "rgba(0,0,0,0.5)",
      }}
      transition={{ duration: 0.4 }}
    >
      <span className="size-1.5 rounded-full" style={{ background: color }} />
      {children}
    </motion.span>
  );
}
