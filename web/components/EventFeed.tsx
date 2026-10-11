"use client";

import { AnimatePresence, motion } from "framer-motion";
import { outcomeBadge } from "@/lib/feed";
import type { FeedItem } from "@/lib/store";
import { GlowingShadow } from "./glowing-shadow";
import { cx, ease, PanelHeaderButton, shortHash } from "./ui";

type EventTone = "info" | "success" | "warning" | "danger" | "neutral";
type EventIconName =
  | "alert"
  | "bank"
  | "check"
  | "database"
  | "document"
  | "lock"
  | "route"
  | "scale"
  | "send"
  | "shield"
  | "system"
  | "undo"
  | "unlock"
  | "users";

const TONE: Record<EventTone, { color: string }> = {
  info: { color: "var(--accent)" },
  success: { color: "var(--low)" },
  warning: { color: "var(--medium)" },
  danger: { color: "var(--danger)" },
  neutral: { color: "rgba(19, 31, 61, 0.42)" },
};

const EVENT_TITLES: Record<string, string> = {
  "session.reset": "Session reset",
  "system.mode": "System mode updated",
  "scenario.started": "Scenario started",
  "payment.created": "Payment received",
  "norms.checked": "Legal route check",
  "risk.scored": "Fraud risk analysis",
  "route.selected": "Route optimization",
  "approval.required": "Approval required",
  "approval.granted": "Dual approval recorded",
  "intent.committed": "Payment intent committed",
  "leg.sent": "Payment leg sent",
  "leg.settled": "Payment leg settled",
  "escrow.deposited": "Funds protected in escrow",
  "payment.held": "Payment held",
  "case.ready": "Analyst case file ready",
  "case.action": "Analyst action recorded",
  "verification.requested": "Supplier verification requested",
  "verification.recorded": "Supplier response recorded",
  "intent.revoked": "Payment intent revoked",
  "escrow.refunded": "Escrow refunded",
  "escrow.released": "Escrow released",
  "intent.executed": "Payment intent executed",
  "payment.credited": "Payment completed",
  "payment.stopped": "Payment stopped",
  "attack.attempted": "Unauthorized release attempted",
  "tx.reverted": "Unauthorized transaction rejected",
  "leg.rejected": "Payment leg rejected",
  "rail.down": "Payment rail unavailable",
  "rail.up": "Payment rail restored",
  "killswitch.on": "Rail kill switch activated",
  "guardian.incident": "Guardian incident",
  "traffic.sample": "Network payment observed",
  "cluster.detected": "Mule cluster detected",
  "clock.advanced": "Demo clock advanced",
  "timelock.on": "Time-lock activated",
  "timelock.off": "Time-lock elapsed",
  "confidential.transfer": "Confidential transfer",
  "breaker.on": "Circuit breaker activated",
  "breaker.off": "Circuit breaker removed",
  "alert.raised": "Security alert sent",
};

const EVENT_ICONS: Record<string, EventIconName> = {
  "session.reset": "undo",
  "system.mode": "system",
  "scenario.started": "system",
  "payment.created": "document",
  "norms.checked": "scale",
  "risk.scored": "database",
  "route.selected": "route",
  "approval.required": "users",
  "approval.granted": "users",
  "intent.committed": "shield",
  "leg.sent": "send",
  "leg.settled": "check",
  "escrow.deposited": "bank",
  "payment.held": "lock",
  "case.ready": "document",
  "case.action": "users",
  "verification.requested": "users",
  "verification.recorded": "shield",
  "intent.revoked": "alert",
  "escrow.refunded": "undo",
  "escrow.released": "unlock",
  "intent.executed": "shield",
  "payment.credited": "check",
  "payment.stopped": "alert",
  "attack.attempted": "alert",
  "tx.reverted": "shield",
  "leg.rejected": "alert",
  "rail.down": "alert",
  "rail.up": "check",
  "killswitch.on": "lock",
  "guardian.incident": "shield",
  "traffic.sample": "route",
  "cluster.detected": "users",
  "clock.advanced": "system",
  "timelock.on": "lock",
  "timelock.off": "unlock",
  "confidential.transfer": "shield",
  "breaker.on": "shield",
  "breaker.off": "unlock",
  "alert.raised": "send",
};

