"use client";

import { useEffect, useRef } from "react";

import { DANGER_COLOR, HOP_COLORS, SIGNAL_COLOR, TIER_COLORS } from "@/lib/colors";
import { formatClock, shortHash } from "@/lib/format";
import { describeEvent, type FeedFamily, type FeedItem } from "@/lib/store";

interface EventFeedProps {
  feed: FeedItem[];
  names: Record<string, string>;
}

const FAMILY: Record<FeedFamily, { label: string; color: string; path: string }> = {
  decision: { label: "Decision", color: SIGNAL_COLOR, path: "M4 12.5l5 5L20 6.5" },
  leg: { label: "Money movement", color: HOP_COLORS.bank, path: "M4 12h15M13 6l6 6-6 6" },
  chain: {
    label: "Avalanche",
    color: HOP_COLORS.chain,
    path: "M10 14l4-4M8.5 11.5L6.6 13.4a3.5 3.5 0 0 0 5 5l1.9-1.9M15.5 12.5l1.9-1.9a3.5 3.5 0 0 0-5-5l-1.9 1.9",
  },
  alert: { label: "Alert", color: TIER_COLORS.MEDIUM, path: "M12 3.5l9 16H3l9-16zM12 10v4M12 17h.01" },
  attack: { label: "Attack", color: DANGER_COLOR, path: "M6 6l12 12M18 6L6 18" },
  system: { label: "System", color: "#8b9bb4", path: "M12 9.5a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5z" },
};

export default function EventFeed({ feed, names }: EventFeedProps) {
  const listRef = useRef<HTMLOListElement>(null);

  useEffect(() => {
    const list = listRef.current;
    if (list) list.scrollTop = list.scrollHeight;
  }, [feed.length]);

  return (
    <section className="panel feed" aria-label="Event stream">
      <header className="feed__header">
        <h2 className="feed__title">Event stream</h2>
        <span className="feed__count">{feed.length} events</span>
      </header>
      {feed.length === 0 ? (
        <p className="feed__empty">Events from the engine appear here as they happen: every decision, leg and on-chain step.</p>
      ) : (
        <ol ref={listRef} className="feed__list" role="log" aria-live="polite" aria-relevant="additions">
          {feed.map((item) => {
            const family = FAMILY[item.family];
            return (
              <li key={`${item.seq}-${item.type}`} className={`feed__item feed__item--${item.family}`}>
                <time className="feed__time" dateTime={item.ts}>
                  {formatClock(item.ts)}
                </time>
                <span className="feed__icon" style={{ color: family.color }} title={family.label}>
                  <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <path d={family.path} />
                  </svg>
                  <span className="sr-only">{family.label}</span>
                </span>
                <span className="feed__body">
                  <span className="feed__text">{describeEvent(item.event, names)}</span>
                  <span className="feed__meta">
                    <code>{item.type}</code>
                    {item.txHash &&
                      (item.explorerUrl ? (
                        <a href={item.explorerUrl} target="_blank" rel="noreferrer">
                          tx {shortHash(item.txHash)}
                        </a>
                      ) : (
                        <span>tx {shortHash(item.txHash)}</span>
                      ))}
                    {item.simulated && <span className="badge">simulated</span>}
                  </span>
                </span>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
