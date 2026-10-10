"use client";

import { AnimatePresence, motion } from "framer-motion";
import type { FeedItem } from "@/lib/store";
import { cx, ease, shortHash, Tag } from "./ui";

const FAMILY_COLOR: Record<FeedItem["family"], string> = {
  decision: "var(--accent)",
  leg: "#3b6bff",
  chain: "#8b5cf6",
  alert: "var(--medium)",
  attack: "var(--danger)",
  system: "rgba(0,0,0,.3)",
};

function offset(ts: string, start: string) {
  const delta = Math.max(0, Date.parse(ts) - Date.parse(start)) / 1000;
  return `+${delta.toFixed(1).padStart(4, "0")}s`;
}

export function EventFeed({ feed }: { feed: FeedItem[] }) {
  const start = feed[0]?.ts;
  const items = [...feed].reverse();
  return (
    <motion.section
      initial={{ opacity: 0, x: 16 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.7, ease, delay: 0.25 }}
      className="card flex min-h-0 flex-1 flex-col rounded-[24px]"
      aria-label="Event feed"
    >
      <div className="flex items-center justify-between px-5 pt-5">
        <Tag index="03">Event feed</Tag>
        <span className="font-mono text-[11px] text-ink-3">{feed.length} events</span>
      </div>
      <div className="scroll-fade no-scrollbar mt-3 min-h-0 flex-1 overflow-y-auto px-3 pb-4" aria-live="polite">
        {items.length === 0 ? (
          <div className="px-2 py-8 text-center text-[12.5px] text-ink-3">
            Every decision and movement appears here,
            <br /> straight from the engine.
          </div>
        ) : null}
        <ul className="space-y-1">
          <AnimatePresence initial={false}>
            {items.map((item) => (
              <motion.li
                key={`${item.seq}-${item.type}`}
                layout="position"
                initial={{ opacity: 0, y: -8, filter: "blur(4px)" }}
                animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.4, ease }}
                className={cx(
                  "rounded-[14px] px-2.5 py-2",
                  item.family === "attack" && "bg-[color-mix(in_srgb,var(--danger)_7%,white)]",
                  item.family === "alert" && "bg-[color-mix(in_srgb,var(--medium)_7%,white)]",
                )}
              >
                <div className="flex items-start gap-2.5">
                  <span className="mt-[7px] size-1.5 shrink-0 rounded-full" style={{ background: FAMILY_COLOR[item.family] }} />
                  <div className="min-w-0 flex-1">
                    <div className="text-[12.5px] leading-snug text-ink">{item.text}</div>
                    <div className="mt-0.5 flex flex-wrap items-center gap-x-2 font-mono text-[10.5px] text-ink-3">
                      <span>{start ? offset(item.ts, start) : ""}</span>
                      <span>{item.type}</span>
                      {item.txHash ? <span title={item.txHash}>tx {shortHash(item.txHash)}</span> : null}
                      {item.simulated ? (
                        <span className="rounded-full border border-[var(--line-strong)] px-1.5 text-[9.5px] uppercase tracking-wide">
                          sim
                        </span>
                      ) : null}
                    </div>
                  </div>
                </div>
              </motion.li>
            ))}
          </AnimatePresence>
        </ul>
      </div>
    </motion.section>
  );
}