const SUCCESS_EVENTS = new Set([
  "norms.checked",
  "approval.granted",
  "leg.settled",
  "escrow.released",
  "intent.executed",
  "payment.credited",
  "rail.up",
  "breaker.off",
  "timelock.off",
]);
const DANGER_EVENTS = new Set([
  "intent.revoked",
  "escrow.refunded",
  "payment.stopped",
  "attack.attempted",
  "tx.reverted",
  "leg.rejected",
  "killswitch.on",
  "guardian.incident",
]);
const WARNING_EVENTS = new Set([
  "escrow.deposited",
  "payment.held",
  "verification.requested",
  "rail.down",
  "breaker.on",
]);
const INFO_EVENTS = new Set([
  "payment.created",
  "route.selected",
  "intent.committed",
  "leg.sent",
  "traffic.sample",
]);

function toneFor(item: FeedItem): EventTone {
  const badge = outcomeBadge(item);
  if (badge) return badge.tone;
  if (item.family === "attack" || DANGER_EVENTS.has(item.type)) return "danger";
  if (item.family === "alert" || WARNING_EVENTS.has(item.type)) return "warning";
  if (SUCCESS_EVENTS.has(item.type)) return "success";
  if (INFO_EVENTS.has(item.type) || item.family === "leg" || item.family === "chain") return "info";
  return "neutral";
}

function statusFor(item: FeedItem) {
  const badge = outcomeBadge(item);
  if (badge) return badge.label;
  switch (item.type) {
    case "session.reset":
      return "Reset";
    case "system.mode":
      return "System";
    case "scenario.started":
      return "Started";
    case "approval.required":
      return "Pending";
    case "payment.created":
      return "Received";
    case "norms.checked":
      return "Compliant";
    case "route.selected":
      return "Route selected";
    case "approval.granted":
      return "Approved";
    case "case.action":
      return "Recorded";
    case "intent.committed":
      return "On chain";
    case "leg.sent":
      return "In transit";
    case "leg.settled":
      return "Settled";
    case "escrow.deposited":
      return "Protected";
    case "payment.held":
      return "Held";
    case "verification.requested":
      return "Review";
    case "intent.revoked":
      return "Revoked";
    case "escrow.refunded":
      return "Refunded";
    case "escrow.released":
      return "Released";
    case "intent.executed":
      return "Executed";
    case "payment.credited":
      return "Settled";
    case "payment.stopped":
      return "Stopped";
    case "attack.attempted":
      return "Fraud";
    case "tx.reverted":
      return "Rejected";
    case "leg.rejected":
      return "Blocked";
    case "rail.down":
      return "Unavailable";
    case "rail.up":
      return "Restored";
    case "killswitch.on":
      return "Cut off";
    case "guardian.incident":
      return "Frozen";
    case "traffic.sample":
      return "Simulated";
    case "cluster.detected":
      return "Detected";
    case "clock.advanced":
      return "Advanced";
    case "timelock.on":
      return "Locked";
    case "timelock.off":
      return "Elapsed";
    case "confidential.transfer":
      return "Private";
    case "breaker.on":
      return "Active";
    case "breaker.off":
      return "Removed";
    case "alert.raised":
      return "Sent";
    default:
      return "Event";
  }
}

function descriptionFor(item: FeedItem) {
  switch (item.type) {
    case "payment.created":
      return item.text.replace(/^Payment received:\s*/i, "");
    case "norms.checked":
      return item.text.replace(/^Norms checked:\s*/i, "");
    case "route.selected":
      return item.text.replace(/^Route selected:\s*/i, "");
    case "approval.granted":
      return item.text.replace(/^Approval granted\s*/i, "");
    case "leg.sent":
      return item.text.replace(/^Leg \d+ sent:\s*/i, "");
    case "leg.settled":
      return item.text.replace(/^Leg \d+ settled\s*/i, "Settled ");
    case "payment.credited":
      return item.text.replace(/^Payment credited\s*/i, "Credited ");
    default:
      return item.text;
  }
}

function clock(ts: string) {
  return ts.slice(11, 19);
}

