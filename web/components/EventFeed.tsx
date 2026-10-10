"use client";

import { useEffect, useRef } from "react";

import { shortHash, type FeedFamily, type FeedItem } from "@/lib/store";

const FAMILY_STYLE: Record<FeedFamily, { label: string; color: string; path: string }> = {
  decision: { label: "Decision", color: "#38bdf8", path: "M5 12.5l4.5 4.5L19 7.5" },
  leg: { label: "Leg", color: "#60a5fa", path: "M4 12h14m-5-5l5 5-5 5" },
  chain: { label: "Chain", color: "#a855f7", path: "M12 3l8 4.5v9L12 21l-8-4.5v-9L12 3z" },
  alert: { label: "Alert", color: "#f59e0b", path: "M12 4l9 16H3L12 4zm0 6v4m0 3v.5" },
  attack: { label: "Attack", color: "#ef4444", path: "M6 6l12 12M18 6L6 18" },
  system: { label: "System", color: "#94a3b8", path: "M12 8a4 4 0 100 8 4 4 0 000-8z" },
};

function clock(ts: string): string {
  const date = new Date(ts);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleTimeString("en-GB", { hour12: false });
}

/** The same story as the globe, in words: newest at the bottom, announced politely. */
export default function EventFeed({ feed }: { feed: FeedItem[] }) {
  const listRef = useRef<HTMLOListElement>(null);
  const last = feed.length > 0 ? feed[feed.length - 1].n : 0;

  useEffect(() => {
    const element = listRef.current;
    if (element) element.scrollTop = element.scrollHeight;
  }, [last]);

  return (
    <section
      aria-label="Event feed"
      className="flex h-full min-h-0 flex-col rounded-xl border border-white/10 bg-slate-950/75 shadow-xl shadow-black/40 backdrop-blur-md"
    >
      <header className="flex items-baseline justify-between border-b border-white/10 px-4 py-2.5">
        <h2 className="text-sm font-semibold text-slate-100">Event feed</h2>
        <span className="text-xs text-slate-400">
          {feed.length} event{feed.length === 1 ? "" : "s"}
        </span>
      </header>
      <ol ref={listRef} role="log" aria-live="polite" aria-relevant="additions" className="relative min-h-0 flex-1 space-y-1 overflow-y-auto px-2 py-2">
        {feed.length === 0 && <li className="px-2 py-1 text-xs text-slate-500">No events yet. Run a scenario with the demo controls.</li>}
        {feed.map((item) => {
          const family = FAMILY_STYLE[item.family];
          return (
            <li key={item.n} className="flex gap-2 rounded-lg px-2 py-1.5 hover:bg-white/5">
              <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full" style={{ backgroundColor: `${family.color}26` }} title={family.label}>
                <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="none" stroke={family.color} strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d={family.path} />
                </svg>
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-[13px] leading-snug text-slate-100">
                  <span className="sr-only">{family.label}: </span>
                  {item.text}
                </p>
                {item.details.map((line, index) => (
                  <p key={index} className="mt-0.5 text-xs leading-snug text-slate-400">
                    {line}
                  </p>
                ))}
                <p className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-slate-500">
                  <time dateTime={item.ts}>{clock(item.ts)}</time>
                  <span className="font-mono">{item.type}</span>
                  {item.simulated && <span className="rounded border border-slate-600 px-1 text-[10px] uppercase tracking-wide text-slate-400">simulated</span>}
                  {item.txHash &&
                    (item.explorerUrl ? (
                      <a href={item.explorerUrl} target="_blank" rel="noopener noreferrer" className="font-mono text-violet-300 underline decoration-dotted hover:text-violet-200">
                        {shortHash(item.txHash)}
                      </a>
                    ) : (
                      <span className="font-mono text-violet-300/80" title={item.txHash}>
                        {shortHash(item.txHash)}
                      </span>
                    ))}
                </p>
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