function EventIcon({ name }: { name: EventIconName }) {
  const glyphs = {
    alert: <><path d="M10 2.8 17.3 16H2.7L10 2.8Z" /><path d="M10 7v4.2M10 14v.1" /></>,
    bank: <><path d="m3 7 7-4 7 4" /><path d="M4 17h12M5.5 8.5v6M9.9 8.5v6M14.5 8.5v6" /></>,
    check: <><circle cx="10" cy="10" r="7" /><path d="m6.8 10.2 2.1 2.1 4.4-4.6" /></>,
    database: <><ellipse cx="10" cy="5" rx="6.5" ry="2.5" /><path d="M3.5 5v5c0 1.4 2.9 2.5 6.5 2.5s6.5-1.1 6.5-2.5V5M3.5 10v5c0 1.4 2.9 2.5 6.5 2.5s6.5-1.1 6.5-2.5v-5" /></>,
    document: <><path d="M5 2.5h6l3.5 3.5v11.5H5z" /><path d="M11 2.5V6h3.5M7.5 9h4.5M7.5 12h4.5" /></>,
    lock: <><rect x="4" y="8.5" width="12" height="9" rx="2" /><path d="M6.5 8.5V6a3.5 3.5 0 0 1 7 0v2.5M10 12v2" /></>,
    route: <><circle cx="4" cy="5" r="2" /><circle cx="16" cy="15" r="2" /><path d="M6 5h3a3 3 0 0 1 3 3v4a3 3 0 0 0 3 3" /><path d="m8.5 2.5 3 2.5-3 2.5" /></>,
    scale: <><path d="M10 3v14M4 5h12M6 5 3 11h6L6 5ZM14 5l-3 6h6l-3-6ZM7 17h6" /></>,
    send: <><path d="m2.5 9 15-6-6 15-2.2-6.8L2.5 9Z" /><path d="m9.3 11.2 3.6-3.6" /></>,
    shield: <><path d="M10 2.5 16 5v4.8c0 3.8-2.5 6.4-6 7.7-3.5-1.3-6-3.9-6-7.7V5l6-2.5Z" /><path d="m7.2 10 1.8 1.8 3.8-4" /></>,
    system: <><circle cx="10" cy="10" r="2.5" /><path d="M10 2.5v2M10 15.5v2M2.5 10h2M15.5 10h2M4.7 4.7l1.4 1.4M13.9 13.9l1.4 1.4M15.3 4.7l-1.4 1.4M6.1 13.9l-1.4 1.4" /></>,
    undo: <><path d="M6 6H2.5V2.5" /><path d="M3 6a7 7 0 1 1 .2 8.3" /></>,
    unlock: <><rect x="4" y="8.5" width="12" height="9" rx="2" /><path d="M6.5 8.5V6a3.5 3.5 0 0 1 6.7-1.4M10 12v2" /></>,
    users: <><circle cx="7.5" cy="7" r="3" /><path d="M2.5 17c.4-3 2.1-4.7 5-4.7s4.6 1.7 5 4.7M13 5.2a2.6 2.6 0 0 1 0 5M14 12.5c2.1.5 3.2 1.9 3.5 4.5" /></>,
  };

  return (
    <svg width="18" height="18" viewBox="0 0 20 20" fill="none" aria-hidden="true">
      <g stroke="currentColor" strokeWidth="1.45" strokeLinecap="round" strokeLinejoin="round">
        {glyphs[name]}
      </g>
    </svg>
  );
}

export function EventFeed({ feed, expanded, onExpandedChange, onOpenIncident }: { feed: FeedItem[]; expanded: boolean; onExpandedChange: (expanded: boolean) => void; onOpenIncident?: () => void }) {
  const items = [...feed].reverse();

  return (
    <GlowingShadow
      initial={{ opacity: 0, x: 16 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.7, ease, delay: 0.25 }}
      layout
      className={cx("flex min-h-0 w-full", expanded ? "flex-1" : "shrink-0")}
      panelClassName="flex min-h-0 flex-1 flex-col overflow-hidden"
      aria-label="Event feed"
    >
      <PanelHeaderButton
        index="03"
        title="Event feed"
        meta={`${feed.length} ${feed.length === 1 ? "event" : "events"}`}
        expanded={expanded}
        controls="event-feed-content"
        onToggle={() => onExpandedChange(!expanded)}
      />

      <AnimatePresence initial={false}>
        {expanded ? (
      <motion.div
        id="event-feed-content"
        key="event-feed-content"
        initial={{ height: 0, opacity: 0 }}
        animate={{ height: "auto", opacity: 1 }}
        exit={{ height: 0, opacity: 0 }}
        transition={{ duration: 0.22, ease }}
        className="thin-scrollbar min-h-0 flex-1 scroll-smooth overflow-x-hidden overflow-y-auto px-3.5 pb-4"
        aria-live="polite"
        aria-relevant="additions"
      >
        {items.length === 0 ? (
          <div className="flex h-full min-h-40 flex-col items-center justify-center px-4 text-center">
            <span className="grid size-8 place-items-center rounded-lg border border-[var(--line)] bg-[var(--surface-2)] text-ink-3">
              <EventIcon name="system" />
            </span>
            <div className="mt-3 text-[12px] font-medium text-ink">No events yet</div>
            <p className="mt-1 max-w-52 text-[11px] leading-relaxed text-ink-3">
              Engine decisions and payment movements will appear here.
            </p>
          </div>
        ) : null}

        <ul>
          <AnimatePresence initial={false}>
            {items.map((item, index) => {
              const tone = toneFor(item);
              const meta = TONE[tone];
              const description = descriptionFor(item);
              return (
                <motion.li
                  key={`${item.seq}-${item.type}`}
                  layout="position"
                  initial={{ opacity: 0, y: -5 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.25, ease }}
                  className="relative grid grid-cols-[8px_43px_20px_minmax(0,1fr)] items-start gap-x-[7px] py-[9px]"
                >
                  {index < items.length - 1 ? (
                    <span
                      className="absolute bottom-[-9px] left-[3px] top-[17px] w-px bg-[rgba(22,35,67,0.12)]"
                      aria-hidden="true"
                    />
                  ) : null}
                  <span
                    className="relative z-[1] mt-[6px] block size-[7px] rounded-full border-2 border-white"
                    style={{
                      background: meta.color,
                      boxShadow: `0 0 0 1px color-mix(in srgb, ${meta.color} 22%, white)`,
                    }}
                    aria-hidden="true"
                  />
                  <time
                    dateTime={item.ts}
                    className="pt-[3px] font-mono text-[9px] leading-none tabular-nums text-ink-3"
                  >
                    {clock(item.ts)}
                  </time>
                  <span
                    className="grid size-5 place-items-center text-[rgba(25,37,68,0.68)]"
                    style={tone === "warning" || tone === "danger" ? { color: meta.color } : undefined}
                  >
                    <EventIcon name={EVENT_ICONS[item.type] ?? "system"} />
                  </span>
                  <div className="min-w-0">
                    <div className="flex min-w-0 items-start justify-between gap-2">
                      <div className="min-w-0 line-clamp-2 text-[11.5px] font-semibold leading-[1.25]" style={{ color: tone === "danger" ? "var(--danger)" : "var(--ink)" }}>
                        {EVENT_TITLES[item.type] ?? item.type}
                      </div>
                      <span
                        className="max-w-[96px] shrink-0 truncate rounded-full border px-2 py-1 text-[8.5px] font-semibold leading-none"
                        style={{
                          color: meta.color,
                          borderColor: `color-mix(in srgb, ${meta.color} 11%, white)`,
                          background: `color-mix(in srgb, ${meta.color} 8%, white)`,
                        }}
                        title={statusFor(item)}
                      >
                        {statusFor(item)}
                      </span>
                    </div>
                    <p className="mt-1 line-clamp-2 text-[10px] leading-[1.35] text-[rgba(0,0,0,0.46)]">
                      {description}
                      {item.txHash ? (
                        <span className="font-mono" title={item.txHash}>
                          {" \u00b7 tx "}
                          {typeof item.explorerUrl === "string" && /^https:\/\//.test(item.explorerUrl) ? (
                            <a
                              href={item.explorerUrl}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="underline-offset-2 hover:underline"
                              style={{ color: item.type === "tx.reverted" || item.family === "attack" ? "var(--danger)" : "var(--accent)" }}
                            >
                              {shortHash(item.txHash)}
                            </a>
                          ) : (
                            shortHash(item.txHash)
                          )}
                        </span>
                      ) : null}
                      {item.simulated ? <span className="font-mono uppercase">{" \u00b7 simulated"}</span> : null}
                    </p>
                    {item.type === "guardian.incident" && onOpenIncident ? (
                      <button type="button" onClick={onOpenIncident} className="mt-1.5 text-[10px] font-medium text-[var(--danger)] underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--danger)]">
                        Open DORA draft
                      </button>
                    ) : null}
                  </div>
                </motion.li>
              );
            })}
          </AnimatePresence>
        </ul>
      </motion.div>
        ) : null}
      </AnimatePresence>
    </GlowingShadow>
  );
}
